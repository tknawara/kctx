"""Shared diagnostics and per-record failure isolation for validation."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from kctx.errors import KctxError


@dataclass(frozen=True, slots=True)
class ValidationDiagnostic:
    category: str
    where: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationCounts:
    assets: int
    relationships: int
    proposals: int
    ktlo: int
    changes: int
    investigations: int
    signatures: int
    dossiers: int
    corrections: int


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ok: bool
    problems: tuple[ValidationDiagnostic, ...]
    warnings: tuple[ValidationDiagnostic, ...]
    counts: ValidationCounts


@dataclass(slots=True)
class Diagnostics:
    problems: list[ValidationDiagnostic] = field(default_factory=list[ValidationDiagnostic])
    warnings: list[ValidationDiagnostic] = field(default_factory=list[ValidationDiagnostic])

    def problem(self, category: str, where: str, message: str) -> None:
        self.problems.append(ValidationDiagnostic(category, where, message))

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(ValidationDiagnostic("warn", where, message))

    def malformed(self, path: Path, error: Exception) -> None:
        message = error.message if isinstance(error, KctxError) else str(error)
        self.problem("malformed", str(path), message)


Record = TypeVar("Record")


def read_record(
    path: Path, decode: Callable[[str], Record], diagnostics: Diagnostics
) -> Record | None:
    """Decode one file; a damaged neighbor must not hide subsequent diagnostics."""
    try:
        return decode(path.read_text(encoding="utf-8"))
    except (KctxError, ValueError, OSError) as error:
        diagnostics.malformed(path, error)
        return None
