"""kctx semantic core — pure Python mirror of the proved Lean calculus.

This package is the production decision core specified by
``docs/kctx/handover.md`` §6 and checked against the Lean reference
evaluator (``formal/Kctx/Reference.lean``) by ``scripts/conformance_check.py``.

Design invariants (mirroring ``formal/Kctx``):

* Pure and total: no I/O, no clock, no randomness; time is an explicit
  integer (epoch seconds) supplied by the caller.
* Nominal identity types: ``ObservationId``/``ClaimId``/``ClaimRef`` never
  interchange.
* Freshness is an assessment relative to a context
  (``Freshness.fresh | stale | unknown``), never a stored property.
* Rejection codes and their order are a wire contract with the Lean
  reference: the same derivation must be rejected with the same code on both
  sides.
* The wire format is positional JSON arrays (see ``wire.py``); field order is
  the contract.

Stdlib only. Python >= 3.11.
"""

from kctx.semantics.model import (
    Atom,
    Binding,
    Claim,
    ClaimProp,
    ClaimRef,
    Correction,
    CorrectionKind,
    CoverageWitness,
    Dep,
    DepKind,
    Derivation,
    EvalCtx,
    Freshness,
    IdKind,
    Ident,
    KB,
    KbView,
    Observation,
    ObsOutcome,
    RuleId,
    Scope,
    SupportRole,
    Ttl,
    SEMANTIC_VERSION,
)
from kctx.semantics.time import assess_fresh, fresh_at
from kctx.semantics.checker import (
    Rejection,
    check_derivation_v,
    supported,
    has_fresh_evidence,
    contested,
    validation_current,
    usable_for,
    deps_satisfied,
    reusable,
)
from kctx.semantics.workflow import (
    Change,
    CommitOutcome,
    HypStatus,
    Hypothesis,
    Investigation,
    JournalEntry,
    Op,
    Proposal,
    ProposalStatus,
    TransitionError,
    add_claim,
    add_correction,
    add_derivation,
    add_observation,
    add_validation,
    apply_changes,
    can_conclude,
    commit_op,
    decided_status,
    legal_transition,
    plan_transition,
    ready_for_proposed,
)
from kctx.semantics import wire

__all__ = [
    "SEMANTIC_VERSION",
    "Atom", "Binding", "Claim", "ClaimProp", "ClaimRef",
    "Correction", "CorrectionKind", "CoverageWitness", "Dep", "DepKind",
    "Derivation", "EvalCtx", "Freshness", "IdKind", "Ident", "KB", "KbView",
    "Observation", "ObsOutcome", "RuleId", "Scope",
    "SupportRole", "Ttl",
    "assess_fresh", "fresh_at",
    "Rejection", "check_derivation_v", "supported",
    "has_fresh_evidence", "contested", "validation_current", "usable_for",
    "deps_satisfied", "reusable",
    "Change", "CommitOutcome", "HypStatus", "Hypothesis", "Investigation",
    "JournalEntry", "Op", "Proposal",
    "ProposalStatus", "TransitionError", "add_claim", "add_correction",
    "add_derivation", "add_observation", "add_validation", "apply_changes",
    "can_conclude", "commit_op",
    "decided_status", "legal_transition", "plan_transition",
    "ready_for_proposed",
    "wire",
]
