"""Explicit JSON codecs; legacy v1 and capture-aware v2 never imply equal assurance."""

from kctx.codecs.capture import decode_worktree_identity, encode_worktree_identity
from kctx.domain.capture import CaptureStatus, CoveragePolicy, ObservationAssessment
from kctx.domain.ids import (
    AssetId,
    ContentDigest,
    ObservationId,
    RelationshipId,
    RunId,
    SourceRevision,
)
from kctx.domain.json import (
    JsonObject,
    JsonValue,
    enum_value,
    fields,
    integer,
    object_value,
    optional_bool,
    text,
    texts,
)
from kctx.domain.records import (
    Asset,
    Coverage,
    CoverageEntry,
    EvidenceOrigins,
    Impact,
    Observation,
    ObservationEvidence,
    ObservationSnapshot,
    ObservationSource,
    Relationship,
    RunCheckpoint,
    RunManifest,
    RunReceipt,
    RunResume,
    SharedEvidence,
)
from kctx.domain.targets import parse_evidence_address
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
from kctx.errors import KctxError


def _fields_v2(
    value: object, *, required: set[str], optional: set[str], v2: set[str]
) -> JsonObject:
    data = object_value(value)
    version = integer(data.get("schema_version", 1), "schema_version")
    if version not in (1, 2):
        raise KctxError("malformed", f"unsupported schema_version {version}")
    return fields(
        data,
        required=required | (v2 if version == 2 else set()),
        optional=optional | {"schema_version"},
        versioned=False,
    )


def decode_asset(value: object) -> Asset:
    d = fields(
        value,
        required={"id", "kind", "name"},
        optional={
            "ttl",
            "inspect",
            "verified_at",
            "notes",
            "owner",
            "locator",
            "aliases",
            "owner_source",
            "projects",
            "lifecycle",
        },
        versioned=True,
    )
    return Asset(
        id=AssetId(text(d["id"], "id")),
        kind=enum_value(AssetKind, d["kind"], "kind"),
        name=text(d["name"], "name"),
        locator=text(d.get("locator", ""), "locator"),
        aliases=texts(d.get("aliases", []), "aliases"),
        owner=text(d.get("owner", "unknown"), "owner"),
        owner_source=text(d.get("owner_source", ""), "owner_source"),
        lifecycle=enum_value(Lifecycle, d.get("lifecycle", "active"), "lifecycle"),
        inspect=text(d.get("inspect", ""), "inspect"),
        projects=texts(d.get("projects", []), "projects"),
        verified_at=None
        if d.get("verified_at", None) is None
        else text(d.get("verified_at", None), "verified_at"),
        ttl=None if d.get("ttl", None) is None else text(d.get("ttl", None), "ttl"),
        notes=text(d.get("notes", ""), "notes"),
    )


def encode_asset(value: Asset) -> JsonObject:
    result: JsonObject = {
        "schema_version": 1,
        "id": value.id.val,
        "kind": value.kind.value,
        "name": value.name,
        "locator": value.locator,
        "aliases": list(value.aliases),
        "owner": value.owner,
        "owner_source": value.owner_source,
        "lifecycle": value.lifecycle.value,
        "inspect": value.inspect,
        "projects": list(value.projects),
        "verified_at": value.verified_at,
        "ttl": value.ttl,
        "notes": value.notes,
    }
    return result


def decode_relationship(value: object) -> Relationship:
    d = fields(
        value,
        required={"type", "id", "to", "from"},
        optional={"applicability", "evidence", "status"},
        versioned=True,
    )
    return Relationship(
        id=RelationshipId(text(d["id"], "id")),
        type=enum_value(RelationshipType, d["type"], "type"),
        from_=AssetId(text(d["from"], "from")),
        to=AssetId(text(d["to"], "to")),
        status=enum_value(RelationshipStatus, d.get("status", "explicit"), "status"),
        evidence=tuple(
            parse_evidence_address(item) for item in texts(d.get("evidence", []), "evidence")
        ),
        applicability=text(d.get("applicability", ""), "applicability"),
    )


def encode_relationship(value: Relationship) -> JsonObject:
    result: JsonObject = {
        "schema_version": 1,
        "id": value.id.val,
        "type": value.type.value,
        "from": value.from_.val,
        "to": value.to.val,
        "status": value.status.value,
        "evidence": [item.spelling for item in value.evidence],
        "applicability": value.applicability,
    }
    return result


def decode_observation_source(value: object) -> ObservationSource:
    d = fields(
        value,
        required={"system", "locator"},
        optional={"role", "revision", "asset"},
        versioned=False,
    )
    return ObservationSource(
        system=enum_value(ObservationSystem, d["system"], "system"),
        locator=text(d["locator"], "locator"),
        asset=None
        if d.get("asset", None) is None
        else AssetId(text(d.get("asset", None), "asset")),
        revision=None
        if d.get("revision", None) is None
        else SourceRevision(text(d.get("revision", None), "revision")),
        role=enum_value(ObservationRole, d.get("role", "note"), "role"),
    )


