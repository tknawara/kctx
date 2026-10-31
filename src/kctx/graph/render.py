"""Compact human-readable output for `kctx graph ...` and `kctx logs`.

Default text output is deliberately small (token-aware for agents): totals
first, then at most the rows each command's own --limit allowed, one line
per row. `--json` still returns the full structure.
"""

from typing import Any

from kctx.graph.observability import format_event_line


def _short(node: str, width: int = 110) -> str:
    return node if len(node) <= width else node[: width - 1] + "…"


def render_graph_text(args: Any, result: Any) -> None:
    if args.command == "logs":
        if not result:
            print("(no events)")
        for e in result:
            print(format_event_line(e))
        return

    cmd = args.graph_command
    if cmd == "sync":
        extra = f", {result['commits_replayed']} commit(s) replayed" if "commits_replayed" in result else ""
        print(f"{result['status']}: kb {result['kb_sha'][:10]} -> dolt {result['dolt_commit']} "
              f"({result['node_count']} nodes, {result['edge_count']} edges{extra})")
    elif cmd == "status":
        if not result["initialized"]:
            print(f"graph not initialized at {result['graph_dir']}; run `kctx graph sync`")
            return
        st = result["sync_state"] or {}
        state = "current" if result["up_to_date"] else f"STALE (kb HEAD {result['kb_head'][:10]})"
        print(f"graph {result['graph_dir']}")
        print(f"synced kb {str(st.get('kb_sha'))[:10]} at {st.get('synced_at')} -- {state}")
        print(f"{result['node_count']} nodes, {result['edge_count']} edges")
    elif cmd == "uses":
        print(f"{result['target']}: {result['total']} inbound edge(s)"
              + (f" (showing {result['returned']})" if result["returned"] < result["total"] else ""))
        for rel, rows in result["by_rel"].items():
            print(f"  {rel} ({len(rows)})")
            for r in rows:
                print(f"    [{r.get('src_kind') or '?'}] {_short(r['src_node'])}")
    elif cmd == "impact":
        print(f"{result['target']}: {result['total']} dependent(s) within depth {result['depth']}"
              + (f" (showing {result['returned']})" if result["returned"] < result["total"] else ""))
        for d in result["dependents"]:
            print(f"  d{d['depth']} [{d.get('kind') or '?'}] {_short(d['node'])}")
    elif cmd == "diff":
        print(f"{result['kb_sha_a']} -> {result['kb_sha_b']}")
        for row in result["summary"]:
            print(f"  {row['rel']:<22} {row['diff_type']:<9} {row['n']}")
    elif cmd == "check":
        p = result["parity"]
        verdict = "MATCH" if p["match"] else "MISMATCH"
        print(f"parity {verdict} at kb {p['kb_sha'][:10]}: {p['direct_cite_tokens']} cite tokens parsed directly = "
              f"{p['graph_binding_rows']} binding rows + {p['skipped_tokens']} skipped "
              f"(illus {p['direct_illus_tokens']} direct / {p['graph_illus_rows']} in graph)")
        for sk in p["skips"]:
            print(f"  skip {sk['src_path']}:{sk['line']} {sk['reason']}")
        for u in p["unexplained"]:
            print(f"  UNEXPLAINED {u['src_path']}: direct={u['direct']} graph={u['graph']} skipped={u['skipped']}")
        for c in result["uses_comparison"]:
            print(f"uses {c['target']}: graph {c['graph_total']} vs `kctx uses` {c['file_total']}")
            for x in c["graph_only"]:
                print(f"  graph-only {x}")
            for x in c["file_only"]:
                print(f"  file-only  {x}")
    else:
        print(result)
