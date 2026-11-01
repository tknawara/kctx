"""Workflow schema 3 values; the finite-witness inference language remains v2.

The definitions mirror Portfolio.lean and DesignWorkflow.lean. Trusted approval
values are adapter capabilities, not authentication supplied by ordinary callers.
"""

from __future__ import annotations

from dataclasses import dataclass

from kctx.domain.ids import (
    ActorId,
    ContextId,
    OperationId,
    ProposalMaterialRevision,
    SnapshotId,
    SourceId,
    TargetRevision,
)
from kctx.semantics.model import KB, AuthoredProposal, ClaimRef, CommitOutcome, Context, Witness

WORKFLOW_SCHEMA_VERSION = 3


@dataclass(frozen=True, slots=True)
class NamedContext:
    id: ContextId
    context: Context


@dataclass(frozen=True, slots=True)
class ClaimAssignment:
    claim: ClaimRef
    context: ContextId
    witness: Witness


@dataclass(frozen=True, slots=True)
class PortfolioState:
    kb: KB
    selected: tuple[ClaimRef, ...]
    contexts: tuple[NamedContext, ...]


@dataclass(frozen=True, slots=True)
class PortfolioPlan:
    id: OperationId
    expected_snapshot: SnapshotId
    candidate: KB
    actor: ActorId
    contexts: tuple[NamedContext, ...]
    assignments: tuple[ClaimAssignment, ...]
    retired_contexts: tuple[ContextId, ...]


@dataclass(frozen=True, slots=True)
class VerifiedPortfolioApproval:
    plan: PortfolioPlan


@dataclass(frozen=True, slots=True)
class PortfolioJournalEntry:
    plan: PortfolioPlan


@dataclass(frozen=True, slots=True)
class PortfolioResult:
    state: PortfolioState
    journal: tuple[PortfolioJournalEntry, ...]
    outcome: CommitOutcome


@dataclass(frozen=True, slots=True)
class PortfolioSelectionPlan:
    id: OperationId
    expected_snapshot: SnapshotId
    retained_snapshot: SnapshotId
    new_snapshot: SnapshotId
    actor: ActorId
    contexts: tuple[NamedContext, ...]
    selected: tuple[ClaimRef, ...]


@dataclass(frozen=True, slots=True)
class VerifiedPortfolioSelectionApproval:
    plan: PortfolioSelectionPlan


@dataclass(frozen=True, slots=True)
class PortfolioSelectionJournalEntry:
    plan: PortfolioSelectionPlan


@dataclass(frozen=True, slots=True)
class PortfolioSelectionResult:
    state: PortfolioState
    journal: tuple[PortfolioSelectionJournalEntry, ...]
    outcome: CommitOutcome


@dataclass(frozen=True, slots=True)
class ImplementationBinding:
    design_revision: ProposalMaterialRevision
    source: SourceId
    target_revision: TargetRevision
    actor: ActorId
    observed_at: int


@dataclass(frozen=True, slots=True)
class DesignProposal:
    authored: AuthoredProposal
    target_source: SourceId
    binding: ImplementationBinding | None


@dataclass(frozen=True, slots=True)
class DesignBindingCommand:
    expected: DesignProposal
    binding: ImplementationBinding


@dataclass(frozen=True, slots=True)
class DesignReopenCommand:
    expected: DesignProposal
    actor: ActorId
    reason: str
