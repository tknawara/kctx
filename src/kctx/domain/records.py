"""Immutable inventory and run records; JSON belongs to codecs.records."""

from dataclasses import dataclass

from kctx.domain.capture import (
    CaptureStatus,
    CoveragePolicy,
    ObservationAssessment,
    WorktreeIdentity,
)
from kctx.domain.ids import (
    AssetId,
    ContentDigest,
    EvidenceId,
    ObservationId,
    RelationshipId,
    RunId,
    SourceRevision,
)
from kctx.domain.vocabulary import (
    AssetKind,
    CoverageOutcome,
    Lifecycle,
    ObservationRole,
    ObservationStatus,
    ObservationSystem,
    Readiness,
    RelationshipStatus,
    RelationshipType,
    RunMode,
    RunState,
)

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class Asset:
    id: AssetId
    kind: AssetKind
    name: str
    locator: str = ""
    aliases: tuple[str, ...] = ()
    owner: str = "unknown"
    owner_source: str = ""
    lifecycle: Lifecycle = Lifecycle.ACTIVE
    inspect: str = ""
    projects: tuple[str, ...] = ()
    verified_at: str | None = None
    ttl: str | None = None
    notes: str = ""


@dataclass(frozen=True, slots=True)
class Relationship:
    id: RelationshipId
    type: RelationshipType
    from_: AssetId
    to: AssetId
    status: RelationshipStatus = RelationshipStatus.EXPLICIT
    evidence: tuple[EvidenceId, ...] = ()
    applicability: str = ""


@dataclass(frozen=True, slots=True)
class ObservationSource:
    system: ObservationSystem
    locator: str
    asset: AssetId | None = None
    revision: SourceRevision | None = None
    role: ObservationRole = ObservationRole.NOTE


@dataclass(frozen=True, slots=True)
class ObservationEvidence:
    locator: str
    sha256: ContentDigest | None = None


@dataclass(frozen=True, slots=True)
class Observation:
    id: ObservationId
    run: RunId
    source: ObservationSource
    observed_at: str
    status: ObservationStatus = ObservationStatus.OK
    command: str | None = None
    environment: str | None = None
    evidence: ObservationEvidence | None = None
    notes: str | None = None
    dirty: bool | None = None
    dirty_diff_sha256: str | None = None
    input_identity: WorktreeIdentity | None = None
    capture_status: CaptureStatus = CaptureStatus.LEGACY
    derived_from: tuple[ObservationId, ...] = ()


@dataclass(frozen=True, slots=True)
class CoverageEntry:
    item: str
    outcome: CoverageOutcome
    evidence: tuple[ObservationId, ...] = ()
    reason: str = ""
    updated_at: str = ""
    prior_outcome: CoverageOutcome | None = None
    policy: CoveragePolicy = CoveragePolicy.SINGLE_SOURCE


@dataclass(frozen=True, slots=True)
class Coverage:
    entries: tuple[CoverageEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class RunManifest:
    run_id: RunId
    task: str
    project: str
    mode: RunMode
    created: str
    state: RunState = RunState.OPEN


@dataclass(frozen=True, slots=True)
class ObservationSnapshot:
    id: ObservationId
    system: ObservationSystem
    locator: str
    revision: SourceRevision | None
    dirty: bool | None
    current_revision: SourceRevision | None = None
    current_dirty: bool | None = None
    changed: bool | None = None
    assessment: ObservationAssessment = ObservationAssessment.UNASSESSED
    current_input_digest: ContentDigest | None = None


@dataclass(frozen=True, slots=True)
class SharedEvidence:
    observation: ObservationId
    items: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceOrigins:
    total_citations: int
    distinct_observations: int
    shared_evidence: tuple[SharedEvidence, ...]


@dataclass(frozen=True, slots=True)
class RunReceipt:
    run: RunId
    receipt: int
    checked_at: str
    readiness: Readiness
    required: tuple[str, ...]
    missing_required: tuple[str, ...]
    stale_observations: tuple[ObservationId, ...]
    observations: tuple[ObservationSnapshot, ...]
    evidence_origins: EvidenceOrigins
    coverage_complete: bool | None = None
    eligible_to_proceed: bool = False
    blocked_required: tuple[str, ...] = ()
    unknown_observations: tuple[ObservationId, ...] = ()


@dataclass(frozen=True, slots=True)
class CoverageCount:
    outcome: CoverageOutcome
    count: int


@dataclass(frozen=True, slots=True)
class RunResume:
    manifest: RunManifest
    coverage_summary: tuple[CoverageCount, ...]
    stale_items: tuple[str, ...]
    checkpoint: str
    last_receipt: RunReceipt | None


@dataclass(frozen=True, slots=True)
class RunCheckpoint:
    run: RunId
    checkpoint_path: str


@dataclass(frozen=True, slots=True)
class ImpactReached:
    asset: AssetId
    via: AssetId
    relationship: RelationshipId
    type: RelationshipType
    status: RelationshipStatus


@dataclass(frozen=True, slots=True)
class ImpactUnexplored:
    from_: AssetId
    relationship: RelationshipId
    to: AssetId
    type: RelationshipType


@dataclass(frozen=True, slots=True)
class Impact:
    asset: AssetId
    depth: int
    reached: tuple[ImpactReached, ...]
    unexplored_edges: tuple[ImpactUnexplored, ...]
    note: str
