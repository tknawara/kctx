"""Durable, bounded knowledge artifacts and cooperating-writer locking."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from kctx.domain.json import JsonObject, JsonValue, object_value
from kctx.errors import KctxError

MAX_RECORD = 1024 * 1024


def canonical(value: JsonValue) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def unique_pairs(pairs: list[tuple[str, JsonValue]]) -> JsonObject:
    result: JsonObject = {}
    for key, value in pairs:
        if key in result:
            raise KctxError("malformed", f"duplicate JSON field: {key}")
        result[key] = value
    return result


def decode(data: bytes) -> JsonObject:
    if len(data) > MAX_RECORD:
        raise KctxError("malformed", "record exceeds 1 MiB bound")
    try:
        value: object = json.loads(data, object_pairs_hook=unique_pairs)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise KctxError("malformed", f"invalid knowledge JSON: {exc}") from exc
    return object_value(value)


def load(path: Path) -> JsonObject:
    return decode(path.read_bytes())


def durable_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save(path: Path, value: JsonObject) -> None:
    data = canonical(value)
    if len(data) > MAX_RECORD:
        raise KctxError("malformed", "record exceeds 1 MiB bound")
    durable_write(path, data)


def durable_unlink(path: Path) -> None:
    if not path.parent.exists():
        return
    path.unlink(missing_ok=True)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


@contextmanager
def writer_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
