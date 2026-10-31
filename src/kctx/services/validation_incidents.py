"""Incident references, conclusion completeness, and regression warnings."""

from dataclasses import dataclass
from pathlib import Path

import kctx.services.investigations as investigations
import kctx.services.ktlo as ktlo
import kctx.services.signatures as signatures
from kctx.domain.ids import AssetId, SignatureId, TicketId
from kctx.domain.incidents import ProjectRef
from kctx.domain.time import parse_flexible_timestamp
from kctx.domain.vocabulary import InvestigationStatus
from kctx.errors import KctxError
from kctx.services.discovery import project_dirs
from kctx.services.validation_common import Diagnostics, read_record


@dataclass(frozen=True, slots=True)
class IncidentCounts:
    ktlo: int
    investigations: int
    signatures: int


def validate_incidents(
    root: Path, asset_ids: set[AssetId], diagnostics: Diagnostics
) -> IncidentCounts:
    ticket_ids: set[TicketId] = set()
    ktlo_paths = ktlo.all_paths(root)
    for path in ktlo_paths:
        parsed = read_record(path, ktlo.parse, diagnostics)
        if parsed is None:
            continue
        record = parsed.frontmatter
        if record.ticket in ticket_ids:
            diagnostics.problem("conflict", str(path), f"duplicate ticket {record.ticket.val!r}")
        ticket_ids.add(record.ticket)
        if not record.assets:
            diagnostics.warn(str(path), "assets list is empty")
        for asset in record.assets:
            if asset not in asset_ids:
                diagnostics.problem(
                    "incomplete",
                    str(path),
                    f"asset {asset.val!r} does not resolve to a known asset",
                )

    signature_ids: set[SignatureId] = set()
    fixed_signatures: dict[SignatureId, str] = {}
    malformed_signatures = 0
    for path in signatures.all_paths(root):
        parsed_signature = read_record(path, signatures.parse, diagnostics)
        if parsed_signature is None:
            malformed_signatures += 1
            continue
        signature = parsed_signature.frontmatter
        if signature.id in signature_ids:
            diagnostics.problem("conflict", str(path), "duplicate signature id")
        signature_ids.add(signature.id)
        if signature.fixed_at:
            fixed_signatures[signature.id] = signature.fixed_at
        for asset in signature.assets:
            if asset not in asset_ids:
                diagnostics.problem(
                    "incomplete",
                    signature.id.val,
                    f"asset {asset.val!r} does not resolve to a known asset",
                )

    projects = {path.name for path in project_dirs(root)}
    investigation_paths = investigations.all_paths(root)
    for path in investigation_paths:
        parsed_investigation = read_record(path, investigations.parse, diagnostics)
        if parsed_investigation is None:
            continue
        investigation = parsed_investigation.frontmatter
        body = parsed_investigation.body
        for asset in (*investigation.assets, *investigation.alerts):
            if asset not in asset_ids:
                diagnostics.problem(
                    "incomplete",
                    investigation.id.val,
                    f"asset/alert {asset.val!r} does not resolve to a known asset",
                )
        for signature_id in investigation.signatures:
            if signature_id not in signature_ids:
                diagnostics.problem(
                    "incomplete",
                    investigation.id.val,
                    f"signature {signature_id.val!r} does not resolve to a known signature",
                )
            fixed_at = fixed_signatures.get(signature_id)
            if fixed_at and investigation.created:
                try:
                    after_fix = parse_flexible_timestamp(
                        investigation.created
                    ) > parse_flexible_timestamp(fixed_at)
                except KctxError:
                    continue
                if after_fix:
                    diagnostics.warn(
                        investigation.id.val,
                        f"possible regression: signature {signature_id.val} was fixed_at {fixed_at} but this investigation is dated {investigation.created}",
                    )
        for spawned in investigation.spawned:
            if isinstance(spawned, ProjectRef):
                name, resolves = spawned.name, spawned.name in projects
            else:
                name, resolves = spawned.val, spawned in ticket_ids
            if not resolves:
                diagnostics.problem(
                    "incomplete",
                    investigation.id.val,
                    f"spawned {name!r} does not resolve to a known ktlo ticket or project",
                )
        try:
            if investigation.status is InvestigationStatus.CONCLUDED:
                missing = investigations.conclusion_problems(body)
                for problem in missing:
                    diagnostics.problem(
                        "incomplete",
                        investigation.id.val,
                        f"concluded without required completion: {problem}",
                    )
            else:
                investigations.parse_hypotheses(body.get("Hypotheses", ""))
        except (KctxError, ValueError) as error:
            diagnostics.malformed(path, error)
    return IncidentCounts(
        len(ktlo_paths), len(investigation_paths), len(signature_ids) + malformed_signatures
    )
