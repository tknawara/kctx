"""argparse wiring for `kctx graph ...`, called from cli.py's own
build_parser()/dispatch() via the one registration hunk added there. Kept
here (not inlined into cli.py) so cli.py's own diff stays a single small
addition: import this module, call add_graph_subparser(sub) while building
the parser, and call dispatch(args, root) when args.command == "graph".
"""

import argparse
from pathlib import Path
from typing import Any, Tuple

from errors import KctxError

from graph import queries as queries_mod
from graph import sync as sync_mod


def add_graph_subparser(sub: "argparse._SubParsersAction") -> None:
    graph_p = sub.add_parser(
        "graph", help="M2 shadow-mode citation/relationship graph (Dolt); files remain authoritative"
    )
    graph_sub = graph_p.add_subparsers(dest="graph_command", required=True)

    sync_p = graph_sub.add_parser("sync", help="extract the graph from tracked files and replay into Dolt")
    sync_p.add_argument("--rebuild", action="store_true", help="delete and recreate the Dolt db first")
    sync_p.add_argument(
        "--history", type=int, default=None, metavar="N",
        help="also replay the last N first-parent kb commits, so as-of/diff work immediately",
    )

    graph_sub.add_parser("status", help="sync state, node/edge counts, whether the graph is current")

    uses_p = graph_sub.add_parser("uses", help="direct inbound edges into an id, grouped by relationship")
    uses_p.add_argument("target")
    uses_p.add_argument("--limit", type=int, default=50)
    uses_p.add_argument("--include-illus", action="store_true", help="include illustrative citations")

    impact_p = graph_sub.add_parser("impact", help="transitive inbound dependents of an id")
    impact_p.add_argument("target")
    impact_p.add_argument("--depth", type=int, default=3)
    impact_p.add_argument("--rel", action="append", default=None, help="restrict traversal to these rel types")
    impact_p.add_argument("--limit", type=int, default=100)

    diff_p = graph_sub.add_parser("diff", help="edges added/removed/modified between two kb shas")
    diff_p.add_argument("kb_sha_a")
    diff_p.add_argument("kb_sha_b")
    diff_p.add_argument("--limit", type=int, default=200)

    check_p = graph_sub.add_parser(
        "check", help="shadow-parity: binding count vs a direct cite.py parse, plus a uses() comparison"
    )
    check_p.add_argument(
        "--sample", dest="sample_ids", action="append", default=None,
        help="an id to compare `kctx graph uses` against `kctx uses` for (repeatable)",
    )


def dispatch(args: argparse.Namespace, root: Path) -> Tuple[Any, int]:
    cmd = args.graph_command
    if cmd == "sync":
        return sync_mod.sync(root, rebuild=args.rebuild, history=args.history), 0
    if cmd == "status":
        return queries_mod.status(root), 0
    if cmd == "uses":
        res = queries_mod.uses(args.target, limit=args.limit, include_illus=args.include_illus)
        return res, (0 if res["total"] else 2)
    if cmd == "impact":
        res = queries_mod.impact(args.target, depth=args.depth, rel=args.rel, limit=args.limit)
        return res, (0 if res["total"] else 2)
    if cmd == "diff":
        return queries_mod.diff(args.kb_sha_a, args.kb_sha_b, limit=args.limit), 0
    if cmd == "check":
        res = queries_mod.check(root, sample_ids=args.sample_ids)
        return res, (0 if res["parity"]["match"] else 2)
    raise KctxError("malformed", f"unhandled graph subcommand {cmd!r}")
