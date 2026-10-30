"""`kctx validate`: schema/enum checks, id uniqueness, relationship endpoint
resolution, and the accepted/applied-requires-decided_by rule.

Never touches legacy per-project journal files (README.md, STATUS.md, etc.) —
only inventory/, proposals/, and runs/.
"""

import re
from pathlib import Path
from typing import Any, Dict, List

import corrections as corrections_mod
import dossiers as dossiers_mod
import investigations as inv_mod
import ktlo as ktlo_mod
import signatures as sig_mod
from errors import KctxError
from inventory import load_all_assets, load_all_relationships
from nav import all_runbook_paths, project_dirs, regression_flags
from proposals import all_paths, has_landed_evidence, parse
from records import (
    ASSET_KINDS,
    CORRECTION_ROW_STATUSES,
    INVESTIGATION_STATUSES,
    INVESTIGATION_TRIGGERS,
    KTLO_STATUSES,
    LIFECYCLES,
    PROPOSAL_DECIDED_STATUSES,
    PROPOSAL_KINDS,
    PROPOSAL_STATUSES,
    REL_STATUSES,
    REL_TYPES,
    RUNBOOK_LAYERS,
    SIGNATURE_STATUSES,
)
from storage import read_frontmatter, split_list_value

_CORRECTION_ROW_STATUS_RE = re.compile(
    "^(" + "|".join(re.escape(s) for s in CORRECTION_ROW_STATUSES) + "|unchanged:.+)$"
)


def _problem(category: str, where: str, message: str) -> Dict[str, str]:
    return {"category": category, "where": where, "message": message}


