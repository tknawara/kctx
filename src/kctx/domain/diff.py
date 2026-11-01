"""Local commit comparison coordinates; these values confer no claim support."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DiffHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int


@dataclass(frozen=True, slots=True)
class DiffFile:
    old_path: str | None
    new_path: str | None
    status: str
    hunks: tuple[DiffHunk, ...]
    binary: bool


@dataclass(frozen=True, slots=True)
class LocalDiff:
    repo_path: Path
    repository: str
    identities: tuple[str, ...]
    base: str
    head: str
    files: tuple[DiffFile, ...]
