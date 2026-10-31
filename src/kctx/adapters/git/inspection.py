"""Retain declared Git input bytes without following source symlink ancestors.

The git-worktree-v1 profile includes HEAD, every index stage/blob, tracked
and non-ignored untracked worktree files, binary bytes, symlink targets,
permission modes and recursively initialized submodules. Ignored files are
outside this explicit profile. Two identical complete reads are required;
this detects observed movement, not an impossible lock-free ABA guarantee.
Git inspection disables executable fsmonitor/hooks/diff configuration and
reads raw blobs, never textconv/filter output. This is not a general Git sandbox.
"""

import base64
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

from kctx.adapters.files.contained import open_directory
from kctx.domain.capture import WorktreeCapture
from kctx.domain.ids import ContentDigest, GitRevision
from kctx.domain.json import JsonObject, JsonValue
from kctx.domain.time import iso_now
from kctx.errors import KctxError

_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


def _identity(descriptor: int) -> tuple[int, int]:
    info = os.fstat(descriptor)
    return info.st_dev, info.st_ino


def _repository_root(path: Path) -> int:
    """Find the nearest .git ancestor using pinned directories, not core.worktree."""
    current = open_directory(path)
    try:
        while True:
            try:
                metadata = os.stat(".git", dir_fd=current, follow_symlinks=False)
            except FileNotFoundError:
                parent = os.open("..", _DIRECTORY_FLAGS, dir_fd=current)
                if _identity(parent) == _identity(current):
                    os.close(parent)
                    raise KctxError("incomplete", f"no Git worktree contains {path}") from None
                os.close(current)
                current = parent
                continue
            if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
                raise KctxError("incomplete", f"unsafe Git metadata entry at {path}")
            return current
    except BaseException:
        os.close(current)
        raise


def _git(root: int, *arguments: str) -> bytes:
    # pass_fds makes the selected directory, not its mutable pathname, the
    # child's working tree. Remove inherited repository/config overrides;
    # inspection reads this explicit root and never needs network credentials.
    selected = f"/proc/self/fd/{root}"
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_ATTR_NOSYSTEM": "1",
        }
    )
    try:
        result = subprocess.run(
            [
                "git",
                "--no-pager",
                "--no-replace-objects",
                "-c",
                "core.fsmonitor=false",
                "-c",
                f"core.hooksPath={os.devnull}",
                "-c",
                "diff.external=",
                "-c",
                "interactive.diffFilter=",
                "-c",
                "core.bare=false",
                f"--work-tree={selected}",
                "-C",
                selected,
                *arguments,
            ],
            capture_output=True,
            check=False,
            pass_fds=(root,),
            env=environment,
        )
    except OSError as exc:
        raise KctxError("incomplete", f"cannot inspect selected Git source: {exc}") from exc
    if result.returncode:
        raise KctxError(
            "incomplete",
            f"cannot inspect selected Git source: {result.stderr.decode(errors='replace').strip()}",
        )
    return result.stdout


def _encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _regular_bytes(descriptor: int, before: os.stat_result) -> bytes:
    if not stat.S_ISREG(before.st_mode):
        raise KctxError("incomplete", "worktree input is not a regular file")
    with os.fdopen(descriptor, "rb", closefd=False) as source:
        data = source.read()
    after = os.fstat(descriptor)
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_mode) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
        after.st_mode,
    ):
        raise KctxError("conflict", "worktree file moved during capture")
    return data


def _worktree_entry(
    root: int, path: bytes, gitlink: str | None, ancestors: frozenset[tuple[int, int]]
) -> tuple[JsonObject, bool]:
    parts = path.split(b"/")
    if any(part in (b"", b".", b"..", b".git") for part in parts):
        raise KctxError("malformed", "unsafe Git input pathname")
    entry: JsonObject = {"path_base64": _encoded(path)}
    parent = os.dup(root)
    try:
        try:
            for component in parts[:-1]:
                child = os.open(component, _DIRECTORY_FLAGS, dir_fd=parent)
                os.close(parent)
                parent = child
            info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            entry["kind"] = "missing"
            return entry, gitlink is not None
        entry["mode"] = stat.S_IMODE(info.st_mode)
        if stat.S_ISLNK(info.st_mode):
            if gitlink is not None:
                raise KctxError("incomplete", "submodule worktree cannot be a symlink")
            target = os.readlink(parts[-1], dir_fd=parent)
            entry.update({"kind": "symlink", "content_base64": _encoded(os.fsencode(target))})
            return entry, False
        flags = _DIRECTORY_FLAGS if gitlink is not None else _FILE_FLAGS
        descriptor = os.open(parts[-1], flags, dir_fd=parent)
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise KctxError("conflict", "worktree entry moved during capture")
            entry["mode"] = stat.S_IMODE(opened.st_mode)
            if gitlink is not None:
                metadata = os.stat(".git", dir_fd=descriptor, follow_symlinks=False)
                if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
                    raise KctxError("incomplete", "unsafe submodule Git metadata")
                nested, dirty = _snapshot(descriptor, ancestors)
                entry.update({"kind": "submodule", "snapshot": nested})
                return entry, dirty or nested["revision"] != gitlink
            entry.update(
                {"kind": "file", "content_base64": _encoded(_regular_bytes(descriptor, opened))}
            )
            return entry, False
        finally:
            os.close(descriptor)
    finally:
        os.close(parent)


