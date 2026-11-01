"""Proved workflow-schema-3 authorization around the unchanged v2 checker.

A family of contexts is not a merged inference context. Every witness and every
assessment is checked under one complete, explicitly selected context.
"""

from dataclasses import replace

from kctx.domain.ids import ContextId, SnapshotId
from kctx.semantics.checker import assess, check, context_matches, usable_for
from kctx.semantics.model import (
    KB,
    Assessment,
    ClaimRef,
    CommitOutcome,
    Context,
    find_claim,
    narrower,
)
from kctx.semantics.wellformed import well_formed
from kctx.semantics.workflow import preserves_prefix
from kctx.semantics.workflow_models import (
    ClaimAssignment,
    NamedContext,
    PortfolioJournalEntry,
    PortfolioPlan,
    PortfolioResult,
    PortfolioSelectionJournalEntry,
    PortfolioSelectionPlan,
    PortfolioSelectionResult,
    PortfolioState,
    VerifiedPortfolioApproval,
    VerifiedPortfolioSelectionApproval,
)


def find_context(contexts: tuple[NamedContext, ...], identity: ContextId) -> NamedContext | None:
    return next((item for item in contexts if item.id == identity), None)


def context_family_valid(kb: KB, contexts: tuple[NamedContext, ...]) -> bool:
    return len({item.id for item in contexts}) == len(contexts) and all(
        context_matches(kb, item.context) for item in contexts
    )


def portfolio_state_valid(state: PortfolioState) -> bool:
    if not well_formed(state.kb):
        return False
    known = {claim.ref for claim in state.kb.claims}
    return (
        len(set(state.selected)) == len(state.selected)
        and all(ref in known for ref in state.selected)
        and context_family_valid(state.kb, state.contexts)
        and (bool(state.contexts) or not state.kb.claims)
    )


def retired_context_ids(
    before: tuple[NamedContext, ...], after: tuple[NamedContext, ...]
) -> tuple[ContextId, ...]:
    remaining = {item.id for item in after}
    return tuple(item.id for item in before if item.id not in remaining)


def context_evolution_valid(
    before: tuple[NamedContext, ...],
    after: tuple[NamedContext, ...],
    retired: tuple[ContextId, ...],
) -> bool:
    if retired != retired_context_ids(before, after) or len(set(retired)) != len(retired):
        return False
    for old in before:
        current = find_context(after, old.id)
        if current is not None and (
            current.context.target != old.context.target
            or current.context.intended_use != old.context.intended_use
        ):
            return False
    return True


def assignment_valid(
    candidate: KB, contexts: tuple[NamedContext, ...], assignment: ClaimAssignment
) -> bool:
    named = find_context(contexts, assignment.context)
    claim = find_claim(candidate, assignment.claim)
    if named is None or claim is None:
        return False
    checked = check(candidate, named.context, assignment.witness)
    return (
        checked is not None
        and checked.statement == claim.statement
        and any(
            derivation.claim == assignment.claim and derivation.witness == assignment.witness
            for derivation in candidate.derivations
        )
        and usable_for(candidate, named.context, assignment.claim)
    )


def portfolio_added_refs(state: PortfolioState, plan: PortfolioPlan) -> tuple[ClaimRef, ...]:
    return tuple(claim.ref for claim in plan.candidate.claims[len(state.kb.claims) :])


def admitted_portfolio(state: PortfolioState, plan: PortfolioPlan) -> PortfolioState:
    return PortfolioState(
        plan.candidate, (*state.selected, *portfolio_added_refs(state, plan)), plan.contexts
    )


def portfolio_plan_valid(state: PortfolioState, plan: PortfolioPlan) -> bool:
    return (
        portfolio_state_valid(state)
        and plan.candidate.snapshot != state.kb.snapshot
        and preserves_prefix(state.kb, plan.candidate)
        and bool(plan.actor.val.strip())
        and bool(plan.contexts)
        and all(plan.actor in item.context.policy.authorized_actors for item in plan.contexts)
        and context_evolution_valid(state.contexts, plan.contexts, plan.retired_contexts)
        and tuple(item.claim for item in plan.assignments) == portfolio_added_refs(state, plan)
        and all(assignment_valid(plan.candidate, plan.contexts, item) for item in plan.assignments)
        and portfolio_state_valid(admitted_portfolio(state, plan))
    )


