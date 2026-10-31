"""Proposal records: Markdown files with flat key: value frontmatter.

A proposal starts life as `status: proposed` (or `draft`, if it's missing a
Research section, two Alternatives, or a runnable Acceptance gates table --
the evolve skill's review gate) and moves through the lifecycle only via
`kctx proposal set`, which enforces the transition graph in
records.PROPOSAL_TRANSITIONS, requires --by for the statuses in
PROPOSAL_DECIDED_STATUSES, requires --note for `regressed`, and requires the
relevant Acceptance gates to have passed before `applied` or `verified`.
Every status change appends a dated line to the Decision log section.

Two on-disk layouts are both read everywhere (list/show/set/gate/validate):
  - new filing:   proposals/<kind>/<date>-<slug>/proposal.md (+ research/,
                  evidence/, gates.json)
  - legacy filing: proposals/<kind>/<date>-<slug>.md, with its own sibling
                  <date>-<slug>.gates.json if it ever gets a gate recorded.
A legacy proposal is never migrated into the directory layout -- its id is
referenced from commits and other notes, so its path can't move.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import gates as gates_mod
from errors import KctxError
from records import (
    PROPOSAL_DECIDED_STATUSES,
    PROPOSAL_KINDS,
    PROPOSAL_ORIGINS,
    PROPOSAL_STATUSES,
    PROPOSAL_TRANSITIONS,
    PROPOSAL_TYPES,
    require_choice,
)
from storage import atomic_write_json, slugify, split_list_value, today

FRONTMATTER_FIELDS = [
    "id",
    "kind",
    "type",
    "title",
    "status",
    "created",
    "updated",
    "origin",
    "proposed_by",
    "requested_by",
    "source_session",
    "project",
    "swept_at",
    "target",
    "references",
    "landed",
    "decided_by",
    "superseded_by",
]
LIST_FIELDS = {"target", "references", "landed"}
# `type` may be a bare string (legacy, and the common case) or a bracketed
# list (a cross-cutting change touching more than one landing checklist).
OPTIONAL_LIST_FIELDS = {"type"}
SECTION_ORDER = [
    "Context",
    "Evidence",
    "Proposed change",
    "Research",
    "Alternatives considered",
    "Acceptance gates",
    "Impact",
    "Landing plan",
    "References",
    "Why general / justification",
    "Decision log",
]
# Sections a new filing always carries, even empty, so the shape is uniform.
NEW_FILING_SECTIONS = SECTION_ORDER
_REPO_SHA_RE = re.compile(r"\b([a-zA-Z][\w.-]*)@([0-9a-f]{7,40})\b")


def proposals_root(root: Path) -> Path:
    return root / "proposals"


def _format_value(key: str, value: Any) -> str:
    if value is None:
        return ""
    if key in LIST_FIELDS:
        items = value if isinstance(value, list) else [value]
        return "[" + ", ".join(items) + "]"
    if key in OPTIONAL_LIST_FIELDS and isinstance(value, list):
        return "[" + ", ".join(value) + "]"
    return str(value)


def _parse_value(key: str, raw: str) -> Any:
    raw = raw.strip()
    if key in LIST_FIELDS:
        return split_list_value(raw)
    if key in OPTIONAL_LIST_FIELDS:
        if raw.startswith("[") and raw.endswith("]"):
            return split_list_value(raw)
        return raw or None
    return raw or None


def _validate_type(type_: Optional[Any]) -> None:
    if type_ is None:
        return
    items = type_ if isinstance(type_, list) else [type_]
    for t in items:
        require_choice(t, PROPOSAL_TYPES, "type")


def render(frontmatter: Dict[str, Any], body: Dict[str, str]) -> str:
    lines = ["---"]
    for key in FRONTMATTER_FIELDS:
        if key in frontmatter:
            lines.append(f"{key}: {_format_value(key, frontmatter.get(key))}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {frontmatter.get('title', '')}")
    # Only sections actually present in `body` are written -- a legacy
    # proposal (five sections) never grows the new ones just because its
    # status changed, and a new filing (which sets every key up front) always
    # keeps its full shape.
    for section in SECTION_ORDER:
        if section not in body:
            continue
        lines.append("")
        lines.append(f"## {section}")
        lines.append("")
        lines.append(body.get(section, "").strip())
    lines.append("")
    return "\n".join(lines)


def parse(text: str) -> Dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise KctxError("malformed", "proposal file missing frontmatter")
    frontmatter: Dict[str, Any] = {}
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        line = lines[i]
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            frontmatter[key] = _parse_value(key, value)
        i += 1
    if i >= len(lines):
        raise KctxError("malformed", "proposal file frontmatter never closes")
    body_lines = lines[i + 1 :]
    body: Dict[str, str] = {}
    current: Optional[str] = None
    buf: List[str] = []
    for line in body_lines:
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            if current is not None:
                body[current] = "\n".join(buf).strip()
            current = m.group(1).strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        body[current] = "\n".join(buf).strip()
    return {"frontmatter": frontmatter, "body": body}


def _home_dir(root: Path, kind: str, created: str, slug: str) -> Path:
    return proposals_root(root) / kind / f"{created}-{slug}"


def _count_bullets(text: str) -> int:
    count = 0
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith(("-", "*")) or re.match(r"^\d+[.)]\s", s):
            count += 1
    return count


def review_gate_missing(body: Dict[str, str]) -> List[str]:
    """What a filing is missing to clear the evolve skill's review gate
    (evolve skill, section 1.b): a Research section (or a justified one-line
    skip -- any non-empty text satisfies this), at least two Alternatives
    considered, and an Acceptance gates table with runnable checks. A
    filing that clears all three goes straight to `proposed`; otherwise it's
    filed as `draft` and isn't shown in review."""
    missing = []
    if not (body.get("Research") or "").strip():
        missing.append("Research (or a one-line justified skip)")
    if _count_bullets(body.get("Alternatives considered", "")) < 2:
        missing.append("Alternatives considered (at least 2)")
    if not gates_mod.parse_gates_table(body):
        missing.append("Acceptance gates (a runnable-checks table)")
    return missing