def encode_observation_source(value: ObservationSource) -> JsonObject:
    result: JsonObject = {
        "system": value.system.value,
        "locator": value.locator,
        "asset": None if value.asset is None else value.asset.val,
        "revision": None if value.revision is None else value.revision.val,
        "role": value.role.value,
    }
    return result


def decode_observation_evidence(value: object) -> ObservationEvidence:
    d = fields(value, required={"locator"}, optional={"sha256"}, versioned=False)
    return ObservationEvidence(
        locator=text(d["locator"], "locator"),
        sha256=None
        if d.get("sha256", None) is None
        else ContentDigest(text(d.get("sha256", None), "sha256")),
    )


def encode_observation_evidence(value: ObservationEvidence) -> JsonObject:
    result: JsonObject = {
        "locator": value.locator,
        "sha256": None if value.sha256 is None else value.sha256.val,
    }
    return result


def decode_observation(value: object) -> Observation:
    d = _fields_v2(
        value,
        required={"source", "id", "observed_at", "run"},
        optional={
            "evidence",
            "environment",
            "dirty_diff_sha256",
            "status",
            "notes",
            "dirty",
            "command",
        },
        v2={"input_identity", "capture_status", "derived_from"},
    )
    observation = Observation(
        id=ObservationId(text(d["id"], "id")),
        run=RunId(text(d["run"], "run")),
        source=decode_observation_source(d["source"]),
        observed_at=text(d["observed_at"], "observed_at"),
        status=enum_value(ObservationStatus, d.get("status", "ok"), "status"),
        command=None if d.get("command", None) is None else text(d.get("command", None), "command"),
        environment=None
        if d.get("environment", None) is None
        else text(d.get("environment", None), "environment"),
        evidence=None
        if d.get("evidence", None) is None
        else decode_observation_evidence(d.get("evidence", None)),
        notes=None if d.get("notes", None) is None else text(d.get("notes", None), "notes"),
        dirty=optional_bool(d.get("dirty", None), "dirty"),
        dirty_diff_sha256=None
        if d.get("dirty_diff_sha256", None) is None
        else text(d.get("dirty_diff_sha256", None), "dirty_diff_sha256"),
        input_identity=None
        if d.get("input_identity") is None
        else decode_worktree_identity(d["input_identity"]),
        capture_status=enum_value(
            CaptureStatus, d.get("capture_status", CaptureStatus.LEGACY.value), "capture_status"
        ),
        derived_from=tuple(
            ObservationId(item) for item in texts(d.get("derived_from", []), "derived_from")
        ),
    )
    if observation.capture_status is CaptureStatus.CAPTURED:
        identity = observation.input_identity
        if identity is None or observation.source.system is not ObservationSystem.GIT:
            raise KctxError("malformed", "captured observation requires a Git input identity")
        if (
            observation.source.revision is None
            or observation.source.revision.val != identity.revision.val
        ):
            raise KctxError("malformed", "capture and source revision disagree")
    elif observation.input_identity is not None:
        raise KctxError(
            "malformed", "uncaptured observation cannot contain captured input identity"
        )
    if (
        len(set(observation.derived_from)) != len(observation.derived_from)
        or observation.id in observation.derived_from
    ):
        raise KctxError("malformed", "duplicate or self-referencing observation provenance")
    return observation


def encode_observation(value: Observation) -> JsonObject:
    result: JsonObject = {
        "schema_version": 1,
        "id": value.id.val,
        "run": value.run.val,
        "source": encode_observation_source(value.source),
        "observed_at": value.observed_at,
        "status": value.status.value,
        "command": value.command,
        "environment": value.environment,
        "evidence": None if value.evidence is None else encode_observation_evidence(value.evidence),
        "notes": value.notes,
        "dirty": value.dirty,
        "dirty_diff_sha256": value.dirty_diff_sha256,
    }
    if (
        value.capture_status is not CaptureStatus.LEGACY
        or value.input_identity is not None
        or value.derived_from
    ):
        result.update(
            {
                "schema_version": 2,
                "input_identity": None
                if value.input_identity is None
                else encode_worktree_identity(value.input_identity),
                "capture_status": value.capture_status.value,
                "derived_from": [identity.val for identity in value.derived_from],
            }
        )
    return result


