"""Workflow transitions mirroring ``formal/Kctx/Workflow.lean``:
proposal lifecycle (one readiness predicate for both filing paths),
investigation conclusion, and conditional commit with idempotent journal
(T20/T21)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional, Tuple

from kctx.semantics.model import KB, Claim, ClaimRef, Correction, Derivation, Observation


class ProposalStatus(Enum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    LANDING = "landing"
    APPLIED = "applied"
    VERIFIED = "verified"
    REGRESSED = "regressed"
    SUPERSEDED = "superseded"


_LEGAL = {
    (ProposalStatus.DRAFT, ProposalStatus.PROPOSED),
    (ProposalStatus.PROPOSED, ProposalStatus.ACCEPTED),
    (ProposalStatus.PROPOSED, ProposalStatus.REJECTED),
    (ProposalStatus.PROPOSED, ProposalStatus.DEFERRED),
    (ProposalStatus.ACCEPTED, ProposalStatus.LANDING),
    (ProposalStatus.LANDING, ProposalStatus.APPLIED),
    (ProposalStatus.APPLIED, ProposalStatus.VERIFIED),
    (ProposalStatus.APPLIED, ProposalStatus.REGRESSED),
    (ProposalStatus.VERIFIED, ProposalStatus.REGRESSED),
}


def legal_transition(src: ProposalStatus, tgt: ProposalStatus) -> bool:
    if tgt is ProposalStatus.SUPERSEDED and src is not ProposalStatus.SUPERSEDED:
        return True
    return (src, tgt) in _LEGAL


_DECIDED = {
    ProposalStatus.ACCEPTED,
    ProposalStatus.REJECTED,
    ProposalStatus.APPLIED,
    ProposalStatus.LANDING,
}


def decided_status(s: ProposalStatus) -> bool:
    return s in _DECIDED


@dataclass(frozen=True, slots=True)
class Proposal:
    id: str
    status: ProposalStatus = ProposalStatus.DRAFT
    research_present: bool = False
    research_justified_skip: bool = False
    alternatives_count: int = 0
    gates_table_present: bool = False
    legacy_profile: bool = False
    decided_by: Optional[str] = None
    landed_refs: Tuple[str, ...] = ()
    land_gates_passed: bool = False
    deploy_use_gates_passed: bool = False


def ready_for_proposed(p: Proposal) -> bool:
    """One readiness predicate for BOTH filing-as-proposed and
    draft→proposed (the old readiness bypass is intentionally gone)."""
    return (
        (p.research_present or p.research_justified_skip)
        and p.alternatives_count >= 2
        and (p.gates_table_present or p.legacy_profile)
    )


class TransitionError(Enum):
    ILLEGAL_TRANSITION = "illegalTransition"
    NOT_READY = "notReady"
    MISSING_ACTOR = "missingActor"
    GATES_NOT_PASSED = "gatesNotPassed"
    LANDED_REFS_UNRESOLVED = "landedRefsUnresolved"


def plan_transition(
    p: Proposal,
    target: ProposalStatus,
    actor: Optional[str],
    landed_refs: Tuple[str, ...],
    refs_resolvable: bool,
):
    """Pure planning (T18): returns ``("planned", proposal)`` or
    ``("refused", code)`` — exactly the Lean ``PlanOutcome`` wire form."""
    if not legal_transition(p.status, target):
        return ["refused", TransitionError.ILLEGAL_TRANSITION.value]
    if target is ProposalStatus.PROPOSED and not ready_for_proposed(p):
        return ["refused", TransitionError.NOT_READY.value]
    if decided_status(target) and actor is None:
        return ["refused", TransitionError.MISSING_ACTOR.value]
    if target is ProposalStatus.APPLIED and not (
        p.land_gates_passed and refs_resolvable and bool(landed_refs)
    ):
        return ["refused", TransitionError.GATES_NOT_PASSED.value]
    if target is ProposalStatus.VERIFIED and not p.deploy_use_gates_passed:
        return ["refused", TransitionError.GATES_NOT_PASSED.value]
    p2 = replace(
        p,
        status=target,
        decided_by=(
            actor
            if decided_status(target)
            else (None if target is ProposalStatus.PROPOSED else p.decided_by)
        ),
        landed_refs=(landed_refs if target is ProposalStatus.APPLIED else p.landed_refs),
    )
    return ["planned", p2]


class HypStatus(Enum):
    OPEN = "openH"
    SUPPORTED = "supportedH"
    REFUTED = "refutedH"
    UNKNOWN = "unknownH"
    MALFORMED = "malformedH"


@dataclass(frozen=True, slots=True)
class Hypothesis:
    text: str
    status: HypStatus


@dataclass(frozen=True, slots=True)
class Investigation:
    id: str
    checked_against: str
    scope_and_limits: str
    hypotheses: Tuple[Hypothesis, ...]


def can_conclude(i: Investigation) -> bool:
    """T19: both sections non-empty, no open hypothesis, and malformed
    hypothesis bullets block (never invisible)."""
    return (
        bool(i.checked_against)
        and bool(i.scope_and_limits)
        and not any(
            h.status in (HypStatus.OPEN, HypStatus.MALFORMED) for h in i.hypotheses
        )
    )


class CommitOutcome(Enum):
    COMMITTED = "committed"
    ALREADY_COMMITTED = "alreadyCommitted"
    PREDECESSOR_CONFLICT = "predecessorConflict"
    INPUT_CONFLICT = "inputConflict"
    REJECTED_INVALID = "rejectedInvalid"


class Change:
    __slots__ = ("tag", "payload")

    def __init__(self, tag: str, payload):
        self.tag = tag
        self.payload = payload


def add_claim(c: Claim) -> Change:
    return Change("addClaim", c)


def add_observation(o: Observation) -> Change:
    return Change("addObservation", o)


def add_derivation(d: Derivation) -> Change:
    return Change("addDerivation", d)


def add_correction(c: Correction) -> Change:
    return Change("addCorrection", c)


def add_validation(ref: ClaimRef, digest: str) -> Change:
    return Change("addValidation", (ref, digest))


@dataclass(frozen=True, slots=True)
class Op:
    id: str
    expected_head: str
    changes: Tuple[Change, ...]
    input_digest: str


@dataclass(frozen=True, slots=True)
class JournalEntry:
    id: str
    head: str
    digest: str


def apply_change(kb: KB, ch: Change) -> KB:
    tag = ch.tag
    if tag == "addClaim":
        return replace(kb, claims=kb.claims + (ch.payload,))
    if tag == "addObservation":
        return replace(kb, observations=kb.observations + (ch.payload,))
    if tag == "addDerivation":
        return replace(kb, derivations=kb.derivations + (ch.payload,))
    if tag == "addCorrection":
        return replace(kb, corrections=kb.corrections + (ch.payload,))
    if tag == "addValidation":
        return replace(kb, validations=kb.validations + (ch.payload,))
    raise AssertionError(tag)


def apply_changes(kb: KB, changes: Tuple[Change, ...]) -> KB:
    for ch in changes:
        kb = apply_change(kb, ch)
    return kb


def commit_op(kb: KB, journal: Tuple[JournalEntry, ...], op: Op):
    """Conditional commit (T20/T21): returns ``(kb, outcome_name)``.
    Rejection of any kind leaves the modeled state unchanged."""
    for e in journal:
        if e.id == op.id:
            if e.digest == op.input_digest and e.head == op.expected_head:
                return kb, CommitOutcome.ALREADY_COMMITTED.value
            return kb, CommitOutcome.INPUT_CONFLICT.value
    if kb.head != op.expected_head:
        return kb, CommitOutcome.PREDECESSOR_CONFLICT.value
    kb2 = apply_changes(kb, op.changes)
    from kctx.semantics.wellformed import view_well_formed

    if not view_well_formed(kb2.view()):
        return kb, CommitOutcome.REJECTED_INVALID.value
    return replace(kb2, head=op.id), CommitOutcome.COMMITTED.value
