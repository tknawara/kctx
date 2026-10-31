"""Domain model mirroring ``formal/Kctx/Model.lean`` (semantic version 1.0.0).

Every type here has a Lean counterpart; field order in the dataclasses is the
wire order in ``wire.py``. Keep them in sync or conformance fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Tuple

SEMANTIC_VERSION = "1.0.0"


class IdKind(Enum):
    ASSET = "asset"
    CLAIM = "claim"
    CLAIM_REV = "claimRev"
    CITATION = "citation"
    OBSERVATION = "observation"
    PROPOSAL = "proposal"
    INVESTIGATION = "investigation"
    SIGNATURE = "signature"
    RULE = "rule"
    OPERATION = "operation"
    SNAPSHOT = "snapshot"


@dataclass(frozen=True, slots=True)
class Ident:
    """Nominal identifier. The ``kind`` field makes asset/claim/proposal ids
    non-interchangeable at runtime (the Lean side enforces it in the type)."""

    val: str
    kind: IdKind = IdKind.ASSET

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.val


@dataclass(frozen=True, slots=True)
class ClaimRef:
    """Logical claim id + immutable revision (handover §4)."""

    id: str
    rev: str


@dataclass(frozen=True, slots=True)
class Scope:
    project: str
    extra: str


def specializes(target: Scope, source: Scope) -> bool:
    """``target`` denotes a sub-scope of ``source``: same project, and
    ``source`` is broad (empty extra) or identical. Mirrors
    ``Scope.specializes``."""
    return target.project == source.project and (
        source.extra == "" or source.extra == target.extra
    )


@dataclass(frozen=True, slots=True)
class Ttl:
    """``expireAfter secs | noExpiry | missing`` — mirrors Lean ``TtlPolicy``.
    A missing policy is never an implicit freshness proof."""

    tag: str
    secs: int | None = None


def ttl_expire_after(secs: int) -> Ttl:
    return Ttl("expireAfter", secs)


TTL_NO_EXPIRY = Ttl("noExpiry")
TTL_MISSING = Ttl("missing")


class Freshness(Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class ObsOutcome(Enum):
    OK = "ok"
    TIMED_OUT = "timedOut"
    PARTIAL_RESULT = "partialResult"
    TRUNCATED = "truncated"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


class SupportRole(Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXTUALIZES = "contextualizes"


class RuleId(Enum):
    AND_INTRO = "andIntro"
    SPECIALIZE = "specialize"
    OBS_SUPPORTS = "obsSupports"
    ALL_CHECKED = "allChecked"


ENABLED_RULES: frozenset[RuleId] = frozenset(RuleId)


@dataclass(frozen=True, slots=True)
class Atom:
    subject: str
    predicate: str
    args: Tuple[str, ...]


class ClaimProp:
    """Tagged union ``atom(a) | conj(atoms) | allChecked(pred, members)``
    (v1 bound: conjunction over flat atoms)."""

    __slots__ = ("tag", "atom", "atoms", "predicate", "members")

    def __init__(
        self,
        tag: str,
        atom: Atom | None = None,
        atoms: Tuple[Atom, ...] | None = None,
        predicate: str | None = None,
        members: Tuple[str, ...] | None = None,
    ):
        self.tag = tag
        self.atom = atom
        self.atoms = atoms
        self.predicate = predicate
        self.members = members

    @classmethod
    def of_atom(cls, a: Atom) -> "ClaimProp":
        return cls("atom", atom=a)

    @classmethod
    def conj(cls, atoms: tuple[Atom, ...] | list[Atom]) -> "ClaimProp":
        return cls("conj", atoms=tuple(atoms))

    @classmethod
    def all_checked(cls, predicate: str, members: tuple[str, ...] | list[str]) -> "ClaimProp":
        return cls("allChecked", predicate=predicate, members=tuple(members))

    def as_atom(self) -> Atom | None:
        return self.atom if self.tag == "atom" else None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ClaimProp):
            return NotImplemented
        return (
            self.tag == other.tag
            and self.atom == other.atom
            and self.atoms == other.atoms
            and self.predicate == other.predicate
            and self.members == other.members
        )

    def __hash__(self) -> int:
        return hash((self.tag, self.atom, self.atoms, self.predicate, self.members))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        if self.tag == "atom":
            return f"ClaimProp.atom{self.atom!r}"
        if self.tag == "conj":
            return f"ClaimProp.conj{self.atoms!r}"
        return f"ClaimProp.allChecked({self.predicate!r}, {self.members!r})"


@dataclass(frozen=True, slots=True)
class Observation:
    id: str
    outcome: ObsOutcome
    observed_at: int
    ttl: Ttl
    system: str
    locator: str


@dataclass(frozen=True, slots=True)
class Claim:
    id: str
    rev: str
    prop: ClaimProp
    scope: Scope


@dataclass(frozen=True, slots=True)
class Binding:
    obs: str
    ref: ClaimRef
    role: SupportRole


class DepKind(Enum):
    SOURCE_CONTENT = "sourceContent"
    KB_RECORD = "kbRecord"
    POLICY = "policy"
    CHECKER = "checker"
    CORRECTION = "correction"
    DISCOVERY = "discovery"


@dataclass(frozen=True, slots=True)
class Dep:
    kind: DepKind
    target: str
    digest: str


@dataclass(frozen=True, slots=True)
class CoverageWitness:
    scope: Scope
    members: Tuple[str, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class Derivation:
    id: str
    rule: RuleId
    premise_groups: Tuple[Tuple[ClaimRef, ...], ...]
    conclusion: ClaimRef
    conclusion_prop: ClaimProp
    scope: Scope
    footprint: Tuple[Dep, ...]
    evidence: str | None
    witness: CoverageWitness | None


class CorrectionKind(Enum):
    RETRACT = "retract"
    DISPUTE = "dispute"
    SUPERSEDE = "supersede"


@dataclass(frozen=True, slots=True)
class Correction:
    kind: CorrectionKind
    target: ClaimRef
    recorded_at: int


@dataclass(frozen=True, slots=True)
class EvalCtx:
    now: int
    require_fresh_evidence: bool = True
    require_validated: bool = True
    require_uncontested: bool = True


@dataclass(frozen=True, slots=True)
class KbView:
    """Read-only projection of a KB the checker consults (Lean ``KbView``)."""

    observations: Tuple[Observation, ...]
    claims: Tuple[Claim, ...]
    bindings: Tuple[Binding, ...]
    corrections: Tuple[Correction, ...]
    derivations: Tuple[Derivation, ...]
    validations: Tuple[Tuple[ClaimRef, str], ...]


@dataclass(frozen=True, slots=True)
class KB:
    head: str
    observations: Tuple[Observation, ...] = ()
    claims: Tuple[Claim, ...] = ()
    bindings: Tuple[Binding, ...] = ()
    derivations: Tuple[Derivation, ...] = ()
    corrections: Tuple[Correction, ...] = ()
    validations: Tuple[Tuple[ClaimRef, str], ...] = ()

    def view(self) -> KbView:
        return KbView(
            self.observations,
            self.claims,
            self.bindings,
            self.corrections,
            self.derivations,
            self.validations,
        )


def find_obs(v: KbView, oid: str) -> Observation | None:
    for o in v.observations:
        if o.id == oid:
            return o
    return None


def find_claim(v: KbView, ref: ClaimRef) -> Claim | None:
    for c in v.claims:
        if c.id == ref.id and c.rev == ref.rev:
            return c
    return None


def prop_of(v: KbView, ref: ClaimRef) -> ClaimProp:
    c = find_claim(v, ref)
    if c is None:
        return ClaimProp.of_atom(Atom("", "", ()))
    return c.prop


def scope_of(v: KbView, ref: ClaimRef) -> Scope | None:
    c = find_claim(v, ref)
    return None if c is None else c.scope