def decode_coverage_entry(value: object) -> CoverageEntry:
    d = _fields_v2(
        value,
        required={"outcome", "item"},
        optional={"reason", "evidence", "prior_outcome", "updated_at"},
        v2={"policy"},
    )
    return CoverageEntry(
        item=text(d["item"], "item"),
        outcome=enum_value(CoverageOutcome, d["outcome"], "outcome"),
        evidence=tuple(ObservationId(item) for item in texts(d.get("evidence", []), "evidence")),
        reason=text(d.get("reason", ""), "reason"),
        updated_at=text(d.get("updated_at", ""), "updated_at"),
        prior_outcome=None
        if d.get("prior_outcome", None) is None
        else enum_value(CoverageOutcome, d.get("prior_outcome", None), "prior_outcome"),
        policy=enum_value(
            CoveragePolicy, d.get("policy", CoveragePolicy.SINGLE_SOURCE.value), "policy"
        ),
    )


def encode_coverage_entry(value: CoverageEntry) -> JsonObject:
    result: JsonObject = {
        "schema_version": 2,
        "item": value.item,
        "outcome": value.outcome.value,
        "evidence": [item.val for item in value.evidence],
        "reason": value.reason,
        "updated_at": value.updated_at,
        "prior_outcome": None if value.prior_outcome is None else value.prior_outcome.value,
        "policy": value.policy.value,
    }
    return result


def decode_run_manifest(value: object) -> RunManifest:
    d = fields(
        value,
        required={"created", "project", "run_id", "task", "mode"},
        optional={"state"},
        versioned=True,
    )
    return RunManifest(
        run_id=RunId(text(d["run_id"], "run_id")),
        task=text(d["task"], "task"),
        project=text(d["project"], "project"),
        mode=enum_value(RunMode, d["mode"], "mode"),
        created=text(d["created"], "created"),
        state=enum_value(RunState, d.get("state", "open"), "state"),
    )


def encode_run_manifest(value: RunManifest) -> JsonObject:
    result: JsonObject = {
        "schema_version": 1,
        "run_id": value.run_id.val,
        "task": value.task,
        "project": value.project,
        "mode": value.mode.value,
        "created": value.created,
        "state": value.state.value,
    }
    return result


def decode_observation_snapshot(value: object) -> ObservationSnapshot:
    d = fields(
        value,
        required={"id", "system", "dirty", "locator", "revision"},
        optional={
            "current_dirty",
            "current_revision",
            "changed",
            "assessment",
            "current_input_digest",
        },
        versioned=False,
    )
    return ObservationSnapshot(
        id=ObservationId(text(d["id"], "id")),
        system=enum_value(ObservationSystem, d["system"], "system"),
        locator=text(d["locator"], "locator"),
        revision=None if d["revision"] is None else SourceRevision(text(d["revision"], "revision")),
        dirty=optional_bool(d["dirty"], "dirty"),
        current_revision=None
        if d.get("current_revision", None) is None
        else SourceRevision(text(d.get("current_revision", None), "current_revision")),
        current_dirty=optional_bool(d.get("current_dirty", None), "current_dirty"),
        changed=optional_bool(d.get("changed", None), "changed"),
        assessment=enum_value(
            ObservationAssessment,
            d.get("assessment", ObservationAssessment.UNASSESSED.value),
            "assessment",
        ),
        current_input_digest=None
        if d.get("current_input_digest") is None
        else ContentDigest(text(d["current_input_digest"], "current_input_digest")),
    )


def encode_observation_snapshot(value: ObservationSnapshot) -> JsonObject:
    result: JsonObject = {
        "id": value.id.val,
        "system": value.system.value,
        "locator": value.locator,
        "revision": None if value.revision is None else value.revision.val,
        "dirty": value.dirty,
        "current_revision": None if value.current_revision is None else value.current_revision.val,
        "current_dirty": value.current_dirty,
        "changed": value.changed,
        "assessment": value.assessment.value,
        "current_input_digest": None
        if value.current_input_digest is None
        else value.current_input_digest.val,
    }
    if value.changed is None:
        del result["current_revision"], result["current_dirty"], result["changed"]
    return result


def decode_coverage(value: object) -> Coverage:
    data = fields(value, required={"entries"})
    entries = object_value(data["entries"], "entries")
    decoded: list[CoverageEntry] = []
    for key, raw in entries.items():
        entry = decode_coverage_entry(raw)
        if entry.item != key:
            raise KctxError("malformed", f"coverage key {key!r} differs from item {entry.item!r}")
        decoded.append(entry)
    return Coverage(tuple(decoded))


def encode_coverage(value: Coverage) -> JsonObject:
    entries: JsonObject = {}
    for entry in value.entries:
        if entry.item in entries:
            raise KctxError("malformed", f"duplicate coverage item {entry.item!r}")
        entries[entry.item] = encode_coverage_entry(entry)
    return {"schema_version": 1, "entries": entries}