def add(
    root: Path,
    *,
    kind: str,
    origin: str,
    title: str,
    context: str,
    evidence: str,
    change: str,
    why: str,
    target: Optional[List[str]] = None,
    type: Optional[Any] = None,
    references: Optional[List[str]] = None,
    project: Optional[str] = None,
    source_session: Optional[str] = None,
    proposed_by: Optional[str] = None,
    requested_by: Optional[str] = None,
    research: str = "",
    alternatives: str = "",
    gates: str = "",
    impact: str = "",
    plan: str = "",
    force: bool = False,
) -> Dict[str, Any]:
    require_choice(kind, PROPOSAL_KINDS, "kind")
    require_choice(origin, PROPOSAL_ORIGINS, "origin")
    _validate_type(type)
    created = today()
    slug = slugify(title)
    home = _home_dir(root, kind, created, slug)
    path = home / "proposal.md"
    proposal_id = f"{kind}/{created}-{slug}"
    if path.exists() and not force:
        raise KctxError(
            "conflict", f"proposal {proposal_id} already exists (use --force)"
        )

    refs = list(references or [])
    body = {
        "Context": context,
        "Evidence": evidence,
        "Proposed change": change,
        "Research": research,
        "Alternatives considered": alternatives,
        "Acceptance gates": gates,
        "Impact": impact,
        "Landing plan": plan,
        # Mirrors the frontmatter `references` index verbatim; kctx doesn't
        # parse cite syntax, so it can't do more than list the same strings.
        "References": "\n".join(f"- {r}" for r in refs),
        "Why general / justification": why,
        "Decision log": "",
    }
    missing = review_gate_missing(body)
    status = "draft" if missing else "proposed"
    log_line = f"- {created}: {status}"
    if missing:
        log_line += f" — missing for review: {', '.join(missing)}"
    body["Decision log"] = log_line

    frontmatter = {
        "id": proposal_id,
        "kind": kind,
        "type": type,
        "title": title,
        "status": status,
        "created": created,
        "updated": created,
        "origin": origin,
        "proposed_by": proposed_by,
        "requested_by": requested_by,
        "source_session": source_session,
        "project": project,
        "swept_at": None,
        "target": list(target or []),
        "references": refs,
        "landed": [],
        "decided_by": None,
        "superseded_by": None,
    }
    home.mkdir(parents=True, exist_ok=True)
    (home / "research").mkdir(exist_ok=True)
    (home / "evidence").mkdir(exist_ok=True)
    gates_json = home / "gates.json"
    if not gates_json.exists():
        atomic_write_json(gates_json, [])
    path.write_text(render(frontmatter, body), encoding="utf-8")
    result = {"id": proposal_id, "path": str(path), "frontmatter": frontmatter}
    if missing:
        result["missing"] = missing
    return result


def all_paths(root: Path) -> List[Path]:
    """Every proposal record path, both layouts: a legacy *.md file directly
    under a kind directory, or <kind>/<date>-<slug>/proposal.md."""
    base = proposals_root(root)
    if not base.exists():
        return []
    out: List[Path] = []
    for kind_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        if kind_dir.name.startswith("."):
            continue
        for item in sorted(kind_dir.iterdir()):
            if item.is_file() and item.suffix == ".md":
                out.append(item)
            elif item.is_dir():
                pm = item / "proposal.md"
                if pm.exists():
                    out.append(pm)
    return out


