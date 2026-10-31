"""Inventory schema, uniqueness, and relationship endpoint checks."""

from dataclasses import dataclass
from pathlib import Path

from kctx.adapters.files.storage import list_json_files, read_json
from kctx.codecs.records import decode_asset, decode_relationship
from kctx.domain.ids import AssetId, RelationshipId
from kctx.domain.records import Asset
from kctx.errors import KctxError
from kctx.services.inventory import assets_dir, relationships_dir
from kctx.services.validation_common import Diagnostics


@dataclass(frozen=True, slots=True)
class InventoryValidation:
    assets: tuple[Asset, ...]
    asset_count: int
    relationship_count: int


def validate_inventory(root: Path, diagnostics: Diagnostics) -> InventoryValidation:
    assets: list[Asset] = []
    asset_ids: set[AssetId] = set()
    asset_paths = list_json_files(assets_dir(root))
    for path in asset_paths:
        try:
            asset = decode_asset(read_json(path))
        except (KctxError, ValueError, OSError) as error:
            diagnostics.malformed(path, error)
            continue
        assets.append(asset)
        if asset.id in asset_ids:
            diagnostics.problem("conflict", asset.id.val, "duplicate asset id")
        asset_ids.add(asset.id)
        if not asset.owner:
            diagnostics.problem("malformed", asset.id.val, "owner must be set (use 'unknown')")

    relationship_ids: set[RelationshipId] = set()
    relationship_paths = list_json_files(relationships_dir(root))
    for path in relationship_paths:
        try:
            relationship = decode_relationship(read_json(path))
        except (KctxError, ValueError, OSError) as error:
            diagnostics.malformed(path, error)
            continue
        if relationship.id in relationship_ids:
            diagnostics.problem("conflict", relationship.id.val, "duplicate relationship id")
        relationship_ids.add(relationship.id)
        for name, endpoint in (("from", relationship.from_), ("to", relationship.to)):
            if endpoint not in asset_ids:
                diagnostics.problem(
                    "incomplete",
                    relationship.id.val,
                    f"endpoint {name}={endpoint.val!r} does not resolve to a known asset",
                )
    return InventoryValidation(tuple(assets), len(asset_paths), len(relationship_paths))
