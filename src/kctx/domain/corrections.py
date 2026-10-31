"""Closed correction references and immutable durable review records."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from kctx.codecs.documents import MarkdownDocument
from kctx.domain.ids import OperationId
from kctx.domain.targets import DossierRef, EvidenceRef, ProposalRef, SigRef
from kctx.domain.vocabulary import CorrectionKind, CorrectionRowStatus

CorrectionTarget = EvidenceRef | DossierRef | SigRef | ProposalRef


class CorrectionTargetKind(Enum):
    EVIDENCE = "ev"
    DOSSIER = "dossier"
    SIGNATURE = "signature"
    PROPOSAL = "proposal"


@dataclass(frozen=True, slots=True)
class UnchangedReview:
    evidence: str


@dataclass(frozen=True, slots=True)
class CorrectionRow:
    file: str
    kind: str
    status: CorrectionRowStatus | UnchangedReview
    owner: str


@dataclass(frozen=True, slots=True)
class Correction:
    target: CorrectionTarget
    target_kind: CorrectionTargetKind
    kind: CorrectionKind
    reason: str
    by_replacement: str | None
    created: str


@dataclass(frozen=True, slots=True)
class CorrectionDocument:
    frontmatter: Correction
    rows: tuple[CorrectionRow, ...]
    document: MarkdownDocument


@dataclass(frozen=True, slots=True)
class CorrectionReferrer:
    file: str
    kind: str
    self: bool | None = None


@dataclass(frozen=True, slots=True)
class CorrectionResult:
    target: CorrectionTarget
    target_kind: CorrectionTargetKind
    target_file: str
    kind: CorrectionKind
    corrections_file: str
    referrers: tuple[CorrectionReferrer, ...]


@dataclass(frozen=True, slots=True)
class CorrectionOperation:
    id: OperationId
    record: Correction
    corrections_file: str
    referrers: tuple[CorrectionReferrer, ...]
