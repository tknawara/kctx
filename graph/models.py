"""Typed records for the shadow graph. Pydantic v2 models -- query results
come back as these, not raw dolt-cli dicts, so a caller gets attribute
access and validation instead of trusting `dolt sql -r json` shape by hand.

Every dispatch-facing function converts these to plain dicts via
`.model_dump(mode="json")` before returning, matching the rest of kctx's
cli.py convention of returning JSON-serializable dicts/lists from dispatch.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    label: Optional[str] = None
    home_path: Optional[str] = None

    @classmethod
    def from_row(cls, row: dict) -> "Node":
        return cls(
            id=row["id"],
            kind=row.get("kind") or "",
            label=row.get("label"),
            home_path=row.get("home_path"),
        )


class Edge(BaseModel):
    """One citation binding or typed relationship row (handover-v2 S6.2's
    binding fields: src record id/path/line, normalized dst id, exact source
    revision, and when it was bound)."""

    model_config = ConfigDict(extra="forbid")

    edge_id: str
    src_node: str
    src_path: Optional[str] = None
    src_line: Optional[int] = None
    dst_node: str
    rel: str
    cite_kind: Optional[str] = None
    rev: Optional[str] = None
    blob_sha: Optional[str] = None
    span: Optional[str] = None
    seen: Optional[str] = None
    state: Optional[str] = None
    illus: bool = False
    raw: Optional[str] = None

    @classmethod
    def from_row(cls, row: dict) -> "Edge":
        return cls(
            edge_id=row["edge_id"],
            src_node=row["src_node"],
            src_path=row.get("src_path"),
            src_line=row.get("src_line"),
            dst_node=row["dst_node"],
            rel=row["rel"],
            cite_kind=row.get("cite_kind"),
            rev=row.get("rev"),
            blob_sha=row.get("blob_sha"),
            span=row.get("span"),
            seen=row.get("seen"),
            state=row.get("state"),
            illus=bool(row.get("illus") or 0),
            raw=row.get("raw"),
        )


class SyncState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_sha: str
    kb_subject: Optional[str] = None
    dolt_commit: Optional[str] = None
    synced_at: str
    node_count: int
    edge_count: int

    @classmethod
    def from_row(cls, row: dict) -> "SyncState":
        return cls(
            kb_sha=row["kb_sha"],
            kb_subject=row.get("kb_subject"),
            dolt_commit=row.get("dolt_commit"),
            synced_at=row["synced_at"],
            node_count=int(row.get("node_count") or 0),
            edge_count=int(row.get("edge_count") or 0),
        )
