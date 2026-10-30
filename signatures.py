"""signatures/<slug>.md records: the known-error record (ITIL KEDB, combined
with Sentry-style fingerprint matching) for a recurring failure mode. Linked
many-to-one from investigations' `signatures:` frontmatter list -- occurrence
history is derived from that list (see nav.timeline), never hand-maintained
here.

Frontmatter/body shape mirrors ktlo.py: flat key: value frontmatter, then
fixed Markdown sections, with section text filled in by hand after `kctx sig
new` scaffolds the file.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from errors import KctxError
from records import SIGNATURE_STATUSES, require_choice
from storage import slugify, split_list_value, today

FRONTMATTER_FIELDS = [
    "id",
    "title",
    "status",
    "match",
    "match_where",
    "assets",
    "owner_group",
    "first_seen",
    "last_seen",
    "workaround",
    "fix",
    "fixed_at",
    "verified_at",
    "ttl",
]
LIST_FIELDS = {"match", "assets", "fix"}
SECTION_ORDER = ["Signature", "Mechanism", "Workaround", "Fix and status", "Learned"]
# Optional, append-only, trailing section for a deliberate `kctx retract`
# (see dossiers.py's parallel CORRECTIONS_HEADING) -- unlike SECTION_ORDER,
# only written when non-empty, so an untouched signature record is unchanged.
OPTIONAL_SECTION = "Corrections"


def signatures_root(root: Path) -> Path:
    return root / "signatures"


def path_for_id(root: Path, sig_id: str) -> Path:
    return signatures_root(root) / f"{sig_id}.md"


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
    lines.append(f"# {frontmatter.get('title', '')}")
    for section in SECTION_ORDER:
        lines.append("")
        lines.append(f"## {section}")
        lines.append("")
        lines.append(body.get(section, "").strip())
    if OPTIONAL_SECTION in body:
        lines.append("")
        lines.append(f"## {OPTIONAL_SECTION}")
        lines.append("")
        lines.append(body[OPTIONAL_SECTION].strip())
    lines.append("")
    return "\n".join(lines)


def parse(text: str) -> Dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise KctxError("malformed", "signature record missing frontmatter")
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
        raise KctxError("malformed", "signature record frontmatter never closes")
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
    base = signatures_root(root)
    if not base.exists():
        return []
    return sorted(base.glob("*.md"))


def new(
    root: Path,
    slug: str,
    *,
    title: Optional[str] = None,
    match: Optional[List[str]] = None,
    match_where: str = "",
    assets: Optional[List[str]] = None,
    owner_group: Optional[str] = None,
    status: str = "suspected",
    first_seen: Optional[str] = None,
    last_seen: Optional[str] = None,
    workaround: str = "",
    fix: Optional[List[str]] = None,
    fixed_at: Optional[str] = None,
    verified_at: Optional[str] = None,
    ttl: Optional[str] = None,
) -> Dict[str, Any]:
    require_choice(status, SIGNATURE_STATUSES, "status")
    sig_id = slugify(slug)
    path = path_for_id(root, sig_id)
    if path.exists():
        raise KctxError("conflict", f"signature {sig_id} already exists")

    frontmatter = {
        "id": sig_id,
        "title": title or slug.replace("-", " "),
        "status": status,
        "match": list(match or []),
        "match_where": match_where,
        "assets": list(assets or []),
        "owner_group": owner_group,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "workaround": workaround,
        "fix": list(fix or []),
        "fixed_at": fixed_at,
        "verified_at": verified_at,
        "ttl": ttl,
    }
    body = {section: "" for section in SECTION_ORDER}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(frontmatter, body), encoding="utf-8")
    return {"id": sig_id, "path": str(path), "frontmatter": frontmatter}


def load(root: Path, sig_id: str) -> Dict[str, Any]:
    path = path_for_id(root, sig_id)
    if not path.exists():
        raise KctxError("not-found", f"signature {sig_id} not found")
    parsed = parse(path.read_text(encoding="utf-8"))
    return {"path": path, **parsed}


def list_signatures(root: Path) -> List[Dict[str, Any]]:
    return [
        parse(p.read_text(encoding="utf-8"))["frontmatter"] for p in all_paths(root)
    ]


def show(root: Path, sig_id: str) -> Dict[str, Any]:
    found = load(root, sig_id)
    fm, body = found["frontmatter"], found["body"]
    return {
        "id": fm.get("id"),
        "frontmatter": fm,
        "sections": [s for s in SECTION_ORDER + [OPTIONAL_SECTION] if s in body],
    }


def _pattern_matches(pattern: str, text: str) -> bool:
    if pattern.startswith("re:"):
        try:
            return re.search(pattern[3:], text, re.IGNORECASE) is not None
        except re.error:
            return False
    return pattern.lower() in text.lower()


def match_signatures(root: Path, text: str) -> List[Dict[str, Any]]:
    """Every signature with at least one `match` pattern (a literal
    substring, or a `re:`-prefixed regex) found in `text`, ranked by how many
    of its patterns matched -- more matched patterns is a stronger hit."""
    hits = []
    for fm in list_signatures(root):
        patterns = fm.get("match") or []
        matched = [p for p in patterns if _pattern_matches(p, text)]
        if matched:
            hits.append(
                {
                    "id": fm.get("id"),
                    "title": fm.get("title"),
                    "status": fm.get("status"),
                    "workaround": fm.get("workaround"),
                    "owner_group": fm.get("owner_group"),
                    "last_seen": fm.get("last_seen"),
                    "matched_patterns": matched,
                }
            )
    hits.sort(key=lambda h: -len(h["matched_patterns"]))
    return hits
