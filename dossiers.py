"""inventory/dossiers/<asset-id>.md: per-system knowledge keyed on an
existing asset id (purpose, interfaces, main flows, config/BREGs, gotchas),
checked for freshness the same lazy way as everything else kctx cites --
`kctx context` batches a `cite check` over the dossier for free, so a claim
only goes stale once someone actually reads it.

A dossier is not a kctx record with CLI-driven frontmatter fields the way an
asset or signature is: `kctx dossier new` only scaffolds the five headings
and `asset`/`updated` frontmatter, then a session fills in cited prose by
hand, the same way a ktlo record's body or a runbook's sections are.
`inventory/dossiers/README.md` is a KB-wide index, not a dossier, and
`inventory/dossiers/archive/` holds retired ones -- both are skipped by
`all_paths`.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from errors import KctxError
from inventory import resolve_asset
from storage import today

HEADINGS = ["Purpose", "Interfaces", "Main flows", "Config & BREGs", "Gotchas"]
OPTIONAL_HEADING = "Unverified"
CORRECTIONS_HEADING = "Corrections"
# Both trailing headings are optional and append-only; `Unverified` is a
# machine's citation-drift note, `Corrections` a human's deliberate
# retraction/dispute/supersession (see `kctx retract`) -- kept as siblings
# rather than merged, since neither says what the other does.
OPTIONAL_HEADINGS = [OPTIONAL_HEADING, CORRECTIONS_HEADING]
_SKIP_NAMES = {"README.md"}


def dossiers_root(root: Path) -> Path:
    return root / "inventory" / "dossiers"


def archive_root(root: Path) -> Path:
    return dossiers_root(root) / "archive"


def dossier_path(root: Path, asset_id: str) -> Path:
    return dossiers_root(root) / f"{asset_id}.md"


def archived_path(root: Path, asset_id: str) -> Path:
    return archive_root(root) / f"{asset_id}.md"


def all_paths(root: Path) -> List[Path]:
    base = dossiers_root(root)
    if not base.exists():
        return []
    return sorted(p for p in base.glob("*.md") if p.name not in _SKIP_NAMES)


def all_archived_paths(root: Path) -> List[Path]:
    base = archive_root(root)
    if not base.exists():
        return []
    return sorted(base.glob("*.md"))


def render(frontmatter: Dict[str, Any], body: Dict[str, str]) -> str:
    lines = [
        "---",
        f"asset: {frontmatter.get('asset', '')}",
        f"updated: {frontmatter.get('updated', '')}",
        "---",
        "",
    ]
    for heading in HEADINGS:
        lines.append(f"## {heading}")
        lines.append("")
        lines.append(body.get(heading, "").strip())
        lines.append("")
    for heading in OPTIONAL_HEADINGS:
        if heading in body:
            lines.append(f"## {heading}")
            lines.append("")
            lines.append(body[heading].strip())
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def parse(text: str) -> Dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise KctxError("malformed", "dossier missing frontmatter")
    frontmatter: Dict[str, Any] = {}
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        line = lines[i]
        if ":" in line:
            key, _, value = line.partition(":")
            frontmatter[key.strip()] = value.strip()
        i += 1
    if i >= len(lines):
        raise KctxError("malformed", "dossier frontmatter never closes")
    body_lines = lines[i + 1 :]
    body: Dict[str, str] = {}
    current: Optional[str] = None
    buf: List[str] = []
    for line in body_lines:
        if line.startswith("## "):
            if current is not None:
                body[current] = "\n".join(buf).strip()
            current = line[3:].strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        body[current] = "\n".join(buf).strip()
    return {"frontmatter": frontmatter, "body": body}


def new(root: Path, asset_id: str) -> Dict[str, Any]:
    resolve_asset(root, asset_id)  # raises not-found if the asset doesn't exist
    path = dossier_path(root, asset_id)
    if path.exists():
        raise KctxError("conflict", f"dossier for {asset_id} already exists")
    frontmatter = {"asset": asset_id, "updated": today()}
    body = {h: "" for h in HEADINGS}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(frontmatter, body), encoding="utf-8")
    return {"asset": asset_id, "path": str(path), "frontmatter": frontmatter}


def load(root: Path, asset_id: str) -> Dict[str, Any]:
    path = dossier_path(root, asset_id)
    if not path.exists():
        raise KctxError("not-found", f"no dossier for {asset_id}")
    parsed = parse(path.read_text(encoding="utf-8"))
    return {"path": path, **parsed}


def show(root: Path, asset_id: str) -> Dict[str, Any]:
    found = load(root, asset_id)
    fm, body = found["frontmatter"], found["body"]
    return {
        "asset": fm.get("asset"),
        "path": str(found["path"]),
        "frontmatter": fm,
        "headings": [h for h in HEADINGS + OPTIONAL_HEADINGS if h in body],
    }


def archive(root: Path, asset_id: str, *, force: bool = False) -> Dict[str, Any]:
    path = dossier_path(root, asset_id)
    if not path.exists():
        raise KctxError("not-found", f"no dossier for {asset_id}")
    if not force:
        asset = resolve_asset(root, asset_id)
        if asset.lifecycle != "retired":
            raise KctxError(
                "incomplete",
                f"asset {asset_id} is lifecycle={asset.lifecycle!r}, not retired "
                "-- pass force to archive anyway",
            )
    dest = archived_path(root, asset_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    path.rename(dest)
    return {"asset": asset_id, "path": str(dest)}


def for_asset(root: Path, asset_id: str) -> Optional[Path]:
    path = dossier_path(root, asset_id)
    return path if path.is_file() else None
