"""Typed use-target references (handover §6.1, M2 slice 7).

`kctx uses <target>` accepts six spellings: `ev:` evidence ids, `sig:` and
`inv:` ids, `proposal/…` ids, bare asset ids/aliases, and `repo@sha:path:L`
code locators. The baseline classified them by scattered
`target.startswith("ev:")` checks with inline slicing at every use site.

This module parses the spelling **once, at the boundary**, into a closed sum;
downstream code switches on the variant, never on string prefixes. Parsing
keeps the baseline's exact acceptance rules (including bare-form search
widening for sig/inv/proposal), so behavior is unchanged — the fixtures suite
(50 nav tests) is the contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple, Union


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """`ev:<home>/<stem>` — no bare-form widening (its only alternate form is
    the migration history `uses` is scoped to tolerate, not solve)."""

    home: str
    stem: str

    @property
    def spelling(self) -> str:
        return f"ev:{self.home}/{self.stem}"

    @property
    def search_strings(self) -> Tuple[str, ...]:
        return (self.spelling,)


@dataclass(frozen=True, slots=True)
class _IdRef:
    """`prefix:id` where the bare id is also a live reference form."""

    prefix: str
    id: str

    @property
    def spelling(self) -> str:
        return f"{self.prefix}:{self.id}"

    @property
    def search_strings(self) -> Tuple[str, ...]:
        return (self.spelling, self.id)


class SigRef(_IdRef):
    __slots__ = ()

    def __init__(self, id: str):
        super().__init__("sig", id)


class InvRef(_IdRef):
    __slots__ = ()

    def __init__(self, id: str):
        super().__init__("inv", id)


@dataclass(frozen=True, slots=True)
class ProposalRef:
    """`proposal/<kind>/<date>-slug` — bare `<date>-slug` is a live form."""

    id: str

    @property
    def spelling(self) -> str:
        return f"proposal/{self.id}"

    @property
    def search_strings(self) -> Tuple[str, ...]:
        return (self.spelling, self.id)


@dataclass(frozen=True, slots=True)
class AssetRef:
    """A bare asset id/alias — resolved against inventory by the caller."""

    ident: str

    @property
    def spelling(self) -> str:
        return self.ident

    @property
    def search_strings(self) -> Tuple[str, ...]:
        return (self.ident,)  # replaced by id+aliases once resolved


@dataclass(frozen=True, slots=True)
class CodeLocator:
    """`repo@sha:path[:L…]` — matched against citations' own path=/L= fields,
    never against free-text file:line mentions."""

    repo: str
    sha: str
    path: str
    line: Optional[Tuple[int, int]]

    @property
    def spelling(self) -> str:
        line = "" if self.line is None else f":{self.line[0]}"
        if self.line is not None and self.line[1] != self.line[0]:
            line = f":{self.line[0]}-{self.line[1]}"
        return f"{self.repo}@{self.sha}:{self.path}{line}"


UseTarget = Union[EvidenceRef, SigRef, InvRef, ProposalRef, AssetRef, CodeLocator]

# Same shape as nav's _USES_LOCATOR_RE (kept in one place; nav imports this).
LOCATOR_RE = re.compile(
    r"^(?P<repo>[^@\s]+)@(?P<sha>[0-9a-fA-F]{7,40}):(?P<path>[^:\s]+)"
    r"(?::(?P<line>\d+(?:-\d+)?))?$"
)


def _line_range(raw: Optional[str]) -> Optional[Tuple[int, int]]:
    if not raw:
        return None
    a, _, b = raw.partition("-")
    try:
        return (int(a), int(b)) if b else (int(a), int(a))
    except ValueError:
        return None  # baseline: an unparseable line is no line constraint


def parse_use_target(raw: str) -> UseTarget:
    """Parse a `kctx uses` target spelling once. Accepts exactly what the
    baseline accepted (prefix rules + locator regex); malformed inputs fall
    through to AssetRef, whose inventory resolution reports not-found — the
    baseline's behavior."""
    m = LOCATOR_RE.match(raw)
    if m:
        return CodeLocator(
            repo=m.group("repo"),
            sha=m.group("sha"),
            path=m.group("path"),
            line=_line_range(m.group("line")),
        )
    if raw.startswith("ev:"):
        rest = raw[len("ev:") :]
        home, _, stem = rest.rpartition("/")  # home may itself contain /
        return EvidenceRef(home=home, stem=stem)
    if raw.startswith("sig:"):
        return SigRef(raw[len("sig:") :])
    if raw.startswith("inv:"):
        return InvRef(raw[len("inv:") :])
    if raw.startswith("proposal/"):
        return ProposalRef(raw[len("proposal/") :])
    return AssetRef(ident=raw)


def search_strings(target: UseTarget) -> Tuple[str, ...]:
    """Literal strings to grep for, per the baseline's widening rules."""
    return target.search_strings
