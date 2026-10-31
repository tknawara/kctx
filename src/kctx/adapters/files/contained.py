"""Descriptor-relative source scans: no symlink ancestors, leaves, or reopen races."""

from __future__ import annotations

import errno
import os
import stat
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from kctx.errors import KctxError

_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def open_directory(path: Path) -> int:
    """Open every component without following links; the caller owns the returned fd.

    Explicit absolute and relative roots are supported. No resolve() or pathname
    containment check is used; even ancestors of the selected root are opened
    relative to an already-held descriptor. OS errors are retained for callers.
    """
    absolute = path.absolute()
    descriptor = os.open(absolute.anchor, _DIRECTORY_FLAGS)
    try:
        for component in absolute.parts[1:]:
            child = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while chunk := os.pread(descriptor, 65536, offset):
        chunks.append(chunk)
        offset += len(chunk)
    return b"".join(chunks)


def _refusal(path: Path, error: OSError) -> KctxError:
    category = "not-found" if error.errno == errno.ENOENT else "permission"
    return KctxError(
        category,
        f"source unavailable: refusing unsafe or inaccessible path {path}: {error.strerror}",
    )


@dataclass(frozen=True, slots=True)
class ContainedFile:
    path: Path
    root: Path
    root_is_file: bool
    original: bytes
    _descriptor: int
    _writable: bool
    _parent: int
    _name: str
    _identity: tuple[int, int]

    def text(self) -> str:
        try:
            return self.original.decode("utf-8")
        except UnicodeDecodeError as error:
            raise KctxError("malformed", f"source {self.path} is not UTF-8") from error

    def _check_unchanged(self) -> None:
        if not self._writable:
            raise KctxError("permission", f"source {self.path} was opened read-only")
        info = os.fstat(self._descriptor)
        current = os.stat(self._name, dir_fd=self._parent, follow_symlinks=False)
        if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != (
            info.st_dev,
            info.st_ino,
        ):
            raise KctxError(
                "conflict", f"source unavailable: {self.path} was replaced during citation scan"
            )
        if info.st_nlink != 1:
            raise KctxError(
                "permission", f"source unavailable: refusing write to linked file {self.path}"
            )
        if _read(self._descriptor) != self.original:
            raise KctxError("conflict", f"source {self.path} changed during citation scan")

    def _write(self, content: bytes) -> None:
        offset = 0
        while offset < len(content):
            written = os.pwrite(self._descriptor, content[offset:], offset)
            if written == 0:
                raise OSError(errno.EIO, "zero-length source write")
            offset += written
        os.ftruncate(self._descriptor, len(content))
        os.fsync(self._descriptor)

    @property
    def inode_identity(self) -> tuple[int, int]:
        return self._identity

    @staticmethod
    def write_updates(updates: Sequence[tuple[ContainedFile, str]]) -> None:
        """Preflight the entire batch, then publish through owned descriptors.

        No pathname is reopened. This is not a multi-file atomic transaction;
        device write failures are reported, never hidden as success.
        """
        encoded = [(source, text.encode("utf-8")) for source, text in updates]
        for source, _content in encoded:
            try:
                source._check_unchanged()
            except OSError as error:
                raise _refusal(source.path, error) from error
        for source, content in encoded:
            try:
                source._write(content)
            except OSError as error:
                raise _refusal(source.path, error) from error


def _acquire_file(
    parent: int,
    name: str,
    path: Path,
    root: Path,
    root_is_file: bool,
    writable: bool,
    stack: ExitStack,
) -> ContainedFile:
    flags = (os.O_RDWR if writable else os.O_RDONLY) | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    descriptor = os.open(name, flags, dir_fd=parent)
    released = False
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise KctxError("permission", f"source unavailable: refusing non-regular file {path}")
        if writable and info.st_nlink != 1:
            raise KctxError(
                "permission", f"source unavailable: refusing write to linked file {path}"
            )
        original = _read(descriptor)
        identity = (info.st_dev, info.st_ino)
        if not writable:
            # Read-only scans visit whole trees; retain no descriptor per file.
            # The held-descriptor protocol below is what write-backs need.
            os.close(descriptor)
            released = True
            return ContainedFile(path, root, root_is_file, original, -1, False, -1, name, identity)
        retained_parent = os.dup(parent)
        try:
            stack.callback(os.close, retained_parent)
            stack.callback(os.close, descriptor)
        except BaseException:
            os.close(retained_parent)
            raise
        released = True  # The stack now owns both descriptors.
        return ContainedFile(
            path,
            root,
            root_is_file,
            original,
            descriptor,
            writable,
            retained_parent,
            name,
            identity,
        )
    finally:
        if not released:
            os.close(descriptor)


def _walk(
    directory: int,
    path: Path,
    root: Path,
    writable: bool,
    stack: ExitStack,
    files: list[ContainedFile],
) -> None:
    with os.scandir(directory) as entries:
        names = sorted(entry.name for entry in entries)
    for name in names:
        child_path = path / name
        info = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode):
            # Never follow links. A Markdown-suffixed leaf would place linked
            # content into scan results or write-backs, so it is refused; any
            # other link names no scannable Markdown and is skipped.
            if name.endswith(".md"):
                raise KctxError(
                    "permission", f"source unavailable: refusing symbolic link {child_path}"
                )
            continue
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory)
            try:
                _walk(child, child_path, root, writable, stack, files)
            finally:
                os.close(child)
        elif name.endswith(".md"):
            files.append(_acquire_file(directory, name, child_path, root, False, writable, stack))


@contextmanager
def contained_markdown(
    paths: Sequence[str], *, writable: bool = False
) -> Iterator[list[ContainedFile]]:
    """Acquire sources before callers can mutate any; never follow links.

    Explicit regular-file roots need not have a Markdown suffix. Directory roots
    recurse over Markdown files; Markdown-suffixed or explicitly selected links
    are refused, and other links in a walk are skipped unread. Write-back runs
    hold every leaf descriptor (and a parent descriptor) open until the context
    exits, so later pathname swaps cannot redirect writes; read-only scans read
    each leaf once and release its descriptor immediately.
    """
    with ExitStack() as stack:
        files: list[ContainedFile] = []
        seen: set[tuple[int, int]] = set()
        for name in paths:
            path = Path(name)
            try:
                parent = open_directory(path.absolute().parent)
                try:
                    leaf = path.absolute().name
                    if not leaf:  # The filesystem root itself.
                        directory = os.dup(parent)
                        info = os.fstat(directory)
                    else:
                        info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
                        directory = -1
                    if stat.S_ISLNK(info.st_mode):
                        raise KctxError(
                            "permission", f"source unavailable: refusing symbolic link {path}"
                        )
                    start = len(files)
                    if stat.S_ISDIR(info.st_mode):
                        if directory == -1:
                            directory = os.open(leaf, _DIRECTORY_FLAGS, dir_fd=parent)
                        try:
                            _walk(directory, path, path, writable, stack, files)
                        finally:
                            os.close(directory)
                    else:
                        files.append(_acquire_file(parent, leaf, path, path, True, writable, stack))
                    # Overlapping explicit roots must not rewrite the same inode twice.
                    unique: list[ContainedFile] = []
                    for source in files[start:]:
                        key = source.inode_identity
                        if key not in seen:
                            unique.append(source)
                            seen.add(key)
                    files[start:] = unique
                finally:
                    os.close(parent)
            except OSError as error:
                raise _refusal(path, error) from error
        yield files
