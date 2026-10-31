"""Compose the bounded context around a resolved inventory asset."""

from pathlib import Path
from typing import TypedDict

from kctx.adapters.files.storage import read_json
from kctx.citations.scan import CitationCheck, run_check
from kctx.codecs.frontmatter import read_frontmatter, split_list_value
from kctx.codecs.records import decode_run_manifest, encode_asset, encode_impact
from kctx.domain.ids import AssetId
from kctx.domain.json import JsonObject
from kctx.domain.records import Asset
from kctx.domain.time import is_past_ttl
from kctx.errors import KctxError
from kctx.services import dossiers, inventory, investigations, signatures
from kctx.services.discovery import (
    PROJECT_REFERENCE_FILES,
    HomeCandidate,
    IncidentHit,
    all_runbook_paths,
    home,
    timeline,
)


class RunbookHit(TypedDict):
    path: str
    layer: str | None


class DossierHit(TypedDict):
    path: str
    headings: list[str]
    open_corrections: bool


class RunHit(TypedDict):
    run: str
    project: str | None
    task: str | None


class ContextFreshness(TypedDict):
    asset_verified_at: str | None
    asset_ttl: str | None
    asset_past_ttl: bool
    citations: CitationCheck


class ContextResult(TypedDict):
    asset: str
    depth: int
    assets: list[JsonObject]
    impact: JsonObject
    linked_docs: list[JsonObject]
    projects: list[str]
    ktlo: list[HomeCandidate]
    runs: list[RunHit]
    investigations: list[IncidentHit]
    signatures: list[IncidentHit]
    runbooks: list[RunbookHit]
    dossier: DossierHit | None
    freshness: ContextFreshness


def _resolve_for_context(root: Path, ident: str) -> Asset:
    try:
        return inventory.resolve_asset(root, ident)
    except KctxError as error:
        if error.category != "not-found":
            raise
        matches = [
            asset
            for asset in inventory.load_all_assets(root)
            if asset.locator and ident.lower() in asset.locator.lower()
        ]
        if not matches:
            raise KctxError("not-found", f"no asset matches {ident!r}") from error
        if len(matches) > 1:
            candidates = ", ".join(asset.id.val for asset in matches)
            raise KctxError(
                "conflict", f"ambiguous asset locator {ident!r}: {candidates}"
            ) from error
        return matches[0]


def _runbooks_for_asset(root: Path, asset: AssetId) -> list[RunbookHit]:
    hits: list[RunbookHit] = []
    for path in all_runbook_paths(root):
        fields = read_frontmatter(path.read_text(encoding="utf-8"))
        alerts = split_list_value(fields.get("alerts", ""))
        assets = split_list_value(fields.get("assets", ""))
        if asset.val in (*alerts, *assets):
            hits.append({"path": str(path.relative_to(root)), "layer": fields.get("layer")})
    return hits


def _dossier_for_asset(root: Path, asset: AssetId) -> DossierHit | None:
    path = dossiers.for_asset(root, asset)
    if path is None:
        return None
    parsed = dossiers.parse(path.read_text(encoding="utf-8"))
    return {
        "path": str(path.relative_to(root)),
        "headings": [
            heading
            for heading in (*dossiers.HEADINGS, *dossiers.OPTIONAL_HEADINGS)
            if heading in parsed.body
        ],
        "open_corrections": bool(parsed.body.get(dossiers.CORRECTIONS_HEADING, "").strip()),
    }


def context(root: Path, ident: str, *, depth: int = 2) -> ContextResult:
    primary = _resolve_for_context(root, ident)
    siblings = [
        asset
        for asset in inventory.load_all_assets(root)
        if asset.id != primary.id and primary.locator and asset.locator == primary.locator
    ]
    impact = inventory.impact(root, primary.id, depth=depth)
    linked_docs: list[JsonObject] = []
    for reached in impact.reached:
        try:
            kind = inventory.get_asset(root, reached.asset).kind.value
        except KctxError:
            continue
        if kind in {"doc", "dashboard", "alert", "runbook"}:
            linked_docs.append(
                {
                    "asset": reached.asset.val,
                    "via": reached.via.val,
                    "relationship": reached.relationship.val,
                    "type": reached.type.value,
                    "status": reached.status.value,
                }
            )
    homes = home(root, primary.id.val)["candidates"]
    projects = sorted({hit["target"] for hit in homes if hit["type"] == "project"})
    ktlo_hits = [hit for hit in homes if hit["type"] == "ktlo"]
    investigation_hits = timeline(root, primary.id.val)["investigations"]
    investigation_ids = {hit["id"] for hit in investigation_hits}
    signature_ids = {
        sid
        for record in investigations.list_investigations(root)
        if record.id.val in investigation_ids
        for sid in record.signatures
    }
    signature_hits: list[IncidentHit] = [
        {"id": record.id.val, "title": record.title, "status": record.status.value}
        for record in signatures.list_signatures(root)
        if record.id in signature_ids
    ]
    dossier = _dossier_for_asset(root, primary.id)
    needles = {primary.id.val, *primary.aliases, *projects}
    run_hits: list[RunHit] = []
    for path in sorted((root / "runs").glob("run-*/manifest.json")):
        text = path.read_text(encoding="utf-8")
        if any(needle and needle in text for needle in needles):
            manifest = decode_run_manifest(read_json(path))
            run_hits.append(
                {"run": manifest.run_id.val, "project": manifest.project, "task": manifest.task}
            )
    paths = [
        str(root / project / name)
        for project in projects
        for name in PROJECT_REFERENCE_FILES
        if (root / project / name).is_file()
    ]
    paths.extend(str(root / hit["target"]) for hit in ktlo_hits if (root / hit["target"]).is_file())
    if dossier:
        paths.append(str(root / dossier["path"]))
    return {
        "asset": primary.id.val,
        "depth": depth,
        "assets": [encode_asset(primary), *[encode_asset(asset) for asset in siblings]],
        "impact": encode_impact(impact),
        "linked_docs": linked_docs,
        "projects": projects,
        "ktlo": ktlo_hits,
        "runs": run_hits,
        "investigations": investigation_hits,
        "signatures": signature_hits,
        "runbooks": _runbooks_for_asset(root, primary.id),
        "dossier": dossier,
        "freshness": {
            "asset_verified_at": primary.verified_at,
            "asset_ttl": primary.ttl,
            "asset_past_ttl": bool(
                primary.verified_at
                and primary.ttl
                and is_past_ttl(primary.verified_at, primary.ttl)
            ),
            "citations": run_check(paths),
        },
    }
