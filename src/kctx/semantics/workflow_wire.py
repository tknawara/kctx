"""Strict value codecs for the proved workflow-schema-3 types.

The v2 Context, Witness and KB codecs remain the only inference value boundary.
There is no decoding path from ordinary JSON to a trusted approval capability
except the explicit development-reference environment below.
"""

from __future__ import annotations

from kctx.domain.ids import (
    ActorId,
    ContextId,
    OperationId,
    ProposalMaterialRevision,
    SnapshotId,
    SourceId,
    TargetRevision,
)
from kctx.semantics import model as M
from kctx.semantics import workflow_models as W
from kctx.semantics.wire import (
    dec_authored_proposal,
    dec_context,
    dec_kb,
    dec_ref,
    dec_witness,
    enc_authored_proposal,
    enc_context,
    enc_kb,
    enc_ref,
    enc_witness,
    items,
    nat,
    obj,
    text,
)


def dec_named_context(value: object) -> W.NamedContext:
    v = obj(value, "id context")
    return W.NamedContext(
        ContextId(text(v["id"])),
        dec_context(v["context"]),
    )


def enc_named_context(value: W.NamedContext) -> dict[str, object]:
    return {
        "id": value.id.val,
        "context": enc_context(value.context),
    }


def dec_claim_assignment(value: object) -> W.ClaimAssignment:
    v = obj(value, "claim context witness")
    return W.ClaimAssignment(
        dec_ref(v["claim"]),
        ContextId(text(v["context"])),
        dec_witness(v["witness"]),
    )


def enc_claim_assignment(value: W.ClaimAssignment) -> dict[str, object]:
    return {
        "claim": enc_ref(value.claim),
        "context": value.context.val,
        "witness": enc_witness(value.witness),
    }


def dec_portfolio_state(value: object) -> W.PortfolioState:
    v = obj(value, "kb selected contexts")
    return W.PortfolioState(
        dec_kb(v["kb"]),
        items(v["selected"], dec_ref),
        items(v["contexts"], dec_named_context),
    )


def enc_portfolio_state(value: W.PortfolioState) -> dict[str, object]:
    return {
        "kb": enc_kb(value.kb),
        "selected": [enc_ref(item) for item in value.selected],
        "contexts": [enc_named_context(item) for item in value.contexts],
    }


def dec_portfolio_plan(value: object) -> W.PortfolioPlan:
    v = obj(value, "id expected_snapshot candidate actor contexts assignments retired_contexts")
    return W.PortfolioPlan(
        OperationId(text(v["id"])),
        SnapshotId(text(v["expected_snapshot"])),
        dec_kb(v["candidate"]),
        ActorId(text(v["actor"])),
        items(v["contexts"], dec_named_context),
        items(v["assignments"], dec_claim_assignment),
        items(v["retired_contexts"], lambda item: ContextId(text(item))),
    )


def enc_portfolio_plan(value: W.PortfolioPlan) -> dict[str, object]:
    return {
        "id": value.id.val,
        "expected_snapshot": value.expected_snapshot.val,
        "candidate": enc_kb(value.candidate),
        "actor": value.actor.val,
        "contexts": [enc_named_context(item) for item in value.contexts],
        "assignments": [enc_claim_assignment(item) for item in value.assignments],
        "retired_contexts": [item.val for item in value.retired_contexts],
    }


def dec_verified_portfolio_approval(value: object) -> W.VerifiedPortfolioApproval:
    v = obj(value, "plan")
    return W.VerifiedPortfolioApproval(
        dec_portfolio_plan(v["plan"]),
    )


def enc_verified_portfolio_approval(value: W.VerifiedPortfolioApproval) -> dict[str, object]:
    return {
        "plan": enc_portfolio_plan(value.plan),
    }


def dec_portfolio_journal_entry(value: object) -> W.PortfolioJournalEntry:
    v = obj(value, "plan")
    return W.PortfolioJournalEntry(
        dec_portfolio_plan(v["plan"]),
    )


def enc_portfolio_journal_entry(value: W.PortfolioJournalEntry) -> dict[str, object]:
    return {
        "plan": enc_portfolio_plan(value.plan),
    }


def dec_portfolio_result(value: object) -> W.PortfolioResult:
    v = obj(value, "state journal outcome")
    return W.PortfolioResult(
        dec_portfolio_state(v["state"]),
        items(v["journal"], dec_portfolio_journal_entry),
        M.CommitOutcome(text(v["outcome"])),
    )


def enc_portfolio_result(value: W.PortfolioResult) -> dict[str, object]:
    return {
        "state": enc_portfolio_state(value.state),
        "journal": [enc_portfolio_journal_entry(item) for item in value.journal],
        "outcome": value.outcome.value,
    }


