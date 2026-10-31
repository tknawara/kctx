"""Validated Dolt rows and nominal identities in the graph projection namespace."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer

from kctx.domain.json import JsonObject, JsonValue, object_value


@dataclass(frozen=True, slots=True)
class GraphNodeId:
    val: str

    def __post_init__(self) -> None:
        if not self.val:
            raise ValueError("graph node id must be a non-empty string")


@dataclass(frozen=True, slots=True)
class GraphEdgeId:
    val: str

    def __post_init__(self) -> None:
        if not self.val:
            raise ValueError("graph edge id must be a non-empty string")


@dataclass(frozen=True, slots=True)
class DoltCommitId:
    """A complete native Dolt commit hash, never a branch or abbreviation."""

    val: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-v]{32}", self.val) is None:
            raise ValueError("expected a complete native Dolt commit hash")


def _node_id(value: object) -> GraphNodeId:
    if isinstance(value, GraphNodeId):
        return value
    if isinstance(value, str):
        return GraphNodeId(value)
    raise ValueError("graph node id must be a string")


def _edge_id(value: object) -> GraphEdgeId:
    if isinstance(value, GraphEdgeId):
        return value
    if isinstance(value, str):
        return GraphEdgeId(value)
    raise ValueError("graph edge id must be a string")


def dolt_bool(value: object) -> bool:
    """Dolt TINYINT JSON is 0/1; older clients also emit those as strings."""
    if isinstance(value, bool):
        return value
    if type(value) is int and value in (0, 1):
        return value == 1
    if isinstance(value, str) and value in ("0", "1"):
        return value == "1"
    raise ValueError("Dolt boolean must be bool, 0, or 1")


def dolt_int(value: object) -> int:
    """Accept integer JSON and decimal integer text, never bool/float truncation."""
    if type(value) is int:
        return value
    if (
        isinstance(value, str)
        and value
        and (
            (value.isascii() and value.isdecimal())
            or (value.startswith("-") and value[1:].isascii() and value[1:].isdecimal())
        )
    ):
        return int(value)
    raise ValueError("Dolt integer must be an integer or decimal integer string")


NodeIdentity = Annotated[
    GraphNodeId,
    BeforeValidator(_node_id),
    PlainSerializer(lambda value: value.val, return_type=str),
]
EdgeIdentity = Annotated[
    GraphEdgeId,
    BeforeValidator(_edge_id),
    PlainSerializer(lambda value: value.val, return_type=str),
]
DoltInteger = Annotated[int, BeforeValidator(dolt_int)]
DoltBoolean = Annotated[bool, BeforeValidator(dolt_bool)]


class RowModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    def to_wire(self) -> JsonObject:
        return object_value(self.model_dump(mode="json"))


class Node(RowModel):
    id: NodeIdentity
    kind: str
    label: str | None = None
    home_path: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, JsonValue]) -> "Node":
        return cls.model_validate(dict(row))


class Edge(RowModel):
    edge_id: EdgeIdentity
    src_node: NodeIdentity
    dst_node: NodeIdentity
    rel: str
    src_path: str | None = None
    src_line: DoltInteger | None = None
    cite_kind: str | None = None
    rev: str | None = None
    blob_sha: str | None = None
    span: str | None = None
    line_selector: str | None = None
    seen: str | None = None
    state: str | None = None
    illus: DoltBoolean = False
    raw: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, JsonValue]) -> "Edge":
        return cls.model_validate(dict(row))


class SyncState(RowModel):
    id: DoltInteger = 1
    kb_sha: str
    kb_subject: str | None = None
    dolt_commit: str | None = None
    synced_at: str
    node_count: DoltInteger = 0
    edge_count: DoltInteger = 0
    input_digest: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, JsonValue]) -> "SyncState":
        return cls.model_validate(dict(row))


class ExtractionDiagnostic(RowModel):
    category: Literal["citation-skip", "record-malformed", "unresolved-repo"]
    src_path: str
    src_line: DoltInteger | None
    reason: str
    raw: str | None = None
    illus: DoltBoolean = False


class UsesRow(RowModel):
    src_node: NodeIdentity
    rel: str
    cite_kind: str | None = None
    seen: str | None = None
    src_kind: str | None = None
    src_home_path: str | None = None


class ImpactRow(RowModel):
    node: NodeIdentity
    depth: DoltInteger
    path: str
    kind: str | None = None
    home_path: str | None = None


class DiffSummary(RowModel):
    rel: str
    diff_type: str
    n: DoltInteger


class DiffSample(RowModel):
    diff_type: str
    rel: str
    src_node: NodeIdentity
    dst_node: NodeIdentity


class TraversalRow(RowModel):
    node: NodeIdentity
    dst_node: NodeIdentity
    kind: str | None = None
    home_path: str | None = None
