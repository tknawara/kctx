"""Authority-bound admission with structural canonical input replay identity."""

from __future__ import annotations

from dataclasses import replace

from kctx.domain.ids import ActorId, CheckerId, ProposalMaterialRevision, TargetRevision
from kctx.semantics.checker import accepted, context_matches, reusable, usable_for
from kctx.semantics.model import (
    KB,
    Application,
    AuthoredGateDefinition,
    AuthoredProfile,
    AuthoredProposal,
    AuthoredStatus,
    CommitOutcome,
    Context,
    GateOutcome,
    GateWhen,
    HypothesisStatus,
    Investigation,
    JournalEntry,
    Plan,
    Proposal,
    ProposalStatus,
    SelectionJournalEntry,
    SelectionPlan,
    SelectionResult,
    SelectionState,
    VerifiedApproval,
    VerifiedSelectionApproval,
    find_claim,
)
from kctx.semantics.wellformed import well_formed


def preserves_prefix(base: KB, candidate: KB) -> bool:
    collections = (
        (base.observations, candidate.observations),
        (base.claims, candidate.claims),
        (base.attestations, candidate.attestations),
        (base.enumerations, candidate.enumerations),
        (base.derivations, candidate.derivations),
        (base.corrections, candidate.corrections),
        (base.receipts, candidate.receipts),
    )
    return all(new[: len(old)] == old for old, new in collections)


def plan_valid(kb: KB, context: Context, plan: Plan) -> bool:
    if (
        not context_matches(kb, context)
        or not well_formed(plan.candidate)
        or plan.candidate.snapshot == kb.snapshot
        or not preserves_prefix(kb, plan.candidate)
    ):
        return False
    candidate_context = replace(context, snapshot=plan.candidate.snapshot)
    claim = find_claim(plan.candidate, plan.claim)
    authority = plan.authority
    added = plan.candidate.claims[len(kb.claims) :]
    if (
        claim is None
        or not _identity_present(authority.actor)
        or authority.target != plan.claim
        or authority.actor not in context.policy.authorized_actors
        or authority.statement != claim.statement
        or authority.policy != context.policy.id
        or authority.intended_use != context.intended_use
        or authority.context != context
        or authority.approved != plan.candidate
        or authority.approvals != added
    ):
        return False
    if not any(
        witness == plan.witness
        for witness, _ in accepted(plan.candidate, candidate_context, plan.claim)
    ):
        return False
    return usable_for(plan.candidate, candidate_context, plan.claim) and all(
        accepted(plan.candidate, candidate_context, item.ref)
        and usable_for(plan.candidate, candidate_context, item.ref)
        for item in added
    )


def apply_plan(
    kb: KB,
    context: Context,
    journal: tuple[JournalEntry, ...],
    plan: Plan,
    *,
    trusted_approvals: tuple[VerifiedApproval, ...] = (),
) -> Application:
    for entry in journal:
        if entry.plan.id == plan.id:
            outcome = (
                CommitOutcome.ALREADY_APPLIED
                if entry.plan == plan
                else CommitOutcome.INPUT_CONFLICT
            )
            return Application(kb, journal, outcome)
    if plan.expected_snapshot != kb.snapshot:
        return Application(kb, journal, CommitOutcome.PREDECESSOR_CONFLICT)
    if not any(approval.plan == plan for approval in trusted_approvals) or not plan_valid(
        kb, context, plan
    ):
        return Application(kb, journal, CommitOutcome.REJECTED)
    return Application(plan.candidate, (JournalEntry(plan), *journal), CommitOutcome.APPLIED)


def transition(kb: KB, context: Context, proposal: Proposal, target: ProposalStatus) -> bool:
    legal = {
        (ProposalStatus.DRAFT, ProposalStatus.PROPOSED),
        (ProposalStatus.PROPOSED, ProposalStatus.APPROVED),
        (ProposalStatus.PROPOSED, ProposalStatus.REJECTED),
        (ProposalStatus.APPROVED, ProposalStatus.APPLIED),
        (ProposalStatus.APPROVED, ProposalStatus.REJECTED),
        (ProposalStatus.APPLIED, ProposalStatus.VERIFIED),
    }
    if (
        (proposal.status, target) not in legal
        or not _identity_present(proposal.actor)
        or not usable_for(kb, context, proposal.target)
    ):
        return False
    for gate in proposal.gates:
        receipt = next((r for r in kb.receipts if r.id == gate), None)
        if receipt is None or not reusable(kb, context, proposal.target, receipt):
            return False
    if (
        target in (ProposalStatus.APPROVED, ProposalStatus.APPLIED, ProposalStatus.VERIFIED)
        and not proposal.gates
    ):
        return False
    if target is ProposalStatus.APPLIED and not _identity_present(proposal.executor):
        return False
    if target is ProposalStatus.VERIFIED and (
        not _identity_present(proposal.executor)
        or not _identity_present(proposal.acceptor)
        or proposal.executor == proposal.acceptor
    ):
        return False
    return True