def dec_portfolio_selection_plan(value: object) -> W.PortfolioSelectionPlan:
    v = obj(value, "id expected_snapshot retained_snapshot new_snapshot actor contexts selected")
    return W.PortfolioSelectionPlan(
        OperationId(text(v["id"])),
        SnapshotId(text(v["expected_snapshot"])),
        SnapshotId(text(v["retained_snapshot"])),
        SnapshotId(text(v["new_snapshot"])),
        ActorId(text(v["actor"])),
        items(v["contexts"], dec_named_context),
        items(v["selected"], dec_ref),
    )


def enc_portfolio_selection_plan(value: W.PortfolioSelectionPlan) -> dict[str, object]:
    return {
        "id": value.id.val,
        "expected_snapshot": value.expected_snapshot.val,
        "retained_snapshot": value.retained_snapshot.val,
        "new_snapshot": value.new_snapshot.val,
        "actor": value.actor.val,
        "contexts": [enc_named_context(item) for item in value.contexts],
        "selected": [enc_ref(item) for item in value.selected],
    }


def dec_verified_portfolio_selection_approval(
    value: object,
) -> W.VerifiedPortfolioSelectionApproval:
    v = obj(value, "plan")
    return W.VerifiedPortfolioSelectionApproval(
        dec_portfolio_selection_plan(v["plan"]),
    )


def enc_verified_portfolio_selection_approval(
    value: W.VerifiedPortfolioSelectionApproval,
) -> dict[str, object]:
    return {
        "plan": enc_portfolio_selection_plan(value.plan),
    }


def dec_portfolio_selection_journal_entry(value: object) -> W.PortfolioSelectionJournalEntry:
    v = obj(value, "plan")
    return W.PortfolioSelectionJournalEntry(
        dec_portfolio_selection_plan(v["plan"]),
    )


def enc_portfolio_selection_journal_entry(
    value: W.PortfolioSelectionJournalEntry,
) -> dict[str, object]:
    return {
        "plan": enc_portfolio_selection_plan(value.plan),
    }


def dec_portfolio_selection_result(value: object) -> W.PortfolioSelectionResult:
    v = obj(value, "state journal outcome")
    return W.PortfolioSelectionResult(
        dec_portfolio_state(v["state"]),
        items(v["journal"], dec_portfolio_selection_journal_entry),
        M.CommitOutcome(text(v["outcome"])),
    )


def enc_portfolio_selection_result(value: W.PortfolioSelectionResult) -> dict[str, object]:
    return {
        "state": enc_portfolio_state(value.state),
        "journal": [enc_portfolio_selection_journal_entry(item) for item in value.journal],
        "outcome": value.outcome.value,
    }


def dec_implementation_binding(value: object) -> W.ImplementationBinding:
    v = obj(value, "design_revision source target_revision actor observed_at")
    return W.ImplementationBinding(
        ProposalMaterialRevision(text(v["design_revision"])),
        SourceId(text(v["source"])),
        TargetRevision(text(v["target_revision"])),
        ActorId(text(v["actor"])),
        nat(v["observed_at"]),
    )


def enc_implementation_binding(value: W.ImplementationBinding) -> dict[str, object]:
    return {
        "design_revision": value.design_revision.val,
        "source": value.source.val,
        "target_revision": value.target_revision.val,
        "actor": value.actor.val,
        "observed_at": value.observed_at,
    }


def dec_design_proposal(value: object) -> W.DesignProposal:
    v = obj(value, "authored target_source binding")
    return W.DesignProposal(
        dec_authored_proposal(v["authored"]),
        SourceId(text(v["target_source"])),
        None if v["binding"] is None else dec_implementation_binding(v["binding"]),
    )


def enc_design_proposal(value: W.DesignProposal) -> dict[str, object]:
    return {
        "authored": enc_authored_proposal(value.authored),
        "target_source": value.target_source.val,
        "binding": None if value.binding is None else enc_implementation_binding(value.binding),
    }


def dec_design_binding_command(value: object) -> W.DesignBindingCommand:
    v = obj(value, "expected binding")
    return W.DesignBindingCommand(
        dec_design_proposal(v["expected"]),
        dec_implementation_binding(v["binding"]),
    )


def enc_design_binding_command(value: W.DesignBindingCommand) -> dict[str, object]:
    return {
        "expected": enc_design_proposal(value.expected),
        "binding": enc_implementation_binding(value.binding),
    }


def dec_design_reopen_command(value: object) -> W.DesignReopenCommand:
    v = obj(value, "expected actor reason")
    return W.DesignReopenCommand(
        dec_design_proposal(v["expected"]),
        ActorId(text(v["actor"])),
        text(v["reason"]),
    )


def enc_design_reopen_command(value: W.DesignReopenCommand) -> dict[str, object]:
    return {
        "expected": enc_design_proposal(value.expected),
        "actor": value.actor.val,
        "reason": value.reason,
    }
