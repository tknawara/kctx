"""Filesystem JSON persistence, content digests and filename normalization."""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import NoReturn

from kctx.errors import KctxError


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise KctxError("malformed", f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> NoReturn:
    raise KctxError("malformed", f"non-finite JSON number {value!r}")


def decode_json(text: str, *, source: str = "JSON") -> object:
    """Decode current or pinned bytes with identical duplicate/scalar rules."""
    try:
        value: object = json.loads(
            text, object_pairs_hook=_object_pairs, parse_constant=_invalid_constant
        )
        return value
    except json.JSONDecodeError as exc:
        raise KctxError("malformed", f"{source}: invalid JSON ({exc})") from exc


def read_json(path: Path) -> object:
    """Read raw JSON; schema codecs, not the file adapter, admit records."""
    try:
        return decode_json(path.read_text(encoding="utf-8"), source=str(path))
    except FileNotFoundError as exc:
        raise KctxError("not-found", f"{path} not found") from exc
    except UnicodeError as exc:
        raise KctxError("malformed", f"{path}: invalid UTF-8") from exc


def _encode_json(data: object) -> str:
    try:
        return json.dumps(data, indent=2, allow_nan=False) + "\n"
    except (TypeError, ValueError) as exc:
        raise KctxError("malformed", f"record is not JSON-serializable: {exc}") from exc


def atomic_write_json(path: Path, data: object) -> None:
    """Write via a temp file in the same directory, then os.replace.

    A crash mid-write leaves an orphaned .tmp-* file next to the target, not
    a half-written target, and callers that list *.json never see it.
    """
    encoded = _encode_json(data)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(encoded)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, str(path))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def exclusive_write_json(path: Path, data: object) -> None:
    """Publish complete immutable bytes with atomic create-if-absent semantics.

    The temporary inode is fsynced before its public name exists. A hard link
    within the same directory arbitrates concurrent creators without replacing
    a winner; interruption can leave only an ignored temporary file.
    """
    encoded = _encode_json(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise KctxError("conflict", f"{path} already exists") from exc
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)


def list_json_files(dir_path: Path) -> list[Path]:
    if not dir_path.exists():
        return []
    return sorted(p for p in dir_path.glob("*.json"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "item"
