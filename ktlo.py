"""ktlo/<YYYY>/<ticket>-<slug>.md records: one-off KTLO/DRQS ticket work that
hasn't grown into (or doesn't need) a tracked project under <project>/.

Frontmatter/body shape mirrors proposals.py: flat key: value frontmatter,
then fixed Markdown sections -- here Symptom / Evidence / Change / Outcome
instead of proposals' five. A record is promoted into a project by
`kctx ktlo promote`, which sets `promoted_to` and leaves the file in place;
it's never deleted or moved.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from errors import KctxError
from storage import slugify, split_list_value, today

FRONTMATTER_FIELDS = [
    "ticket",
    "title",
    "assets",
    "status",
    "prs",
    "summary",
    "created",
    "updated",
    "promoted_to",
]
LIST_FIELDS = {"assets", "prs"}
SECTION_ORDER = ["Symptom", "Evidence", "Change", "Outcome"]

TICKET_RE = re.compile(r"^\{?\s*([A-Za-z]+)[\s-]*(\d+)\s*\}?$")


def normalize_ticket(raw: str) -> Dict[str, str]:
    """Accept 'DRQS 123', '{DRQS 123}', 'drqs-123', or 'RDTSPBP-123' and
    return a canonical id ('DRQS-123') and a lowercase filename slug
    ('drqs-123')."""
    m = TICKET_RE.match(raw.strip())
    if not m:
        raise KctxError("malformed", f"unrecognized ticket id {raw!r}")
    prefix, number = m.group(1).upper(), m.group(2)
    return {"id": f"{prefix}-{number}", "slug": f"{prefix.lower()}-{number}"}


def ktlo_root(root: Path) -> Path:
    return root / "ktlo"


def _format_value(key: str, value: Any) -> str:
    if value is None:
        return ""
    if key in LIST_FIELDS:
        items = value if isinstance(value, list) else [value]
        return "[" + ", ".join(items) + "]"
    return str(value)


def _parse_value(key: str, raw: str) -> Any:
    raw = raw.strip()
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
    lines.append(f"# {frontmatter.get('ticket', '')}: {frontmatter.get('title', '')}")
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
        raise KctxError("malformed", "ktlo record missing frontmatter")
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
        raise KctxError("malformed", "ktlo record frontmatter never closes")
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
    base = ktlo_root(root)
    if not base.exists():
        return []
    return sorted(base.glob("*/*.md"))


def _path_for(root: Path, year: str, slug_component: str, title_slug: str) -> Path:
    return ktlo_root(root) / year / f"{slug_component}-{title_slug}.md"


def new(
    root: Path,
    *,
    ticket: str,
    title: str,
    assets: Optional[List[str]] = None,
) -> Dict[str, Any]:
    norm = normalize_ticket(ticket)
    created = today()
    year = created[:4]
    title_slug = slugify(title)
    path = _path_for(root, year, norm["slug"], title_slug)
    if path.exists():
        raise KctxError("conflict", f"ktlo record {path} already exists")

    frontmatter = {
        "ticket": norm["id"],
        "title": title,
        "assets": list(assets or []),
        "status": "todo",
        "prs": [],
        "summary": "",
        "created": created,
        "updated": created,
        "promoted_to": None,
    }
    body = {section: "" for section in SECTION_ORDER}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(frontmatter, body), encoding="utf-8")
    return {"ticket": norm["id"], "path": str(path), "frontmatter": frontmatter}


def load_by_ticket(root: Path, ticket: str) -> Dict[str, Any]:
    norm = normalize_ticket(ticket)
    for p in all_paths(root):
        parsed = parse(p.read_text(encoding="utf-8"))
        if parsed["frontmatter"].get("ticket") == norm["id"]:
            return {"path": p, **parsed}
    raise KctxError("not-found", f"ktlo record for ticket {norm['id']} not found")


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


def promote(root: Path, ticket: str, project: str) -> Dict[str, Any]:
    found = load_by_ticket(root, ticket)
    path = found["path"]
    fm = found["frontmatter"]
    body = found["body"]
    already = fm.get("promoted_to") == project

    if not already:
        fm["promoted_to"] = project
        fm["updated"] = today()
        path.write_text(render(fm, body), encoding="utf-8")

    rel = path.relative_to(ktlo_root(root)).as_posix()
    pointer = f"ktlo promote: {fm['ticket']} -> {project} (ktlo/{rel})"
    _append_log_pointer(root, project, pointer)

    return {
        "ticket": fm["ticket"],
        "project": project,
        "path": str(path),
        "already_promoted": already,
    }
