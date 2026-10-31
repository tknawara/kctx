"""Acceptance-gate tables and their recorded outcomes.

A proposal's Acceptance gates section is a Markdown table with columns
id|claim|check|when|by (evolve skill, section 1.a.5). It's usually its own
top-level "## Acceptance gates" section, but a proposal authored with the
gates table nested under another section (e.g. "### Acceptance gates" inside
"## Proposed change") is just as valid -- proposals.parse() only splits on
`##` headings, so that table ends up inside the parent section's text. This
module parses the table either way, and manages gates.json, the append-only
list of {gate, outcome, evidence, at, by, rev} results that `kctx proposal
gate` writes and that `proposal set --status applied|verified` reads to
decide whether the transition is allowed. gates.json never records evidence
content itself -- a cite string or an obs/ev locator passed through as an
opaque string.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from errors import KctxError
from records import GATE_OUTCOMES, require_choice
from storage import atomic_write_json, iso_now

_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_SEP_CELL_RE = re.compile(r"^:?-+:?$")
_GATES_HEADING_RE = re.compile(r"^#{1,6}\s*Acceptance gates\s*$", re.IGNORECASE)
_ANY_HEADING_RE = re.compile(r"^#{1,6}\s")


def _extract_nested_gates_text(body: Dict[str, str]) -> str:
    """Find an "Acceptance gates" heading at any level (##, ###, ####, ...)
    nested inside one of a proposal's top-level section bodies, and return
    the text between it and the next heading line. Checks sections in dict
    order and returns the first match -- a proposal has one gates table."""
    for text in body.values():
        lines = (text or "").splitlines()
        for i, line in enumerate(lines):
            if _GATES_HEADING_RE.match(line.strip()):
                captured = []
                for l in lines[i + 1 :]:
                    if _ANY_HEADING_RE.match(l.strip()):
                        break
                    captured.append(l)
                return "\n".join(captured)
    return ""


def parse_gates_table(section: Union[str, Dict[str, str]]) -> List[Dict[str, str]]:
    """Parse an Acceptance gates Markdown table into a list of gate dicts.

    `section` is either the gates section's own text (the common case: a
    caller already resolved a top-level "## Acceptance gates" body entry), or
    the full parsed `body` dict, in which case a nested "Acceptance gates"
    heading at any level is found anywhere in it first.

    Returns [] when nothing parseable is found -- free prose, an empty
    section, or a legacy proposal with no Acceptance gates content at all.
    Callers treat an empty result as "nothing to enforce", not an error,
    since a legacy single-file proposal is allowed to have none.
    """
    if isinstance(section, dict):
        section_text = section.get("Acceptance gates") or _extract_nested_gates_text(
            section
        )
    else:
        section_text = section
    rows = []
    for line in (section_text or "").splitlines():
        m = _ROW_RE.match(line)
        if not m:
            continue
        rows.append([c.strip() for c in m.group(1).split("|")])
    if not rows:
        return []
    header = [c.lower() for c in rows[0]]
    if "id" not in header or "when" not in header:
        return []
    idx = {name: i for i, name in enumerate(header)}
    gates = []
    for row in rows[1:]:
        if all(_SEP_CELL_RE.match(c) for c in row if c):
            continue
        if len(row) <= max(idx.values()):
            continue
        gid = row[idx["id"]].strip()
        if not gid or gid.lower() == "id":
            continue
        gate: Dict[str, str] = {"id": gid}
        for key in ("claim", "check", "when", "by"):
            if key in idx and idx[key] < len(row):
                gate[key] = row[idx[key]].strip()
        gates.append(gate)
    return gates


def gates_rev(section: Union[str, Dict[str, str]]) -> str:
    """Digest of the Acceptance-gate *definitions* — the revision gate
    results are bound to (handover 8.1: gate-definition identity). Stable
    across unrelated edits (status flips, Decision-log lines), changes
    exactly when the gate table changes, so a pass recorded against an
    older table stops winning the moment the definitions change."""
    import hashlib

    if isinstance(section, dict):
        text = section.get("Acceptance gates") or _extract_nested_gates_text(
            section
        )
    else:
        text = section
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def gates_json_path(proposal_md_path: Path) -> Path:
    """The gates.json sibling for a given proposal record path.

    A directory-home proposal (path ends in proposal.md) owns gates.json
    inside its own directory. A legacy single-file proposal gets a sibling
    <stem>.gates.json next to it in the shared kind directory -- it never
    gains a directory of its own, so it never moves.
    """
    if proposal_md_path.name == "proposal.md":
        return proposal_md_path.parent / "gates.json"
    return proposal_md_path.parent / f"{proposal_md_path.stem}.gates.json"


def load_results(proposal_md_path: Path) -> List[Dict[str, Any]]:
    p = gates_json_path(proposal_md_path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise KctxError("malformed", f"{p}: invalid JSON ({e})")
    if not isinstance(data, list):
        raise KctxError("malformed", f"{p}: expected a JSON list")
    return data


def latest_outcomes(
    results: List[Dict[str, Any]], rev: Optional[str] = None
) -> Dict[str, str]:
    """Last recorded outcome per gate id; results is append-only so the last
    entry for a given gate id wins.

    Revision binding (handover 8.1): when `rev` is given, entries that carry
    a different `rev` are skipped — a pass recorded against an older
    proposal revision must not win merely because its gate id matches.
    Entries with no `rev` are legacy results: they predate revision binding
    and keep their old semantics (they are consulted regardless). They do
    not acquire the modern guarantee; binding starts when `rev` is recorded.
    """
    latest: Dict[str, str] = {}
    for r in results:
        if rev is not None and r.get("rev") not in (None, rev):
            continue
        latest[r["gate"]] = r["outcome"]
    return latest


def append_result(
    proposal_md_path: Path,
    *,
    gate: str,
    outcome: str,
    evidence: str,
    by: Optional[str] = None,
    rev: Optional[str] = None,
) -> Dict[str, Any]:
    require_choice(outcome, GATE_OUTCOMES, "outcome")
    entry: Dict[str, Any] = {
        "gate": gate,
        "outcome": outcome,
        "evidence": evidence,
        "at": iso_now(),
    }
    if by:
        entry["by"] = by
    if rev:
        entry["rev"] = rev
    p = gates_json_path(proposal_md_path)
    results = load_results(proposal_md_path)
    results.append(entry)
    atomic_write_json(p, results)
    return entry


def pending_for_when(
    table: List[Dict[str, str]],
    results: List[Dict[str, Any]],
    whens: set,
    rev: Optional[str] = None,
) -> List[str]:
    """Gate ids in `table` whose `when` is in `whens` and whose latest
    outcome (within `rev` when given) isn't 'pass' (including never-run)."""
    latest = latest_outcomes(results, rev)
    return [
        g["id"]
        for g in table
        if g.get("when") in whens and latest.get(g["id"]) != "pass"
    ]