def decode_run_receipt(value: object) -> RunReceipt:
    data = _fields_v2(
        value,
        required={
            "run",
            "receipt",
            "checked_at",
            "readiness",
            "required",
            "missing_required",
            "stale_observations",
            "observations",
            "evidence_origins",
        },
        optional=set(),
        v2={"coverage_complete", "eligible_to_proceed", "blocked_required", "unknown_observations"},
    )
    eligible = optional_bool(data.get("eligible_to_proceed", False), "eligible_to_proceed")
    if eligible is None:
        raise KctxError("malformed", "eligible_to_proceed must be a boolean")
    origins = fields(
        data["evidence_origins"],
        required={"total_citations", "distinct_observations", "shared_evidence"},
        versioned=False,
    )
    shared = object_value(origins["shared_evidence"], "shared_evidence")
    observations = data["observations"]
    if not isinstance(observations, list):
        raise KctxError("malformed", "observations must be an array")
    receipt = RunReceipt(
        run=RunId(text(data["run"], "run")),
        receipt=integer(data["receipt"], "receipt"),
        checked_at=text(data["checked_at"], "checked_at"),
        readiness=enum_value(Readiness, data["readiness"], "readiness"),
        required=texts(data["required"], "required"),
        missing_required=texts(data["missing_required"], "missing_required"),
        stale_observations=tuple(
            ObservationId(item) for item in texts(data["stale_observations"], "stale_observations")
        ),
        observations=tuple(decode_observation_snapshot(item) for item in observations),
        evidence_origins=EvidenceOrigins(
            integer(origins["total_citations"], "total_citations"),
            integer(origins["distinct_observations"], "distinct_observations"),
            tuple(
                SharedEvidence(ObservationId(key), texts(items, "shared_evidence"))
                for key, items in shared.items()
            ),
        ),
        coverage_complete=optional_bool(data.get("coverage_complete"), "coverage_complete"),
        eligible_to_proceed=eligible,
        blocked_required=texts(data.get("blocked_required", []), "blocked_required"),
        unknown_observations=tuple(
            ObservationId(item)
            for item in texts(data.get("unknown_observations", []), "unknown_observations")
        ),
    )
    if receipt.eligible_to_proceed and (
        receipt.readiness is not Readiness.READY
        or receipt.coverage_complete is not True
        or receipt.missing_required
        or receipt.blocked_required
        or receipt.stale_observations
        or receipt.unknown_observations
    ):
        raise KctxError("malformed", "receipt eligibility conflicts with recorded assessment")
    return receipt


def encode_run_receipt(value: RunReceipt) -> JsonObject:
    shared: JsonObject = {
        entry.observation.val: list(entry.items) for entry in value.evidence_origins.shared_evidence
    }
    return {
        "schema_version": 2,
        "run": value.run.val,
        "receipt": value.receipt,
        "checked_at": value.checked_at,
        "readiness": value.readiness.value,
        "required": list(value.required),
        "missing_required": list(value.missing_required),
        "stale_observations": [item.val for item in value.stale_observations],
        "observations": [encode_observation_snapshot(item) for item in value.observations],
        "evidence_origins": {
            "total_citations": value.evidence_origins.total_citations,
            "distinct_observations": value.evidence_origins.distinct_observations,
            "shared_evidence": shared,
        },
        "coverage_complete": value.coverage_complete,
        "eligible_to_proceed": value.eligible_to_proceed,
        "blocked_required": list(value.blocked_required),
        "unknown_observations": [item.val for item in value.unknown_observations],
    }


def encode_run_resume(value: RunResume) -> JsonObject:
    summary: JsonObject = {item.outcome.value: item.count for item in value.coverage_summary}
    return {
        "manifest": encode_run_manifest(value.manifest),
        "coverage_summary": summary,
        "stale_items": list(value.stale_items),
        "checkpoint": value.checkpoint,
        "last_receipt": None
        if value.last_receipt is None
        else encode_run_receipt(value.last_receipt),
    }


def encode_run_checkpoint(value: RunCheckpoint) -> JsonObject:
    return {"run": value.run.val, "checkpoint_path": value.checkpoint_path}


def encode_impact(value: Impact) -> JsonObject:
    reached: list[JsonValue] = [
        {
            "asset": item.asset.val,
            "via": item.via.val,
            "relationship": item.relationship.val,
            "type": item.type.value,
            "status": item.status.value,
        }
        for item in value.reached
    ]
    unexplored: list[JsonValue] = [
        {
            "from": item.from_.val,
            "relationship": item.relationship.val,
            "to": item.to.val,
            "type": item.type.value,
        }
        for item in value.unexplored_edges
    ]
    return {
        "asset": value.asset.val,
        "depth": value.depth,
        "reached": reached,
        "unexplored_edges": unexplored,
        "note": value.note,
        "warnings": list(value.warnings),
    }
