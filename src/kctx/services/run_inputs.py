"""Persist and reassess the declared Git input profile for a run observation."""

import base64
import binascii
import hashlib
from dataclasses import replace
from pathlib import Path

from kctx.adapters.files.storage import exclusive_write_json, read_json
from kctx.adapters.git.inspection import capture_worktree
from kctx.domain.capture import (
    CaptureProfile,
    CaptureStatus,
    ObservationAssessment,
    WorktreeCapture,
    WorktreeIdentity,
)
from kctx.domain.ids import RunId, SourceRevision
from kctx.domain.json import fields, text
from kctx.domain.records import Observation, ObservationSnapshot
from kctx.errors import KctxError


def _retained_payload(root: Path, run_id: RunId, identity: WorktreeIdentity) -> bytes:
    expected_path = f"input-snapshots/{identity.digest.val}.json"
    if identity.retained_path != expected_path:
        raise KctxError("malformed", "retained input path does not match digest")
    path = root / "runs" / run_id.val / expected_path
    data = fields(read_json(path), required={"profile", "sha256", "payload_base64"})
    if data["profile"] != identity.profile.value or data["sha256"] != identity.digest.val:
        raise KctxError("malformed", "retained input metadata does not match identity")
    try:
        payload = base64.b64decode(text(data["payload_base64"], "payload_base64"), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise KctxError("malformed", "invalid retained input bytes") from exc
    if hashlib.sha256(payload).hexdigest() != identity.digest.val:
        raise KctxError("malformed", "retained input bytes do not match digest")
    return payload


def retain_input(root: Path, run_id: RunId, capture: WorktreeCapture) -> WorktreeIdentity:
    identity = WorktreeIdentity(
        CaptureProfile.GIT_WORKTREE_V1,
        capture.revision,
        capture.digest,
        f"input-snapshots/{capture.digest.val}.json",
        capture.started_at,
        capture.completed_at,
    )
    path = root / "runs" / run_id.val / identity.retained_path
    data = {
        "schema_version": 1,
        "profile": identity.profile.value,
        "sha256": identity.digest.val,
        "payload_base64": base64.b64encode(capture.payload).decode("ascii"),
    }
    try:
        exclusive_write_json(path, data)
    except KctxError as exc:
        if exc.category != "conflict":
            raise
        if _retained_payload(root, run_id, identity) != capture.payload:
            raise KctxError("conflict", "retained input identity collision") from exc
    return identity


def assess_git_input(root: Path, observation: Observation) -> ObservationSnapshot:
    source = observation.source
    snapshot = ObservationSnapshot(
        observation.id, source.system, source.locator, source.revision, observation.dirty
    )
    try:
        current = capture_worktree(source.locator)
    except KctxError as exc:
        assessment = (
            ObservationAssessment.MOVED
            if exc.category == "conflict"
            else ObservationAssessment.UNAVAILABLE
        )
        return replace(snapshot, assessment=assessment)
    snapshot = replace(
        snapshot,
        current_revision=SourceRevision(current.revision.val),
        current_dirty=current.dirty,
        current_input_digest=current.digest,
    )
    if (
        observation.capture_status is not CaptureStatus.CAPTURED
        or observation.input_identity is None
    ):
        return replace(snapshot, assessment=ObservationAssessment.LEGACY_INSUFFICIENT)
    identity = observation.input_identity
    try:
        _retained_payload(root, observation.run, identity)
    except (KctxError, OSError):
        return replace(snapshot, assessment=ObservationAssessment.RETAINED_MISSING)
    changed = current.digest != identity.digest or current.revision != identity.revision
    return replace(
        snapshot,
        changed=changed,
        assessment=ObservationAssessment.CHANGED if changed else ObservationAssessment.UNCHANGED,
    )
