"""Validated nominal identities. Only boundary codecs unwrap ``val``."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

from kctx.errors import KctxError

_SLUG = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
_TOKEN = r"[A-Za-z0-9][A-Za-z0-9_.:-]*"


def _validate_identity(value: object, pattern: str, kind: str) -> None:
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise KctxError("malformed", f"invalid {kind}: {value!r}")


@dataclass(frozen=True, slots=True)
class _Identity:
    val: str
    _pattern: ClassVar[str] = _TOKEN

    def __post_init__(self) -> None:
        _validate_identity(self.val, self._pattern, type(self).__name__)

    def __str__(self) -> str:
        return self.val


@dataclass(frozen=True, slots=True)
class AssetId(_Identity):
    _pattern: ClassVar[str] = _SLUG


@dataclass(frozen=True, slots=True)
class RelationshipId(_Identity):
    _pattern: ClassVar[str] = rf"{_SLUG}(?:__{_SLUG})*"


@dataclass(frozen=True, slots=True)
class EvidenceId(_Identity):
    _pattern: ClassVar[str] = _SLUG


@dataclass(frozen=True, slots=True)
class ObservationId(_Identity):
    pass


@dataclass(frozen=True, slots=True)
class ProposalId(_Identity):
    _pattern: ClassVar[str] = rf"(?:{_TOKEN}|{_SLUG}/{_SLUG})"


@dataclass(frozen=True, slots=True)
class InvestigationId(_Identity):
    _pattern: ClassVar[str] = rf"(?:{_TOKEN}|[0-9]{{4}}/[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}-{_SLUG})"


@dataclass(frozen=True, slots=True)
class SignatureId(_Identity):
    _pattern: ClassVar[str] = _SLUG


@dataclass(frozen=True, slots=True)
class ClaimId(_Identity):
    pass


@dataclass(frozen=True, slots=True)
class ClaimRevision(_Identity):
    pass


@dataclass(frozen=True, slots=True)
class CitationId(_Identity):
    pass


@dataclass(frozen=True, slots=True)
class RuleVersion(_Identity):
    pass


@dataclass(frozen=True, slots=True)
class OperationId(_Identity):
    pass


@dataclass(frozen=True, slots=True)
class SnapshotId(_Identity):
    pass


@dataclass(frozen=True, slots=True)
class DerivationId(_Identity):
    pass


@dataclass(frozen=True, slots=True)
class RunId(_Identity):
    pass


@dataclass(frozen=True, slots=True)
class GateId(_Identity):
    pass


@dataclass(frozen=True, slots=True)
class TicketId(_Identity):
    pass


def parse_asset_id(raw: str) -> AssetId:
    return AssetId(raw)


def parse_evidence_id(raw: str) -> EvidenceId:
    return EvidenceId(raw)


def parse_relationship_id(raw: str) -> RelationshipId:
    return RelationshipId(raw)


@dataclass(frozen=True, slots=True)
class PlanId(_Identity):
    _pattern: ClassVar[str] = r"[0-9a-f]{64}"


@dataclass(frozen=True, slots=True)
class SourceCaptureId(_Identity):
    _pattern: ClassVar[str] = r"[0-9a-f]{64}"


@dataclass(frozen=True, slots=True)
class ContentDigest(_Identity):
    _pattern: ClassVar[str] = r"[0-9a-f]{64}"


@dataclass(frozen=True, slots=True)
class PolicyDigest(_Identity):
    _pattern: ClassVar[str] = r"[0-9a-f]{64}"


@dataclass(frozen=True, slots=True)
class ReleaseId(_Identity):
    _pattern: ClassVar[str] = r"(?:[0-9a-f]{40}|[0-9a-f]{64})"


@dataclass(frozen=True, slots=True)
class DoltCommitId(_Identity):
    _pattern: ClassVar[str] = r"[0-9a-v]{32}"


@dataclass(frozen=True, slots=True)
class AuthorityKeyId(_Identity):
    pass


@dataclass(frozen=True, slots=True)
class AttestationId(_Identity):
    pass


@dataclass(frozen=True, slots=True)
class EnumerationId(_Identity):
    pass


@dataclass(frozen=True, slots=True)
class CorrectionId(_Identity):
    pass


@dataclass(frozen=True, slots=True)
class ReceiptId(_Identity):
    pass


@dataclass(frozen=True, slots=True)
class PolicyId(_Identity):
    pass


@dataclass(frozen=True, slots=True)
class CheckerId(_Identity):
    _pattern: ClassVar[str] = r"[\s\S]+"


@dataclass(frozen=True, slots=True)
class _OpaqueIdentity(_Identity):
    """A nonempty external identity; provider codecs validate its syntax."""

    _pattern: ClassVar[str] = r"[\s\S]+"


@dataclass(frozen=True, slots=True)
class SourceId(_OpaqueIdentity):
    pass


@dataclass(frozen=True, slots=True)
class SourceRevision(_OpaqueIdentity):
    pass


@dataclass(frozen=True, slots=True)
class ContentId(_OpaqueIdentity):
    pass


@dataclass(frozen=True, slots=True)
class ProjectId(_OpaqueIdentity):
    pass


@dataclass(frozen=True, slots=True)
class ActorId(_OpaqueIdentity):
    pass


@dataclass(frozen=True, slots=True)
class ProposalMaterialRevision(_OpaqueIdentity):
    pass


@dataclass(frozen=True, slots=True)
class TargetRevision(_OpaqueIdentity):
    pass


@dataclass(frozen=True, slots=True)
class GitRevision(_Identity):
    _pattern: ClassVar[str] = r"(?:[0-9a-f]{40}|[0-9a-f]{64})"
