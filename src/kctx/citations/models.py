"""Typed citation syntax results; parsed fields are not admitted knowledge."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from kctx.domain.json import JsonObject


class CitationKind(Enum):
    CODE = "code"
    COMMIT = "commit"
    PR = "pr"
    TICKET = "ticket"
    BREG = "breg"
    DEPLOY = "deploy"
    QUERY = "query"
    DOC = "doc"
    WEB = "web"
    USR = "usr"
    EV = "ev"
    GATE = "gate"
    RECORD = "record"
    PROPOSAL = "proposal"
    METRIC = "metric"
    LOG = "log"
    DATA = "data"


class CitationStatus(Enum):
    FRESH = "fresh"
    MOVED = "moved"
    CHANGED = "changed"
    GONE = "gone"
    UNVERIFIABLE = "unverifiable"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class MadeCitation:
    line: str
    fields: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))

    def to_wire(self) -> JsonObject:
        fields: JsonObject = {key: value for key, value in self.fields.items()}
        return {"line": self.line, "fields": fields}


@dataclass(frozen=True, slots=True)
class Classification:
    status: CitationStatus
    reason: str | None = None
    head: str | None = None
    line_range: str | None = None
    sym_line: int | None = None
    state: str | None = None
    query: str | None = None

    def to_wire(self) -> JsonObject:
        result: JsonObject = {"status": self.status.value}
        for key, value in (
            ("reason", self.reason),
            ("head", self.head),
            ("L", self.line_range),
            ("sym_line", self.sym_line),
            ("state", self.state),
            ("q", self.query),
        ):
            if value is not None:
                result[key] = value
        return result