def load(root: Path, proposal_id: str) -> Dict[str, Any]:
    for p in all_paths(root):
        parsed = parse(p.read_text(encoding="utf-8"))
        if parsed["frontmatter"].get("id") == proposal_id:
            return {"path": p, **parsed}
    raise KctxError("not-found", f"proposal {proposal_id} not found")


def list_proposals(
    root: Path,
    *,
    status: Optional[str] = None,
    kind: Optional[str] = None,
    pending_gates: bool = False,
) -> List[Dict[str, Any]]:
    out = []
    for p in all_paths(root):
        parsed = parse(p.read_text(encoding="utf-8"))
        fm = parsed["frontmatter"]
        if status and fm.get("status") != status:
            continue
        if kind and fm.get("kind") != kind:
            continue
        if pending_gates:
            if fm.get("status") != "applied":
                continue
            table = gates_mod.parse_gates_table(parsed["body"])
            if not table:
                continue
            results = gates_mod.load_results(p)
            pending = gates_mod.pending_for_when(
                table, results, {"deploy", "use"}, rev=_gate_rev(parsed["body"])
            )
            if not pending:
                continue
            fm = dict(fm)
            fm["pending_gates"] = pending
        out.append(fm)
    return out


def show(root: Path, proposal_id: str) -> Dict[str, Any]:
    found = load(root, proposal_id)
    fm = found["frontmatter"]
    body = found["body"]
    table = gates_mod.parse_gates_table(body)
    results = gates_mod.load_results(found["path"])
    latest = gates_mod.latest_outcomes(results)
    gate_status = [{**g, "outcome": latest.get(g["id"], "unk")} for g in table]
    return {
        "id": fm.get("id"),
        "frontmatter": fm,
        "sections": [s for s in SECTION_ORDER if s in body],
        "gates": gate_status,
    }


def _check_transition(current: Optional[str], new: str) -> None:
    if new == current:
        raise KctxError("malformed", f"already status={current!r}")
    if new == "superseded":
        return
    allowed = PROPOSAL_TRANSITIONS.get(current, set())
    if new not in allowed:
        choices = sorted(allowed | {"superseded"})
        raise KctxError(
            "malformed",
            f"illegal transition {current!r} -> {new!r}; allowed: {choices}",
        )


def _gate_rev(body: Dict[str, str]) -> str:
    """Digest of the Acceptance-gate definitions — the revision gate
    results are bound to. Stable across unrelated edits (status flips,
    Decision-log lines); changes exactly when the gate table changes."""
    return gates_mod.gates_rev(body)


def _gate_block(path: Path, body: Dict[str, str], status: str) -> Optional[str]:
    """None if the transition to `status` may proceed; otherwise the message
    for why it's blocked. A legacy proposal with no Acceptance gates table at
    all is waved through (warn, not block) so history isn't broken."""
    table = gates_mod.parse_gates_table(body)
    if not table:
        return None
    whens = {"land"} if status == "applied" else {"deploy", "use"}
    results = gates_mod.load_results(path)
    pending = gates_mod.pending_for_when(table, results, whens, rev=_gate_rev(body))
    if pending:
        return f"status={status!r} blocked: gate(s) {', '.join(pending)} haven't passed"
    return None


