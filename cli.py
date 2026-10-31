"""Argument parsing and command dispatch for kctx.

Exit codes: 0 ok, 2 partial, 3 blocked, 1 error. Errors print a stable
category (see errors.KctxError) alongside the message, in both text and
--json output.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import admit as admit_mod
import corrections as corrections_mod
import dossiers as dossiers_mod
import inventory
import investigations as inv_mod
import ktlo as ktlo_mod
import nav
import proposals as proposals_mod
import runs as runs_mod
import signatures as sig_mod
import validate as validate_mod
from errors import KctxError
from storage import find_root


class ProposalListTable:
    """Special formatter for proposal list text output: compact table with STATUS, CREATED, TYPE, ID."""

    def __init__(self, proposals: List[Dict[str, Any]]):
        self.proposals = proposals


class DrainResult:
    """Special formatter for `stale --drain` text output: a one-line
    mechanical-writeback summary followed by the remaining judgment items,
    grouped by bucket with a file:line and the hint for what to do next."""

    def __init__(self, result: Dict[str, Any]):
        self.result = result


class ProposalSingleResult:
    """Special formatter for proposal add/set/gate text output: id, path, and
    any missing/warnings lines the underlying call returned."""

    def __init__(
        self,
        id: str,
        path: str,
        missing: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
    ):
        self.id = id
        self.path = path
        self.missing = missing or []
        self.warnings = warnings or []


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kctx")
    p.add_argument(
        "--json",
        action="store_true",
        help="emit structured JSON instead of readable text",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="validate inventory/proposal/run records")

    asset_p = sub.add_parser("asset")
    asset_sub = asset_p.add_subparsers(dest="asset_command", required=True)

    a_add = asset_sub.add_parser("add")
    a_add.add_argument("--kind", required=True)
    a_add.add_argument("--name", required=True)
    a_add.add_argument("--id")
    a_add.add_argument("--alias", dest="aliases", action="append", default=[])
    a_add.add_argument("--locator", default="")
    a_add.add_argument("--owner", default="unknown")
    a_add.add_argument("--owner-source", dest="owner_source", default="")
    a_add.add_argument("--lifecycle", default="active")
    a_add.add_argument("--inspect", default="")
    a_add.add_argument("--project", dest="projects", action="append", default=[])
    a_add.add_argument("--verified-at", dest="verified_at")
    a_add.add_argument("--ttl")
    a_add.add_argument("--notes", default="")

    a_show = asset_sub.add_parser("show")
    a_show.add_argument("ident")

    a_list = asset_sub.add_parser("list")
    a_list.add_argument("--kind")
    a_list.add_argument("--project")

    rel_p = sub.add_parser("rel")
    rel_sub = rel_p.add_subparsers(dest="rel_command", required=True)
    r_add = rel_sub.add_parser("add")
    r_add.add_argument("--type", required=True)
    r_add.add_argument("--from", dest="from_", required=True)
    r_add.add_argument("--to", required=True)
    r_add.add_argument("--id")
    r_add.add_argument("--status", default="explicit")
    r_add.add_argument("--evidence", dest="evidence", action="append", default=[])
    r_add.add_argument("--applicability", default="")

    impact_p = sub.add_parser("impact")
    impact_p.add_argument("asset")
    impact_p.add_argument("--depth", type=int, default=2)

    home_p = sub.add_parser("home")
    home_p.add_argument("ident")

    context_p = sub.add_parser("context")
    context_p.add_argument("ident")
    context_p.add_argument("--depth", type=int, default=2)

    stale_p = sub.add_parser("stale")
    stale_p.add_argument("--project")
    stale_p.add_argument(
        "--offline",
        action="store_true",
        help="no network: cite stale --offline plus kctx's own offline checks",
    )
    stale_p.add_argument(
        "--drain",
        action="store_true",
        help="write back cite check --touch --mark, then report remaining judgment items",
    )
    stale_p.add_argument(
        "paths",
        nargs="*",
        help="explicit paths for --drain when --project is not given",
    )

    admit_p = sub.add_parser("admit")
    admit_p.add_argument(
        "pr_ref", nargs="?", help="PR url or org/repo#N, as a shortcut for --repo"
    )
    admit_p.add_argument("--repo", help="org/repo to sweep from its cursor to head")
    admit_p.add_argument(
        "--since", help="sha or date; required the first time --repo has no cursor"
    )
    admit_p.add_argument("--dry-run", dest="dry_run", action="store_true")

    dossier_p = sub.add_parser("dossier")
    dossier_sub = dossier_p.add_subparsers(dest="dossier_command", required=True)
    d_new = dossier_sub.add_parser("new")
    d_new.add_argument("asset")
    d_archive = dossier_sub.add_parser("archive")
    d_archive.add_argument("asset")
    d_archive.add_argument("--force", action="store_true")

    ktlo_p = sub.add_parser("ktlo")
    ktlo_sub = ktlo_p.add_subparsers(dest="ktlo_command", required=True)
    k_new = ktlo_sub.add_parser("new")
    k_new.add_argument("ticket")
    k_new.add_argument("--title", required=True)
    k_new.add_argument("--asset", dest="assets", action="append", default=[])
    k_promote = ktlo_sub.add_parser("promote")
    k_promote.add_argument("ticket")
    k_promote.add_argument("project")

    inv_p = sub.add_parser("inv")
    inv_sub = inv_p.add_subparsers(dest="inv_command", required=True)
    i_new = inv_sub.add_parser("new")
    i_new.add_argument("slug")
    i_new.add_argument("--trigger", required=True)
    i_new.add_argument("--title")
    i_new.add_argument("--ticket", dest="tickets", action="append", default=[])
    i_new.add_argument("--alert", dest="alerts", action="append", default=[])
    i_new.add_argument("--asset", dest="assets", action="append", default=[])
    i_new.add_argument("--window", dest="windows", action="append", default=[])
    i_new.add_argument("--impact-summary", dest="impact_summary", default="")
    i_new.add_argument(
        "--created",
        help="backfill a historical creation date (YYYY-MM-DD); defaults to today",
    )
    i_list = inv_sub.add_parser("list")
    i_list.add_argument("--open", dest="open_only", action="store_true")
    i_list.add_argument("--asset")
    i_show = inv_sub.add_parser("show")
    i_show.add_argument("id")
    i_conclude = inv_sub.add_parser("conclude")
    i_conclude.add_argument("id")
    i_promote = inv_sub.add_parser("promote")
    i_promote.add_argument("id")
    i_promote.add_argument("project")

    sig_p = sub.add_parser("sig")
    sig_sub = sig_p.add_subparsers(dest="sig_command", required=True)
    s_new = sig_sub.add_parser("new")
    s_new.add_argument("slug")
    s_new.add_argument("--title")
    s_new.add_argument("--match", dest="match", action="append", default=[])
    s_new.add_argument("--match-where", dest="match_where", default="")
    s_new.add_argument("--asset", dest="assets", action="append", default=[])
    s_new.add_argument("--owner-group", dest="owner_group")
    s_new.add_argument("--status", default="suspected")
    s_new.add_argument("--first-seen", dest="first_seen")
    s_new.add_argument("--last-seen", dest="last_seen")
    s_new.add_argument("--workaround", default="")
    s_new.add_argument("--fix", dest="fix", action="append", default=[])
    s_new.add_argument("--fixed-at", dest="fixed_at")
    s_new.add_argument("--verified-at", dest="verified_at")
    s_new.add_argument("--ttl")
    s_list = sig_sub.add_parser("list")
    s_show = sig_sub.add_parser("show")
    s_show.add_argument("id")

    match_p = sub.add_parser("match")
    match_p.add_argument("text")

    timeline_p = sub.add_parser("timeline")
    timeline_p.add_argument("ident")

    uses_p = sub.add_parser("uses")
    uses_p.add_argument("target")

    retract_p = sub.add_parser("retract")
    retract_p.add_argument("target")
    retract_p.add_argument("--reason", required=True)
    retract_p.add_argument(
        "--kind", required=True, choices=sorted(["retract", "dispute", "supersede"])
    )
    retract_p.add_argument("--by-replacement", dest="by_replacement")

    run_p = sub.add_parser("run")
    run_sub = run_p.add_subparsers(dest="run_command", required=True)
    rn = run_sub.add_parser("new")
    rn.add_argument("--project", required=True)
    rn.add_argument(
        "--mode", required=True, choices=sorted(["advice", "review", "authoring"])
    )
    rn.add_argument("--task", required=True)

    observe_p = sub.add_parser("observe")
    observe_p.add_argument("run")
    observe_p.add_argument("--system", required=True)
    observe_p.add_argument("--locator", required=True)
    observe_p.add_argument("--asset")
    observe_p.add_argument("--revision")
    observe_p.add_argument("--role", default="note")
    observe_p.add_argument("--status", default="ok")
    observe_p.add_argument("--cmd", dest="observed_command")
    observe_p.add_argument("--environment")
    observe_p.add_argument("--evidence")
    observe_p.add_argument("--note")

    cover_p = sub.add_parser("cover")
    cover_p.add_argument("run")
    cover_p.add_argument("--item", required=True)
    cover_p.add_argument("--outcome", required=True)
    cover_p.add_argument("--evidence", dest="evidence", action="append", default=[])
    cover_p.add_argument("--reason", default="")

    check_p = sub.add_parser("check")
    check_p.add_argument("run")
    check_p.add_argument("--require", dest="require", action="append", default=[])

    resume_p = sub.add_parser("resume")
    resume_p.add_argument("run")

    checkpoint_p = sub.add_parser("checkpoint")
    checkpoint_p.add_argument("run")
    checkpoint_p.add_argument("--note", required=True)

    proposal_p = sub.add_parser("proposal")
    proposal_sub = proposal_p.add_subparsers(dest="proposal_command", required=True)

    p_add = proposal_sub.add_parser("add")
    p_add.add_argument("--kind", required=True)
    p_add.add_argument("--origin", required=True)
    p_add.add_argument("--type", dest="type", action="append", default=[])
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--target", dest="target", action="append", default=[])
    p_add.add_argument("--context", required=True)
    p_add.add_argument("--evidence", required=True)
    p_add.add_argument("--change", required=True)
    p_add.add_argument("--why", required=True)
    p_add.add_argument("--research", default="")
    p_add.add_argument("--alternatives", default="")
    p_add.add_argument(
        "--gates", default="", help="a markdown table, or a path to a file holding one"
    )
    p_add.add_argument("--impact", default="")
    p_add.add_argument("--plan", default="")
    p_add.add_argument("--ref", dest="references", action="append", default=[])
    p_add.add_argument("--project")
    p_add.add_argument("--session", dest="source_session")
    p_add.add_argument("--proposed-by", dest="proposed_by")
    p_add.add_argument("--requested-by", dest="requested_by")
    p_add.add_argument("--force", action="store_true")

    p_list = proposal_sub.add_parser("list")
    p_list.add_argument("--status")
    p_list.add_argument("--kind")
    p_list.add_argument("--pending-gates", dest="pending_gates", action="store_true")

    p_set = proposal_sub.add_parser("set")
    p_set.add_argument("id")
    p_set.add_argument("--status")
    p_set.add_argument("--by")
    p_set.add_argument("--note")
    p_set.add_argument("--superseded-by", dest="superseded_by")
    p_set.add_argument("--origin")
    p_set.add_argument("--proposed-by", dest="proposed_by")
    p_set.add_argument("--requested-by", dest="requested_by")
    p_set.add_argument("--swept-at", dest="swept_at")
    p_set.add_argument("--landed", dest="landed_add", action="append", default=None)

    p_gate = proposal_sub.add_parser("gate")
    p_gate.add_argument("id")
    p_gate.add_argument("gate")
    p_gate.add_argument("--outcome", required=True, choices=["pass", "fail", "unk"])
    p_gate.add_argument("--evidence", required=True)
    p_gate.add_argument("--by")
    p_gate.add_argument("--rev")

    p_show = proposal_sub.add_parser("show")
    p_show.add_argument("id")

    # M2 shadow-mode citation/relationship graph (Dolt), plus the log-replay
    # command for its observability. These are the only kctx subcommands
    # backed by third-party deps (pydantic/structlog), so the import is
    # guarded: every existing test calls cli.main() directly under plain
    # python3 with no venv, and must keep working with neither package
    # installed. Under the real `kctx` wrapper (always `uv run`) the import
    # succeeds and both subcommands register normally.
    try:
        from kctx.graph.cli_graph import add_graph_subparser
        from kctx.graph.observability import add_logs_subparser
    except ImportError:
        pass
    else:
        add_graph_subparser(sub)
        add_logs_subparser(sub)

    return p


def dispatch(args: argparse.Namespace, root) -> Tuple[Any, int]:
    cmd = args.command

    if cmd == "validate":
        res = validate_mod.validate(root)
        return res, (0 if res["ok"] else 1)

    if cmd == "asset":
        if args.asset_command == "add":
            res = inventory.asset_add(
                root,
                kind=args.kind,
                name=args.name,
                id=args.id,
                aliases=args.aliases,
                locator=args.locator,
                owner=args.owner,
                owner_source=args.owner_source,
                lifecycle=args.lifecycle,
                inspect=args.inspect,
                projects=args.projects,
                verified_at=args.verified_at,
                ttl=args.ttl,
                notes=args.notes,
            )
            return res, 0
        if args.asset_command == "show":
            return inventory.asset_show(root, args.ident), 0
        if args.asset_command == "list":
            return inventory.asset_list(root, kind=args.kind, project=args.project), 0

    if cmd == "rel" and args.rel_command == "add":
        res = inventory.rel_add(
            root,
            type=args.type,
            from_=args.from_,
            to=args.to,
            id=args.id,
            status=args.status,
            evidence=args.evidence,
            applicability=args.applicability,
        )
        return res, 0

    if cmd == "impact":
        return inventory.impact(root, args.asset, depth=args.depth), 0

    if cmd == "home":
        res = nav.home(root, args.ident)
        return res, (0 if res["candidates"] else 2)

    if cmd == "context":
        return nav.context(root, args.ident, depth=args.depth), 0

    if cmd == "stale":
        if args.drain:
            res = nav.drain(root, project=args.project, paths=args.paths or None)
            if not res["citations_available"]:
                code = 3
            else:
                code = 0 if res["total_remaining"] == 0 else 2
            return res, code
        return nav.stale(root, project=args.project, offline=args.offline), 0

    if cmd == "admit":
        res = admit_mod.admit(
            root,
            repo=args.repo,
            pr_ref=args.pr_ref,
            since=args.since,
            dry_run=args.dry_run,
        )
        return res, res["exit_code"]

    if cmd == "dossier":
        if args.dossier_command == "new":
            res = dossiers_mod.new(root, args.asset)
            return res, 0
        if args.dossier_command == "archive":
            res = dossiers_mod.archive(root, args.asset, force=args.force)
            return res, 0

    if cmd == "ktlo":
        if args.ktlo_command == "new":
            res = ktlo_mod.new(
                root, ticket=args.ticket, title=args.title, assets=args.assets
            )
            return res, 0
        if args.ktlo_command == "promote":
            res = ktlo_mod.promote(root, args.ticket, args.project)
            return res, 0

    if cmd == "inv":
        if args.inv_command == "new":
            res = inv_mod.new(
                root,
                args.slug,
                trigger=args.trigger,
                title=args.title,
                tickets=args.tickets,
                alerts=args.alerts,
                assets=args.assets,
                windows=args.windows,
                impact_summary=args.impact_summary,
                created=args.created,
            )
            return res, 0
        if args.inv_command == "list":
            res = inv_mod.list_investigations(
                root, open_only=args.open_only, asset=args.asset
            )
            return res, 0
        if args.inv_command == "show":
            return inv_mod.show(root, args.id), 0
        if args.inv_command == "conclude":
            res = inv_mod.conclude(root, args.id)
            return res, 0
        if args.inv_command == "promote":
            res = inv_mod.promote(root, args.id, args.project)
            return res, 0

    if cmd == "sig":
        if args.sig_command == "new":
            res = sig_mod.new(
                root,
                args.slug,
                title=args.title,
                match=args.match,
                match_where=args.match_where,
                assets=args.assets,
                owner_group=args.owner_group,
                status=args.status,
                first_seen=args.first_seen,
                last_seen=args.last_seen,
                workaround=args.workaround,
                fix=args.fix,
                fixed_at=args.fixed_at,
                verified_at=args.verified_at,
                ttl=args.ttl,
            )
            return res, 0
        if args.sig_command == "list":
            return sig_mod.list_signatures(root), 0
        if args.sig_command == "show":
            return sig_mod.show(root, args.id), 0

    if cmd == "match":
        res = nav.match(root, args.text)
        has_hits = bool(res["signatures"] or res["investigations"] or res["ktlo"])
        return res, (0 if has_hits else 2)

    if cmd == "timeline":
        return nav.timeline(root, args.ident), 0

    if cmd == "uses":
        res = nav.uses(root, args.target)
        return res, (0 if res["referrers"] else 2)

    if cmd == "retract":
        res = corrections_mod.retract(
            root,
            args.target,
            reason=args.reason,
            kind=args.kind,
            by_replacement=args.by_replacement,
        )
        return res, 0

    if cmd == "run" and args.run_command == "new":
        res = runs_mod.new_run(
            root, project=args.project, mode=args.mode, task=args.task
        )
        return res, 0

    if cmd == "observe":
        res = runs_mod.add_observation(
            root,
            args.run,
            system=args.system,
            locator=args.locator,
            asset=args.asset,
            revision=args.revision,
            role=args.role,
            status=args.status,
            command=args.observed_command,
            environment=args.environment,
            evidence=args.evidence,
            note=args.note,
        )
        return res, 0

    if cmd == "cover":
        res = runs_mod.cover(
            root,
            args.run,
            item=args.item,
            outcome=args.outcome,
            evidence=args.evidence,
            reason=args.reason,
        )
        return res, 0

    if cmd == "check":
        res = runs_mod.check(root, args.run, require=args.require)
        code = {"ready": 0, "partial": 2, "blocked": 3}[res["readiness"]]
        return res, code

    if cmd == "resume":
        return runs_mod.resume(root, args.run), 0

    if cmd == "checkpoint":
        return runs_mod.checkpoint(root, args.run, note=args.note), 0

    if cmd == "proposal":
        if args.proposal_command == "add":
            type_val = None
            if args.type:
                type_val = args.type[0] if len(args.type) == 1 else list(args.type)
            gates_text = args.gates
            if gates_text:
                gates_path = Path(gates_text)
                if gates_path.is_file():
                    gates_text = gates_path.read_text(encoding="utf-8")
            res = proposals_mod.add(
                root,
                kind=args.kind,
                origin=args.origin,
                type=type_val,
                title=args.title,
                target=args.target,
                context=args.context,
                evidence=args.evidence,
                change=args.change,
                why=args.why,
                research=args.research,
                alternatives=args.alternatives,
                gates=gates_text,
                impact=args.impact,
                plan=args.plan,
                references=args.references,
                project=args.project,
                source_session=args.source_session,
                proposed_by=args.proposed_by,
                requested_by=args.requested_by,
                force=args.force,
            )
            return res, 0
        if args.proposal_command == "list":
            proposals = proposals_mod.list_proposals(
                root,
                status=args.status,
                kind=args.kind,
                pending_gates=args.pending_gates,
            )
            return proposals, 0
        if args.proposal_command == "set":
            res = proposals_mod.set_status(
                root,
                args.id,
                status=args.status,
                by=args.by,
                note=args.note,
                superseded_by=args.superseded_by,
                origin=args.origin,
                proposed_by=args.proposed_by,
                requested_by=args.requested_by,
                swept_at=args.swept_at,
                landed_add=args.landed_add,
            )
            return res, 0
        if args.proposal_command == "gate":
            res = proposals_mod.gate(
                root,
                args.id,
                args.gate,
                outcome=args.outcome,
                evidence=args.evidence,
                by=args.by,
                rev=args.rev,
            )
            return res, 0
        if args.proposal_command == "show":
            return proposals_mod.show(root, args.id), 0

    if cmd == "graph":
        from kctx.graph.cli_graph import dispatch as graph_dispatch

        return graph_dispatch(args, root)

    if cmd == "logs":
        from kctx.graph.observability import logs_dispatch

        return logs_dispatch(args)

    raise KctxError("malformed", f"unhandled command {cmd!r}")


def render_text(result: Any) -> None:
    if isinstance(result, DrainResult):
        res = result.result
        if not res["citations_available"]:
            print(f"citations unavailable: {res.get('note')}")
            return
        touched_files = res["touched_files"]
        print(f"touched (fresh/moved/marked write-back): {len(touched_files)} file(s)")
        for tf in touched_files:
            for ch in tf["changes"]:
                print(f"  {tf['file']}:{ch['line_no']}")
                print(f"    - {ch['before']}")
                print(f"    + {ch['after']}")
        if res["total_remaining"] == 0:
            print("nothing remains")
        else:
            for bucket, items in res["remaining"].items():
                if not items:
                    continue
                print(f"{bucket} ({len(items)}) -- {nav.DRAIN_BUCKET_HINTS[bucket]}")
                for item in items:
                    print(f"  {item['file']}:{item['line_no']} ({item['kind']})")
            print(f"-- {res['total_remaining']} item(s) remaining")
        open_corrections = res.get("open_corrections") or []
        if open_corrections:
            print(f"open corrections ({res['open_corrections_total']}):")
            for row in open_corrections:
                print(
                    f"  {row['file']} -- {row['target']}: {row['referrer']} "
                    f"({row['status']})"
                )
    elif isinstance(result, ProposalListTable):
        proposals = result.proposals
        if not proposals:
            print("(none)")
            return

        headers = ["STATUS", "CREATED", "TYPE", "ORIGIN", "ID"]
        rows = []
        for p in proposals:
            rows.append(
                [
                    str(p.get("status", "")),
                    str(p.get("created", "")),
                    str(p.get("type", "") or ""),
                    str(p.get("origin", "") or ""),
                    str(p.get("id", "")),
                ]
            )

        if rows:
            col_widths = [len(h) for h in headers]
            for row in rows:
                for i, cell in enumerate(row):
                    col_widths[i] = max(col_widths[i], len(cell))

            header_line = "  ".join(
                h.ljust(col_widths[i]) for i, h in enumerate(headers)
            )
            print(header_line)
            print("  ".join("-" * w for w in col_widths))
            for row in rows:
                print(
                    "  ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row))
                )
    elif isinstance(result, ProposalSingleResult):
        print(f"id: {result.id}")
        print(f"path: {result.path}")
        for m in result.missing:
            print(f"missing for review: {m}")
        for w in result.warnings:
            print(f"warning: {w}")
    elif isinstance(result, list):
        if not result:
            print("(none)")
        for item in result:
            if isinstance(item, dict):
                print(" | ".join(f"{k}={v}" for k, v in item.items()))
            else:
                print(item)
    elif isinstance(result, dict):
        for k, v in result.items():
            print(f"{k}: {v}")
    else:
        print(result)


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    as_json = args.json

    try:
        root = find_root()
        result, code = dispatch(args, root)
    except KctxError as e:
        payload = {"error": e.category, "message": e.message}
        if as_json:
            print(json.dumps(payload))
        else:
            print(f"error ({e.category}): {e.message}", file=sys.stderr)
        return 1

    if not as_json and args.command == "stale" and args.drain:
        result = DrainResult(result)

    if not as_json and args.command == "proposal":
        if args.proposal_command == "list":
            result = ProposalListTable(result)
        elif args.proposal_command == "add":
            path_str = (
                result["path"] if isinstance(result, dict) and "path" in result else ""
            )
            proposal_id = result.get("id", "") if isinstance(result, dict) else ""
            if path_str:
                path_rel = (
                    Path(path_str).relative_to(root)
                    if Path(path_str).is_absolute()
                    else path_str
                )
            else:
                path_rel = ""
            missing = result.get("missing", []) if isinstance(result, dict) else []
            result = ProposalSingleResult(proposal_id, str(path_rel), missing=missing)
        elif args.proposal_command == "set":
            proposal_id = result.get("id", "") if isinstance(result, dict) else ""
            warnings = result.get("warnings", []) if isinstance(result, dict) else []
            if proposal_id:
                found = proposals_mod.load(root, proposal_id)
                path_str = str(found["path"])
                path_rel = (
                    Path(path_str).relative_to(root)
                    if Path(path_str).is_absolute()
                    else path_str
                )
            else:
                path_rel = ""
            result = ProposalSingleResult(proposal_id, str(path_rel), warnings=warnings)

    if as_json:
        print(json.dumps(result, indent=2, default=str))
    elif args.command in ("graph", "logs"):
        from kctx.graph.render import render_graph_text

        render_graph_text(args, result)
    else:
        render_text(result)
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