def _snapshot(root: int, ancestors: frozenset[tuple[int, int]]) -> tuple[JsonObject, bool]:
    selected = _identity(root)
    if selected in ancestors:
        raise KctxError("malformed", "recursive submodule worktree")
    ancestors = ancestors | {selected}
    revision = GitRevision(_git(root, "rev-parse", "--verify", "HEAD").decode("ascii").strip())
    # Git status/diff can execute clean filters while hashing worktree files.
    # Compare raw retained inputs ourselves instead of invoking either command.
    head: dict[bytes, tuple[bytes, bytes]] = {}
    for record in _git(root, "ls-tree", "-r", "-z", revision.val).split(b"\0"):
        if record:
            metadata, path = record.split(b"\t", 1)
            mode, _kind, oid = metadata.split(b" ")
            head[path] = (mode, oid)
    staged: dict[bytes, tuple[bytes, bytes]] = {}
    dirty = False
    index: list[JsonValue] = []
    blobs: JsonObject = {}
    gitlinks: dict[bytes, str] = {}
    for record in _git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not record:
            continue
        metadata, path = record.split(b"\t", 1)
        mode, oid, stage = metadata.split(b" ")
        oid_text = oid.decode("ascii")
        index.append(
            {
                "path_base64": _encoded(path),
                "mode": mode.decode("ascii"),
                "oid": oid_text,
                "stage": int(stage),
            }
        )
        staged[path] = (mode, oid)
        dirty = dirty or stage != b"0"
        if mode == b"160000":
            gitlinks[path] = oid_text
        elif oid_text not in blobs:
            # Raw object bytes: no --textconv, --filters, diff or external helpers.
            blobs[oid_text] = _encoded(_git(root, "cat-file", "blob", oid_text))
    dirty = dirty or staged != head
    paths = set(
        _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0")
    ) - {b""}
    worktree: list[JsonValue] = []
    for path in sorted(paths):
        entry, nested_dirty = _worktree_entry(root, path, gitlinks.get(path), ancestors)
        worktree.append(entry)
        dirty = dirty or nested_dirty
        indexed = staged.get(path)
        if indexed is None:
            dirty = True
        elif path not in gitlinks:
            mode, oid = indexed
            expected_kind = "symlink" if mode == b"120000" else "file"
            actual_mode = entry.get("mode")
            executable = isinstance(actual_mode, int) and bool(actual_mode & stat.S_IXUSR)
            dirty = dirty or (
                entry.get("kind") != expected_kind
                or entry.get("content_base64") != blobs[oid.decode("ascii")]
                or (expected_kind == "file" and executable != (mode == b"100755"))
            )
    return {
        "profile": "git-worktree-v1",
        "revision": revision.val,
        "index": index,
        "index_blobs": blobs,
        "worktree": worktree,
    }, dirty


def capture_worktree(repo_path: str) -> WorktreeCapture:
    """Return pinned stable input bytes, or explicit unavailable/conflict errors."""
    started_at = iso_now()
    try:
        root = _repository_root(Path(repo_path))
        try:
            first, first_dirty = _snapshot(root, frozenset())
            second, second_dirty = _snapshot(root, frozenset())
            final_revision = _git(root, "rev-parse", "--verify", "HEAD").decode("ascii").strip()
            current_root = _repository_root(Path(repo_path))
            try:
                same_root = _identity(root) == _identity(current_root)
            finally:
                os.close(current_root)
        finally:
            os.close(root)
    except OSError as exc:
        raise KctxError(
            "incomplete", f"Git source unsafe or unavailable during capture: {repo_path}: {exc}"
        ) from exc
    if (
        not same_root
        or first != second
        or first_dirty != second_dirty
        or final_revision != first["revision"]
    ):
        raise KctxError("conflict", f"Git source moved during capture: {repo_path}")
    payload = json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    revision = first["revision"]
    if not isinstance(revision, str):
        raise KctxError("malformed", "captured Git revision is not text")
    return WorktreeCapture(
        GitRevision(revision),
        ContentDigest(hashlib.sha256(payload).hexdigest()),
        payload,
        first_dirty,
        started_at,
        iso_now(),
    )