def conclude(investigation: Investigation) -> bool:
    """Authored investigation completion, explicitly not factual admission."""
    return bool(
        investigation.checked_against.strip() and investigation.scope_and_limits.strip()
    ) and all(
        hypothesis.text.strip() and hypothesis.status is not HypothesisStatus.OPEN
        for hypothesis in investigation.hypotheses
    )


def _identity_present(
    value: ActorId | CheckerId | ProposalMaterialRevision | TargetRevision | None,
) -> bool:
    return value is not None and bool(value.val.strip())


def authored_gate_valid(definition: AuthoredGateDefinition) -> bool:
    return _identity_present(definition.by) and all(
        value.strip() for value in (definition.id.val, definition.claim, definition.check)
    )


def authored_ready(proposal: AuthoredProposal) -> bool:
    if proposal.profile is AuthoredProfile.LEGACY_LIMITED:
        return True
    return (
        proposal.research_present
        and proposal.alternatives_count >= 2
        and len({definition.id for definition in proposal.gate_definitions})
        == len(proposal.gate_definitions)
        and bool(proposal.gate_definitions)
        and all(authored_gate_valid(d) for d in proposal.gate_definitions)
    )


def authored_gate_passes(
    proposal: AuthoredProposal, definition: AuthoredGateDefinition, now: int
) -> bool:
    if (
        not proposal.environment.strip()
        or not proposal.scope.strip()
        or not _identity_present(proposal.proposal_revision)
    ):
        return False
    result = next(
        (
            result
            for result in reversed(proposal.gate_results)
            if result.definition == definition
            and result.target_revision == proposal.target_revision
            and result.proposal_revision == proposal.proposal_revision
            and result.environment == proposal.environment
            and result.scope == proposal.scope
            and _identity_present(result.checker)
            and (not _identity_present(definition.checker) or result.checker == definition.checker)
            and result.observed_at <= now
        ),
        None,
    )
    return (
        result is not None
        and result.result is GateOutcome.PASS
        and now <= result.expires_at
        and bool(result.evidence_refs)
        and all(ref.strip() for ref in result.evidence_refs)
        and _identity_present(result.actor)
    )


def authored_edge(current: AuthoredStatus, target: AuthoredStatus) -> bool:
    legal = {
        (AuthoredStatus.DRAFT, AuthoredStatus.PROPOSED),
        (AuthoredStatus.PROPOSED, AuthoredStatus.DRAFT),
        (AuthoredStatus.PROPOSED, AuthoredStatus.ACCEPTED),
        (AuthoredStatus.PROPOSED, AuthoredStatus.REJECTED),
        (AuthoredStatus.ACCEPTED, AuthoredStatus.LANDING),
        (AuthoredStatus.ACCEPTED, AuthoredStatus.DEFERRED),
        (AuthoredStatus.LANDING, AuthoredStatus.APPLIED),
        (AuthoredStatus.APPLIED, AuthoredStatus.VERIFIED),
        (AuthoredStatus.APPLIED, AuthoredStatus.REGRESSED),
        (AuthoredStatus.VERIFIED, AuthoredStatus.REGRESSED),
    }
    return (current, target) in legal or (
        target is AuthoredStatus.SUPERSEDED and current is not target
    )


def authored_supersession_valid(proposal: AuthoredProposal) -> bool:
    rows = {row.id: row for row in proposal.proposals}
    if (
        len(rows) != len(proposal.proposals)
        or proposal.id not in rows
        or proposal.superseded_by is None
    ):
        return False
    seen = {proposal.id}
    target = proposal.superseded_by
    while target is not None:
        if target in seen or target not in rows:
            return False
        seen.add(target)
        target = rows[target].superseded_by
    return True


def authored_transition(proposal: AuthoredProposal, target: AuthoredStatus, now: int) -> bool:
    return authored_edge(proposal.status, target) and authored_candidate_valid(
        proposal, target, now
    )


