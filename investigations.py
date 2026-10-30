"""investigations/<YYYY>/<YYYY-MM-DD>-<slug>/README.md records: the incident
record for on-call and ad-hoc work -- one per alert firing, DRQS/WP ticket,
rota item, or ad-hoc question (ops-knowledge-layer proposal, section 1a).

Frontmatter/body shape mirrors ktlo.py and proposals.py: flat key: value
frontmatter, then fixed Markdown sections. `kctx inv new` scaffolds empty
sections and an `evidence/` + `queries/` sibling directory; the agent fills
section text and the `signatures`/`follow_ups` frontmatter lists by editing
the file directly, the same way a ktlo record's Symptom/Evidence/Change/
Outcome text is never driven through CLI flags. `kctx inv conclude` only
validates the result and flips status -- it writes nothing but that.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from errors import KctxError
from records import INVESTIGATION_TRIGGERS, require_choice
from storage import slugify, split_list_value, today

FRONTMATTER_FIELDS = [
    "id",
    "title",
    "trigger",
    "tickets",
    "alerts",
    "assets",
    "windows",
    "impact_summary",
    "status",
    "signatures",
    "follow_ups",
    "spawned",
    "promoted_to",
    "created",
    "updated",
    "summary",
]
# Plain string lists, rendered/parsed with the same bracket+comma convention
# as ktlo.py and proposals.py.
LIST_FIELDS = {"tickets", "alerts", "assets", "windows", "signatures", "spawned"}
SECTION_ORDER = [
    "Trigger and symptom",
    "Impact",
    "Timeline",
    "Recurrence check",
    "Hypotheses",
    "Findings",
    "Scope and limits",
    "Follow-ups",
    "Learned",
    "What made it hard / what went well",
    "Checked against",
]

_HYPOTHESIS_RE = re.compile(
    r"^[-*]\s*(H\d+)\s*:\s*(open|supported|refuted|unk)\b", re.IGNORECASE
)


def investigations_root(root: Path) -> Path:
    return root / "investigations"


def _dir_for(root: Path, year: str, dirname: str) -> Path:
    return investigations_root(root) / year / dirname


def _format_follow_up(entry: Any) -> str:
    """owner:status[:ticket] -- ticket is omitted when absent, since the
    common case is 'the same ticket already in `tickets:`', not a new one."""
    if isinstance(entry, str):
        return entry
    owner = entry.get("owner", "")
    status = entry.get("status", "")
    ticket = entry.get("ticket") or ""
    parts = [owner, status]
    if ticket:
        parts.append(ticket)
    return ":".join(parts)


def _parse_follow_up(raw: str) -> Dict[str, str]:
    parts = raw.split(":")
    owner = parts[0].strip() if len(parts) > 0 else ""
    status = parts[1].strip() if len(parts) > 1 else ""
    ticket = parts[2].strip() if len(parts) > 2 else ""
    return {"owner": owner, "status": status, "ticket": ticket}


def _format_value(key: str, value: Any) -> str:
    if value is None:
        return ""
    if key == "follow_ups":
        items = value if isinstance(value, list) else [value]
        return "[" + ", ".join(_format_follow_up(v) for v in items) + "]"
    if key in LIST_FIELDS:
        items = value if isinstance(value, list) else [value]
        return "[" + ", ".join(items) + "]"
    return str(value)


def _parse_value(key: str, raw: str) -> Any:
    raw = raw.strip()
    if key == "follow_ups":
        return [_parse_follow_up(x) for x in split_list_value(raw)]
    if key in LIST_FIELDS:
        return split_list_value(raw)
    return raw or None


def render(frontmatter: Dict[str, Any], body: Dict[str, str]) -> str:
    lines = ["---"]
    for key in FRONTMATTER_FIELDS:
        if key in frontmatter:
            lines.append(f"{key}: {_format_value(key, frontmatter.get(key))}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {frontmatter.get('title', '')}")
    for section in SECTION_ORDER:
        lines.append("")
        lines.append(f"## {section}")
        lines.append("")
        lines.append(body.get(section, "").strip())
    lines.append("")
    return "\n".join(lines)


def parse(text: str) -> Dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise KctxError("malformed", "investigation record missing frontmatter")
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
        raise KctxError("malformed", "investigation record frontmatter never closes")
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


def all_paths(root: Path) -> List[Path]:
    base = investigations_root(root)
    if not base.exists():
        return []
    return sorted(base.glob("*/*/README.md"))


def path_for_id(root: Path, inv_id: str) -> Path:
    return investigations_root(root) / inv_id / "README.md"


def new(
    root: Path,
    slug: str,
    *,
    trigger: str,
    title: Optional[str] = None,
    tickets: Optional[List[str]] = None,
    alerts: Optional[List[str]] = None,
    assets: Optional[List[str]] = None,
    windows: Optional[List[str]] = None,
    impact_summary: str = "",
    created: Optional[str] = None,
) -> Dict[str, Any]:
    require_choice(trigger, INVESTIGATION_TRIGGERS, "trigger")
    created = created or today()
    year = created[:4]
    dir_slug = slugify(slug)
    dirname = f"{created}-{dir_slug}"
    inv_id = f"{year}/{dirname}"
    home = _dir_for(root, year, dirname)
    path = home / "README.md"
    if path.exists():
        raise KctxError("conflict", f"investigation {inv_id} already exists")

    frontmatter = {
        "id": inv_id,
        "title": title or slug.replace("-", " "),
        "trigger": trigger,
        "tickets": list(tickets or []),
        "alerts": list(alerts or []),
        "assets": list(assets or []),
        "windows": list(windows or []),
        "impact_summary": impact_summary,
        "status": "open",
        "signatures": [],
        "follow_ups": [],
        "spawned": [],
        "promoted_to": None,
        "created": created,
        "updated": created,
        "summary": "",
    }
    body = {section: "" for section in SECTION_ORDER}
    home.mkdir(parents=True, exist_ok=True)
    (home / "evidence").mkdir(exist_ok=True)
    (home / "queries").mkdir(exist_ok=True)
    path.write_text(render(frontmatter, body), encoding="utf-8")
    return {"id": inv_id, "path": str(path), "frontmatter": frontmatter}


def load(root: Path, inv_id: str) -> Dict[str, Any]:
    path = path_for_id(root, inv_id)
    if not path.exists():
        raise KctxError("not-found", f"investigation {inv_id} not found")
    parsed = parse(path.read_text(encoding="utf-8"))
    return {"path": path, **parsed}


def list_investigations(
    root: Path, *, open_only: bool = False, asset: Optional[str] = None
) -> List[Dict[str, Any]]:
    out = []
    for p in all_paths(root):
        fm = parse(p.read_text(encoding="utf-8"))["frontmatter"]
        if open_only and fm.get("status") not in ("open", "monitoring"):
            continue
        if (
            asset
            and asset not in (fm.get("assets") or [])
            and asset not in (fm.get("alerts") or [])
        ):
            continue
        out.append(fm)
    return out


def show(root: Path, inv_id: str) -> Dict[str, Any]:
    found = load(root, inv_id)
    fm, body, path = found["frontmatter"], found["body"], found["path"]
    home = path.parent
    evidence = sorted(p.name for p in (home / "evidence").glob("*.md"))
    queries = (
        sorted(p.name for p in (home / "queries").glob("*"))
        if (home / "queries").exists()
        else []
    )
    return {
        "id": fm.get("id"),
        "frontmatter": fm,
        "sections": [s for s in SECTION_ORDER if s in body],
        "evidence": evidence,
        "queries": queries,
    }


def parse_hypotheses(text: str) -> List[Dict[str, str]]:
    """Every `- H<n>: <status> ...` bullet at the top level of the
    Hypotheses section. Indented continuation lines and prose between
    bullets are ignored -- only lines that open a new hypothesis count."""
    out = []
    for line in (text or "").splitlines():
        m = _HYPOTHESIS_RE.match(line.strip())
        if m:
            out.append({"id": m.group(1), "status": m.group(2).lower()})
    return out


def conclude(root: Path, inv_id: str) -> Dict[str, Any]:
    found = load(root, inv_id)
    fm, body, path = found["frontmatter"], found["body"], found["path"]

    missing = []
    if not (body.get("Checked against") or "").strip():
        missing.append("Checked against")
    if not (body.get("Scope and limits") or "").strip():
        missing.append("Scope and limits")
    open_hyps = [
        h["id"]
        for h in parse_hypotheses(body.get("Hypotheses", ""))
        if h["status"] == "open"
    ]
    if open_hyps:
        missing.append(f"Hypotheses still open: {', '.join(open_hyps)}")
    if missing:
        raise KctxError(
            "incomplete",
            f"cannot conclude {inv_id}: missing {'; '.join(missing)}",
        )

    fm["status"] = "concluded"
    fm["updated"] = today()
    path.write_text(render(fm, body), encoding="utf-8")
    return dict(fm)


LOG_TEMPLATE = """---
summary:
tags: []
---
# {date}

