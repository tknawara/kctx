"""Run lifecycle: new, observe, cover, check, resume, checkpoint.

A run is a directory under runs/<run-id>/ holding a manifest, immutable
observations, a coverage.json, numbered receipts, and a checkpoint log.
"""

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import git_utils
from errors import KctxError
from records import (
    COVERAGE_OUTCOMES,
    OBS_ROLES,
    OBS_STATUSES,
    OBS_SYSTEMS,
    RUN_MODES,
    CoverageEntry,
    Observation,
    ObservationSource,
    require_choice,
)
from storage import (
    atomic_write_json,
    compact_now,
    exclusive_write_json,
    iso_now,
    list_json_files,
    read_json,
    sha256_file,
)


def run_dir(root: Path, run_id: str) -> Path:
    return root / "runs" / run_id


def manifest_path(root: Path, run_id: str) -> Path:
    return run_dir(root, run_id) / "manifest.json"


def observations_dir(root: Path, run_id: str) -> Path:
    return run_dir(root, run_id) / "observations"


def coverage_path(root: Path, run_id: str) -> Path:
    return run_dir(root, run_id) / "coverage.json"


def receipts_dir(root: Path, run_id: str) -> Path:
    return run_dir(root, run_id) / "receipts"


def checkpoint_path(root: Path, run_id: str) -> Path:
    return run_dir(root, run_id) / "checkpoint.md"


def _require_run(root: Path, run_id: str) -> Dict[str, Any]:
    p = manifest_path(root, run_id)
    if not p.exists():
        raise KctxError("not-found", f"run {run_id} not found")
    return read_json(p)


def _numbered_receipts(root: Path, run_id: str) -> List[Path]:
    return sorted(
        list_json_files(receipts_dir(root, run_id)), key=lambda p: int(p.stem)
    )


def new_run(root: Path, *, project: str, mode: str, task: str) -> Dict[str, Any]:
    require_choice(mode, RUN_MODES, "mode")
    run_id = f"run-{compact_now()}-{uuid.uuid4().hex[:6]}"
    d = run_dir(root, run_id)
    if d.exists():
        raise KctxError("conflict", f"run {run_id} already exists")
    observations_dir(root, run_id).mkdir(parents=True)
    receipts_dir(root, run_id).mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "task": task,
        "project": project,
        "mode": mode,
        "created": iso_now(),
        "state": "open",
    }
    atomic_write_json(manifest_path(root, run_id), manifest)
    return manifest


def add_observation(
    root: Path,
    run_id: str,
    *,
    system: str,
    locator: str,
    asset: Optional[str] = None,
    revision: Optional[str] = None,
    role: str = "note",
    status: str = "ok",
    command: Optional[str] = None,
    environment: Optional[str] = None,
    evidence: Optional[str] = None,
    note: Optional[str] = None,
    obs_id: Optional[str] = None,
) -> Dict[str, Any]:
    _require_run(root, run_id)
    require_choice(system, OBS_SYSTEMS, "system")
    require_choice(role, OBS_ROLES, "role")
    require_choice(status, OBS_STATUSES, "status")

    dirty: Optional[bool] = None
    dirty_digest: Optional[str] = None
    if system == "git" and revision is None and git_utils.is_local_git_repo(locator):
        revision, dirty, dirty_digest = git_utils.resolve_git_state(locator)

    evidence_record = None
    if evidence:
        ev_path = Path(evidence)
        if ev_path.is_file():
            evidence_record = {"locator": evidence, "sha256": sha256_file(ev_path)}
        else:
            evidence_record = {"locator": evidence, "sha256": None}

    oid = obs_id or f"obs-{compact_now()}-{uuid.uuid4().hex[:8]}"
    source = ObservationSource(
        system=system, locator=locator, asset=asset, revision=revision, role=role
    )
    observation = Observation(
        id=oid,
        run=run_id,
        source=source,
        observed_at=iso_now(),
        status=status,
        command=command,
        environment=environment,
        evidence=evidence_record,
        notes=note,
        dirty=dirty,
        dirty_diff_sha256=dirty_digest,
    )
    path = observations_dir(root, run_id) / f"{oid}.json"
    exclusive_write_json(path, observation.to_dict())
    return observation.to_dict()


def load_observations(root: Path, run_id: str) -> List[Dict[str, Any]]:
    return [read_json(p) for p in list_json_files(observations_dir(root, run_id))]


def get_observation(root: Path, run_id: str, obs_id: str) -> Dict[str, Any]:
    p = observations_dir(root, run_id) / f"{obs_id}.json"
    if not p.exists():
        raise KctxError("not-found", f"observation {obs_id} not found in run {run_id}")
    return read_json(p)


def load_coverage(root: Path, run_id: str) -> Dict[str, Any]:
    p = coverage_path(root, run_id)
    if not p.exists():
        return {"schema_version": 1, "entries": {}}
    return read_json(p)


def cover(
    root: Path,
    run_id: str,
    *,
    item: str,
    outcome: str,
    evidence: Optional[List[str]] = None,
    reason: str = "",
) -> Dict[str, Any]:
    _require_run(root, run_id)
    require_choice(outcome, COVERAGE_OUTCOMES, "outcome")
    evidence = list(evidence or [])

    if outcome == "supported":
        if not evidence:
            raise KctxError(
                "incomplete",
                "outcome=supported requires at least one --evidence observation id",
            )
        observed = []
        for oid in evidence:
            obs = get_observation(root, run_id, oid)
            if obs.get("status") != "ok":
                raise KctxError(
                    "incomplete",
                    f"outcome=supported refused: evidence {oid} has status {obs.get('status')!r}, not ok",
                )
            observed.append(obs)
        if len(observed) > 1:
            by_origin: Dict[Any, List[str]] = {}
            for obs in observed:
                src = obs.get("source") or {}
                key = (src.get("system"), src.get("locator"))
                by_origin.setdefault(key, []).append(obs["id"])
            if len(by_origin) == 1:
                (all_ids,) = by_origin.values()
                raise KctxError(
                    "incomplete",
                    f"outcome=supported refused: evidence {', '.join(all_ids)} share "
                    "the same (source.system, source.locator) origin -- not "
                    "independent corroboration",
                )
    elif not reason:
        raise KctxError("incomplete", f"outcome={outcome!r} requires --reason")

    entry = CoverageEntry(
        item=item,
        outcome=outcome,
        evidence=evidence,
        reason=reason,
        updated_at=iso_now(),
    )
    data = load_coverage(root, run_id)
    data["entries"][item] = entry.to_dict()
    atomic_write_json(coverage_path(root, run_id), data)
    return entry.to_dict()


