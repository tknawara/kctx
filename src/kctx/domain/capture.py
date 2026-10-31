"""Typed source versions, content digests and retained Git capture profiles."""

from dataclasses import dataclass
from enum import Enum

from kctx.domain.ids import ContentDigest, GitRevision


class CaptureProfile(Enum):
    GIT_WORKTREE_V1 = "git-worktree-v1"


class CaptureStatus(Enum):
    LEGACY = "legacy-unassessed"
    NOT_APPLICABLE = "not-applicable"
    CAPTURED = "captured"
    MOVED = "moved-during-capture"
    UNAVAILABLE = "unavailable"


class ObservationAssessment(Enum):
    UNASSESSED = "unassessed"
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    UNAVAILABLE = "unavailable"
    MOVED = "moved-during-check"
    LEGACY_INSUFFICIENT = "legacy-input-identity-insufficient"
    RETAINED_MISSING = "retained-input-missing-or-corrupt"


@dataclass(frozen=True, slots=True)
class WorktreeIdentity:
    profile: CaptureProfile
    revision: GitRevision
    digest: ContentDigest
    retained_path: str
    started_at: str
    completed_at: str


@dataclass(frozen=True, slots=True)
class WorktreeCapture:
    revision: GitRevision
    digest: ContentDigest
    payload: bytes
    dirty: bool
    started_at: str
    completed_at: str


class CoveragePolicy(Enum):
    SINGLE_SOURCE = "single-source"
    INDEPENDENT_ORIGINS = "independent-origins"

    @property
    def minimum_origins(self) -> int:
        return 2 if self is CoveragePolicy.INDEPENDENT_ORIGINS else 1
