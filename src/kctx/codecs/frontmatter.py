"""Flat-frontmatter access and citation-aware list splitting.

The shared document codec owns parsing and duplicate diagnostics. This
read-only view permits documents without frontmatter, as navigation expects.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from kctx.codecs.documents import parse_document


@dataclass(frozen=True, slots=True)
class FrontmatterBlock:
    entries: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", MappingProxyType(dict(self.entries)))

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.entries.get(key, default)


def parse_frontmatter(text: str) -> FrontmatterBlock:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return FrontmatterBlock()
    for index, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return FrontmatterBlock(parse_document("\n".join(lines[: index + 1])).frontmatter)
    return FrontmatterBlock(parse_document(text).frontmatter)


def read_frontmatter(text: str) -> dict[str, str]:
    """Return a mutable caller-owned view; ambiguous keys are malformed."""
    return dict(parse_frontmatter(text).entries)


def split_commas_respecting_brackets(raw: str) -> list[str]:
    """Split on top-level commas, treating a `⟦...⟧` durable citation or a
    double-quoted span as opaque — a comma inside either (e.g. a cite's
    `sym="a, b"`) doesn't start a new list item. If the raw value has an odd
    number of quote characters, quotes are not tracked (to prevent a stray
    quote from swallowing commas); only ⟦...⟧ are respected in that case."""
    items: list[str] = []
    buf: list[str] = []
    depth = 0
    quote_count = raw.count('"')
    in_quotes = False if quote_count % 2 == 0 else None
    for ch in raw:
        if ch == '"' and in_quotes is not None:
            in_quotes = not in_quotes
            buf.append(ch)
        elif ch == "⟦" and (in_quotes is None or not in_quotes):
            depth += 1
            buf.append(ch)
        elif ch == "⟧" and (in_quotes is None or not in_quotes):
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0 and not in_quotes:
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    items.append("".join(buf))
    return [x.strip() for x in items if x.strip()]


def split_list_value(raw: str) -> list[str]:
    raw = raw.strip()
    if not (raw.startswith("[") and raw.endswith("]")):
        return []
    return split_commas_respecting_brackets(raw[1:-1])
