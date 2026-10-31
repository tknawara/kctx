"""Independent source-binding oracle for immutable graph qualification.

This does not call the graph extractor or its record/edge projection helpers.
Only authored syntax decoding and repository identity normalization are shared.
Golden tests additionally fix literal expected rows independently of both paths.
"""

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from kctx.adapters.git.citations import ORG_REPO_RE
from kctx.citations.syntax import is_illustrative, parse_cite_body
from kctx.codecs.frontmatter import read_frontmatter, split_commas_respecting_brackets
from kctx.domain.json import JsonObject, JsonValue, object_value, optional_text, texts
from kctx.errors import KctxError
from kctx.graph.identity import RepositoryIdentity, canonical_repo
from kctx.graph.models import Edge, ExtractionDiagnostic, GraphEdgeId, GraphNodeId
from kctx.graph.source_tokens import (
    decode_json_source,
    iter_source_tokens,
    json_field_string_sources,
)

_SHORT = re.compile(
    r"^(?P<repo>[\w./-]+)@(?P<rev>[0-9a-fA-F]{7,40}(?:\+dirty)?):(?P<path>[^:]+)(?::(?P<L>\d+(?:-\d+)?))?$"
)
MAX_MISMATCH_SAMPLES = 100


@dataclass(frozen=True, slots=True)
class ExpectedBindings:
    edges: tuple[Edge, ...]
    skips: tuple[ExtractionDiagnostic, ...]
    token_ids: frozenset[GraphEdgeId]
    token_count: int
    illustrative_count: int
    other_diagnostics: tuple[ExtractionDiagnostic, ...] = ()


def _source_node(path: str, content: str, diagnostics: list[ExtractionDiagnostic]) -> str:
    fallback = "doc:" + path
    name = PurePosixPath(path)
    try:
        if path.endswith(".json"):
            value = decode_json_source(content)
            if path.startswith("inventory/assets/"):
                record = object_value(value, path)
                ident = optional_text(record.get("id"), "asset.id")
                if not ident:
                    raise KctxError("malformed", "asset.id is required and must not be empty")
                optional_text(record.get("name", ident), "asset.name")
                return ident
            if path.startswith("inventory/relationships/"):
                record = object_value(value, path)
                source = optional_text(record.get("from"), "relationship.from")
                target = optional_text(record.get("to"), "relationship.to")
                kind = optional_text(record.get("type"), "relationship.type")
                if not (source and target and kind):
                    raise KctxError(
                        "malformed",
                        "relationship.from, to and type are required and must not be empty",
                    )
                optional_text(record.get("status"), "relationship.status")
                texts(record.get("evidence", []), "relationship.evidence")
                return source
            return fallback
        fields = read_frontmatter(content)
        if path.startswith("inventory/dossiers/") and name.name != "README.md":
            return "dossier:" + fields["asset"] if fields.get("asset") else fallback
        if path.startswith("signatures/"):
            return "sig:" + fields["id"] if fields.get("id") else fallback
        if path.startswith("investigations/") and name.name == "README.md":
            return "inv:" + fields["id"] if fields.get("id") else fallback
        if path.startswith("proposals/") and name.name == "proposal.md":
            return "proposal:" + fields["id"] if fields.get("id") else fallback
        if "evidence" in name.parts:
            home = "/".join(name.parts[: name.parts.index("evidence")])
            return f"ev:{home}/{name.stem}" if home and name.stem else fallback
    except (KctxError, json.JSONDecodeError) as exc:
        diagnostics.append(
            ExtractionDiagnostic(
                category="record-malformed",
                src_path=path,
                src_line=exc.lineno if isinstance(exc, json.JSONDecodeError) else 1,
                reason=str(exc),
                raw=content,
            )
        )
        return fallback
    return fallback


def _edge_key(
    source: str, target: str, path: str, line: int, ordinal: int, rel: str = "cites"
) -> GraphEdgeId:
    material = f"{source}|{target}|{rel}|{path}|{line}|{ordinal}"
    return GraphEdgeId(hashlib.sha256(material.encode()).hexdigest()[:20])


def _alias_diagnostic(
    repo: str,
    path: str,
    line: int,
    raw: str,
    diagnostics: list[ExtractionDiagnostic],
    *,
    illus: bool = False,
) -> None:
    if not ORG_REPO_RE.fullmatch(repo):
        diagnostics.append(
            ExtractionDiagnostic(
                category="unresolved-repo",
                src_path=path,
                src_line=line,
                reason=f"repository alias {repo!r} has no canonical org/repo identity",
                raw=raw,
                illus=illus,
            )
        )


