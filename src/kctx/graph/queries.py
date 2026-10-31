"""Read-side traversal of the shadow graph: status/uses/impact/diff/check.

Every value interpolated into SQL goes through graph.quoting (sql_quote
always; validate_id as a second guard on anything meant to look like an id).
No agent-facing function here builds a query from unsanitized input.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from kctx.domain.json import JsonObject, JsonValue, object_value, optional_text
from kctx.domain.json import text as json_text
from kctx.domain.targets import parse_use_target
from kctx.errors import KctxError
from kctx.graph.dolt_store import DoltStore
from kctx.graph.extract import MAX_DIAGNOSTICS, MAX_GRAPH_EDGES, commit_date, read_tree_at_sha
from kctx.graph.generation import CompletedSnapshot, completed_snapshot
from kctx.graph.identity import RepositoryIdentity
from kctx.graph.inputs import generation_inputs
from kctx.graph.models import (
    DiffSample,
    DiffSummary,
    DoltCommitId,
    Edge,
    ExtractionDiagnostic,
    GraphNodeId,
    ImpactRow,
    TraversalRow,
    UsesRow,
    dolt_int,
)
from kctx.graph.operations import require_owner
from kctx.graph.parity import compare_bindings, expected_bindings
from kctx.graph.quoting import sql_quote, validate_id
from kctx.graph.sync import dolt_db_dir, head_sha
from kctx.observability import span
from kctx.services.backlinks import uses_from_files

MAX_QUERY_LIMIT = 1000
MAX_TRAVERSAL_ROWS = 10000


class SqlReader(Protocol):
    def sql_read(self, query: str) -> list[JsonObject]: ...


@dataclass(frozen=True, slots=True)
class QueryContext:
    """One validated generation and its read transport, never a mutable candidate."""

    reader: SqlReader
    snapshot: CompletedSnapshot
    db_dir: Path


def _selection(kb_root: Path, context: QueryContext | None) -> tuple[SqlReader, CompletedSnapshot]:
    if context is not None:
        return context.reader, context.snapshot
    store = _store()
    return store, select_snapshot(store, kb_root)


def _limit(value: int, name: str = "limit", maximum: int = MAX_QUERY_LIMIT) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise KctxError("malformed", f"{name} must be an integer from 1 to {maximum}")
    return value


def _store() -> DoltStore:
    return DoltStore(dolt_db_dir())


def select_snapshot(store: DoltStore, kb_root: Path) -> CompletedSnapshot:
    """Validate ownership and select one complete native read generation."""
    if not store.is_initialized():
        raise KctxError("not-found", "graph is not initialized; run `kctx graph sync` first")
    require_owner(store, kb_root)
    snapshot = completed_snapshot(store)
    if snapshot is None:
        raise KctxError("not-found", "graph has no completed sync; run `kctx graph sync` first")
    return snapshot


def status(kb_root: Path, *, context: QueryContext | None = None) -> JsonObject:
    with span("graph.status"):
        if context is None:
            native = _store()
            if not native.is_initialized():
                return {"initialized": False, "graph_dir": str(native.db_dir)}
            require_owner(native, kb_root)
            snapshot = completed_snapshot(native)
            store: SqlReader = native
            db_dir = native.db_dir
        else:
            store, snapshot, db_dir = context.reader, context.snapshot, context.db_dir
        st = snapshot.state if snapshot is not None else None
        counts = (
            store.sql_read(
                f"SELECT (SELECT COUNT(*) FROM nodes AS OF {sql_quote(snapshot.data_commit.val)}) AS node_count, "
                f"(SELECT COUNT(*) FROM edges AS OF {sql_quote(snapshot.data_commit.val)}) AS edge_count"
            )
            if snapshot is not None
            else []
        )
        kb_head = head_sha(kb_root)
        current_digest = (
            generation_inputs(kb_root, kb_sha=kb_head).digest if st is not None else None
        )
        return {
            "initialized": True,
            "graph_dir": str(db_dir),
            "sync_state": st.to_wire() if st else None,
            "node_count": dolt_int(counts[0]["node_count"]) if counts else 0,
            "edge_count": dolt_int(counts[0]["edge_count"]) if counts else 0,
            "kb_head": kb_head,
            "up_to_date": st is not None
            and st.kb_sha == kb_head
            and st.input_digest == current_digest,
            "input_digest": st.input_digest if st else None,
            "current_input_digest": current_digest,
        }


def uses(
    target: GraphNodeId,
    *,
    kb_root: Path,
    limit: int = 50,
    include_illus: bool = False,
    context: QueryContext | None = None,
) -> JsonObject:
    """Direct inbound edges into `target`, grouped by rel -- the graph
    analogue of `kctx uses`, but direction-aware (dst_node = target, not a
    literal-substring scan that can't tell an outgoing edge from an incoming
    one -- see RESULTS.md's query-1 false-positive finding)."""
    _limit(limit)
    store, snapshot = _selection(kb_root, context)
    limited, total = _uses_rows(store, snapshot, target, include_illus=include_illus, limit=limit)
    by_rel: dict[str, list[JsonValue]] = {}
    for row in limited:
        by_rel.setdefault(row.rel, []).append(row.to_wire())
    return {"target": target.val, "total": total, "returned": len(limited), "by_rel": dict(by_rel)}


def _inbound_filter(target: GraphNodeId, *, include_illus: bool) -> str:
    validate_id(target.val)
    return f"e.dst_node = {sql_quote(target.val)}" + ("" if include_illus else " AND e.illus = 0")


def _uses_rows(
    store: SqlReader,
    snapshot: CompletedSnapshot,
    target: GraphNodeId,
    *,
    include_illus: bool,
    limit: int = MAX_QUERY_LIMIT,
) -> tuple[list[UsesRow], int]:
    predicate = _inbound_filter(target, include_illus=include_illus)
    with span("graph.uses", target=target.val):
        counts = store.sql_read(
            f"SELECT COUNT(*) AS n FROM edges AS OF {sql_quote(snapshot.data_commit.val)} e "
            f"WHERE {predicate}"
        )
        total = dolt_int(counts[0]["n"]) if counts else 0
        rows = store.sql_read(
            "SELECT e.src_node, e.rel, e.cite_kind, e.seen, n.kind AS src_kind, "
            "n.home_path AS src_home_path "
            f"FROM edges AS OF {sql_quote(snapshot.data_commit.val)} e "
            f"LEFT JOIN nodes AS OF {sql_quote(snapshot.data_commit.val)} n ON n.id = e.src_node "
            f"WHERE {predicate} "
            f"ORDER BY e.rel, e.src_node LIMIT {limit}"
        )
    return [UsesRow.model_validate(row) for row in rows], total


def impact(
    target: GraphNodeId,
    *,
    kb_root: Path,
    depth: int = 3,
    rel: list[str] | None = None,
    limit: int = 100,
    context: QueryContext | None = None,
) -> JsonObject:
    """Breadth-first inbound traversal with explicit work and output bounds."""
    validate_id(target.val)
    _limit(limit)
    _limit(depth, "depth", 10)
    if rel is not None and len(rel) > 32:
        raise KctxError("malformed", "at most 32 relationship filters are supported")
    rel_filter = ""
    if rel:
        for relation in rel:
            validate_id(relation)
        rel_filter = " AND e.rel IN (" + ", ".join(sql_quote(value) for value in rel) + ")"
    store, snapshot = _selection(kb_root, context)
    frontier = {target: target.val}
    expanded = {target}
    found: dict[GraphNodeId, ImpactRow] = {}
    examined = 0
    for hop in range(1, depth + 1):
        next_frontier: dict[GraphNodeId, str] = {}
        entries = sorted(frontier, key=lambda node: node.val)
        for offset in range(0, len(entries), 200):
            destinations = ", ".join(sql_quote(node.val) for node in entries[offset : offset + 200])
            rows = store.sql_read(
                "SELECT e.src_node AS node, e.dst_node, n.kind, n.home_path "
                f"FROM edges AS OF {sql_quote(snapshot.data_commit.val)} e "
                f"LEFT JOIN nodes AS OF {sql_quote(snapshot.data_commit.val)} n ON n.id=e.src_node "
                f"WHERE e.dst_node IN ({destinations}) AND e.illus=0{rel_filter} "
                f"ORDER BY e.src_node,e.dst_node LIMIT {MAX_TRAVERSAL_ROWS - examined + 1}"
            )
            examined += len(rows)
            if examined > MAX_TRAVERSAL_ROWS:
                raise KctxError(
                    "incomplete",
                    f"impact exceeds {MAX_TRAVERSAL_ROWS} examined edges; reduce depth or relationship filters",
                )
            for raw in rows:
                row = TraversalRow.model_validate(raw)
                path = frontier[row.dst_node] + " <- " + row.node.val
                if row.node not in found:
                    found[row.node] = ImpactRow(
                        node=row.node, depth=hop, path=path, kind=row.kind, home_path=row.home_path
                    )
                if row.node not in expanded:
                    expanded.add(row.node)
                    next_frontier[row.node] = path
        frontier = next_frontier
        if not frontier:
            break
    dependents = sorted(found.values(), key=lambda row: (row.depth, row.node.val))
    return {
        "target": target.val,
        "depth": depth,
        "total": len(dependents),
        "returned": min(len(dependents), limit),
        "dependents": [row.to_wire() for row in dependents[:limit]],
    }


def _resolve_dolt_ref(store: SqlReader, snapshot: CompletedSnapshot, ref: str) -> DoltCommitId:
    validate_id(ref)
    if ref.upper() == "HEAD" or ref.upper() == "WORKING":
        return snapshot.data_commit
    rows = (
        store.sql_read(
            f"SELECT kb_sha,dolt_commit FROM kb_commits AS OF {sql_quote(snapshot.metadata_commit.val)} "
            f"WHERE kb_sha LIKE {sql_quote(ref.lower() + '%')} ORDER BY kb_sha LIMIT 2"
        )
        if re.fullmatch(r"[0-9a-fA-F]{1,64}", ref)
        else []
    )
    if len(rows) > 1:
        raise KctxError("conflict", f"ambiguous KB revision prefix: {ref}")
    if rows:
        commit = optional_text(rows[0].get("dolt_commit"), "dolt_commit")
        if not commit:
            raise KctxError(
                "incomplete", f"KB revision has no completed native graph commit: {ref}"
            )
        return DoltCommitId(commit)
    resolved = store.sql_read(f"SELECT hashof({sql_quote(ref)}) AS dolt_commit")
    if not resolved:
        raise KctxError("not-found", f"graph revision not found: {ref}")
    return DoltCommitId(json_text(resolved[0]["dolt_commit"], "Dolt revision"))


def source_paths(
    target: GraphNodeId,
    *,
    kb_root: Path,
    revision: str = "HEAD",
    limit: int = MAX_QUERY_LIMIT,
    context: QueryContext | None = None,
) -> JsonObject:
    """Exact inbound source paths, including illustrative edges, at one revision.

    Unlike uses(), these are edge origins, not the canonical home of each node.
    Revision resolution is constrained to the selected session's native history.
    """
    _limit(limit)
    predicate = _inbound_filter(target, include_illus=True)
    store, snapshot = _selection(kb_root, context)
    ref = _resolve_dolt_ref(store, snapshot, revision)
    source = f"edges AS OF {sql_quote(ref.val)} e"
    counts = store.sql_read(
        f"SELECT COUNT(DISTINCT e.src_path) AS n FROM {source} WHERE {predicate}"
    )
    rows = store.sql_read(
        f"SELECT DISTINCT e.src_path FROM {source} WHERE {predicate} ORDER BY e.src_path LIMIT {limit}"
    )
    paths: list[JsonValue] = [json_text(row["src_path"], "edge source path") for row in rows]
    return {
        "target": target.val,
        "revision": revision,
        "dolt_ref": ref.val,
        "total": dolt_int(counts[0]["n"]) if counts else 0,
        "returned": len(paths),
        "paths": paths,
    }


def diff(
    kb_sha_a: str,
    kb_sha_b: str,
    *,
    kb_root: Path,
    limit: int = 200,
    context: QueryContext | None = None,
) -> JsonObject:
    _limit(limit)
    with span("graph.diff", a=kb_sha_a, b=kb_sha_b):
        store, snapshot = _selection(kb_root, context)
        ref_a = _resolve_dolt_ref(store, snapshot, kb_sha_a)
        ref_b = ref_a if kb_sha_b == kb_sha_a else _resolve_dolt_ref(store, snapshot, kb_sha_b)
        summary = store.sql_read(
            "SELECT COALESCE(to_rel, from_rel) AS rel, diff_type, COUNT(*) AS n "
            f"FROM dolt_diff({sql_quote(ref_a.val)}, {sql_quote(ref_b.val)}, 'edges') "
            "GROUP BY rel, diff_type ORDER BY rel, diff_type"
        )
        sample = store.sql_read(
            "SELECT diff_type, COALESCE(to_rel, from_rel) AS rel, "
            "COALESCE(to_src_node, from_src_node) AS src_node, "
            "COALESCE(to_dst_node, from_dst_node) AS dst_node "
            f"FROM dolt_diff({sql_quote(ref_a.val)}, {sql_quote(ref_b.val)}, 'edges') "
            f"ORDER BY rel, diff_type LIMIT {int(limit)}"
        )
    return {
        "kb_sha_a": kb_sha_a,
        "kb_sha_b": kb_sha_b,
        "dolt_ref_a": ref_a.val,
        "dolt_ref_b": ref_b.val,
        "summary": [DiffSummary.model_validate(row).to_wire() for row in summary],
        "sample": [DiffSample.model_validate(row).to_wire() for row in sample],
        "sample_limit": limit,
    }


def check(kb_root: Path, *, sample_ids: list[GraphNodeId] | None = None) -> JsonObject:
    """Compare exact source bindings against one pinned native generation."""
    if sample_ids is not None and len(sample_ids) > 32:
        raise KctxError("malformed", "at most 32 graph check samples are supported")
    with span(
        "graph.check", sample_ids=[target.val for target in sample_ids] if sample_ids else None
    ):
        store = _store()
        snapshot = select_snapshot(store, kb_root)
        if snapshot.inputs is None:
            raise KctxError(
                "incomplete",
                "historical graph generation lacks input provenance; run graph sync before qualification",
            )
        identity_wire = object_value(
            snapshot.inputs.get("repository_identity"), "generation repository identity"
        )
        identity = RepositoryIdentity(
            json_text(identity_wire.get("checkout_name"), "checkout_name"),
            optional_text(identity_wire.get("origin_url"), "origin_url"),
        )
        sha = snapshot.state.kb_sha
        files = read_tree_at_sha(kb_root, sha)
        expected = expected_bindings(files, commit_date(kb_root, sha), identity)
        raw_edges = store.sql_read(
            f"SELECT * FROM edges AS OF {sql_quote(snapshot.data_commit.val)} "
            "WHERE rel='cites' OR (rel='references' AND raw IS NOT NULL) "
            f"ORDER BY edge_id LIMIT {MAX_GRAPH_EDGES + 1}"
        )
        raw_diagnostics = store.sql_read(
            f"SELECT details FROM extraction_diagnostics AS OF {sql_quote(snapshot.data_commit.val)} "
            f"ORDER BY diagnostic_id LIMIT {MAX_DIAGNOSTICS + 1}"
        )
        if len(raw_edges) > MAX_GRAPH_EDGES or len(raw_diagnostics) > MAX_DIAGNOSTICS:
            raise KctxError("incomplete", "graph parity input exceeds the extraction work bound")
        edges = [Edge.from_row(row) for row in raw_edges]
        diagnostics: list[ExtractionDiagnostic] = []
        for row in raw_diagnostics:
            try:
                value: object = json.loads(json_text(row.get("details"), "extraction diagnostic"))
            except json.JSONDecodeError as exc:
                raise KctxError(
                    "malformed", f"invalid stored extraction diagnostic: {exc}"
                ) from exc
            diagnostics.append(ExtractionDiagnostic.model_validate(value))
        parity = compare_bindings(expected, edges, diagnostics)
        inputs_match = generation_inputs(kb_root, kb_sha=sha).digest == snapshot.state.input_digest
        parity.update(
            {
                "kb_sha": sha,
                "input_digest": snapshot.state.input_digest,
                "inputs_match": inputs_match,
                "match": parity["match"] is True and inputs_match,
            }
        )
        uses_comparison: list[JsonValue] = []
        for target in sample_ids or []:
            graph_rows, total = _uses_rows(store, snapshot, target, include_illus=True)
            graph_paths = {row.src_home_path for row in graph_rows if row.src_home_path}
            file_res = uses_from_files(kb_root, parse_use_target(target.val), files)
            file_paths = {row["file"] for row in file_res["referrers"]}
            comparison: JsonObject = {
                "target": target.val,
                "graph_total": total,
                "file_total": len(file_paths),
                "graph_only": [path for path in sorted(graph_paths - file_paths)],
                "file_only": [path for path in sorted(file_paths - graph_paths)],
                "truncated": total > len(graph_rows),
            }
            uses_comparison.append(comparison)
    return {"parity": parity, "uses_comparison": uses_comparison}
