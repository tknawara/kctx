"""Typed incident records, distinct from incomplete authored Markdown drafts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from kctx.codecs.documents import MarkdownDocument
from kctx.domain.ids import AssetId, InvestigationId, SignatureId, TicketId
from kctx.domain.targets import FixReference
from kctx.domain.vocabulary import (
    HypothesisStatus,
    InvestigationStatus,
    InvestigationTrigger,
    KtloStatus,
    SignatureStatus,
)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ParsedDocument(Generic[T]):
    frontmatter: T
    document: MarkdownDocument

    @property
    def body(self) -> Mapping[str, str]:
        return self.document.sections


@dataclass(frozen=True, slots=True)
class LoadedDocument(Generic[T]):
    path: Path
    frontmatter: T
    document: MarkdownDocument

    @property
    def body(self) -> Mapping[str, str]:
        return self.document.sections


@dataclass(frozen=True, slots=True)
class FollowUpStatus:
    """Authored status prose: unlike lifecycle states, no closed corpus vocabulary."""

    text: str


@dataclass(frozen=True, slots=True)
class FollowUp:
    owner: str
    status: FollowUpStatus
    ticket: TicketId | None = None


@dataclass(frozen=True, slots=True)
class ProjectRef:
    name: str


@dataclass(frozen=True, slots=True)
class Investigation:
    id: InvestigationId
    title: str
    trigger: InvestigationTrigger
    tickets: tuple[TicketId, ...]
    alerts: tuple[AssetId, ...]
    assets: tuple[AssetId, ...]
    windows: tuple[str, ...]
    impact_summary: str
    status: InvestigationStatus
    signatures: tuple[SignatureId, ...]
    follow_ups: tuple[FollowUp, ...]
    spawned: tuple[TicketId | ProjectRef, ...]
    promoted_to: str | None
    created: str
    updated: str
    summary: str


@dataclass(frozen=True, slots=True)
class Hypothesis:
    id: str
    status: HypothesisStatus
    text: str


@dataclass(frozen=True, slots=True)
class Signature:
    id: SignatureId
    title: str
    status: SignatureStatus
    match: tuple[str, ...]
    match_where: str
    assets: tuple[AssetId, ...]
    owner_group: str | None
    first_seen: str | None
    last_seen: str | None
    workaround: str
    fix: tuple[FixReference, ...]
    fixed_at: str | None
    verified_at: str | None
    ttl: str | None


@dataclass(frozen=True, slots=True)
class SignatureMatch:
    id: SignatureId
    title: str
    status: SignatureStatus
    workaround: str
    owner_group: str | None
    last_seen: str | None
    matched_patterns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Ktlo:
    ticket: TicketId
    title: str
    assets: tuple[AssetId, ...]
    status: KtloStatus
    prs: tuple[str, ...]
    summary: str
    created: str
    updated: str
    promoted_to: str | None


@dataclass(frozen=True, slots=True)
class Dossier:
    asset: AssetId
    updated: str


@dataclass(frozen=True, slots=True)
class InvestigationCreated:
    id: InvestigationId
    path: Path
    frontmatter: Investigation


@dataclass(frozen=True, slots=True)
class InvestigationShown:
    id: InvestigationId
    frontmatter: Investigation
    sections: tuple[str, ...]
    evidence: tuple[str, ...]
    queries: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InvestigationPromoted:
    id: InvestigationId
    project: str
    path: Path
    already_promoted: bool


@dataclass(frozen=True, slots=True)
class SignatureCreated:
    id: SignatureId
    path: Path
    frontmatter: Signature


@dataclass(frozen=True, slots=True)
class SignatureShown:
    id: SignatureId
    frontmatter: Signature
    sections: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KtloCreated:
    ticket: TicketId
    path: Path
    frontmatter: Ktlo


@dataclass(frozen=True, slots=True)
class KtloPromoted:
    ticket: TicketId
    project: str
    path: Path
    already_promoted: bool


@dataclass(frozen=True, slots=True)
class DossierCreated:
    asset: AssetId
    path: Path
    frontmatter: Dossier


@dataclass(frozen=True, slots=True)
class DossierShown:
    asset: AssetId
    path: Path
    frontmatter: Dossier
    headings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DossierArchived:
    asset: AssetId
    path: Path
