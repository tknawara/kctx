"""Free-form reference and dossier completeness validation."""

from pathlib import Path

import kctx.services.dossiers as dossiers
from kctx.codecs.validation import decode_change_references, decode_runbook_references
from kctx.domain.ids import AssetId
from kctx.domain.records import Asset
from kctx.domain.vocabulary import Lifecycle
from kctx.services.discovery import all_runbook_paths, project_dirs
from kctx.services.validation_common import Diagnostics, read_record


def validate_references(root: Path, asset_ids: set[AssetId], diagnostics: Diagnostics) -> int:
    for path in all_runbook_paths(root):
        runbook = read_record(path, decode_runbook_references, diagnostics)
        if runbook is None:
            continue
        for asset in (*runbook.alerts, *runbook.assets):
            if asset not in asset_ids:
                diagnostics.problem(
                    "incomplete",
                    str(path),
                    f"asset/alert {asset.val!r} does not resolve to a known asset",
                )

    changes_count = 0
    for project in project_dirs(root):
        for path in sorted((project / "changes").glob("*.md")):
            changes_count += 1
            change = read_record(path, decode_change_references, diagnostics)
            if change is None:
                continue
            if not change.assets:
                diagnostics.warn(str(path), "assets list is empty")
            for asset in change.assets:
                if asset not in asset_ids:
                    diagnostics.problem(
                        "incomplete",
                        str(path),
                        f"asset {asset.val!r} does not resolve to a known asset",
                    )
    return changes_count


def validate_dossiers(root: Path, assets: tuple[Asset, ...], diagnostics: Diagnostics) -> int:
    lifecycle = {asset.id: asset.lifecycle for asset in assets}
    count = 0
    for path in dossiers.all_paths(root):
        count += 1
        parsed = read_record(path, dossiers.parse, diagnostics)
        if parsed is None:
            continue
        asset_id = parsed.frontmatter.asset
        if asset_id not in lifecycle:
            diagnostics.problem(
                "incomplete", str(path), f"asset {asset_id.val!r} does not resolve to a known asset"
            )
        missing = [heading for heading in dossiers.HEADINGS if heading not in parsed.body]
        if missing:
            diagnostics.problem("malformed", str(path), f"missing heading(s): {', '.join(missing)}")
        if lifecycle.get(asset_id) is Lifecycle.RETIRED:
            diagnostics.warn(
                str(path), f"dossier for retired asset {asset_id.val!r} sits outside archive/"
            )
    # Archived records retain their schema contract, not current heading requirements.
    for path in dossiers.all_archived_paths(root):
        count += 1
        read_record(path, dossiers.parse, diagnostics)
    return count
