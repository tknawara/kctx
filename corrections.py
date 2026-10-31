"""corrections/<date>-<slug>.md: `kctx retract`'s own record.

A retraction appends a dated entry to the target's own Corrections (or, for
a proposal, Decision log) section, then snapshots `nav.uses()`'s referrer
list into one of these files -- one row per referrer, `status: pending` and
a blank owner for manual fill. Never edits a referrer; see retract().
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import dossiers as dossiers_mod
import nav
import proposals as proposals_mod
import signatures as sig_mod
from errors import KctxError
from records import CORRECTION_KINDS, require_choice
from storage import read_frontmatter, slugify, today


def corrections_root(root: Path) -> Path:
    return root / "corrections"


def all_paths(root: Path) -> List[Path]:
    base = corrections_root(root)
    if not base.exists():
        return []
    return sorted(base.glob("*.md"))


def format_entry(
    *, date: str, kind: str, reason: str, by_replacement: Optional[str] = None
) -> str:
    line = f"- {date}: {kind} — {reason}"
    if by_replacement:
        line += f" (replacement: {by_replacement})"
    return line


def render(
    *,
    target: str,
    target_kind: str,
    kind: str,
    reason: str,
    by_replacement: Optional[str],
    created: str,
    referrers: List[Dict[str, Any]],
) -> str:
    lines = [
        "---",
        f"target: {target}",
        f"target_kind: {target_kind}",
        f"kind: {kind}",
        f"reason: {reason}",
        f"by_replacement: {by_replacement or ''}",
        f"created: {created}",
        "---",
        "",
        f"# Corrections: {target}",
        "",
    ]
    if not referrers:
        lines.append("(no known referrers at time of retraction)")
        lines.append("")
        return "\n".join(lines)
    lines.append("| file | kind | status | owner |")
    lines.append("|---|---|---|---|")
    for r in referrers:
        lines.append(f"| {r['file']} | {r['kind']} | pending | |")
    lines.append("")
    return "\n".join(lines)


def parse(text: str) -> Dict[str, Any]:
    fm = read_frontmatter(text)
    if not fm:
        raise KctxError("malformed", "corrections record missing frontmatter")
    rows: List[Dict[str, str]] = []
    in_table = False
    for line in text.splitlines():
        s = line.strip()
        if not in_table:
            if s.startswith("| file "):
                in_table = True
            continue
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(set(c) <= {"-"} for c in cells):
            continue  # the |---|---| separator row
        if len(cells) >= 4:
            rows.append(
                {"file": cells[0], "kind": cells[1], "status": cells[2], "owner": cells[3]}
            )
    return {"frontmatter": fm, "rows": rows}


def _split_ev_target(target: str) -> Tuple[str, str]:
    return nav.split_ev_id(target[len("ev:") :])


def target_resolves(root: Path, target: str) -> bool:
    try:
        if target.startswith("ev:"):
            home, stem = _split_ev_target(target)
            return nav.resolve_ev_path(root, home, stem) is not None
        if target.startswith("sig:"):
            return sig_mod.path_for_id(root, target[len("sig:") :]).is_file()
        if target.startswith("proposal/"):
            proposals_mod.load(root, target[len("proposal/") :])
            return True
        return dossiers_mod.dossier_path(root, target).is_file()
    except KctxError:
        return False


def _append_to_section(text: str, heading: str, entry_line: str) -> str:
    """Append `entry_line` under a trailing `## {heading}` section, replacing
    a bare `none` placeholder rather than appending after it. Creates the
    section (at the end of the file) if it isn't there yet. Assumes the
    section is the last one in the file -- true of an ev record's template
    `## Corrections`, the only raw-markdown case this is used for."""
    marker = f"## {heading}"
    if marker not in text:
        return text.rstrip("\n") + f"\n\n{marker}\n\n{entry_line}\n"
    before, _, after = text.partition(marker)
    existing = after.strip("\n")
    new_body = entry_line if existing.strip().lower() in ("", "none") else existing + "\n" + entry_line
    return before.rstrip("\n") + "\n\n" + marker + "\n\n" + new_body + "\n"


def _append_ev_correction(root: Path, target: str, entry_line: str) -> Path:
    home, stem = _split_ev_target(target)
    path = nav.resolve_ev_path(root, home, stem)
    if path is None:
        raise KctxError("not-found", f"no evidence record resolves for {target!r}")
    path.write_text(
        _append_to_section(path.read_text(encoding="utf-8"), "Corrections", entry_line),
        encoding="utf-8",
    )
    return path


def _append_dossier_correction(root: Path, asset_id: str, entry_line: str) -> Path:
    found = dossiers_mod.load(root, asset_id)
    fm, body = found["frontmatter"], found["body"]
    existing = body.get(dossiers_mod.CORRECTIONS_HEADING, "").strip()
    body[dossiers_mod.CORRECTIONS_HEADING] = (
        existing + "\n" + entry_line if existing else entry_line
    )
    fm["updated"] = today()
    found["path"].write_text(dossiers_mod.render(fm, body), encoding="utf-8")
    return found["path"]


def _append_signature_correction(root: Path, sig_id: str, entry_line: str) -> Path:
    found = sig_mod.load(root, sig_id)
    fm, body = found["frontmatter"], found["body"]
    existing = body.get(sig_mod.OPTIONAL_SECTION, "").strip()
    body[sig_mod.OPTIONAL_SECTION] = existing + "\n" + entry_line if existing else entry_line
    found["path"].write_text(sig_mod.render(fm, body), encoding="utf-8")
    return found["path"]


def _append_proposal_correction(root: Path, proposal_id: str, entry_line: str) -> Path:
    found = proposals_mod.load(root, proposal_id)
    fm, body = found["frontmatter"], found["body"]
    body["Decision log"] = (body.get("Decision log", "") + "\n" + entry_line).strip()
    fm["updated"] = today()
    found["path"].write_text(proposals_mod.render(fm, body), encoding="utf-8")
    return found["path"]


def _target_kind(root: Path, target: str) -> str:
    """Kind label for a target, resolved without mutating anything (the
    plan half of the plan/apply split: kind resolution is a read)."""
    if target.startswith("ev:"):
        return "ev"
    if target.startswith("sig:"):
        return "signature"
    if target.startswith("proposal/"):
        return "proposal"
    if target.startswith("inv:"):
        raise KctxError(
            "malformed",
            "retract doesn't support inv: targets (no Corrections/Decision-log "
            "slot) -- ev:, a dossier asset id, sig:, and proposal/ only",
        )
    return "dossier"


def _append_target_correction(root: Path, target: str, entry_line: str) -> Tuple[str, Path]:
    if target.startswith("ev:"):
        return "ev", _append_ev_correction(root, target, entry_line)
    if target.startswith("sig:"):
        return "signature", _append_signature_correction(
            root, target[len("sig:") :], entry_line
        )
    if target.startswith("proposal/"):
        return "proposal", _append_proposal_correction(
            root, target[len("proposal/") :], entry_line
        )
    if target.startswith("inv:"):
        raise KctxError(
            "malformed",
            "retract doesn't support inv: targets (no Corrections/Decision-log "
            "slot) -- ev:, a dossier asset id, sig:, and proposal/ only",
        )
    return "dossier", _append_dossier_correction(root, target, entry_line)


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    i = 2
    while True:
        candidate = path.with_name(f"{path.stem}-{i}{path.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def retract(
    root: Path,
    target: str,
    *,
    reason: str,
    kind: str,
    by_replacement: Optional[str] = None,
) -> Dict[str, Any]:
    require_choice(kind, CORRECTION_KINDS, "kind")
    if not reason.strip():
        raise KctxError("incomplete", "retract requires --reason")

    created = today()
    entry_line = format_entry(
        date=created, kind=kind, reason=reason, by_replacement=by_replacement
    )

    # Plan (handover 8.4): resolve kind and referrers against the pinned
    # pre-mutation state -- referrer discovery must not see the target's own
    # just-appended correction text. Then commit in recoverable order:
    # the durable correction event (with its pending-review rows) is written
    # first, so a failure before/while updating the target leaves a visible,
    # replayable operation rather than a lost one.
    target_kind = _target_kind(root, target)
    uses_result = nav.uses(root, target)
    referrers = [r for r in uses_result["referrers"] if not r.get("self")]

    out_path = _unique_path(corrections_root(root) / f"{created}-{slugify(target)}.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        render(
            target=target,
            target_kind=target_kind,
            kind=kind,
            reason=reason,
            by_replacement=by_replacement,
            created=created,
            referrers=referrers,
        ),
        encoding="utf-8",
    )

    _, target_path = _append_target_correction(root, target, entry_line)

    return {
        "target": target,
        "target_kind": target_kind,
        "target_file": str(target_path.relative_to(root)),
        "kind": kind,
        "corrections_file": str(out_path.relative_to(root)),
        "referrers": referrers,
    }
