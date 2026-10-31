"""Crash-recoverable, local-only publication of native Dolt generations.

The checkout owner and advisory writer lock live at the stable graph root.
Each durable intent owns a unique generation directory; native backup/restore
preserves all refs without copying live database files. Only active.json makes
a candidate visible. Interrupted, dirty, and obsolete candidates are retained,
never reset, overwritten, adopted, or deleted. Native/noncooperating writers
and remote publication are outside this protocol.
"""

import fcntl
import os
import re
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from kctx.adapters.dolt.native import restore_backup
from kctx.adapters.files.storage import atomic_write_json, exclusive_write_json, read_json
from kctx.domain.json import JsonObject, fields, integer, optional_text, text
from kctx.errors import KctxError
from kctx.graph.dolt_store import DoltStore
from kctx.graph.generation import (
    COMPLETED_BRANCH,
    CompletedSnapshot,
    completed_pointer,
    completed_snapshot,
    snapshot_at,
)
from kctx.graph.inputs import GenerationInputs
from kctx.graph.models import DoltCommitId

_ID = re.compile(r"[0-9a-f]{32}")
_DIGEST = re.compile(r"[0-9a-f]{64}")


def _contained(home: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or not path.parts or any(part in {".", ".."} for part in path.parts):
        raise KctxError("conflict", "graph operation path must stay inside graph_dir")
    result = home / path
    current = home
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise KctxError(
                "conflict", f"graph operation path must not traverse symlinks: {current}"
            )
    if not result.resolve().is_relative_to(home):
        raise KctxError("conflict", "graph operation path escapes graph_dir")
    return result


def _db_path(home: Path, relative: str) -> Path:
    parts = Path(relative).parts
    if relative != "dolt" and not (
        len(parts) == 3
        and parts[0] == "generations"
        and _ID.fullmatch(parts[1])
        and parts[2] == "dolt"
    ):
        raise KctxError("malformed", "invalid graph generation database path")
    return _contained(home, relative)


def graph_home(store: DoltStore) -> Path:
    path = store.db_dir.absolute()
    if path.name != "dolt":
        raise KctxError("malformed", "invalid graph database directory")
    if path.parent.parent.name == "generations" and _ID.fullmatch(path.parent.name):
        home = path.parent.parent.parent.resolve()
    else:
        home = path.parent.resolve()
    _db_path(home, str(path.relative_to(home)))
    return home


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _durable_json(path: Path, value: JsonObject) -> None:
    atomic_write_json(path, value)
    _sync_directory(path.parent)


def _active(home: Path) -> JsonObject | None:
    path = _contained(home, "active.json")
    if not path.exists():
        return None
    value = fields(
        read_json(path), required={"operation_id", "db_path", "metadata_commit", "input_digest"}
    )
    operation_id = text(value["operation_id"], "graph operation id")
    if not _ID.fullmatch(operation_id) or value["db_path"] != f"generations/{operation_id}/dolt":
        raise KctxError("malformed", "active graph path disagrees with its operation")
    _db_path(home, text(value["db_path"], "active graph database"))
    if _commit(value["metadata_commit"]) is None:
        raise KctxError("malformed", "active graph requires a native metadata commit")
    _digest(value["input_digest"])
    return value


def active_db_dir(home: Path) -> Path:
    """Capture the active path once; old paths remain valid after publication."""
    home = home.expanduser().resolve()
    active = _active(home)
    return _db_path(home, text(active["db_path"], "active graph database") if active else "dolt")


def _check_owner(path: Path, kb_root: Path, operation_id: str | None = None) -> None:
    if not path.is_file():
        raise KctxError(
            "conflict",
            "graph database has no checkout ownership marker; select a new graph_dir rather than adopting or deleting existing history",
        )
    owner = fields(read_json(path), required={"checkout"}, optional={"operation_id"})
    expected = str(kb_root.resolve(strict=True))
    actual = text(owner["checkout"], "graph checkout owner")
    if actual != expected or owner.get("operation_id") != operation_id:
        raise KctxError(
            "conflict",
            f"graph database ownership does not match checkout {expected!r} and its operation; preserve existing history",
        )


def require_owner(store: DoltStore, kb_root: Path) -> None:
    home = graph_home(store)
    _check_owner(_contained(home, "dolt.owner.json"), kb_root)
    if store.db_dir != home / "dolt":
        operation_id = store.db_dir.parent.name
        _check_owner(
            _contained(home, f"generations/{operation_id}/dolt.owner.json"), kb_root, operation_id
        )


def require_clean(store: DoltStore) -> None:
    if not store.is_initialized():
        return
    active = store.sql_read("SELECT active_branch() AS active_name")
    if active and active[0].get("active_name") == COMPLETED_BRANCH:
        raise KctxError(
            "conflict", "the completed graph branch must not be checked out for writing"
        )
    if store.sql_read("SELECT table_name FROM dolt_status"):
        raise KctxError(
            "conflict",
            "graph has unpublished working changes; preserve/review them with native Dolt or select a new graph_dir",
        )


@contextmanager
def writer(home: Path, kb_root: Path) -> Iterator[DoltStore]:
    """Resolve publication under the stable lock, before any native writes."""
    home = home.expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True)
    with _contained(home, "dolt.writer.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            owner = _contained(home, "dolt.owner.json")
            if not owner.exists():
                for name in ("dolt", "generations", "operations"):
                    existing = _contained(home, name)
                    if existing.exists() and (not existing.is_dir() or any(existing.iterdir())):
                        raise KctxError(
                            "conflict",
                            "refusing to claim existing unowned graph history; select a new graph_dir",
                        )
                if _contained(home, "active.json").exists():
                    raise KctxError("conflict", "refusing to adopt an unowned active graph")
                _durable_json(
                    owner, {"schema_version": 1, "checkout": str(kb_root.resolve(strict=True))}
                )
            store = DoltStore(active_db_dir(home))
            require_owner(store, kb_root)
            if _active(home) is not None and not store.is_initialized():
                raise KctxError(
                    "conflict",
                    "active graph database is missing; refusing to replace published history",
                )
            if store.db_dir.exists() and any(store.db_dir.iterdir()) and not store.is_initialized():
                raise KctxError(
                    "conflict",
                    "published graph directory contains unknown state; refusing to overwrite it",
                )
            require_clean(store)
            yield store
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _commit(value: object) -> DoltCommitId | None:
    if value is None:
        return None
    try:
        return DoltCommitId(text(value, "graph operation commit"))
    except ValueError as error:
        raise KctxError("malformed", str(error)) from error


def _digest(value: object) -> str:
    digest = text(value, "graph operation input digest")
    if not _DIGEST.fullmatch(digest):
        raise KctxError("malformed", "invalid graph operation input digest")
    return digest


@dataclass(slots=True)
class Operation:
    home: Path
    record: JsonObject
    store: DoltStore

    @property
    def path(self) -> Path:
        return _contained(self.home, f"operations/{self.record['operation_id']}.json")

    @property
    def predecessor(self) -> DoltCommitId | None:
        return _commit(self.record["predecessor_commit"])

    def save(self, status: str, *, reason: str | None = None) -> None:
        self.record["status"] = status
        self.record["reason"] = reason
        _durable_json(self.path, self.record)


def _read_operation(home: Path, path: Path, dolt_bin: str) -> Operation:
    record = fields(
        read_json(path),
        required={
            "operation_id",
            "checkout",
            "status",
            "predecessor_path",
            "predecessor_commit",
            "candidate_path",
            "backup_path",
            "kb_sha",
            "input_digest",
            "rebuild",
            "history",
            "commits_replayed",
            "metadata_commit",
            "reason",
        },
    )
    operation_id = text(record["operation_id"], "graph operation id")
    if not _ID.fullmatch(operation_id) or path.name != f"{operation_id}.json":
        raise KctxError("malformed", "invalid graph operation journal identity")
    if (
        record["candidate_path"] != f"generations/{operation_id}/dolt"
        or record["backup_path"] != f"generations/{operation_id}/native-backup"
    ):
        raise KctxError("malformed", "graph operation paths disagree with their identity")
    candidate = _db_path(home, text(record["candidate_path"], "graph candidate path"))
    _db_path(home, text(record["predecessor_path"], "graph predecessor path"))
    _contained(home, text(record["backup_path"], "graph backup path"))
    _commit(record["predecessor_commit"])
    _commit(record["metadata_commit"])
    _digest(record["input_digest"])
    text(record["checkout"], "graph operation checkout")
    if (
        re.fullmatch(
            r"(?:[0-9a-f]{40}|[0-9a-f]{64})", text(record["kb_sha"], "graph operation KB commit")
        )
        is None
    ):
        raise KctxError("malformed", "invalid graph operation KB commit")
    if record["status"] not in ("pending", "ready", "activated", "abandoned"):
        raise KctxError("malformed", "invalid graph operation status")
    if type(record["rebuild"]) is not bool or (
        record["history"] is not None and not 1 <= integer(record["history"], "history") <= 1000
    ):
        raise KctxError("malformed", "invalid graph operation sync options")
    if integer(record["commits_replayed"], "commits replayed") < 1:
        raise KctxError("malformed", "invalid graph operation replay count")
    optional_text(record["reason"], "graph operation reason")
    return Operation(home, record, DoltStore(candidate, dolt_bin=dolt_bin))


def start(
    published: DoltStore,
    kb_root: Path,
    inputs: GenerationInputs,
    previous: CompletedSnapshot | None,
    *,
    rebuild: bool,
    history: int | None,
    commits_replayed: int,
) -> Operation:
    """Persist intent first, then transfer native history to a fresh directory."""
    home = graph_home(published)
    operation_id = uuid4().hex
    candidate = _db_path(home, f"generations/{operation_id}/dolt")
    backup = _contained(home, f"generations/{operation_id}/native-backup")
    journal = _contained(home, "operations")
    generations = _contained(home, "generations")
    journal.mkdir(exist_ok=True)
    generations.mkdir(exist_ok=True)
    _sync_directory(home)
    record: JsonObject = {
        "schema_version": 1,
        "operation_id": operation_id,
        "checkout": str(kb_root.resolve(strict=True)),
        "status": "pending",
        "predecessor_path": str(published.db_dir.relative_to(home)),
        "predecessor_commit": previous.metadata_commit.val if previous else None,
        "candidate_path": str(candidate.relative_to(home)),
        "backup_path": str(backup.relative_to(home)),
        "kb_sha": inputs.kb_sha,
        "input_digest": inputs.digest,
        "rebuild": rebuild,
        "history": history,
        "commits_replayed": commits_replayed,
        "metadata_commit": None,
        "reason": None,
    }
    operation = Operation(home, record, DoltStore(candidate, dolt_bin=published.dolt_bin))
    exclusive_write_json(operation.path, record)
    candidate.parent.mkdir()
    _sync_directory(generations)
    _durable_json(
        candidate.with_name("dolt.owner.json"),
        {
            "schema_version": 1,
            "checkout": record["checkout"],
            "operation_id": operation_id,
        },
    )
    if published.is_initialized():
        branch_rows = published.sql_read("SELECT active_branch() AS active_name")
        branch = text(branch_rows[0].get("active_name"), "published graph branch")
        published.backup_to(backup)
        restore_backup(
            backup,
            candidate,
            dolt_bin=published.dolt_bin,
            config_root=_contained(home, f"generations/{operation_id}/restore-config"),
        )
        operation.store.checkout(branch)
        require_clean(operation.store)
        if (
            completed_pointer(operation.store) != operation.predecessor
            or operation.store.head_commit_hash() != published.head_commit_hash()
        ):
            raise KctxError(
                "conflict", "native graph backup changed publication identity; candidate retained"
            )
    return operation


def recover(
    published: DoltStore,
    kb_root: Path,
    inputs: GenerationInputs,
    previous: CompletedSnapshot | None,
    *,
    rebuild: bool,
    history: int | None,
) -> tuple[Operation, CompletedSnapshot] | None:
    """Reuse only owned, clean, fully committed work; retain everything else."""
    home = graph_home(published)
    journal = _contained(home, "operations")
    if not journal.exists():
        return None
    for path in sorted(journal.glob("*.json")):
        _contained(home, str(path.relative_to(home)))
        operation = _read_operation(home, path, published.dolt_bin)
        record = operation.record
        if record["status"] in ("activated", "abandoned"):
            continue
        if record["checkout"] != str(kb_root.resolve(strict=True)):
            raise KctxError(
                "conflict", "graph operation belongs to a different checkout; refusing to change it"
            )
        matches = (
            record["input_digest"] == inputs.digest
            and record["kb_sha"] == inputs.kb_sha
            and record["rebuild"] == rebuild
            and record["history"] == history
        )
        # The manifest can be durable while its final journal update was interrupted.
        if operation.store.db_dir == published.db_dir:
            if (
                previous is None
                or previous.state.input_digest != record["input_digest"]
                or previous.metadata_commit.val != record["metadata_commit"]
            ):
                raise KctxError("conflict", "activated graph disagrees with its pending operation")
            if matches:
                return operation, previous
            operation.save("activated")
            continue
        predecessor = previous.metadata_commit if previous else None
        if (
            not matches
            or record["predecessor_path"] != str(published.db_dir.relative_to(home))
            or operation.predecessor != predecessor
        ):
            operation.save(
                "abandoned",
                reason="superseded inputs, sync options, or predecessor; candidate retained",
            )
            continue
        try:
            require_owner(operation.store, kb_root)
            if not operation.store.is_initialized():
                raise KctxError("conflict", "candidate native database was not initialized")
            require_clean(operation.store)
            head = _commit(operation.store.head_commit_hash())
            if head is None or head == predecessor:
                raise KctxError("conflict", "candidate has no new complete native snapshot")
            snapshot = snapshot_at(operation.store, head)
            if (
                snapshot.inputs is None
                or snapshot.state.input_digest != inputs.digest
                or snapshot.state.kb_sha != inputs.kb_sha
            ):
                raise KctxError("conflict", "candidate generation inputs are not current")
            if completed_pointer(operation.store) not in (predecessor, head):
                raise KctxError("conflict", "candidate completed pointer was independently changed")
            if record["metadata_commit"] is not None and record["metadata_commit"] != head.val:
                raise KctxError("conflict", "candidate metadata disagrees with its journal")
        except (KctxError, OSError, subprocess.SubprocessError) as error:
            operation.save("abandoned", reason=f"{error}; candidate retained without changes")
            continue
        return operation, snapshot
    return None


def _sync_tree(path: Path) -> None:
    """Persist native files before the durable selector can reference them."""
    for directory, directories, files in os.walk(path, followlinks=False):
        parent = Path(directory)
        if any((parent / name).is_symlink() for name in directories + files):
            raise KctxError(
                "conflict", "candidate database contains a symlink; refusing publication"
            )
        for name in files:
            fd = os.open(parent / name, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        _sync_directory(parent)
    _sync_directory(path.parent)


def _write_active(operation: Operation, snapshot: CompletedSnapshot) -> None:
    _durable_json(
        _contained(operation.home, "active.json"),
        {
            "schema_version": 1,
            "operation_id": operation.record["operation_id"],
            "db_path": operation.record["candidate_path"],
            "metadata_commit": snapshot.metadata_commit.val,
            "input_digest": snapshot.state.input_digest,
        },
    )


def activate(operation: Operation, snapshot: CompletedSnapshot, kb_root: Path) -> None:
    """After native completion, atomically select the candidate; caller locks."""
    published = DoltStore(active_db_dir(operation.home), dolt_bin=operation.store.dolt_bin)
    require_owner(published, kb_root)
    require_clean(published)
    if published.db_dir == operation.store.db_dir:
        operation.save("activated")
        return
    if (
        str(published.db_dir.relative_to(operation.home)) != operation.record["predecessor_path"]
        or completed_pointer(published) != operation.predecessor
    ):
        raise KctxError(
            "conflict", "published graph changed during sync; candidate retained without activation"
        )
    require_owner(operation.store, kb_root)
    require_clean(operation.store)
    candidate = completed_snapshot(operation.store)
    if (
        candidate != snapshot
        or candidate is None
        or candidate.state.input_digest != operation.record["input_digest"]
        or operation.store.head_commit_hash() != candidate.metadata_commit.val
    ):
        raise KctxError("conflict", "candidate is not its clean, completed, journaled generation")
    _sync_tree(operation.store.db_dir)
    operation.record["metadata_commit"] = snapshot.metadata_commit.val
    operation.save("ready")
    _write_active(operation, snapshot)
    operation.save("activated")