def validate(root: Path) -> Dict[str, Any]:
    problems: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []

    assets = load_all_assets(root)
    seen_asset_ids = set()
    for a in assets:
        if a.id in seen_asset_ids:
            problems.append(_problem("conflict", a.id, "duplicate asset id"))
        seen_asset_ids.add(a.id)
        if a.kind not in ASSET_KINDS:
            problems.append(_problem("malformed", a.id, f"bad kind {a.kind!r}"))
        if a.lifecycle not in LIFECYCLES:
            problems.append(
                _problem("malformed", a.id, f"bad lifecycle {a.lifecycle!r}")
            )
        if not a.owner:
            problems.append(
                _problem("malformed", a.id, "owner must be set (use 'unknown')")
            )

    asset_id_set = {a.id for a in assets}
    rels = load_all_relationships(root)
    seen_rel_ids = set()
    for r in rels:
        if r.id in seen_rel_ids:
            problems.append(_problem("conflict", r.id, "duplicate relationship id"))
        seen_rel_ids.add(r.id)
        if r.type not in REL_TYPES:
            problems.append(_problem("malformed", r.id, f"bad type {r.type!r}"))
        if r.status not in REL_STATUSES:
            problems.append(_problem("malformed", r.id, f"bad status {r.status!r}"))
        if r.from_ not in asset_id_set:
            problems.append(
                _problem(
                    "incomplete",
                    r.id,
                    f"endpoint from={r.from_!r} does not resolve to a known asset",
                )
            )
        if r.to not in asset_id_set:
            problems.append(
                _problem(
                    "incomplete",
                    r.id,
                    f"endpoint to={r.to!r} does not resolve to a known asset",
                )
            )

    seen_proposal_ids = set()
    for p in all_paths(root):
        parsed = parse(p.read_text(encoding="utf-8"))
        fm, body = parsed["frontmatter"], parsed["body"]
        pid = fm.get("id")
        if pid in seen_proposal_ids:
            problems.append(_problem("conflict", str(p), "duplicate proposal id"))
        seen_proposal_ids.add(pid)
        if fm.get("kind") not in PROPOSAL_KINDS:
            problems.append(_problem("malformed", pid, f"bad kind {fm.get('kind')!r}"))
        if fm.get("status") not in PROPOSAL_STATUSES:
            problems.append(
                _problem("malformed", pid, f"bad status {fm.get('status')!r}")
            )
        if fm.get("status") in PROPOSAL_DECIDED_STATUSES and not fm.get("decided_by"):
            problems.append(
                _problem(
                    "incomplete", pid, f"status={fm.get('status')} requires decided_by"
                )
            )
        if fm.get("status") in ("applied", "verified") and not has_landed_evidence(
            fm, body
        ):
            problems.append(
                _problem(
                    "incomplete",
                    pid,
                    f"status={fm.get('status')} requires a repo@sha in `landed` "
                    "or the Decision log",
                )
            )
        # A new-format filing (directory home) always carries `origin`; a
        # proposal filed before the evolve skill existed may not, and an
        # optional Context-section backfill can only do so much -- warn
        # rather than block.
        if p.name == "proposal.md" and not fm.get("origin"):
            warnings.append(_problem("warn", pid, "new-format proposal missing origin"))

    seen_ticket_ids = set()
    ktlo_count = 0
    for p in ktlo_mod.all_paths(root):
        ktlo_count += 1
        try:
            fm = ktlo_mod.parse(p.read_text(encoding="utf-8"))["frontmatter"]
        except KctxError as e:
            problems.append(_problem("malformed", str(p), e.message))
            continue
        ticket = fm.get("ticket")
        if not ticket:
            problems.append(_problem("malformed", str(p), "missing ticket"))
        else:
            if ticket in seen_ticket_ids:
                problems.append(
                    _problem("conflict", str(p), f"duplicate ticket {ticket!r}")
                )
            seen_ticket_ids.add(ticket)
        if fm.get("status") not in KTLO_STATUSES:
            problems.append(
                _problem("malformed", str(p), f"bad status {fm.get('status')!r}")
            )
        rec_assets = fm.get("assets") or []
        if not rec_assets:
            warnings.append(_problem("warn", str(p), "assets list is empty"))
        for aid in rec_assets:
            if aid not in asset_id_set:
                problems.append(
                    _problem(
                        "incomplete",
                        str(p),
                        f"asset {aid!r} does not resolve to a known asset",
                    )
                )

    signature_id_set = set()
    for p in sig_mod.all_paths(root):
        fm = sig_mod.parse(p.read_text(encoding="utf-8"))["frontmatter"]
        sid = fm.get("id")
        if sid in signature_id_set:
            problems.append(_problem("conflict", str(p), "duplicate signature id"))
        signature_id_set.add(sid)
        if fm.get("status") not in SIGNATURE_STATUSES:
            problems.append(
                _problem("malformed", sid, f"bad status {fm.get('status')!r}")
            )
        for aid in fm.get("assets") or []:
            if aid not in asset_id_set:
                problems.append(
                    _problem(
                        "incomplete",
                        sid,
                        f"asset {aid!r} does not resolve to a known asset",
                    )
                )

    project_names = {p.name for p in project_dirs(root)}
    spawnable_ids = seen_ticket_ids | project_names

    investigation_count = 0
    for p in inv_mod.all_paths(root):
        investigation_count += 1
        try:
            parsed = inv_mod.parse(p.read_text(encoding="utf-8"))
        except KctxError as e:
            problems.append(_problem("malformed", str(p), e.message))
            continue
        fm, body = parsed["frontmatter"], parsed["body"]
        iid = fm.get("id")
        if fm.get("trigger") not in INVESTIGATION_TRIGGERS:
            problems.append(
                _problem("malformed", iid, f"bad trigger {fm.get('trigger')!r}")
            )
        if fm.get("status") not in INVESTIGATION_STATUSES:
            problems.append(
                _problem("malformed", iid, f"bad status {fm.get('status')!r}")
            )
        for aid in (fm.get("assets") or []) + (fm.get("alerts") or []):
            if aid not in asset_id_set:
                problems.append(
                    _problem(
                        "incomplete",
                        iid,
                        f"asset/alert {aid!r} does not resolve to a known asset",
                    )
                )
        for sid in fm.get("signatures") or []:
            if sid not in signature_id_set:
                problems.append(
                    _problem(
                        "incomplete",
                        iid,
                        f"signature {sid!r} does not resolve to a known signature",
                    )
                )
        for spawned_id in fm.get("spawned") or []:
            if spawned_id not in spawnable_ids:
                problems.append(
                    _problem(
                        "incomplete",
                        iid,
                        f"spawned {spawned_id!r} does not resolve to a known "
                        "ktlo ticket or project",
                    )
                )
        if fm.get("status") == "concluded":
            if not (body.get("Checked against") or "").strip():
                problems.append(
                    _problem("incomplete", iid, "concluded without Checked against")
                )
            if not (body.get("Scope and limits") or "").strip():
                problems.append(
                    _problem("incomplete", iid, "concluded without Scope and limits")
                )
            open_hyps = [
                h["id"]
                for h in inv_mod.parse_hypotheses(body.get("Hypotheses", ""))
                if h["status"] == "open"
            ]
            if open_hyps:
                problems.append(
                    _problem(
                        "incomplete",
                        iid,
                        f"concluded with open hypotheses: {', '.join(open_hyps)}",
                    )
                )

    for p in all_runbook_paths(root):
        fm = read_frontmatter(p.read_text(encoding="utf-8"))
        if not fm:
            continue  # free-form runbook, no frontmatter contract yet
        if fm.get("layer") and fm.get("layer") not in RUNBOOK_LAYERS:
            problems.append(
                _problem("malformed", str(p), f"bad layer {fm.get('layer')!r}")
            )
        rb_assets = (
            split_list_value(fm.get("alerts", "")) if fm.get("alerts") else []
        ) + (split_list_value(fm.get("assets", "")) if fm.get("assets") else [])
        for aid in rb_assets:
            if aid not in asset_id_set:
                problems.append(
                    _problem(
                        "incomplete",
                        str(p),
                        f"asset/alert {aid!r} does not resolve to a known asset",
                    )
                )

    for r in regression_flags(root):
        warnings.append(
            _problem(
                "warn",
                r["investigation"],
                f"possible regression: signature {r['signature']} was fixed_at "
                f"{r['fixed_at']} but this investigation is dated {r['created']}",
            )
        )

    lifecycle_by_id = {a.id: a.lifecycle for a in assets}
    dossier_count = 0
    for p in dossiers_mod.all_paths(root):
        dossier_count += 1
        try:
            parsed = dossiers_mod.parse(p.read_text(encoding="utf-8"))
        except KctxError as e:
            problems.append(_problem("malformed", str(p), e.message))
            continue
        fm, body = parsed["frontmatter"], parsed["body"]
        asset_id = fm.get("asset")
        if not asset_id or asset_id not in asset_id_set:
            problems.append(
                _problem(
                    "incomplete",
                    str(p),
                    f"asset {asset_id!r} does not resolve to a known asset",
                )
            )
        missing_headings = [h for h in dossiers_mod.HEADINGS if h not in body]
        if missing_headings:
            problems.append(
                _problem(
                    "malformed",
                    str(p),
                    f"missing heading(s): {', '.join(missing_headings)}",
                )
            )
        if lifecycle_by_id.get(asset_id) == "retired":
            warnings.append(
                _problem(
                    "warn",
                    str(p),
                    f"dossier for retired asset {asset_id!r} sits outside archive/",
                )
            )

    # Archived dossiers are checked lightly: a retired asset's dossier is
    # expected to drift out of sync with its headings, so only the
    # frontmatter/asset-id contract is enforced here.
    for p in dossiers_mod.all_archived_paths(root):
        dossier_count += 1
        try:
            parsed = dossiers_mod.parse(p.read_text(encoding="utf-8"))
        except KctxError as e:
            problems.append(_problem("malformed", str(p), e.message))
            continue
        if not parsed["frontmatter"].get("asset"):
            warnings.append(
                _problem("warn", str(p), "archived dossier missing asset field")
            )

    corrections_count = 0
    for p in corrections_mod.all_paths(root):
        corrections_count += 1
        try:
            parsed = corrections_mod.parse(p.read_text(encoding="utf-8"))
        except KctxError as e:
            problems.append(_problem("malformed", str(p), e.message))
            continue
        fm, rows = parsed["frontmatter"], parsed["rows"]
        target = fm.get("target")
        if not target or not corrections_mod.target_resolves(root, target):
            problems.append(
                _problem("incomplete", str(p), f"target {target!r} does not resolve")
            )
        for row in rows:
            status = row.get("status", "")
            if not _CORRECTION_ROW_STATUS_RE.match(status):
                problems.append(
                    _problem(
                        "malformed",
                        str(p),
                        f"bad row status {status!r} for referrer {row.get('file')!r}",
                    )
                )

    changes_count = 0
    for proj_dir in project_dirs(root):
        changes_dir = proj_dir / "changes"
        if not changes_dir.is_dir():
            continue
        for p in sorted(changes_dir.glob("*.md")):
            changes_count += 1
            fm = read_frontmatter(p.read_text(encoding="utf-8"))
            if not fm:
                continue  # no frontmatter contract yet -- nothing to check
            raw_assets = fm.get("assets")
            change_assets = split_list_value(raw_assets) if raw_assets else []
            if not change_assets:
                warnings.append(_problem("warn", str(p), "assets list is empty"))
            for aid in change_assets:
                if aid not in asset_id_set:
                    problems.append(
                        _problem(
                            "incomplete",
                            str(p),
                            f"asset {aid!r} does not resolve to a known asset",
                        )
                    )

    return {
        "ok": not problems,
        "problems": problems,
        "warnings": warnings,
        "counts": {
            "assets": len(assets),
            "relationships": len(rels),
            "proposals": len(seen_proposal_ids),
            "ktlo": ktlo_count,
            "changes": changes_count,
            "investigations": investigation_count,
            "signatures": len(signature_id_set),
            "dossiers": dossier_count,
            "corrections": corrections_count,
        },
    }
