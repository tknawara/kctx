"""Strict codecs for retained Git input identity, separate from legacy digests."""

from kctx.domain.capture import CaptureProfile, WorktreeIdentity
from kctx.domain.ids import ContentDigest, GitRevision
from kctx.domain.json import JsonObject, enum_value, fields, text
from kctx.errors import KctxError


def decode_worktree_identity(value: object) -> WorktreeIdentity:
    data = fields(
        value,
        required={"profile", "revision", "digest", "retained_path", "started_at", "completed_at"},
        versioned=False,
    )
    digest = ContentDigest(text(data["digest"], "digest"))
    retained_path = text(data["retained_path"], "retained_path")
    if retained_path != f"input-snapshots/{digest.val}.json":
        raise KctxError("malformed", "retained input path does not match its digest")
    return WorktreeIdentity(
        enum_value(CaptureProfile, data["profile"], "profile"),
        GitRevision(text(data["revision"], "revision")),
        digest,
        retained_path,
        text(data["started_at"], "started_at"),
        text(data["completed_at"], "completed_at"),
    )


def encode_worktree_identity(value: WorktreeIdentity) -> JsonObject:
    return {
        "profile": value.profile.value,
        "revision": value.revision.val,
        "digest": value.digest.val,
        "retained_path": value.retained_path,
        "started_at": value.started_at,
        "completed_at": value.completed_at,
    }
