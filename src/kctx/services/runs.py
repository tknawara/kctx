"""Run lifecycle with immutable observations, coverage and revision-bound receipts."""

import uuid
from dataclasses import replace
from pathlib import Path

from kctx.adapters.files.storage import (
    atomic_write_json,
    exclusive_write_json,
    list_json_files,
    read_json,
    sha256_file,
)
from kctx.adapters.git.inspection import capture_worktree
from kctx.codecs.records import (
    decode_coverage,
    decode_observation,
    decode_run_manifest,
    decode_run_receipt,
    encode_coverage,
    encode_observation,
    encode_run_manifest,
    encode_run_receipt,
)
from kctx.domain.capture import (
    CaptureStatus,
    CoveragePolicy,
    ObservationAssessment,
    WorktreeIdentity,
)
from kctx.domain.ids import (
    AssetId,
    ContentDigest,
    GitRevision,
    ObservationId,
    RunId,
    SourceRevision,
)
from kctx.domain.records import (
    Coverage,
    CoverageCount,
    CoverageEntry,
    EvidenceOrigins,
    Observation,
    ObservationEvidence,
    ObservationSnapshot,
    ObservationSource,
    RunCheckpoint,
    RunManifest,
    RunReceipt,
    RunResume,
    SharedEvidence,
)
from kctx.domain.time import compact_now, iso_now
from kctx.domain.vocabulary import (
    CoverageOutcome,
    ObservationRole,
    ObservationStatus,
    ObservationSystem,
    Readiness,
    RunMode,
)
from kctx.errors import KctxError
from kctx.services.run_inputs import assess_git_input, retain_input
from kctx.services.run_provenance import evidence_dependencies, independent_origins


def run_dir(root: Path, run_id: RunId) -> Path:
    return root / "runs" / run_id.val


def manifest_path(root: Path, run_id: RunId) -> Path:
    return run_dir(root, run_id) / "manifest.json"


def observations_dir(root: Path, run_id: RunId) -> Path:
    return run_dir(root, run_id) / "observations"


def coverage_path(root: Path, run_id: RunId) -> Path:
    return run_dir(root, run_id) / "coverage.json"


def receipts_dir(root: Path, run_id: RunId) -> Path:
    return run_dir(root, run_id) / "receipts"


def checkpoint_path(root: Path, run_id: RunId) -> Path:
    return run_dir(root, run_id) / "checkpoint.md"


def _require_run(root: Path, run_id: RunId) -> RunManifest:
    path = manifest_path(root, run_id)
    if not path.exists():
        raise KctxError("not-found", f"run {run_id} not found")
    manifest = decode_run_manifest(read_json(path))
    if manifest.run_id != run_id:
        raise KctxError("malformed", f"manifest identity does not match run {run_id}")
    return manifest


def _numbered_receipts(root: Path, run_id: RunId) -> list[Path]:
    return sorted(list_json_files(receipts_dir(root, run_id)), key=lambda p: int(p.stem))


def new_run(root: Path, *, project: str, mode: RunMode, task: str) -> RunManifest:
    run_id = RunId(f"run-{compact_now()}-{uuid.uuid4().hex[:6]}")
    if run_dir(root, run_id).exists():
        raise KctxError("conflict", f"run {run_id} already exists")
    observations_dir(root, run_id).mkdir(parents=True)
    receipts_dir(root, run_id).mkdir(parents=True)
    manifest = RunManifest(run_id, task, project, mode, iso_now())
    atomic_write_json(manifest_path(root, run_id), encode_run_manifest(manifest))
    return manifest