def set_status(
    root: Path,
    proposal_id: str,
    *,
    status: Optional[str] = None,
    by: Optional[str] = None,
    note: Optional[str] = None,
    superseded_by: Optional[str] = None,
    origin: Optional[str] = None,
    proposed_by: Optional[str] = None,
    requested_by: Optional[str] = None,
    swept_at: Optional[str] = None,
    landed_add: Optional[List[str]] = None,
) -> Dict[str, Any]:
    found = load(root, proposal_id)
    path = found["path"]
    fm = found["frontmatter"]
    body = found["body"]
    warnings: List[str] = []

    if status is not None:
        require_choice(status, PROPOSAL_STATUSES, "status")
        _check_transition(fm.get("status"), status)

        # One readiness predicate for both filing paths (handover 8.1):
        # draft -> proposed must clear the same review gate as filing
        # directly as proposed. The earlier bypass (any draft could be
        # promoted) is an intentional contract change; the old fixture
        # test_draft_to_proposed_is_legal was updated accordingly.
        if status == "proposed" and fm.get("status") == "draft":
            missing = review_gate_missing(body)
            if missing:
                raise KctxError(
                    "incomplete",
                    "status='proposed' blocked: still missing for review: "
                    + ", ".join(missing),
                )

        if status in PROPOSAL_DECIDED_STATUSES and not by:
            raise KctxError("incomplete", f"status={status!r} requires --by")
        if status == "regressed" and not note:
            raise KctxError("incomplete", "status='regressed' requires --note")
        if status in ("applied", "verified"):
            block = _gate_block(path, body, status)
            if block:
                raise KctxError("incomplete", block)
            if not gates_mod.parse_gates_table(body):
                warnings.append(
                    f"legacy proposal has no Acceptance gates table; "
                    f"status={status!r} allowed without gate verification"
                )

        fm["status"] = status
        if by:
            fm["decided_by"] = by
        if superseded_by:
            fm["superseded_by"] = superseded_by

        log_line = f"- {today()}: {status}"
        if by:
            log_line += f" by {by}"
        if note:
            log_line += f" — {note}"
        body["Decision log"] = (body.get("Decision log", "") + "\n" + log_line).strip()
    elif not any(
        v is not None for v in (origin, proposed_by, requested_by, swept_at, landed_add)
    ):
        raise KctxError(
            "incomplete", "set requires --status or at least one field to update"
        )

    if origin is not None:
        require_choice(origin, PROPOSAL_ORIGINS, "origin")
        fm["origin"] = origin
    if proposed_by is not None:
        fm["proposed_by"] = proposed_by
    if requested_by is not None:
        fm["requested_by"] = requested_by
    if swept_at is not None:
        fm["swept_at"] = swept_at
    if landed_add:
        existing = list(fm.get("landed") or [])
        for item in landed_add:
            if item not in existing:
                existing.append(item)
        fm["landed"] = existing

    fm["updated"] = today()
    path.write_text(render(fm, body), encoding="utf-8")
    result = dict(fm)
    if warnings:
        result["warnings"] = warnings
    return result


def gate(
    root: Path,
    proposal_id: str,
    gate_id: str,
    *,
    outcome: str,
    evidence: str,
    by: Optional[str] = None,
    rev: Optional[str] = None,
) -> Dict[str, Any]:
    found = load(root, proposal_id)
    path = found["path"]
    fm = found["frontmatter"]
    body = found["body"]
    table = gates_mod.parse_gates_table(body)
    if table and gate_id not in {g["id"] for g in table}:
        raise KctxError(
            "not-found",
            f"gate {gate_id!r} not declared in {proposal_id}'s Acceptance gates table",
        )

    recorded_rev = rev or _gate_rev(body)
    entry = gates_mod.append_result(
        path,
        gate=gate_id,
        outcome=outcome,
        evidence=evidence,
        by=by,
        rev=recorded_rev,
    )

    log_line = f"- {today()}: gate {gate_id} -> {outcome}"
    if by:
        log_line += f" by {by}"
    log_line += f" ({evidence})"
    body["Decision log"] = (body.get("Decision log", "") + "\n" + log_line).strip()
    fm["updated"] = today()
    path.write_text(render(fm, body), encoding="utf-8")
    return entry


def has_landed_evidence(fm: Dict[str, Any], body: Dict[str, str]) -> bool:
    """True if an applied/verified proposal can point at what actually
    landed: a non-empty `landed` frontmatter list, or a repo@sha-shaped token
    somewhere in its Decision log. Used by validate.validate()."""
    if fm.get("landed"):
        return True
    return bool(_REPO_SHA_RE.search(body.get("Decision log", "")))


def backfill_landed_from_notes(
    root: Path, *, dry_run: bool = False
) -> List[Dict[str, Any]]:
    """One-time repair for proposals that reached applied/verified before the
    `landed` frontmatter field existed: scan the Decision log for
    `repo@sha`-shaped tokens (the format every landing note already uses) and
    record them. Never overwrites an existing non-empty `landed` list, and
    never touches a proposal whose notes don't contain a recognizable token.
    """
    changed = []
    for p in all_paths(root):
        parsed = parse(p.read_text(encoding="utf-8"))
        fm = parsed["frontmatter"]
        body = parsed["body"]
        if fm.get("status") not in ("applied", "verified"):
            continue
        if fm.get("landed"):
            continue
        found_tokens = [
            f"{m.group(1)}@{m.group(2)}"
            for m in _REPO_SHA_RE.finditer(body.get("Decision log", ""))
        ]
        if not found_tokens:
            continue
        # de-dupe, keep first-seen order
        tokens: List[str] = []
        for t in found_tokens:
            if t not in tokens:
                tokens.append(t)
        changed.append({"id": fm.get("id"), "path": str(p), "landed": tokens})
        if not dry_run:
            fm["landed"] = tokens
            p.write_text(render(fm, body), encoding="utf-8")
    return changed
