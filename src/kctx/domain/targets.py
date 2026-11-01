"""Closed navigation references, decoded once at the command boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import assert_never

from kctx.domain.ids import AssetId, EvidenceId, InvestigationId, ProposalId, SignatureId
from kctx.errors import KctxError


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    home: str
    stem: EvidenceId

    @property
    def spelling(self) -> str:
        return f"ev:{self.home}/{self.stem.val}"


@dataclass(frozen=True, slots=True)
class SigRef:
    id: SignatureId

    @property
    def spelling(self) -> str:
        return f"sig:{self.id.val}"


@dataclass(frozen=True, slots=True)
class InvRef:
    id: InvestigationId

    @property
    def spelling(self) -> str:
        return f"inv:{self.id.val}"


@dataclass(frozen=True, slots=True)
class ProposalRef:
    id: ProposalId

    @property
    def spelling(self) -> str:
        return f"proposal/{self.id.val}"


@dataclass(frozen=True, slots=True)
class DossierRef:
    id: AssetId

    @property
    def spelling(self) -> str:
        return self.id.val


@dataclass(frozen=True, slots=True)
class AssetRef:
    """Unresolved prose selector: aliases and locator fragments remain strings."""

    ident: str

    @property
    def spelling(self) -> str:
        return self.ident


@dataclass(frozen=True, slots=True)
class CodeLocator:
    repo: str
    sha: str
    path: str
    line: tuple[int, int] | None

    @property
    def spelling(self) -> str:
        suffix = "" if self.line is None else f":{self.line[0]}"
        if self.line is not None and self.line[1] != self.line[0]:
            suffix = f":{self.line[0]}-{self.line[1]}"
        return f"{self.repo}@{self.sha}:{self.path}{suffix}"


UseTarget = EvidenceRef | SigRef | InvRef | ProposalRef | DossierRef | AssetRef | CodeLocator
LOCATOR_RE = re.compile(
    r"^(?P<repo>[^@\s]+)@(?P<sha>[0-9a-fA-F]{7,40}):(?P<path>[^:\s]+)"
    r"(?::(?P<line>\d+(?:-\d+)?))?$"
)


def line_range(raw: str | None) -> tuple[int, int] | None:
    if not raw:
        return None
    a, _, b = raw.partition("-")
    try:
        return (int(a), int(b)) if b else (int(a), int(a))
    except ValueError:
        return None


EvidenceAddress = EvidenceRef | CodeLocator
FixReference = ProposalId | EvidenceAddress


def parse_evidence_address(raw: str) -> EvidenceAddress:
    """An evidence record address or an exact code position, never bare prose."""
    if raw.startswith("ev:"):
        home, separator, stem = raw[3:].rpartition("/")
        if not separator or not home:
            raise KctxError("malformed", f"bad ev: id {raw!r}, expected <home>/<stem>")
        return EvidenceRef(home, EvidenceId(stem))
    match = LOCATOR_RE.fullmatch(raw)
    if match:
        lines = line_range(match["line"])
        if lines is not None and (lines[0] < 1 or lines[1] < lines[0]):
            raise KctxError("malformed", f"invalid code locator line range: {raw!r}")
        return CodeLocator(match["repo"], match["sha"], match["path"], lines)
    raise KctxError(
        "malformed",
        f"evidence must be ev:<home>/<stem> or a code locator org/repo@<sha>:<path>, got {raw!r}",
    )


def parse_fix_reference(raw: str) -> FixReference:
    """Decode authored fix identity without inferring resolution or support."""
    if raw.startswith("ev:") or "@" in raw:
        return parse_evidence_address(raw)
    return ProposalId(raw)


def fix_reference_spelling(reference: FixReference) -> str:
    match reference:
        case ProposalId():
            return reference.val
        case EvidenceRef() | CodeLocator():
            return reference.spelling
        case _:
            assert_never(reference)


def parse_use_target(raw: str) -> UseTarget:
    if raw.startswith("ev:") or LOCATOR_RE.fullmatch(raw):
        return parse_evidence_address(raw)
    if raw.startswith("sig:"):
        return SigRef(SignatureId(raw[4:]))
    if raw.startswith("inv:"):
        return InvRef(InvestigationId(raw[4:]))
    if raw.startswith("proposal/"):
        return ProposalRef(ProposalId(raw[9:]))
    return AssetRef(raw)


def search_strings(target: UseTarget) -> tuple[str, ...]:
    match target:
        case EvidenceRef() | AssetRef() | DossierRef() | CodeLocator():
            return (target.spelling,)
        case SigRef() | InvRef() | ProposalRef():
            return (target.spelling, target.id.val)
        case _:
            assert_never(target)