def check(
    root: Path, run_id: str, *, require: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Revalidate git-backed observations, downgrade stale coverage to
    needs-recheck, compute readiness, and persist a revision-bound receipt.
    """
    _require_run(root, run_id)
    require = list(require or [])
    observations = load_observations(root, run_id)
    coverage = load_coverage(root, run_id)
    entries = coverage.get("entries", {})

    stale_obs_ids: List[str] = []
    obs_snapshot: List[Dict[str, Any]] = []
    for obs in observations:
        src = obs.get("source", {})
        snap = {
            "id": obs["id"],
            "system": src.get("system"),
            "locator": src.get("locator"),
            "revision": src.get("revision"),
            "dirty": obs.get("dirty"),
        }
        if src.get("system") == "git" and git_utils.is_local_git_repo(
            src.get("locator", "")
        ):
            cur_rev, cur_dirty, cur_digest = git_utils.resolve_git_state(src["locator"])
            changed = (
                cur_rev != src.get("revision")
                or cur_dirty != bool(obs.get("dirty"))
                or (cur_dirty and cur_digest != obs.get("dirty_diff_sha256"))
            )
            snap["current_revision"] = cur_rev
            snap["current_dirty"] = cur_dirty
            snap["changed"] = changed
            if changed:
                stale_obs_ids.append(obs["id"])
        obs_snapshot.append(snap)

    coverage_changed = False
    for entry in entries.values():
        if any(oid in stale_obs_ids for oid in entry.get("evidence", [])):
            if entry.get("outcome") != "needs-recheck":
                entry["prior_outcome"] = entry.get("outcome")
                entry["outcome"] = "needs-recheck"
                entry["updated_at"] = iso_now()
                coverage_changed = True
    if coverage_changed:
        atomic_write_json(coverage_path(root, run_id), coverage)

    # Evidence-origin accounting (Q21): count distinct observations behind
    # coverage, not citations, so the same note cited twice isn't mistaken
    # for two independent pieces of evidence.
    citation_count = 0
    obs_to_items: Dict[str, List[str]] = {}
    for item, entry in entries.items():
        for oid in entry.get("evidence", []):
            citation_count += 1
            obs_to_items.setdefault(oid, []).append(item)
    shared_evidence = {
        oid: items for oid, items in obs_to_items.items() if len(items) > 1
    }

    missing_required = [
        item
        for item in require
        if entries.get(item, {}).get("outcome") not in ("supported", "violated")
    ]

    if missing_required:
        readiness = "blocked"
    elif stale_obs_ids or any(
        e.get("outcome")
        in ("unavailable", "not-examined", "inconclusive", "needs-recheck")
        for e in entries.values()
    ):
        readiness = "partial"
    else:
        readiness = "ready"

    n = len(_numbered_receipts(root, run_id)) + 1
    receipt = {
        "schema_version": 1,
        "run": run_id,
        "receipt": n,
        "checked_at": iso_now(),
        "readiness": readiness,
        "required": require,
        "missing_required": missing_required,
        "stale_observations": stale_obs_ids,
        "observations": obs_snapshot,
        "evidence_origins": {
            "total_citations": citation_count,
            "distinct_observations": len(obs_to_items),
            "shared_evidence": shared_evidence,
        },
    }
    while True:
        try:
            exclusive_write_json(receipts_dir(root, run_id) / f"{n}.json", receipt)
            break
        except KctxError:
            n += 1
            receipt["receipt"] = n
    return receipt


def resume(root: Path, run_id: str) -> Dict[str, Any]:
    manifest = _require_run(root, run_id)
    coverage = load_coverage(root, run_id)
    entries = coverage.get("entries", {})
    stale_items = [
        item for item, e in entries.items() if e.get("outcome") == "needs-recheck"
    ]
    outcome_counts: Dict[str, int] = {}
    for e in entries.values():
        outcome_counts[e.get("outcome", "?")] = (
            outcome_counts.get(e.get("outcome", "?"), 0) + 1
        )

    ckpt_path = checkpoint_path(root, run_id)
    checkpoint_text = (
        ckpt_path.read_text(encoding="utf-8") if ckpt_path.exists() else ""
    )

    receipts = _numbered_receipts(root, run_id)
    last_receipt = read_json(receipts[-1]) if receipts else None

    return {
        "manifest": manifest,
        "coverage_summary": outcome_counts,
        "stale_items": stale_items,
        "checkpoint": checkpoint_text,
        "last_receipt": last_receipt,
    }


def checkpoint(root: Path, run_id: str, *, note: str) -> Dict[str, Any]:
    _require_run(root, run_id)
    p = checkpoint_path(root, run_id)
    existing = p.read_text(encoding="utf-8") if p.exists() else ""
    section = f"\n## {iso_now()}\n\n{note}\n"
    p.write_text(existing + section, encoding="utf-8")
    return {"run": run_id, "checkpoint_path": str(p)}
