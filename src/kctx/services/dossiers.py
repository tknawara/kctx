"""Per-asset authored dossiers; updates preserve unknown Markdown verbatim."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from kctx.codecs.documents import MarkdownDocument, parse_document, read_document, render_document
from kctx.domain.ids import AssetId
from kctx.domain.incidents import (
    Dossier,
    DossierArchived,
    DossierCreated,
    DossierShown,
    LoadedDocument,
    ParsedDocument,
)
from kctx.domain.time import today
from kctx.domain.vocabulary import Lifecycle
from kctx.errors import KctxError
from kctx.services.inventory import get_asset

HEADINGS = ["Purpose", "Interfaces", "Main flows", "Config & BREGs", "Gotchas"]
OPTIONAL_HEADING = "Unverified"
CORRECTIONS_HEADING = "Corrections"
OPTIONAL_HEADINGS = [OPTIONAL_HEADING, CORRECTIONS_HEADING]


def dossiers_root(root: Path) -> Path:
    return root / "inventory" / "dossiers"


def archive_root(root: Path) -> Path:
    return dossiers_root(root) / "archive"


def dossier_path(root: Path, asset_id: AssetId) -> Path:
    return dossiers_root(root) / f"{asset_id.val}.md"


def archived_path(root: Path, asset_id: AssetId) -> Path:
    return archive_root(root) / f"{asset_id.val}.md"


def all_paths(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(p for p in dossiers_root(root).glob("*.md") if p.name != "README.md"))


def all_archived_paths(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(archive_root(root).glob("*.md")))


def parse_draft(text: str) -> MarkdownDocument:
    return parse_document(text)


def _decode(doc: MarkdownDocument) -> Dossier:
    if not doc.frontmatter.get("asset"):
        raise KctxError("malformed", "dossier missing asset")
    return Dossier(AssetId(doc.frontmatter["asset"]), doc.frontmatter.get("updated", ""))


def parse(text: str) -> ParsedDocument[Dossier]:
    doc = parse_draft(text)
    return ParsedDocument(_decode(doc), doc)


def frontmatter_to_wire(record: Dossier) -> dict[str, object]:
    return {"asset": record.asset.val, "updated": record.updated}


def render(record: Dossier, body: Mapping[str, str]) -> str:
    sections = {s: body.get(s, "") for s in HEADINGS}
    sections.update((s, body[s]) for s in OPTIONAL_HEADINGS if s in body)
    return render_document({"asset": record.asset.val, "updated": record.updated}, sections).text


def new(root: Path, asset_id: AssetId) -> DossierCreated:
    get_asset(root, asset_id)
    path = dossier_path(root, asset_id)
    if path.exists():
        raise KctxError("conflict", f"dossier for {asset_id} already exists")
    record = Dossier(asset_id, today())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(record, {}), encoding="utf-8")
    return DossierCreated(asset_id, path, record)


def load(root: Path, asset_id: AssetId) -> LoadedDocument[Dossier]:
    path = dossier_path(root, asset_id)
    if not path.exists():
        raise KctxError("not-found", f"no dossier for {asset_id}")
    doc = read_document(path)
    return LoadedDocument(path, _decode(doc), doc)


def show(root: Path, asset_id: AssetId) -> DossierShown:
    found = load(root, asset_id)
    return DossierShown(
        found.frontmatter.asset,
        found.path,
        found.frontmatter,
        tuple(h for h in HEADINGS + OPTIONAL_HEADINGS if h in found.body),
    )


def archive(root: Path, asset_id: AssetId, *, force: bool = False) -> DossierArchived:
    path = dossier_path(root, asset_id)
    if not path.exists():
        raise KctxError("not-found", f"no dossier for {asset_id}")
    if not force:
        asset = get_asset(root, asset_id)
        if asset.lifecycle is not Lifecycle.RETIRED:
            raise KctxError(
                "incomplete",
                f"asset {asset_id} is lifecycle={asset.lifecycle.value!r}, not retired -- pass force to archive anyway",
            )
    dest = archived_path(root, asset_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    path.rename(dest)
    return DossierArchived(asset_id, dest)


def for_asset(root: Path, asset_id: AssetId) -> Path | None:
    path = dossier_path(root, asset_id)
    return path if path.is_file() else None


def result_to_wire(result: DossierCreated | DossierShown | DossierArchived) -> dict[str, object]:
    out: dict[str, object] = {"asset": result.asset.val, "path": str(result.path)}
    if not isinstance(result, DossierArchived):
        out["frontmatter"] = frontmatter_to_wire(result.frontmatter)
    if isinstance(result, DossierShown):
        out["headings"] = list(result.headings)
    return out