def authored_candidate_valid(proposal: AuthoredProposal, target: AuthoredStatus, now: int) -> bool:
    """Validate an authored candidate independently of its transition history."""
    if target is AuthoredStatus.SUPERSEDED and not authored_supersession_valid(proposal):
        return False
    if target in (
        AuthoredStatus.ACCEPTED,
        AuthoredStatus.LANDING,
        AuthoredStatus.APPLIED,
        AuthoredStatus.VERIFIED,
    ) and (
        not _identity_present(proposal.accepted_revision)
        or proposal.accepted_revision != proposal.proposal_revision
    ):
        return False
    if target in (
        AuthoredStatus.ACCEPTED,
        AuthoredStatus.REJECTED,
        AuthoredStatus.LANDING,
        AuthoredStatus.APPLIED,
    ) and not _identity_present(proposal.actor):
        return False
    if target in (
        AuthoredStatus.PROPOSED,
        AuthoredStatus.ACCEPTED,
        AuthoredStatus.LANDING,
        AuthoredStatus.APPLIED,
        AuthoredStatus.VERIFIED,
    ) and not authored_ready(proposal):
        return False
    if target in (
        AuthoredStatus.ACCEPTED,
        AuthoredStatus.LANDING,
        AuthoredStatus.APPLIED,
        AuthoredStatus.VERIFIED,
    ) and not _identity_present(proposal.acceptor):
        return False
    if target in (
        AuthoredStatus.LANDING,
        AuthoredStatus.APPLIED,
        AuthoredStatus.VERIFIED,
    ) and not _identity_present(proposal.executor):
        return False
    if target in (AuthoredStatus.APPLIED, AuthoredStatus.VERIFIED):
        if (
            not _identity_present(proposal.target_revision)
            or not proposal.landed_refs
            or any(not ref.strip() for ref in proposal.landed_refs)
        ):
            return False
        if not all(
            any(resolution.reference == ref for resolution in proposal.resolved_landed)
            for ref in proposal.landed_refs
        ):
            return False
        if not any(
            resolution.reference in proposal.landed_refs
            and resolution.target_revision == proposal.target_revision
            for resolution in proposal.resolved_landed
        ):
            return False
        definitions = proposal.gate_definitions
        if target is AuthoredStatus.APPLIED:
            definitions = tuple(d for d in definitions if d.when is GateWhen.LAND)
            if not definitions:
                return False
        elif not (
            any(d.when is GateWhen.DEPLOY for d in definitions)
            and any(d.when is GateWhen.USE for d in definitions)
        ):
            return False
        if not all(authored_gate_passes(proposal, definition, now) for definition in definitions):
            return False
    if target is AuthoredStatus.REGRESSED and not proposal.regression_note.strip():
        return False
    return True


def selection_plan_valid(
    state: SelectionState, context: Context, plan: SelectionPlan, *, retained: tuple[KB, ...] = ()
) -> bool:
    if (
        not context_matches(state.kb, context)
        or not well_formed(state.kb)
        or len(set(state.selected)) != len(state.selected)
        or any(find_claim(state.kb, ref) is None for ref in state.selected)
        or plan.new_snapshot == state.kb.snapshot
        or len({kb.snapshot for kb in retained}) != len(retained)
        or any(kb.snapshot == plan.new_snapshot for kb in retained)
        or not _identity_present(plan.actor)
        or plan.actor not in context.policy.authorized_actors
        or plan.context != context
        or plan.policy != context.policy.id
        or plan.intended_use != context.intended_use
    ):
        return False
    targets = tuple(kb for kb in retained if kb.snapshot == plan.target_snapshot)
    if len(targets) != 1:
        return False
    target = targets[0]
    return (
        well_formed(target)
        and preserves_prefix(target, state.kb)
        and plan.selected == tuple(claim.ref for claim in target.claims)
        and all(find_claim(state.kb, ref) is not None for ref in plan.selected)
    )


def apply_selection(
    state: SelectionState,
    context: Context,
    journal: tuple[SelectionJournalEntry, ...],
    plan: SelectionPlan,
    *,
    trusted_approvals: tuple[VerifiedSelectionApproval, ...] = (),
    retained: tuple[KB, ...] = (),
) -> SelectionResult:
    for entry in journal:
        if entry.plan.id == plan.id:
            outcome = (
                CommitOutcome.ALREADY_APPLIED
                if entry.plan == plan
                else CommitOutcome.INPUT_CONFLICT
            )
            return SelectionResult(state, journal, outcome)
    if plan.expected_snapshot != state.kb.snapshot:
        return SelectionResult(state, journal, CommitOutcome.PREDECESSOR_CONFLICT)
    if not any(approval.plan == plan for approval in trusted_approvals) or not selection_plan_valid(
        state, context, plan, retained=retained
    ):
        return SelectionResult(state, journal, CommitOutcome.REJECTED)
    selected = SelectionState(replace(state.kb, snapshot=plan.new_snapshot), plan.selected)
    return SelectionResult(selected, (SelectionJournalEntry(plan), *journal), CommitOutcome.APPLIED)