def _literal_edge(
    source: str,
    path: str,
    line: int,
    ordinal: int,
    raw: str,
    fields: Mapping[str, str],
    illus: bool,
    seen_date: str,
    identity: RepositoryIdentity,
) -> Edge:
    kind = fields["kind"]
    revision = blob = span = selector = state = None
    if kind == "code":
        target = f"code:{canonical_repo(fields.get('repo'), fields.get('url'), identity)}:{fields.get('path', '')}"
        revision, blob, span, selector = (
            fields.get("rev"),
            fields.get("blob"),
            fields.get("span"),
            fields.get("L"),
        )
    elif kind == "commit":
        target = f"code:{canonical_repo(fields.get('repo'), fields.get('url'), identity)}@{fields.get('rev')}"
        revision = fields.get("rev")
    elif kind in ("ev", "proposal", "ticket"):
        target = f"{kind}:{fields.get('id')}"
        if kind == "proposal":
            state = fields.get("state")
    elif kind in ("web", "doc"):
        target = f"{kind}:{fields.get('url', '')}" + (
            f"#{fields['section']}" if fields.get("section") else ""
        )
    elif kind == "pr":
        target = f"pr:{canonical_repo(fields.get('repo'), fields.get('url'), identity)}#{fields.get('n', '')}"
        state = fields.get("state")
    elif kind == "query":
        digest = hashlib.sha256((fields.get("sys", "") + fields.get("q", "")).encode()).hexdigest()[
            :12
        ]
        target = "query:" + digest
    elif kind == "record":
        target = f"doc:{fields.get('path')}"
        state = fields.get("state")
    elif kind == "usr":
        target = f"usr:{fields.get('date')}"
    else:
        digest = hashlib.sha256(json.dumps(dict(fields), sort_keys=True).encode()).hexdigest()[:16]
        target = f"{kind}:{digest}"
    return Edge(
        edge_id=_edge_key(source, target, path, line, ordinal),
        src_node=GraphNodeId(source),
        dst_node=GraphNodeId(target),
        rel="cites",
        src_path=path,
        src_line=line,
        cite_kind=kind,
        rev=revision,
        blob_sha=blob,
        span=span,
        line_selector=selector,
        seen=fields.get("seen") or seen_date,
        state=state,
        illus=illus,
        raw=raw,
    )


def _relationship_locators(
    path: str,
    content: str,
    source: str,
    seen_date: str,
    identity: RepositoryIdentity,
    diagnostics: list[ExtractionDiagnostic],
) -> list[Edge]:
    if (
        not path.startswith("inventory/relationships/")
        or not path.endswith(".json")
        or source == "doc:" + path
    ):
        return []
    edges: list[Edge] = []
    for fragment in json_field_string_sources(content, "evidence"):
        match = _SHORT.fullmatch(fragment.text)
        if match:
            start = fragment.offset(0)
            line = content.count("\n", 0, start) + 1
            repo = canonical_repo(match["repo"], None, identity)
            target = f"code:{repo}:{match['path']}"
            raw = content[start : fragment.offset(len(fragment.text))]
            _alias_diagnostic(repo, path, line, raw, diagnostics)
            edges.append(
                Edge(
                    edge_id=_edge_key(source, target, path, line, -(start + 1)),
                    src_node=GraphNodeId(source),
                    dst_node=GraphNodeId(target),
                    rel="cites",
                    src_path=path,
                    src_line=line,
                    cite_kind="code",
                    rev=match["rev"],
                    line_selector=match["L"],
                    seen=seen_date,
                    raw=raw,
                )
            )
    return edges


def _proposal_references(
    path: str,
    content: str,
    source: str,
    seen_date: str,
    identity: RepositoryIdentity,
    diagnostics: list[ExtractionDiagnostic],
) -> list[Edge]:
    if (
        not source.startswith("proposal:")
        or not path.startswith("proposals/")
        or PurePosixPath(path).name != "proposal.md"
    ):
        return []
    fields = read_frontmatter(content)
    raw_list = fields.get("references", "").strip()
    if raw_list.startswith("[") and raw_list.endswith("]"):
        raw_list = raw_list[1:-1]
    references = split_commas_respecting_brackets(raw_list) if raw_list else []
    field = re.search(r"(?m)^\s*references:", content)
    offset = field.end() if field else 0
    edges: list[Edge] = []
    for ordinal, reference in enumerate(references):
        start = content.find(reference, offset)
        if start < 0:
            raise KctxError("malformed", f"{path}: reference has no authored source location")
        offset = start + len(reference)
        line = content.count("\n", 0, start) + 1
        match = _SHORT.match(reference)
        revision = selector = None
        if match:
            repo = canonical_repo(match["repo"], None, identity)
            target, kind = f"code:{repo}:{match['path']}", "code"
            revision, selector = match["rev"], match["L"]
            _alias_diagnostic(repo, path, line, reference, diagnostics)
        elif reference.startswith(("http://", "https://")):
            target, kind = "web:" + reference, "web"
        elif re.fullmatch(r"[\w-]+/\d{4}-\d{2}-\d{2}-[\w-]+", reference):
            target, kind = "proposal:" + reference, "proposal"
        elif reference.startswith("ev:"):
            target, kind = reference, "ev"
        else:
            continue
        edges.append(
            Edge(
                edge_id=_edge_key(source, target, path, line, ordinal, "references"),
                src_node=GraphNodeId(source),
                dst_node=GraphNodeId(target),
                rel="references",
                src_path=path,
                src_line=line,
                cite_kind=kind,
                rev=revision,
                line_selector=selector,
                seen=seen_date,
                state=fields.get("status"),
                raw=reference,
            )
        )
    return edges