def add_observation(
    root: Path,
    run_id: RunId,
    *,
    system: ObservationSystem,
    locator: str,
    asset: AssetId | None = None,
    revision: SourceRevision | None = None,
    role: ObservationRole = ObservationRole.NOTE,
    status: ObservationStatus = ObservationStatus.OK,
    command: str | None = None,
    environment: str | None = None,
    evidence: str | None = None,
    note: str | None = None,
    obs_id: ObservationId | None = None,
    derived_from: tuple[ObservationId, ...] = (),
) -> Observation:
    _require_run(root, run_id)
    oid = (
        obs_id
        if obs_id is not None
        else ObservationId(f"obs-{compact_now()}-{uuid.uuid4().hex[:8]}")
    )
    if oid in derived_from or len(set(derived_from)) != len(derived_from):
        raise KctxError("malformed", "duplicate or self-referencing observation provenance")
    for parent in derived_from:
        get_observation(root, run_id, parent)
    dirty: bool | None = None
    input_identity: WorktreeIdentity | None = None
    capture_status = CaptureStatus.NOT_APPLICABLE
    if system is ObservationSystem.GIT:
        expected_revision = None if revision is None else GitRevision(revision.val)
        try:
            capture = capture_worktree(locator)
            if expected_revision is not None and capture.revision != expected_revision:
                raise KctxError(
                    "conflict", "Git source does not match the requested immutable revision"
                )
        except KctxError as exc:
            if exc.category not in ("conflict", "incomplete"):
                raise
            capture_status = (
                CaptureStatus.MOVED if exc.category == "conflict" else CaptureStatus.UNAVAILABLE
            )
            if status is ObservationStatus.OK:
                status = (
                    ObservationStatus.PARTIAL
                    if capture_status is CaptureStatus.MOVED
                    else ObservationStatus.NOT_FOUND
                )
        else:
            input_identity = retain_input(root, run_id, capture)
            revision = SourceRevision(capture.revision.val)
            dirty = capture.dirty
            capture_status = CaptureStatus.CAPTURED
    evidence_record = None
    if evidence:
        ev_path = Path(evidence)
        evidence_record = ObservationEvidence(
            evidence, ContentDigest(sha256_file(ev_path)) if ev_path.is_file() else None
        )
    source = ObservationSource(system, locator, asset, revision, role)
    observation = Observation(
        oid,
        run_id,
        source,
        iso_now(),
        status,
        command,
        environment,
        evidence_record,
        note,
        dirty,
        None,
        input_identity,
        capture_status,
        derived_from,
    )
    exclusive_write_json(
        observations_dir(root, run_id) / f"{oid.val}.json", encode_observation(observation)
    )
    return observation


def load_observations(root: Path, run_id: RunId) -> tuple[Observation, ...]:
    observations = tuple(
        decode_observation(read_json(p)) for p in list_json_files(observations_dir(root, run_id))
    )
    if any(observation.run != run_id for observation in observations):
        raise KctxError("malformed", f"observation run does not match {run_id}")
    return observations


def get_observation(root: Path, run_id: RunId, obs_id: ObservationId) -> Observation:
    path = observations_dir(root, run_id) / f"{obs_id.val}.json"
    if not path.exists():
        raise KctxError("not-found", f"observation {obs_id} not found in run {run_id}")
    observation = decode_observation(read_json(path))
    if observation.run != run_id or observation.id != obs_id:
        raise KctxError("malformed", "observation identity does not match its path")
    return observation


def load_coverage(root: Path, run_id: RunId) -> Coverage:
    path = coverage_path(root, run_id)
    return decode_coverage(read_json(path)) if path.exists() else Coverage()


def cover(
    root: Path,
    run_id: RunId,
    *,
    item: str,
    outcome: CoverageOutcome,
    evidence: tuple[ObservationId, ...] = (),
    reason: str = "",
    policy: CoveragePolicy = CoveragePolicy.SINGLE_SOURCE,
) -> CoverageEntry:
    _require_run(root, run_id)
    if outcome is CoverageOutcome.NEEDS_RECHECK:
        raise KctxError("malformed", "needs-recheck is a runtime-only coverage outcome")
    if outcome is CoverageOutcome.SUPPORTED:
        if not evidence:
            raise KctxError(
                "incomplete", "outcome=supported requires at least one --evidence observation id"
            )
        observed = {observation.id: observation for observation in load_observations(root, run_id)}
        count = independent_origins(observed, evidence)
        minimum = max(policy.minimum_origins, 2 if len(evidence) > 1 else 1)
        if count < minimum:
            raise KctxError(
                "incomplete",
                f"outcome=supported refused: policy {policy.value} requires {minimum} independent origins; found {count}",
            )
    elif not reason:
        raise KctxError("incomplete", f"outcome={outcome.value!r} requires --reason")
    entry = CoverageEntry(item, outcome, evidence, reason, iso_now(), policy=policy)
    entries = {old.item: old for old in load_coverage(root, run_id).entries}
    entries[item] = entry
    atomic_write_json(
        coverage_path(root, run_id), encode_coverage(Coverage(tuple(entries.values())))
    )
    return entry


