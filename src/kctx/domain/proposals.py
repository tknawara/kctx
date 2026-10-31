"""Immutable admitted proposal and acceptance-gate records."""

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from kctx.codecs.documents import MarkdownDocument
from kctx.domain.ids import GateId, ProposalId, ProposalMaterialRevision, TargetRevision
from kctx.domain.vocabulary import (
    GateOutcome,
    GateWhen,
    ProposalKind,
    ProposalOrigin,
    ProposalStatus,
    ProposalType,
)


class ProposalProfile(Enum):
    MODERN = "modern"
    LEGACY_LIMITED = "legacy_limited"


@dataclass(frozen=True, slots=True)
class Proposal:
    id: ProposalId
    kind: ProposalKind
    title: str
    status: ProposalStatus
    created: str
    origin: ProposalOrigin | None = None
    target: tuple[str, ...] = ()
    type: ProposalType | tuple[ProposalType, ...] | None = None
    updated: str | None = None
    proposed_by: str | None = None
    requested_by: str | None = None
    source_session: str | None = None
    project: str | None = None
    swept_at: str | None = None
    references: tuple[str, ...] = ()
    landed: tuple[str, ...] = ()
    decided_by: str | None = None
    superseded_by: ProposalId | None = None
    profile: ProposalProfile = ProposalProfile.MODERN
    target_revision: TargetRevision | None = None
    acceptor: str | None = None
    executor: str | None = None
    verifier: str | None = None
    accepted_revision: ProposalMaterialRevision | None = None
    environment: str | None = None
    scope: str | None = None
    last_actor: str | None = None
    regression_note: str | None = None


@dataclass(frozen=True, slots=True)
class ProposalDocument:
    path: Path
    proposal: Proposal
    document: MarkdownDocument

    @property
    def revision(self) -> str:
        return hashlib.sha256(self.document.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ProposalAdded:
    id: ProposalId
    path: Path
    proposal: Proposal
    missing: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProposalUpdated:
    proposal: Proposal
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProposalListing:
    proposal: Proposal
    pending_gates: tuple[GateId, ...] = ()


@dataclass(frozen=True, slots=True)
class GateDefinition:
    id: GateId
    when: GateWhen
    claim: str | None = None
    check: str | None = None
    by: str | None = None
    checker: str | None = None


@dataclass(frozen=True, slots=True)
class GateResult:
    gate: GateId
    outcome: GateOutcome
    evidence: str
    at: str
    by: str | None = None
    rev: str | None = None
    target_revision: TargetRevision | None = None
    checker: str | None = None
    observed_at: int | None = None
    expires_at: int | None = None
    definition: GateDefinition | None = None
    proposal_revision: ProposalMaterialRevision | None = None
    environment: str | None = None
    scope: str | None = None
    repo_rev: str | None = None


@dataclass(frozen=True, slots=True)
class GateStatus:
    definition: GateDefinition
    outcome: GateOutcome


@dataclass(frozen=True, slots=True)
class ProposalShown:
    id: ProposalId
    proposal: Proposal
    sections: tuple[str, ...]
    gates: tuple[GateStatus, ...]
    revision: str


@dataclass(frozen=True, slots=True)
class ProposalBackfill:
    id: ProposalId
    path: Path
    landed: tuple[str, ...]
