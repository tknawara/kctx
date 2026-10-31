"""Read-side traversal of the shadow graph: status/uses/impact/diff/check.

Every value interpolated into SQL goes through graph.quoting (sql_quote
always; validate_id as a second guard on anything meant to look like an id).
No agent-facing function here builds a query from unsanitized input.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import nav as nav_mod
from errors import KctxError

from kctx.graph.cite_loader import load_cite_module
from kctx.graph.dolt_store import DoltStore
from kctx.graph.extract import extract_graph, read_tree_at_sha
from kctx.graph.observability import span
from kctx.graph.quoting import sql_quote, validate_id
from kctx.graph.sync import dolt_db_dir, head_sha, latest_sync_state


def _store() -> DoltStore:
    return DoltStore(dolt_db_dir())


def status(kb_root: Path) -> Dict[str, Any]:
    with span("graph.status"):
        store = _store()
        if not store.is_initialized():
            return {"initialized": False, "graph_dir": str(dolt_db_dir())}
        st = latest_sync_state(store)
        counts = store.sql_read(
            "SELECT (SELECT COUNT(*) FROM nodes) AS node_count, (SELECT COUNT(*) FROM edges) AS edge_count"
        )
        kb_head = head_sha(kb_root)
        return {
            "initialized": True,
            "graph_dir": str(dolt_db_dir()),
            "sync_state": st,
            "node_count": counts[0]["node_count"] if counts else 0,
            "edge_count": counts[0]["edge_count"] if counts else 0,
            "kb_head": kb_head,
            "up_to_date": bool(st) and st.get("kb_sha") == kb_head,
        }


def uses(target: str, *, limit: int = 50, include_illus: bool = False) -> Dict[str, Any]:
    """Direct inbound edges into `target`, grouped by rel -- the graph
    analogue of `kctx uses`, but direction-aware (dst_node = target, not a
    literal-substring scan that can't tell an outgoing edge from an incoming
    one -- see RESULTS.md's query-1 false-positive finding)."""
    validate_id(target)
    with span("graph.uses", target=target, limit=limit):
        store = _store()
        illus_clause = "" if include_illus else "AND e.illus = 0"
        rows = store.sql_read(
            "SELECT e.src_node, e.rel, e.cite_kind, e.seen, n.kind AS src_kind, "
            "n.home_path AS src_home_path "
            "FROM edges e LEFT JOIN nodes n ON n.id = e.src_node "
            f"WHERE e.dst_node = {sql_quote(target)} {illus_clause} "
            "ORDER BY e.rel, e.src_node"
        )
    total = len(rows)
    limited = rows[:limit]
    by_rel: Dict[str, List[Dict[str, Any]]] = {}
    for r in limited:
        by_rel.setdefault(r["rel"], []).append(r)
    return {"target": target, "total": total, "returned": len(limited), "by_rel": by_rel}


def impact(
    target: str, *, depth: int = 3, rel: Optional[List[str]] = None, limit: int = 100
) -> Dict[str, Any]:
    """Transitive inbound dependents of `target` (change-impact traversal),
    bounded to `depth` hops -- the bound is what makes this cycle-safe: a
    cycle just means a node is reachable at more than one depth, not an
    infinite query, and the dedup below keeps each node's shortest path."""
    validate_id(target)
    if depth < 1 or depth > 10:
        raise KctxError("malformed", f"depth must be 1-10, got {depth}")
    rel_filter = ""
    if rel:
        for r in rel:
            validate_id(r)
        rel_list = ", ".join(sql_quote(r) for r in rel)
        rel_filter = f"AND e.rel IN ({rel_list})"
    with span("graph.impact", target=target, depth=depth, rel=rel):
        store = _store()
        q = f"""
        WITH RECURSIVE dep(node, depth, path) AS (
            SELECT {sql_quote(target)}, 0, CAST({sql_quote(target)} AS CHAR(4000))
            UNION
            SELECT e.src_node, dep.depth + 1, CONCAT(dep.path, ' <- ', e.src_node)
            FROM edges e JOIN dep ON e.dst_node = dep.node
            WHERE dep.depth < {int(depth)} AND e.illus = 0 {rel_filter}
        )
        SELECT d.node, d.depth, d.path, n.kind, n.home_path
        FROM dep d LEFT JOIN nodes n ON n.id = d.node
        WHERE d.depth > 0
        ORDER BY d.depth, d.node
        """
        rows = store.sql_read(q)
    seen: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if r["node"] not in seen:
            seen[r["node"]] = r
    dependents = list(seen.values())
    total = len(dependents)
    return {
        "target": target,
        "depth": depth,
        "total": total,
        "returned": min(total, limit),
        "dependents": dependents[:limit],
    }


def _resolve_dolt_ref(store: DoltStore, ref: str) -> str:
    validate_id(ref)
    if ref.upper() == "HEAD" or ref.upper() == "WORKING":
        return ref.upper()
    rows = store.sql_read(
        f"SELECT dolt_commit FROM kb_commits WHERE kb_sha LIKE {sql_quote(ref + '%')} "
        "ORDER BY seq DESC LIMIT 1"
    )
    if rows and rows[0].get("dolt_commit"):
        return rows[0]["dolt_commit"]
    return ref


def diff(kb_sha_a: str, kb_sha_b: str, *, limit: int = 200) -> Dict[str, Any]:
    with span("graph.diff", a=kb_sha_a, b=kb_sha_b):
        store = _store()
        ref_a = _resolve_dolt_ref(store, kb_sha_a)
        ref_b = _resolve_dolt_ref(store, kb_sha_b)
        summary = store.sql_read(
            "SELECT COALESCE(to_rel, from_rel) AS rel, diff_type, COUNT(*) AS n "
            f"FROM dolt_diff({sql_quote(ref_a)}, {sql_quote(ref_b)}, 'edges') "
            "GROUP BY rel, diff_type ORDER BY rel, diff_type"
        )
        sample = store.sql_read(
            "SELECT diff_type, COALESCE(to_rel, from_rel) AS rel, "
            "COALESCE(to_src_node, from_src_node) AS src_node, "
            "COALESCE(to_dst_node, from_dst_node) AS dst_node "
            f"FROM dolt_diff({sql_quote(ref_a)}, {sql_quote(ref_b)}, 'edges') "
            f"ORDER BY rel, diff_type LIMIT {int(limit)}"
        )
    return {
        "kb_sha_a": kb_sha_a, "kb_sha_b": kb_sha_b,
        "dolt_ref_a": ref_a, "dolt_ref_b": ref_b,
        "summary": summary, "sample": sample, "sample_limit": limit,
    }


def check(kb_root: Path, *, sample_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Shadow-parity gate (G1/G2 input): compares the graph's citation-
    binding count against a direct cite.py parse of the same files at the
    same kb sha, and compares `kctx graph uses` against `kctx uses` for a
    handful of sample ids."""
    with span("graph.check", sample_ids=sample_ids):
        store = _store()
        st = latest_sync_state(store)
        if not st:
            raise KctxError("not-found", "graph has no sync_state; run `kctx graph sync` first")
        sha = st["kb_sha"]

        cite_mod = load_cite_module()
        files = read_tree_at_sha(kb_root, sha)
        direct_by_path: Dict[str, int] = {}
        direct_illus = 0
        for path, text in files.items():
            for m in cite_mod.CITE_LINE_RE.finditer(text):
                direct_by_path[path] = direct_by_path.get(path, 0) + 1
                if cite_mod.is_illustrative(m.group("body")):
                    direct_illus += 1
        direct_total = sum(direct_by_path.values())

        # Skips are re-derived by the same extraction the sync ran at this
        # sha (not stored in Dolt: a skipped token has no row by definition).
        skips = extract_graph(files, sha, st.get("synced_at") or "", kb_root).stats.cite_tokens_dropped
        skips_by_path: Dict[str, int] = {}
        for sk in skips:
            skips_by_path[sk["src_path"]] = skips_by_path.get(sk["src_path"], 0) + 1

        rows = store.sql_read(
            "SELECT src_path, COUNT(*) AS n, SUM(illus) AS illus_n FROM edges "
            "WHERE rel = 'cites' AND src_line IS NOT NULL GROUP BY src_path"
        )
        graph_by_path = {r["src_path"]: int(r["n"]) for r in rows}
        graph_total = sum(graph_by_path.values())
        graph_illus = sum(int(r.get("illus_n") or 0) for r in rows)

        unexplained = []
        for path in sorted(set(direct_by_path) | set(graph_by_path)):
            d, g, k = direct_by_path.get(path, 0), graph_by_path.get(path, 0), skips_by_path.get(path, 0)
            if d != g + k:
                unexplained.append({"src_path": path, "direct": d, "graph": g, "skipped": k})

        parity = {
            "kb_sha": sha,
            "direct_cite_tokens": direct_total,
            "direct_illus_tokens": direct_illus,
            "graph_binding_rows": graph_total,
            "graph_illus_rows": graph_illus,
            "skipped_tokens": len(skips),
            "skips": skips,
            "unexplained": unexplained,
            "match": direct_total == graph_total + len(skips) and not unexplained and direct_illus == graph_illus + sum(1 for sk in skips if sk.get("illus")),
        }

        uses_comparison = []
        for target in sample_ids or []:
            graph_res = uses(target, limit=1000, include_illus=True)
            graph_paths = {
                r["src_home_path"]
                for rows in graph_res["by_rel"].values()
                for r in rows
                if r.get("src_home_path")
            }
            file_res = nav_mod.uses(kb_root, target)
            file_paths = {r["file"] for r in file_res["referrers"]}
            uses_comparison.append({
                "target": target,
                "graph_total": graph_res["total"],
                "file_total": len(file_paths),
                "graph_only": sorted(graph_paths - file_paths),
                "file_only": sorted(file_paths - graph_paths),
            })

    return {"parity": parity, "uses_comparison": uses_comparison}
