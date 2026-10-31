"""Pure immutable values for the version 2 finite-witness calculus."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from kctx.domain.ids import (
    ActorId,
    AttestationId,
    CheckerId,
    ClaimId,
    ClaimRevision,
    ContentId,
    CorrectionId,
    DerivationId,
    EnumerationId,
    GateId,
    ObservationId,
    OperationId,
    PolicyId,
    ProjectId,
    ProposalId,
    ProposalMaterialRevision,
    ReceiptId,
    RuleVersion,
    SnapshotId,
    SourceId,
    SourceRevision,
    TargetRevision,
)

SEMANTIC_VERSION = "2.0.0"
SCHEMA_VERSION = 2


class TtlTag(Enum):
    EXPIRE_AFTER = "expireAfter"
    NO_EXPIRY = "noExpiry"
    MISSING = "missing"


def _require_ttl_tag(value: object) -> None:
    if not isinstance(value, TtlTag):
        raise ValueError("invalid ttl tag")


@dataclass(frozen=True, slots=True)
class Ttl:
    tag: TtlTag
    secs: int | None = None

    def __post_init__(self) -> None:
        _require_ttl_tag(self.tag)
        if self.tag is TtlTag.EXPIRE_AFTER:
            if isinstance(self.secs, bool) or not isinstance(self.secs, int):
                raise ValueError("expireAfter requires integer seconds")
        elif self.secs is not None:
            raise ValueError("non-expiring ttl cannot carry seconds")


def ttl_expire_after(secs: int) -> Ttl:
    return Ttl(TtlTag.EXPIRE_AFTER, secs)


TTL_NO_EXPIRY = Ttl(TtlTag.NO_EXPIRY)
TTL_MISSING = Ttl(TtlTag.MISSING)


class Freshness(Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Scope:
    project: ProjectId
    selector: str


def narrower(target: Scope, source: Scope) -> bool:
    return target.project == source.project and (
        not source.selector or target.selector == source.selector
    )


@dataclass(frozen=True, slots=True)
class Atom:
    subject: str
    predicate: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Atomic:
    atom: Atom


@dataclass(frozen=True, slots=True)
class Truth:
    pass


@dataclass(frozen=True, slots=True)
class Conjunction:
    left: Formula
    right: Formula


@dataclass(frozen=True, slots=True)
class All:
    enumeration: EnumerationId
    predicate: str


@dataclass(frozen=True, slots=True)
class Absent:
    enumeration: EnumerationId


@dataclass(frozen=True, slots=True)
class Inventory:
    enumeration: EnumerationId


Formula = Atomic | Truth | Conjunction | All | Absent | Inventory


class Polarity(Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


@dataclass(frozen=True, slots=True)
class Statement:
    formula: Formula
    scope: Scope
    polarity: Polarity = Polarity.POSITIVE


@dataclass(frozen=True, slots=True)
class ClaimRef:
    id: ClaimId
    rev: ClaimRevision


@dataclass(frozen=True, slots=True)
class Claim:
    id: ClaimId
    revision: ClaimRevision
    statement: Statement

    @property
    def ref(self) -> ClaimRef:
        return ClaimRef(self.id, self.revision)


class ObsOutcome(Enum):
    OK = "ok"
    TIMEOUT = "timeout"
    PARTIAL = "partial"
    TRUNCATED = "truncated"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class Observation:
    id: ObservationId
    source: SourceId
    revision: SourceRevision
    content: ContentId
    observed_at: int
    outcome: ObsOutcome


@dataclass(frozen=True, slots=True)
class Attestation:
    id: AttestationId
    claim: ClaimRef
    observation: ObservationId
    statement: Statement
    authority: ActorId


@dataclass(frozen=True, slots=True)
class Enumeration:
    id: EnumerationId
    source: SourceId
    revision: SourceRevision
    query: str
    scope: Scope
    observation: ObservationId
    members: tuple[str, ...]
    universe: tuple[str, ...]
    method: str


@dataclass(frozen=True, slots=True)
class AttestWitness:
    attestation: AttestationId


@dataclass(frozen=True, slots=True)
class TruthWitness:
    scope: Scope


@dataclass(frozen=True, slots=True)
class AndWitness:
    left: Witness
    right: Witness


@dataclass(frozen=True, slots=True)
class SpecializeWitness:
    scope: Scope
    premise: Witness


@dataclass(frozen=True, slots=True)
class AllWitness:
    enumeration: EnumerationId
    predicate: str
    premise: Witness


@dataclass(frozen=True, slots=True)
class AbsentWitness:
    enumeration: EnumerationId
    premise: Witness


Witness = AttestWitness | TruthWitness | AndWitness | SpecializeWitness | AllWitness | AbsentWitness


@dataclass(frozen=True, slots=True)
class Derivation:
    id: DerivationId
    claim: ClaimRef
    witness: Witness


class CorrectionKind(Enum):
    RETRACT = "retract"
    DISPUTE = "dispute"
    SUPERSEDE = "supersede"


@dataclass(frozen=True, slots=True)
class Correction:
    id: CorrectionId
    kind: CorrectionKind
    target: ClaimRef
    replacement: ClaimRef | None
    recorded_at: int


@dataclass(frozen=True, slots=True)
class Policy:
    id: PolicyId
    require_fresh: bool
    require_validation: bool
    require_uncontested: bool
    ttl: Ttl
    authorized_actors: tuple[ActorId, ...]


@dataclass(frozen=True, slots=True)
class SourceSelection:
    source: SourceId
    revision: SourceRevision
    content: ContentId


@dataclass(frozen=True, slots=True)
class Context:
    snapshot: SnapshotId
    semantic_version: str
    ruleset: RuleVersion
    checker: CheckerId
    policy: Policy
    now: int
    target: Scope
    intended_use: str
    sources: tuple[SourceSelection, ...]


@dataclass(frozen=True, slots=True)
class ObservationDependency:
    value: Observation


@dataclass(frozen=True, slots=True)
class ClaimDependency:
    value: Claim


@dataclass(frozen=True, slots=True)
class AttestationDependency:
    value: Attestation


@dataclass(frozen=True, slots=True)
class EnumerationDependency:
    value: Enumeration


@dataclass(frozen=True, slots=True)
class CorrectionsDependency:
    target: ClaimRef
    events: tuple[Correction, ...]


@dataclass(frozen=True, slots=True)
class ContextDependency:
    value: Context


Dependency = (
    ObservationDependency
    | ClaimDependency
    | AttestationDependency
    | EnumerationDependency
    | CorrectionsDependency
    | ContextDependency
)


@dataclass(frozen=True, slots=True)
class Receipt:
    id: ReceiptId
    claim: ClaimRef
    context: Context
    witness: Witness
    dependencies: tuple[Dependency, ...]
    result: ReceiptResult
    expires_at: int


class ReceiptResult(Enum):
    PASS = "pass"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class KB:
    snapshot: SnapshotId
    observations: tuple[Observation, ...] = ()
    claims: tuple[Claim, ...] = ()
    attestations: tuple[Attestation, ...] = ()
    enumerations: tuple[Enumeration, ...] = ()
    derivations: tuple[Derivation, ...] = ()
    corrections: tuple[Correction, ...] = ()
    receipts: tuple[Receipt, ...] = ()


@dataclass(frozen=True, slots=True)
class Checked:
    statement: Statement
    dependencies: tuple[Dependency, ...]


class Support(Enum):
    NONE = "none"
    POSITIVE = "positive"
    NEGATIVE = "negative"
    BOTH = "both"


@dataclass(frozen=True, slots=True)
class Assessment:
    support: Support
    applicable: bool
    freshness: Freshness
    validated: bool
    contested: bool
    available: bool
    usable: bool


@dataclass(frozen=True, slots=True)
class Authority:
    actor: ActorId
    target: ClaimRef
    intended_use: str
    policy: PolicyId
    statement: Statement
    approved: KB
    approvals: tuple[Claim, ...]
    context: Context


@dataclass(frozen=True, slots=True)
class Plan:
    id: OperationId
    expected_snapshot: SnapshotId
    candidate: KB
    authority: Authority
    claim: ClaimRef
    witness: Witness


@dataclass(frozen=True, slots=True)
class VerifiedApproval:
    """Trusted adapter capability: construct only after authenticating this plan."""

    plan: Plan


@dataclass(frozen=True, slots=True)
class JournalEntry:
    plan: Plan


class CommitOutcome(Enum):
    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"
    INPUT_CONFLICT = "input_conflict"
    PREDECESSOR_CONFLICT = "predecessor_conflict"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class Application:
    kb: KB
    journal: tuple[JournalEntry, ...]
    outcome: CommitOutcome


class ProposalStatus(Enum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    APPLIED = "applied"
    VERIFIED = "verified"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class Proposal:
    id: ProposalId
    revision: ClaimRevision
    target: ClaimRef
    status: ProposalStatus
    actor: ActorId | None
    executor: ActorId | None
    acceptor: ActorId | None
    gates: tuple[ReceiptId, ...]


class HypothesisStatus(Enum):
    SUPPORTED = "supported"
    REFUTED = "refuted"
    OPEN = "open"
    UNKNOWN = "unk"


@dataclass(frozen=True, slots=True)
class Hypothesis:
    text: str
    status: HypothesisStatus


@dataclass(frozen=True, slots=True)
class Investigation:
    checked_against: str
    scope_and_limits: str
    hypotheses: tuple[Hypothesis, ...]


class AuthoredStatus(Enum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    LANDING = "landing"
    APPLIED = "applied"
    VERIFIED = "verified"
    REGRESSED = "regressed"
    DEFERRED = "deferred"
    SUPERSEDED = "superseded"


class AuthoredProfile(Enum):
    MODERN = "modern"
    LEGACY_LIMITED = "legacy_limited"


class GateWhen(Enum):
    LAND = "land"
    DEPLOY = "deploy"
    USE = "use"


class GateOutcome(Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unk"


@dataclass(frozen=True, slots=True)
class AuthoredGateDefinition:
    id: GateId
    claim: str
    check: str
    when: GateWhen
    by: ActorId | None
    checker: CheckerId | None


@dataclass(frozen=True, slots=True)
class AuthoredGateResult:
    definition: AuthoredGateDefinition
    target_revision: TargetRevision | None
    checker: CheckerId | None
    result: GateOutcome
    observed_at: int
    expires_at: int
    proposal_revision: ProposalMaterialRevision | None
    environment: str
    scope: str
    evidence_refs: tuple[str, ...]
    actor: ActorId | None


@dataclass(frozen=True, slots=True)
class AuthoredReplacement:
    id: ProposalId
    superseded_by: ProposalId | None


@dataclass(frozen=True, slots=True)
class AuthoredLanded:
    """Exact resolution projected by the source adapter, not authored approval."""

    reference: str
    target_revision: TargetRevision


@dataclass(frozen=True, slots=True)
class AuthoredProposal:
    status: AuthoredStatus
    profile: AuthoredProfile
    research_present: bool
    alternatives_count: int
    target_revision: TargetRevision | None
    gate_definitions: tuple[AuthoredGateDefinition, ...]
    gate_results: tuple[AuthoredGateResult, ...]
    actor: ActorId | None
    acceptor: ActorId | None
    executor: ActorId | None
    verifier: ActorId | None
    landed_refs: tuple[str, ...]
    regression_note: str
    id: ProposalId
    superseded_by: ProposalId | None
    proposals: tuple[AuthoredReplacement, ...]
    accepted_revision: ProposalMaterialRevision | None
    proposal_revision: ProposalMaterialRevision | None
    environment: str
    scope: str
    resolved_landed: tuple[AuthoredLanded, ...]


@dataclass(frozen=True, slots=True)
class SelectionState:
    kb: KB
    selected: tuple[ClaimRef, ...]


@dataclass(frozen=True, slots=True)
class SelectionPlan:
    id: OperationId
    expected_snapshot: SnapshotId
    target_snapshot: SnapshotId
    new_snapshot: SnapshotId
    selected: tuple[ClaimRef, ...]
    actor: ActorId | None
    policy: PolicyId
    intended_use: str
    context: Context


@dataclass(frozen=True, slots=True)
class VerifiedSelectionApproval:
    plan: SelectionPlan


@dataclass(frozen=True, slots=True)
class SelectionJournalEntry:
    plan: SelectionPlan


@dataclass(frozen=True, slots=True)
class SelectionResult:
    state: SelectionState
    journal: tuple[SelectionJournalEntry, ...]
    outcome: CommitOutcome


def find_claim(kb: KB, ref: ClaimRef) -> Claim | None:
    return next((claim for claim in kb.claims if claim.ref == ref), None)


def find_observation(kb: KB, ident: ObservationId) -> Observation | None:
    return next((observation for observation in kb.observations if observation.id == ident), None)


def member_formula(members: tuple[str, ...], predicate: str) -> Formula:
    result: Formula = Truth()
    for member in reversed(members):
        result = Conjunction(Atomic(Atom(member, predicate)), result)
    return result