## Done
-

## Findings
-

## Next
-
"""


def _append_log_pointer(root: Path, project: str, pointer: str) -> None:
    log_dir = root / project / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{today()}.md"
    if not log_path.exists():
        log_path.write_text(LOG_TEMPLATE.format(date=today()), encoding="utf-8")

    text = log_path.read_text(encoding="utf-8")
    if pointer in text:
        return

    out_lines: List[str] = []
    inserted = False
    for line in text.splitlines():
        out_lines.append(line)
        if not inserted and line.strip() == "## Done":
            out_lines.append(f"- {pointer}")
            inserted = True
    if not inserted:
        out_lines.append("")
        out_lines.append("## Done")
        out_lines.append(f"- {pointer}")
    log_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")


def promote(root: Path, inv_id: str, project: str) -> Dict[str, Any]:
    found = load(root, inv_id)
    path = found["path"]
    fm = found["frontmatter"]
    body = found["body"]
    already = fm.get("promoted_to") == project

    if not already:
        fm["promoted_to"] = project
        fm["updated"] = today()
        path.write_text(render(fm, body), encoding="utf-8")

    pointer = f"investigation promote: {inv_id} -> {project} (investigations/{inv_id}/README.md)"
    _append_log_pointer(root, project, pointer)

    return {
        "id": inv_id,
        "project": project,
        "path": str(path),
        "already_promoted": already,
    }
