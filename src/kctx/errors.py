"""Shared error type for kctx.

Every command raises KctxError for expected failures (not found, malformed
records, stale inputs, write conflicts, incomplete evidence, permission and
timeout problems) so the CLI can report a stable category instead of a raw
traceback.
"""

from dataclasses import dataclass
from typing import Literal, TypeAlias

from kctx.redaction import mask_secrets

ErrorCategory: TypeAlias = Literal[
    "not-found", "malformed", "stale", "conflict", "incomplete", "permission", "timeout"
]

CATEGORIES: frozenset[ErrorCategory] = frozenset(
    {"not-found", "malformed", "stale", "conflict", "incomplete", "permission", "timeout"}
)

_CODES: dict[ErrorCategory, str] = {
    "not-found": "E101",
    "malformed": "E102",
    "stale": "E103",
    "conflict": "E104",
    "incomplete": "E105",
    "permission": "E106",
    "timeout": "E107",
}


@dataclass(frozen=True, slots=True)
class DiagnosticLabel:
    location: str
    note: str = ""

    def to_wire(self) -> dict[str, str]:
        return {"location": mask_secrets(self.location), "note": mask_secrets(self.note)}


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    severity: Literal["error", "warning"]
    message: str
    labels: tuple[DiagnosticLabel, ...] = ()
    help: str | None = None

    def to_wire(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": mask_secrets(self.message),
            "labels": [label.to_wire() for label in self.labels],
            "help": mask_secrets(self.help) if self.help is not None else None,
        }


class KctxError(Exception):
    def __init__(
        self,
        category: ErrorCategory,
        message: str,
        *,
        labels: tuple[DiagnosticLabel, ...] = (),
        help: str | None = None,
    ) -> None:
        if category not in CATEGORIES:
            raise ValueError(f"unknown error category {category!r}")
        safe_message = mask_secrets(message)
        super().__init__(safe_message)
        self.category = category
        self.message = safe_message
        self.diagnostic = Diagnostic(_CODES[category], "error", safe_message, labels, help)
