"""Flat-frontmatter and Markdown document codecs (handover §6, §7.4).

Extracted verbatim from the flat `storage.py` so services and the future
document representation share one owner (the handover's "shared parsers have
a clear owner" rule). Behavior is byte-compatible with the baseline — the
fixture suite is the contract — with two typed additions:

- :func:`parse_frontmatter` also reports **duplicate keys** (diagnosed, per
  the handover's "duplicate frontmatter keys are diagnostics, not silent
  loss" rule) instead of silently keeping the last one.
- :func:`split_list_value`/``split_commas_respecting_brackets`` keep their
  exact baseline semantics (⟦cite⟧- and quote-opaque comma splitting).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True, slots=True)
class FrontmatterBlock:
    """Parsed flat `key: value` frontmatter plus diagnostics.

    `entries` preserves first-occurrence order and, on duplicate keys, the
    *last* value (baseline behavior for readers) — but `duplicate_keys` makes
    the collision visible so callers can refuse to edit ambiguous documents.
    """

    entries: Dict[str, str] = field(default_factory=dict)
    duplicate_keys: Tuple[str, ...] = ()

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self.entries.get(key, default)


def parse_frontmatter(text: str) -> FrontmatterBlock:
    """Parse a flat frontmatter block delimited by `---` lines.

    Returns an empty block when the text doesn't open with one (callers treat
    that as nothing to check, not malformed — baseline behavior).
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return FrontmatterBlock()
    entries: Dict[str, str] = {}
    order: List[str] = []
    dupes: List[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            if k in entries and k not in dupes:
                dupes.append(k)
            if k not in entries:
                order.append(k)
            entries[k] = v.strip()
    return FrontmatterBlock(entries=dict(entries), duplicate_keys=tuple(dupes))


def read_frontmatter(text: str) -> dict:
    """Baseline-compatible view: the plain dict (last-wins on duplicates;
    use :func:`parse_frontmatter` when duplicates matter)."""
    return parse_frontmatter(text).entries


def split_commas_respecting_brackets(raw: str) -> List[str]:
    """Split on top-level commas, treating a `⟦...⟧` durable citation or a
    double-quoted span as opaque — a comma inside either (e.g. a cite's
    `sym="a, b"`) doesn't start a new list item. If the raw value has an odd
    number of quote characters, quotes are not tracked (to prevent a stray
    quote from swallowing commas); only ⟦...⟧ are respected in that case."""
    items: List[str] = []
    buf: List[str] = []
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


def split_list_value(raw: str) -> List[str]:
    raw = raw.strip()
    if not (raw.startswith("[") and raw.endswith("]")):
        return []
    return split_commas_respecting_brackets(raw[1:-1])
