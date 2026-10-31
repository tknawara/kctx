"""Typed local operations; no CLI wrappers, signing, or arbitrary source-file capture."""

import base64
import binascii
from pathlib import Path

from kctx.citations import code, construction, rendering, scan
from kctx.config import Config
from kctx.domain.ids import (
    AuthorityKeyId,
    PlanId,
    PolicyDigest,
    ProposalId,
    ReleaseId,
    SourceId,
    SourceRevision,
)
from kctx.domain.json import JsonObject, integer, object_value
from kctx.domain.targets import parse_use_target
from kctx.errors import KctxError
from kctx.graph import queries, sync
from kctx.graph.models import GraphNodeId
from kctx.graph.query_session import QuerySession
from kctx.semantics.wire import dec_context, dec_ref
from kctx.services import backlinks, context, discovery
from kctx.services.knowledge import KnowledgeEngine
from kctx.services.knowledge_models import Approval, CaptureKind

from . import schemas as s


class Operations:
    def __init__(self, root: Path) -> None:
        self.root = root.absolute()
        self.graph: QuerySession | None = None
        self.knowledge: KnowledgeEngine | None = None

    def close(self) -> None:
        if self.graph is not None:
            self.graph.close()
            self.graph = None

    def graph_session(self, *, refresh: bool = False) -> QuerySession:
        if self.graph is None or refresh:
            # Keep the old session usable if opening the new publication fails.
            replacement = QuerySession(self.root)
            replacement.__enter__()
            previous = self.graph
            self.graph = replacement
            if previous is not None:
                previous.close()
        return self.graph

    def knowledge_engine(self) -> KnowledgeEngine:
        if self.knowledge is None:
            config = Config.load()
            if config.knowledge_dir is None:
                raise KctxError("incomplete", "configure knowledge_dir in config.toml")
            anchor = (
                PolicyDigest(config.knowledge_policy_digest)
                if config.knowledge_policy_digest
                else None
            )
            self.knowledge = KnowledgeEngine(self.root, config.knowledge_dir, anchor)
        return self.knowledge

    def citation_path(self, value: str) -> str:
        path = Path(value)
        if ".." in path.parts:
            raise KctxError("permission", "citation path must remain under the knowledge root")
        if not path.is_absolute():
            path = self.root / path
        if not path.is_relative_to(self.root):
            raise KctxError("permission", "citation path must remain under the knowledge root")
        # Actual acquisition remains descriptor-relative in contained_markdown.
        return str(path)

    def invoke(self, method: str, params: s.Params) -> JsonObject:
        payload: JsonObject
        exit_code = 0
        generation: JsonObject | None = None
        complete = True
        if method.startswith("graph."):
            if isinstance(params, s.Sync):
                payload = sync.sync(self.root, rebuild=params.rebuild, history=params.history)
                # This is the new publication; an existing reader stays pinned.
                generation = {
                    "selection": "published",
                    "kb_sha": payload.get("kb_sha"),
                    "data_commit": payload.get("dolt_commit"),
                    "input_digest": payload.get("input_digest"),
                }
            elif isinstance(params, s.Check):
                payload = queries.check(
                    self.root,
                    sample_ids=None
                    if params.sample_ids is None
                    else [GraphNodeId(value) for value in params.sample_ids],
                )
                parity = object_value(payload["parity"])
                exit_code = 0 if parity["match"] else 2
                complete = exit_code == 0
                generation = {
                    "selection": "checked",
                    "kb_sha": parity["kb_sha"],
                    "input_digest": parity["input_digest"],
                }
            else:
                session = self.graph_session(refresh=method == "graph.refresh")
                if isinstance(params, s.Uses):
                    payload = session.uses(
                        GraphNodeId(params.target),
                        limit=params.limit,
                        include_illus=params.include_illus,
                    )
                    exit_code = 0 if payload["total"] else 2
                elif isinstance(params, s.Impact):
                    payload = session.impact(
                        GraphNodeId(params.target),
                        depth=params.depth,
                        rel=params.rel,
                        limit=params.limit,
                    )
                    exit_code = 0 if payload["total"] else 2
                elif isinstance(params, s.SourcePaths):
                    payload = session.source_paths(
                        GraphNodeId(params.target), revision=params.revision, limit=params.limit
                    )
                elif isinstance(params, s.Diff):
                    payload = session.diff(params.kb_sha_a, params.kb_sha_b, limit=params.limit)
                else:
                    payload = session.status()
                generation = session.identity()
                # Completeness refers to this pinned result, not merely successful IO.
                complete = bool(generation["is_current_publication"])
                status = (
                    payload if method in ("graph.status", "graph.refresh") else session.status()
                )
                complete = complete and status["up_to_date"] is True
                if isinstance(params, s.Diff):
                    summary = payload["summary"]
                    sample = payload["sample"]
                    if isinstance(summary, list) and isinstance(sample, list):
                        complete = complete and len(sample) >= sum(
                            integer(object_value(row)["n"], "diff count") for row in summary
                        )
        elif method.startswith("knowledge."):
            engine = self.knowledge_engine()
            if isinstance(params, s.Capture):
                try:
                    content = base64.b64decode(params.content_base64, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise KctxError(
                        "malformed", "content_base64 must contain valid base64 bytes"
                    ) from exc
                payload = engine.capture(
                    CaptureKind(params.kind),
                    SourceId(params.source),
                    SourceRevision(params.revision),
                    content,
                    params.observed_at,
                ).wire()
            elif isinstance(params, s.Propose):
                payload = engine.propose(
                    object_value(params.candidate), params.target_use, params.now
                ).wire()
            elif isinstance(params, s.Admit):
                payload = engine.admit(
                    PlanId(params.plan), Approval.decode(object_value(params.approval))
                )
            elif isinstance(params, s.Rollback):
                payload = engine.rollback(
                    ReleaseId(params.release),
                    dec_context(params.context),
                    AuthorityKeyId(params.key_id),
                ).wire()
            elif isinstance(params, s.KnowledgeContext):
                payload = engine.context(
                    tuple(dec_ref(value) for value in params.claims),
                    dec_context(params.context),
                    params.limit,
                    None if params.continuation is None else object_value(params.continuation),
                    ReleaseId(params.release) if params.release is not None else None,
                )
            elif isinstance(params, s.Explain):
                payload = engine.explain(
                    dec_ref(params.claim),
                    dec_context(params.context),
                    ReleaseId(params.release) if params.release is not None else None,
                )
            else:
                payload = engine.recover()
                recovered = payload["operations"]
                if not isinstance(recovered, list):
                    raise KctxError("incomplete", "recovery returned an invalid operation list")
                complete = all(
                    isinstance(item, dict) and item.get("outcome") in ("applied", "already_applied")
                    for item in recovered
                )
            if "release" in payload:
                generation = {"release": payload["release"], "selection": "exact"}
            if payload.get("missing"):
                complete = False
            records = payload.get("records")
            if isinstance(records, list):
                for record in records:
                    assessment = object_value(object_value(record)["assessment"])
                    complete = (
                        complete
                        and assessment["freshness"] == "fresh"
                        and assessment["available"] is True
                    )
        elif isinstance(params, s.CiteMake):
            citation = params.citation
            if isinstance(citation, s.CiteCode):
                payload = code.make_code(
                    citation.repo,
                    citation.path,
                    citation.line_range,
                    sym=citation.sym,
                    rev=citation.rev,
                    ttl=citation.ttl,
                    allow_dirty=citation.allow_dirty,
                    sens=citation.sens,
                    redact=citation.redact,
                ).to_wire()
            elif isinstance(citation, s.CiteProposal):
                payload = construction.make_proposal(
                    ProposalId(citation.id), ttl=citation.ttl
                ).to_wire()
            else:
                payload = construction.make_other(
                    citation.kind, citation.fields.model_dump(exclude_unset=True)
                ).to_wire()
        elif isinstance(params, s.CiteCheck):
            if bool(params.paths) == (params.inline_line is not None):
                raise KctxError("malformed", "provide either nonempty paths or inline_line")
            result = scan.run_check(
                paths=[self.citation_path(path) for path in params.paths],
                inline_line=params.inline_line,
                touch=params.touch,
                touch_all=params.touch_all,
                mark=params.mark,
            )
            payload = scan.check_to_wire(result)
            exit_code = result["exit_code"]
            complete = result["available"] and exit_code == 0
        elif isinstance(params, s.CiteStale):
            if not params.paths:
                raise KctxError("malformed", "paths must not be empty")
            stale = scan.run_stale(
                [self.citation_path(path) for path in params.paths], offline=params.offline
            )
            payload = scan.stale_to_wire(stale)
            exit_code = stale["exit_code"]
            complete = stale["available"] and exit_code == 0 and stale["total"] == 0
        elif isinstance(params, s.CiteRender):
            target = (
                params.target if "⟦cite" in params.target else self.citation_path(params.target)
            )
            payload = {
                "rendered": [
                    rendering.render_one(
                        fields, fmt=params.fmt, audience=params.audience, do_check=params.do_check
                    )
                    for fields, _raw in rendering.extract_cite_items(target)
                ]
            }
        elif isinstance(params, s.AuthoredContext):
            payload = object_value(context.context(self.root, params.ident, depth=params.depth))
            freshness = object_value(payload["freshness"])
            citations = object_value(freshness["citations"])
            complete = (
                not freshness["asset_past_ttl"]
                and citations["available"] is True
                and citations["exit_code"] == 0
            )
        elif isinstance(params, s.Home):
            payload = object_value(discovery.home(self.root, params.ident))
            exit_code = 0 if payload["candidates"] else 2
        elif isinstance(params, s.Target):
            payload = object_value(backlinks.uses(self.root, parse_use_target(params.target)))
            exit_code = 0 if payload["referrers"] else 2
        else:
            raise KctxError("malformed", "unsupported engine operation")
        complete = complete and payload.get("complete", True) is True
        if payload.get("truncated") is True or payload.get("up_to_date") is False:
            complete = False
        if type(payload.get("returned")) is int and type(payload.get("total")) is int:
            complete = complete and integer(payload["returned"], "returned") >= integer(
                payload["total"], "total"
            )
        if not complete and exit_code == 0:
            exit_code = 3
        return {
            "payload": payload,
            "exit_code": exit_code,
            "generation": generation,
            "complete": complete,
        }
