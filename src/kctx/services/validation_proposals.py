"""Proposal diagnostics backed by the authored transition candidate predicates."""

import time
from pathlib import Path

from kctx.codecs.documents import parse_document
from kctx.codecs.proposals import decode_proposal
from kctx.domain.ids import ProposalId
from kctx.domain.proposals import ProposalDocument, ProposalProfile
from kctx.errors import KctxError
from kctx.semantics.design_workflow import design_candidate_problems
from kctx.semantics.model import AuthoredReplacement
from kctx.semantics.workflow import authored_candidate_problems
from kctx.services.gates import load_results
from kctx.services.proposals import (
    DECIDED_STATUSES,
    all_paths,
    design_assessment,
    persisted_assessment,
)
from kctx.services.validation_common import Diagnostics


def validate_proposals(root: Path, diagnostics: Diagnostics) -> int:
    seen: set[ProposalId] = set()
    records: list[ProposalDocument] = []
    malformed_count = 0
    for path in all_paths(root):
        try:
            document = parse_document(path.read_text(encoding="utf-8"))
            profile = (
                ProposalProfile.MODERN
                if path.name == "proposal.md"
                else ProposalProfile.LEGACY_LIMITED
            )
            proposal = decode_proposal(document, profile=profile)
            if (
                profile is ProposalProfile.MODERN
                and proposal.profile is ProposalProfile.LEGACY_LIMITED
            ):
                raise KctxError(
                    "malformed", "directory-home proposal cannot claim a legacy profile"
                )
        except (KctxError, ValueError, OSError) as error:
            diagnostics.malformed(path, error)
            malformed_count += 1
            continue
        if proposal.id in seen:
            diagnostics.problem("conflict", str(path), "duplicate proposal id")
        seen.add(proposal.id)
        records.append(ProposalDocument(path, proposal, document))
        if proposal.status in DECIDED_STATUSES and not proposal.decided_by:
            diagnostics.problem(
                "incomplete", proposal.id.val, f"status={proposal.status.value} requires decided_by"
            )
        if path.name == "proposal.md" and proposal.origin is None:
            diagnostics.warn(proposal.id.val, "new-format proposal missing origin")

    # Build the supersession graph only from individually admitted records. An
    # unrelated malformed proposal must not abort assessment of its neighbors.
    replacements = tuple(
        AuthoredReplacement(record.proposal.id, record.proposal.superseded_by) for record in records
    )
    now = int(time.time())
    for record in records:
        try:
            model = persisted_assessment(
                record.proposal,
                record.document,
                load_results(record.path),
                replacements=replacements,
                root=root,
            )
            if record.proposal.profile is ProposalProfile.LEGACY_LIMITED and (
                record.proposal.status in DECIDED_STATUSES
            ):
                diagnostics.warn(
                    record.proposal.id.val,
                    "legacy_limited authored profile: historical status is not verified "
                    "knowledge or release authority",
                )
            problems = (
                design_candidate_problems(
                    design_assessment(record.proposal, model), model.status, now
                )
                if record.proposal.workflow_version == 3
                else authored_candidate_problems(model, model.status, now)
            )
            if problems:
                diagnostics.problem(
                    "incomplete",
                    record.proposal.id.val,
                    f"status={record.proposal.status.value} violates authored candidate "
                    f"invariants: {', '.join(problems)}",
                )
        except (KctxError, ValueError, OSError) as error:
            diagnostics.malformed(record.path, error)
    return len(seen) + malformed_count