def check(root: Path, run_id: RunId, *, require: tuple[str, ...] = ()) -> RunReceipt:
    """Revalidate git evidence and persist coverage downgrades and a receipt."""
    _require_run(root, run_id)
    observations = load_observations(root, run_id)
    by_id = {observation.id: observation for observation in observations}
    coverage = load_coverage(root, run_id)
    stale_obs_ids: set[ObservationId] = set()
    unknown_obs_ids: set[ObservationId] = set()
    snapshots: list[ObservationSnapshot] = []
    for observation in observations:
        source = observation.source
        if source.system is ObservationSystem.GIT:
            snapshot = assess_git_input(root, observation)
            if snapshot.assessment is ObservationAssessment.CHANGED:
                stale_obs_ids.add(observation.id)
            elif snapshot.assessment is not ObservationAssessment.UNCHANGED:
                unknown_obs_ids.add(observation.id)
        else:
            snapshot = ObservationSnapshot(
                observation.id, source.system, source.locator, source.revision, observation.dirty
            )
        snapshots.append(snapshot)
    entries: dict[str, CoverageEntry] = {}
    coverage_changed = False
    for entry in coverage.entries:
        dependencies = evidence_dependencies(by_id, entry.evidence)
        invalid_provenance = False
        if entry.outcome is CoverageOutcome.SUPPORTED:
            try:
                count = independent_origins(by_id, entry.evidence)
                invalid_provenance = count < max(
                    entry.policy.minimum_origins, 2 if len(entry.evidence) > 1 else 1
                )
            except KctxError:
                invalid_provenance = True
        if (
            dependencies.intersection(stale_obs_ids | unknown_obs_ids) or invalid_provenance
        ) and entry.outcome is not CoverageOutcome.NEEDS_RECHECK:
            entry = replace(
                entry,
                prior_outcome=entry.outcome,
                outcome=CoverageOutcome.NEEDS_RECHECK,
                updated_at=iso_now(),
            )
            coverage_changed = True
        entries[entry.item] = entry
    if coverage_changed:
        atomic_write_json(
            coverage_path(root, run_id), encode_coverage(Coverage(tuple(entries.values())))
        )
    citation_count = 0
    obs_to_items: dict[ObservationId, list[str]] = {}
    for item, entry in entries.items():
        for oid in entry.evidence:
            citation_count += 1
            obs_to_items.setdefault(oid, []).append(item)
    missing_required = tuple(
        item
        for item in require
        if item not in entries
        or entries[item].outcome not in (CoverageOutcome.SUPPORTED, CoverageOutcome.VIOLATED)
    )
    blocked_required = tuple(
        item
        for item in require
        if item not in entries or entries[item].outcome is not CoverageOutcome.SUPPORTED
    )
    if blocked_required:
        readiness = Readiness.BLOCKED
    elif (
        stale_obs_ids
        or unknown_obs_ids
        or any(
            entry.outcome
            in (
                CoverageOutcome.VIOLATED,
                CoverageOutcome.UNAVAILABLE,
                CoverageOutcome.NOT_EXAMINED,
                CoverageOutcome.INCONCLUSIVE,
                CoverageOutcome.NEEDS_RECHECK,
            )
            for entry in entries.values()
        )
    ):
        readiness = Readiness.PARTIAL
    else:
        readiness = Readiness.READY
    n = len(_numbered_receipts(root, run_id)) + 1
    receipt = RunReceipt(
        run_id,
        n,
        iso_now(),
        readiness,
        require,
        missing_required,
        tuple(snapshot.id for snapshot in snapshots if snapshot.id in stale_obs_ids),
        tuple(snapshots),
        EvidenceOrigins(
            citation_count,
            len(obs_to_items),
            tuple(
                SharedEvidence(oid, tuple(items))
                for oid, items in obs_to_items.items()
                if len(items) > 1
            ),
        ),
        coverage_complete=not missing_required,
        eligible_to_proceed=readiness is Readiness.READY,
        blocked_required=blocked_required,
        unknown_observations=tuple(
            snapshot.id for snapshot in snapshots if snapshot.id in unknown_obs_ids
        ),
    )
    while True:
        try:
            exclusive_write_json(
                receipts_dir(root, run_id) / f"{n}.json", encode_run_receipt(receipt)
            )
            return receipt
        except KctxError as exc:
            if exc.category != "conflict":
                raise
            n += 1
            receipt = replace(receipt, receipt=n)


def resume(root: Path, run_id: RunId) -> RunResume:
    manifest = _require_run(root, run_id)
    coverage = load_coverage(root, run_id)
    counts: dict[CoverageOutcome, int] = {}
    for entry in coverage.entries:
        counts[entry.outcome] = counts.get(entry.outcome, 0) + 1
    path = checkpoint_path(root, run_id)
    checkpoint_text = path.read_text(encoding="utf-8") if path.exists() else ""
    receipts = _numbered_receipts(root, run_id)
    last_receipt = decode_run_receipt(read_json(receipts[-1])) if receipts else None
    return RunResume(
        manifest,
        tuple(CoverageCount(outcome, count) for outcome, count in counts.items()),
        tuple(
            entry.item
            for entry in coverage.entries
            if entry.outcome is CoverageOutcome.NEEDS_RECHECK
        ),
        checkpoint_text,
        last_receipt,
    )


def checkpoint(root: Path, run_id: RunId, *, note: str) -> RunCheckpoint:
    _require_run(root, run_id)
    path = checkpoint_path(root, run_id)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(existing + f"\n## {iso_now()}\n\n{note}\n", encoding="utf-8")
    return RunCheckpoint(run_id, str(path))
