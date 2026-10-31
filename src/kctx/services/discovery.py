"""Project homes and incident discovery over authored workspace records."""

from pathlib import Path
from typing import NotRequired, TypedDict

from kctx.errors import KctxError
from kctx.services import inventory, investigations, ktlo, signatures

_SHARED_DIRS = {
    "inventory",
    "runs",
    "proposals",
    "tools",
    "ktlo",
    "investigations",
    "signatures",
    "runbooks",
    "queries",
}
PROJECT_REFERENCE_FILES = ("README.md", "inventory.md", "STATUS.md")
HOME_BOUNDARY_NOTE = "No project or ktlo home matched: this may be a brand-new area, or the inventory simply hasn't caught up -- absence here is not proof nothing tracks it."
MATCH_BOUNDARY_NOTE = "no known signature; this is not proof it's new -- a fresh search in the relevant systems is required before concluding so"


class HomeCandidate(TypedDict):
    type: str
    target: str
    evidence: str


class HomeResult(TypedDict):
    ident: str
    candidates: list[HomeCandidate]
    note: NotRequired[str]


class IncidentHit(TypedDict):
    id: str
    title: str | None
    status: str | None
    created: NotRequired[str | None]


class TimelineResult(TypedDict):
    ident: str
    investigations: list[IncidentHit]


class KtloHit(TypedDict):
    ticket: str
    path: str


class SignatureHit(TypedDict):
    id: str
    title: str
    status: str
    workaround: str
    owner_group: str | None
    last_seen: str | None
    matched_patterns: list[str]


class MatchResult(TypedDict):
    query: str
    signatures: list[SignatureHit]
    investigations: list[IncidentHit]
    ktlo: list[KtloHit]
    note: NotRequired[str]
    warnings: NotRequired[list[str]]


def is_project_name(name: str) -> bool:
    return not name.startswith(".") and name not in _SHARED_DIRS


def project_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [p for p in sorted(root.iterdir()) if p.is_dir() and is_project_name(p.name)]


def all_runbook_paths(root: Path) -> list[Path]:
    return sorted((root / "runbooks").glob("*/*.md"))


def home(root: Path, ident: str) -> HomeResult:
    candidates: dict[tuple[str, str], HomeCandidate] = {}

    def add(kind: str, target: str, evidence: str) -> None:
        key = (kind, target)
        if key not in candidates:
            candidates[key] = {"type": kind, "target": target, "evidence": evidence}
        elif evidence not in candidates[key]["evidence"]:
            candidates[key]["evidence"] += "; " + evidence

    try:
        asset = inventory.resolve_asset(root, ident)
    except KctxError as error:
        if error.category != "not-found":
            raise
        asset = next(
            (
                a
                for a in inventory.load_all_assets(root)
                if a.locator and ident.lower() in a.locator.lower()
            ),
            None,
        )
    if asset is not None:
        if asset.projects:
            for project in asset.projects:
                add("project", project, f"asset {asset.id} projects includes {project!r}")
        else:
            add("asset-only", asset.id.val, f"asset {asset.id} matched but lists no projects")
    for directory in project_dirs(root):
        for name in PROJECT_REFERENCE_FILES:
            path = directory / name
            if path.is_file() and ident.lower() in path.read_text(encoding="utf-8").lower():
                add("project", directory.name, f"{directory.name}/{name} references {ident!r}")
    try:
        ticket = ktlo.normalize_ticket(ident)
    except KctxError:
        ticket = None
    for path in ktlo.all_paths(root):
        record = ktlo.parse(path.read_text(encoding="utf-8")).frontmatter
        reasons: list[str] = []
        if ticket is not None and record.ticket == ticket:
            reasons.append(f"ticket={record.ticket}")
        if any(a.val == ident for a in record.assets):
            reasons.append(f"assets includes {ident!r}")
        if reasons:
            add("ktlo", str(path.relative_to(root)), "; ".join(reasons))
    for record in investigations.list_investigations(root):
        reasons = []
        if ticket is not None and ticket in record.tickets:
            reasons.append(f"tickets includes {ticket.val!r}")
        if any(a.val == ident for a in record.assets):
            reasons.append(f"assets includes {ident!r}")
        if any(a.val == ident for a in record.alerts):
            reasons.append(f"alerts includes {ident!r}")
        if reasons:
            add("investigation", record.id.val, "; ".join(reasons))
    result: HomeResult = {"ident": ident, "candidates": list(candidates.values())}
    if not candidates:
        result["note"] = HOME_BOUNDARY_NOTE
    return result


def timeline(root: Path, ident: str) -> TimelineResult:
    hits: list[IncidentHit] = []
    for record in investigations.list_investigations(root):
        if any(
            value.val == ident
            for value in (*record.assets, *record.alerts, *record.signatures, *record.tickets)
        ):
            hits.append(
                {
                    "id": record.id.val,
                    "title": record.title,
                    "status": record.status.value,
                    "created": record.created,
                }
            )
    hits.sort(key=lambda hit: (hit.get("created") or "", hit["id"]))
    return {"ident": ident, "investigations": hits}


def match(root: Path, text: str) -> MatchResult:
    """Search signatures, investigations and KTLO notes; unreadable records are
    skipped and disclosed rather than aborting the search for readable ones."""
    skipped: list[str] = []
    signature_hits: list[SignatureHit] = [
        {
            "id": hit.id.val,
            "title": hit.title,
            "status": hit.status.value,
            "workaround": hit.workaround,
            "owner_group": hit.owner_group,
            "last_seen": hit.last_seen,
            "matched_patterns": list(hit.matched_patterns),
        }
        for hit in signatures.match_signatures(root, text, skipped=skipped)
    ]
    investigation_hits: list[IncidentHit] = []
    for path in investigations.all_paths(root):
        try:
            full = path.read_text(encoding="utf-8")
            if text.lower() in full.lower():
                record = investigations.parse(full).frontmatter
                investigation_hits.append(
                    {"id": record.id.val, "title": record.title, "status": record.status.value}
                )
        except (KctxError, ValueError, OSError) as error:
            skipped.append(f"investigation {path.relative_to(root)}: {error}")
    ktlo_hits: list[KtloHit] = []
    for path in ktlo.all_paths(root):
        try:
            parsed = ktlo.parse(path.read_text(encoding="utf-8"))
            if text.lower() in parsed.body.get("Symptom", "").lower():
                ktlo_hits.append(
                    {"ticket": parsed.frontmatter.ticket.val, "path": str(path.relative_to(root))}
                )
        except (KctxError, ValueError, OSError) as error:
            skipped.append(f"ktlo {path.relative_to(root)}: {error}")
    result: MatchResult = {
        "query": text,
        "signatures": signature_hits,
        "investigations": investigation_hits,
        "ktlo": ktlo_hits,
    }
    if skipped:
        result["warnings"] = sorted(dict.fromkeys(skipped))
    if not signature_hits and not investigation_hits and not ktlo_hits:
        result["note"] = MATCH_BOUNDARY_NOTE
    return result
