"""Validate native completed snapshots independently of their active directory.

The local operations journal owns checkout isolation and atomic activation.
The native completed branch advances only after provenance and parent linkage
are complete, leaving both data and metadata history available to readers.
"""

import json
import re
from dataclasses import dataclass

from pydantic import ValidationError

from kctx.domain.json import JsonObject, object_value, text
from kctx.errors import KctxError
from kctx.graph.dolt_store import DoltStore
from kctx.graph.inputs import manifest_digest
from kctx.graph.models import DoltCommitId, SyncState
from kctx.graph.quoting import sql_quote

COMPLETED_BRANCH = "kctx-complete"


@dataclass(frozen=True, slots=True)
class CompletedSnapshot:
    metadata_commit: DoltCommitId
    data_commit: DoltCommitId
    state: SyncState
    inputs: JsonObject | None


def completed_pointer(store: DoltStore) -> DoltCommitId | None:
    if not store.is_initialized():
        return None
    rows = store.sql_read(
        f"SELECT name FROM dolt_branches WHERE name = {sql_quote(COMPLETED_BRANCH)}"
    )
    if not rows:
        return None
    hashes = store.sql_read(f"SELECT hashof({sql_quote(COMPLETED_BRANCH)}) AS h")
    if len(hashes) != 1:
        raise KctxError(
            "malformed", "completed graph reference did not resolve to one native commit"
        )
    return _native_commit(hashes[0].get("h"))


def _native_commit(value: object) -> DoltCommitId:
    try:
        return DoltCommitId(text(value, "native Dolt commit"))
    except ValueError as exc:
        raise KctxError("malformed", str(exc)) from exc


def completed_snapshot(store: DoltStore) -> CompletedSnapshot | None:
    metadata = completed_pointer(store)
    if metadata is None:
        return None
    return snapshot_at(store, metadata)


def snapshot_at(store: DoltStore, metadata: DoltCommitId) -> CompletedSnapshot:
    """Validate a candidate before advancing the completed pointer."""
    rows = store.sql_read(f"SELECT * FROM sync_state AS OF {sql_quote(metadata.val)} WHERE id = 1")
    if len(rows) != 1:
        raise KctxError("malformed", "completed graph generation requires exactly one sync state")
    required = {"id", "kb_sha", "dolt_commit", "synced_at", "node_count", "edge_count"}
    if any(rows[0].get(name) is None for name in required):
        raise KctxError(
            "malformed", "completed graph sync state is missing required generation fields"
        )
    try:
        state = SyncState.from_row(rows[0])
    except ValidationError as exc:
        raise KctxError("malformed", f"invalid completed graph sync state: {exc}") from exc
    if (
        state.dolt_commit is None
        or not state.synced_at.strip()
        or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", state.kb_sha) is None
        or state.node_count < 0
        or state.edge_count < 0
    ):
        raise KctxError(
            "malformed",
            "completed graph generation has an incomplete native commit identity or invalid counts",
        )
    data = _native_commit(state.dolt_commit)
    parents = store.sql_read(f"SELECT hashof({sql_quote(metadata.val + '~1')}) AS h")
    if len(parents) != 1 or _native_commit(parents[0].get("h")) != data:
        raise KctxError("malformed", "completed graph metadata must name its native data parent")
    inputs: JsonObject | None = None
    if state.input_digest is not None:
        if re.fullmatch(r"[0-9a-f]{64}", state.input_digest) is None:
            raise KctxError("malformed", "invalid graph generation input digest")
        manifests = store.sql_read(
            f"SELECT * FROM generation_inputs AS OF {sql_quote(metadata.val)} WHERE id = 1"
        )
        if len(manifests) != 1 or manifests[0].get("input_digest") != state.input_digest:
            raise KctxError(
                "malformed", "generation input manifest is missing or disagrees with sync state"
            )
        try:
            inputs = object_value(
                json.loads(text(manifests[0].get("manifest"), "generation manifest"))
            )
        except json.JSONDecodeError as exc:
            raise KctxError("malformed", f"invalid generation manifest JSON: {exc}") from exc
        if manifest_digest(inputs) != state.input_digest or inputs.get("kb_sha") != state.kb_sha:
            raise KctxError("malformed", "generation manifest digest or KB identity does not match")
    return CompletedSnapshot(metadata, data, state, inputs)


def publish(store: DoltStore, metadata: DoltCommitId, predecessor: DoltCommitId | None) -> None:
    """Advance only after complete metadata exists; caller holds writer lock."""
    candidate = snapshot_at(store, metadata)
    if candidate.inputs is None:
        raise KctxError(
            "malformed", "new completed generations require reproducible input provenance"
        )
    if completed_pointer(store) != predecessor:
        raise KctxError(
            "conflict",
            "completed graph pointer changed during sync; candidate retained without publication",
        )
    store.move_branch(COMPLETED_BRANCH, metadata.val)