def expected_bindings(
    files: Mapping[str, str], seen_date: str, identity: RepositoryIdentity
) -> ExpectedBindings:
    edges: list[Edge] = []
    skips: list[ExtractionDiagnostic] = []
    other_diagnostics: list[ExtractionDiagnostic] = []
    token_ids: set[GraphEdgeId] = set()
    total = illustrative = 0
    for path, content in sorted(files.items()):
        source = _source_node(path, content, other_diagnostics)
        for token in iter_source_tokens(path, content):
            total += 1
            illus = is_illustrative(token.body)
            illustrative += int(illus)
            try:
                if not token.complete:
                    raise KctxError("malformed", "unterminated citation token")
                fields = parse_cite_body(token.body)
                if not fields.get("kind"):
                    raise KctxError("malformed", "no kind= field")
                edge = _literal_edge(
                    source,
                    path,
                    token.src_line,
                    token.ordinal,
                    token.raw,
                    fields,
                    illus,
                    seen_date,
                    identity,
                )
            except KctxError as exc:
                skips.append(
                    ExtractionDiagnostic(
                        category="citation-skip",
                        src_path=path,
                        src_line=token.src_line,
                        reason=str(exc),
                        raw=token.raw,
                        illus=illus,
                    )
                )
                continue
            if fields["kind"] in ("code", "commit", "pr"):
                repo = canonical_repo(fields.get("repo"), fields.get("url"), identity)
                _alias_diagnostic(
                    repo, path, token.src_line, token.raw, other_diagnostics, illus=illus
                )
            edges.append(edge)
            token_ids.add(edge.edge_id)
        edges.extend(
            _relationship_locators(path, content, source, seen_date, identity, other_diagnostics)
        )
        edges.extend(
            _proposal_references(path, content, source, seen_date, identity, other_diagnostics)
        )
    return ExpectedBindings(
        tuple(edges),
        tuple(skips),
        frozenset(token_ids),
        total,
        illustrative,
        tuple(other_diagnostics),
    )


def compare_bindings(
    expected: ExpectedBindings, actual: Sequence[Edge], diagnostics: Sequence[ExtractionDiagnostic]
) -> JsonObject:
    remaining = {edge.edge_id: edge for edge in expected.edges}
    mismatches: list[JsonValue] = []
    mismatch_count = 0
    graph_tokens = graph_illus = 0
    for edge in actual:
        if edge.edge_id in expected.token_ids:
            graph_tokens += 1
            graph_illus += int(edge.illus)
        original = remaining.pop(edge.edge_id, None)
        if original != edge:
            mismatch_count += 1
            if len(mismatches) < MAX_MISMATCH_SAMPLES:
                mismatches.append(
                    {
                        "edge_id": edge.edge_id.val,
                        "expected": original.to_wire() if original else None,
                        "actual": edge.to_wire(),
                    }
                )
    for edge in remaining.values():
        mismatch_count += 1
        if len(mismatches) < MAX_MISMATCH_SAMPLES:
            mismatches.append(
                {"edge_id": edge.edge_id.val, "expected": edge.to_wire(), "actual": None}
            )
    expected_diagnostics = Counter(
        item.model_dump_json() for item in (*expected.skips, *expected.other_diagnostics)
    )
    actual_diagnostics = Counter(item.model_dump_json() for item in diagnostics)
    diagnostic_match = actual_diagnostics == expected_diagnostics
    return {
        "direct_cite_tokens": expected.token_count,
        "direct_illus_tokens": expected.illustrative_count,
        "graph_binding_rows": graph_tokens,
        "graph_illus_rows": graph_illus,
        "expected_binding_rows": len(expected.edges),
        "actual_binding_rows": len(actual),
        "skipped_tokens": len(expected.skips),
        "skips": [
            {
                "src_path": skip.src_path,
                "line": skip.src_line,
                "reason": skip.reason,
                "raw": skip.raw,
                "illus": skip.illus,
            }
            for skip in diagnostics[:MAX_MISMATCH_SAMPLES]
            if skip.category == "citation-skip"
        ],
        "diagnostics": [item.to_wire() for item in diagnostics[:MAX_MISMATCH_SAMPLES]],
        "diagnostic_count": len(diagnostics),
        "diagnostics_truncated": len(diagnostics) > MAX_MISMATCH_SAMPLES,
        "diagnostics_match": diagnostic_match,
        "binding_mismatch_count": mismatch_count,
        "binding_mismatches": mismatches,
        "unexplained": mismatches,
        "representation_complete": not diagnostics,
        "match": mismatch_count == 0 and diagnostic_match,
    }