def apply_portfolio(
    state: PortfolioState,
    journal: tuple[PortfolioJournalEntry, ...],
    plan: PortfolioPlan,
    *,
    trusted_approvals: tuple[VerifiedPortfolioApproval, ...] = (),
) -> PortfolioResult:
    for entry in journal:
        if entry.plan.id == plan.id:
            outcome = (
                CommitOutcome.ALREADY_APPLIED
                if entry.plan == plan
                else CommitOutcome.INPUT_CONFLICT
            )
            return PortfolioResult(state, journal, outcome)
    if plan.expected_snapshot != state.kb.snapshot:
        return PortfolioResult(state, journal, CommitOutcome.PREDECESSOR_CONFLICT)
    if not any(approval.plan == plan for approval in trusted_approvals) or not portfolio_plan_valid(
        state, plan
    ):
        return PortfolioResult(state, journal, CommitOutcome.REJECTED)
    return PortfolioResult(
        admitted_portfolio(state, plan),
        (PortfolioJournalEntry(plan), *journal),
        CommitOutcome.APPLIED,
    )


def query_context_allowed(state: PortfolioState, identity: ContextId, query: Context) -> bool:
    if not context_family_valid(state.kb, state.contexts) or not context_matches(state.kb, query):
        return False
    approved = find_context(state.contexts, identity)
    return (
        approved is not None
        and query == replace(approved.context, target=query.target, now=query.now)
        and narrower(query.target, approved.context.target)
        and approved.context.now <= query.now
    )


def assess_portfolio(
    state: PortfolioState, identity: ContextId, query: Context, ref: ClaimRef
) -> Assessment | None:
    if query_context_allowed(state, identity, query) and ref in state.selected:
        return assess(state.kb, query, ref)
    return None


def selected_portfolio(state: PortfolioState, plan: PortfolioSelectionPlan) -> PortfolioState:
    return PortfolioState(
        replace(state.kb, snapshot=plan.new_snapshot), plan.selected, plan.contexts
    )


def selection_contexts_valid(
    before: tuple[NamedContext, ...], after: tuple[NamedContext, ...], snapshot: SnapshotId
) -> bool:
    if tuple(item.id for item in before) != tuple(item.id for item in after):
        return False
    for current in after:
        old = find_context(before, current.id)
        if (
            old is None
            or current.context != replace(old.context, snapshot=snapshot, now=current.context.now)
            or old.context.now > current.context.now
        ):
            return False
    return True


def portfolio_selection_valid(
    state: PortfolioState,
    plan: PortfolioSelectionPlan,
    *,
    retained: tuple[PortfolioState, ...] = (),
) -> bool:
    if (
        not portfolio_state_valid(state)
        or not plan.actor.val.strip()
        or plan.new_snapshot == state.kb.snapshot
        or any(old.kb.snapshot == plan.new_snapshot for old in retained)
        or len({old.kb.snapshot for old in retained}) != len(retained)
        or not plan.contexts
        or not selection_contexts_valid(state.contexts, plan.contexts, plan.new_snapshot)
        or not all(plan.actor in item.context.policy.authorized_actors for item in plan.contexts)
        or not portfolio_state_valid(selected_portfolio(state, plan))
    ):
        return False
    target = next((old for old in retained if old.kb.snapshot == plan.retained_snapshot), None)
    return (
        target is not None
        and portfolio_state_valid(target)
        and preserves_prefix(target.kb, state.kb)
        and plan.selected == target.selected
    )


def apply_portfolio_selection(
    state: PortfolioState,
    journal: tuple[PortfolioSelectionJournalEntry, ...],
    plan: PortfolioSelectionPlan,
    *,
    trusted_approvals: tuple[VerifiedPortfolioSelectionApproval, ...] = (),
    retained: tuple[PortfolioState, ...] = (),
) -> PortfolioSelectionResult:
    for entry in journal:
        if entry.plan.id == plan.id:
            outcome = (
                CommitOutcome.ALREADY_APPLIED
                if entry.plan == plan
                else CommitOutcome.INPUT_CONFLICT
            )
            return PortfolioSelectionResult(state, journal, outcome)
    if plan.expected_snapshot != state.kb.snapshot:
        return PortfolioSelectionResult(state, journal, CommitOutcome.PREDECESSOR_CONFLICT)
    if not any(
        approval.plan == plan for approval in trusted_approvals
    ) or not portfolio_selection_valid(state, plan, retained=retained):
        return PortfolioSelectionResult(state, journal, CommitOutcome.REJECTED)
    return PortfolioSelectionResult(
        selected_portfolio(state, plan),
        (PortfolioSelectionJournalEntry(plan), *journal),
        CommitOutcome.APPLIED,
    )
