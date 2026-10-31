"""Conditional writes for cooperating POSIX authored-record writers.

A record lock covers read/validate/publish. This is not a cross-file or
cross-store transaction; multi-record authoritative publication uses releases.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from kctx.errors import KctxError


@dataclass(frozen=True, slots=True)
class FileRevision:
    val: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", self.val) is None:
            raise KctxError("malformed", "invalid authored-file revision")


def revision_of(content: bytes) -> FileRevision:
    return FileRevision(hashlib.sha256(content).hexdigest())


def read_revision(path: Path) -> FileRevision | None:
    try:
        return revision_of(path.read_bytes())
    except FileNotFoundError:
        return None


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Lock one logical record; callers use the same record for sibling files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(f".{path.name}.kctx-lock")
    with lock.open("a+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, content: bytes, *, exclusive: bool = False) -> None:
    """Publish only fully written bytes; optional atomic create-if-absent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise KctxError("conflict", f"{path} already exists") from exc
        else:
            os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def compare_and_write(path: Path, content: bytes, *, expected: FileRevision | None) -> FileRevision:
    """Caller holds file_lock across its read/validate/write operation.

    The predecessor check detects a stale candidate; the lock serializes all
    cooperating writers. Uncooperative direct filesystem edits are not CAS.
    """
    if read_revision(path) != expected:
        raise KctxError("conflict", f"{path} changed since the candidate was read")
    atomic_write_bytes(path, content, exclusive=expected is None)
    return revision_of(content)
