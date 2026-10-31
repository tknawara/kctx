"""Nominal identity types for the legacy record layer (handover §6.1, M2).

The semantics core (`kctx.semantics.model`) already enforces nominal identity
for the calculus records; this module brings the same discipline to the
*legacy* CLI boundary (assets, relationships, evidence, …) so that a
validated id enters the system once, at parse time — never re-parsed from a
bare string deep in application logic.

Each type is a frozen value object with the same validation rule the corpus
already follows: non-empty, no whitespace, lowercase ASCII letters/digits/
hyphens (the slug alphabet `slugify` produces). Parse once at the boundary
with `parse_*`; downstream code carries the typed value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NewType

from errors import KctxError

# Phantom markers for static checkers: an AssetId is never an EvidenceId
# even though both wrap a string (Q01's guard rail; the runtime class below
# is what actually enforces it at the boundary).
_AssetId = NewType("_AssetId", str)
_EvidenceId = NewType("_EvidenceId", str)
_RelationshipId = NewType("_RelationshipId", str)

_ID_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


@dataclass(frozen=True, slots=True)
class SlugId:
    """A validated slug-namespace identity. Subclasses fix the namespace."""

    __kind__ = "id"

    val: str

    def __post_init__(self) -> None:
        if not _ID_RE.match(self.val):
            raise KctxError(
                "malformed",
                f"{self.__kind__} {self.val!r} must match {_ID_RE.pattern!r} "
                "(non-empty, lowercase letters/digits/hyphens)",
            )

    def __str__(self) -> str:
        return self.val

    # Explicit, not accidental: comparisons and dict keys use the wrapped
    # string so JSON records stay byte-compatible.
    def __eq__(self, other: object) -> bool:
        if isinstance(other, SlugId):
            return self.__class__ is other.__class__ and self.val == other.val
        if isinstance(other, str):
            return self.val == other
        return NotImplemented

    def __hash__(self) -> int:
        # Hash as the wrapped string so id-keyed dicts interop with the
        # string keys JSON records use; __eq__ still separates namespaces.
        return hash(self.val)


class AssetId(SlugId):
    __kind__ = "asset id"


class EvidenceId(SlugId):
    __kind__ = "evidence id"


# Relationship ids are slug segments joined by `__` (the corpus convention:
# type__from__to), so each namespace gets the pattern its records actually use.
_REL_ID_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(__[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")


class RelationshipId(SlugId):
    __kind__ = "relationship id"

    def __post_init__(self) -> None:
        if not _REL_ID_RE.match(self.val):
            raise KctxError(
                "malformed",
                f"relationship id {self.val!r} must be slug segments joined "
                "by __ (each matching the asset-id alphabet)",
            )


def parse_asset_id(raw: str) -> AssetId:
    return AssetId(raw)


def parse_evidence_id(raw: str) -> EvidenceId:
    return EvidenceId(raw)


def parse_relationship_id(raw: str) -> RelationshipId:
    return RelationshipId(raw)
