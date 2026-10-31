"""Validate typed record families without letting one malformed file abort a report.

Each family decodes records independently and keeps schema diagnostics separate
from unresolved references and advisory warnings. Counts include malformed files
that were inspected; proposal/signature duplicate identities retain one count.
Legacy project journals remain outside the validation contract.
"""

from pathlib import Path

from kctx.services.validation_common import (
    Diagnostics,
    ValidationCounts,
    ValidationDiagnostic,
    ValidationResult,
)
from kctx.services.validation_corrections import validate_corrections
from kctx.services.validation_documents import validate_dossiers, validate_references
from kctx.services.validation_incidents import validate_incidents
from kctx.services.validation_inventory import validate_inventory
from kctx.services.validation_proposals import validate_proposals


def validate(root: Path) -> ValidationResult:
    diagnostics = Diagnostics()
    inventory = validate_inventory(root, diagnostics)
    asset_ids = {asset.id for asset in inventory.assets}
    proposals = validate_proposals(root, diagnostics)
    incidents = validate_incidents(root, asset_ids, diagnostics)
    changes = validate_references(root, asset_ids, diagnostics)
    dossiers = validate_dossiers(root, inventory.assets, diagnostics)
    corrections = validate_corrections(root, diagnostics)
    return ValidationResult(
        ok=not diagnostics.problems,
        problems=tuple(diagnostics.problems),
        warnings=tuple(diagnostics.warnings),
        counts=ValidationCounts(
            assets=inventory.asset_count,
            relationships=inventory.relationship_count,
            proposals=proposals,
            ktlo=incidents.ktlo,
            changes=changes,
            investigations=incidents.investigations,
            signatures=incidents.signatures,
            dossiers=dossiers,
            corrections=corrections,
        ),
    )


def result_to_wire(result: ValidationResult) -> dict[str, object]:
    """Encode the stable CLI report without exposing mutable domain records."""

    def diagnostic(value: ValidationDiagnostic) -> dict[str, str]:
        return {"category": value.category, "where": value.where, "message": value.message}

    counts = result.counts
    return {
        "ok": result.ok,
        "problems": [diagnostic(value) for value in result.problems],
        "warnings": [diagnostic(value) for value in result.warnings],
        "counts": {
            "assets": counts.assets,
            "relationships": counts.relationships,
            "proposals": counts.proposals,
            "ktlo": counts.ktlo,
            "changes": counts.changes,
            "investigations": counts.investigations,
            "signatures": counts.signatures,
            "dossiers": counts.dossiers,
            "corrections": counts.corrections,
        },
    }
