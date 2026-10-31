"""The authored ⟦cite …⟧ grammar, independent of source resolution."""

import hashlib
import re
from collections.abc import Iterator, Mapping, Sequence

from kctx.errors import KctxError

CITE_LINE_RE = re.compile(r"⟦cite(?P<body>.*?)⟧", re.DOTALL)
FIELD_RE = re.compile(r'(\w+)=(?:"([^"]*)"|([^\s⟧]+))')
RANGE_RE = re.compile(r"^(\d+)-(\d+)$")
UNPINNED_RE = re.compile(r"@(main|HEAD|master):")
ILLUS_RE = re.compile(r"^\s*illus\b")


def is_illustrative(body: str) -> bool:
    return bool(ILLUS_RE.match(body))


def parse_cite_body(body: str) -> dict[str, str]:
    """Decode raw fields, retaining extensions and rejecting ambiguous duplicates."""
    fields: dict[str, str] = {}
    for match in FIELD_RE.finditer(body):
        key = match.group(1)
        if key in fields:
            raise KctxError("malformed", f"duplicate citation field {key!r}")
        fields[key] = match.group(2) if match.group(2) is not None else match.group(3)
    return fields


def find_cite_lines(text: str) -> Iterator[tuple[re.Match[str], dict[str, str]]]:
    for match in CITE_LINE_RE.finditer(text):
        yield match, parse_cite_body(match.group("body"))


def _format_field(key: str, value: str) -> str:
    if not re.fullmatch(r"\w+", key) or "⟧" in value:
        raise KctxError("malformed", f"unrepresentable citation field {key!r}")
    if re.search(r"\s", value) or not value or value.startswith('"'):
        if '"' in value:
            raise KctxError(
                "malformed", f"citation field {key!r} cannot quote embedded double quotes"
            )
        return f'{key}="{value}"'
    return f"{key}={value}"


def format_cite(fields: Mapping[str, str], order: Sequence[str]) -> str:
    parts: list[str] = []
    emitted: set[str] = set()
    for key in (*order, *fields):
        if key not in emitted and fields.get(key):
            parts.append(_format_field(key, fields[key]))
            emitted.add(key)
    return "⟦cite " + " ".join(parts) + "⟧"


def _field_match(raw_cite: str, key: str) -> re.Match[str] | None:
    # Match fields only inside the body: a final unquoted value must never
    # consume the closing delimiter, nor a quoted value masquerade as a key.
    cite = CITE_LINE_RE.fullmatch(raw_cite)
    if cite is None:
        raise KctxError("malformed", "expected one complete ⟦cite …⟧ token")
    parse_cite_body(cite.group("body"))
    for match in FIELD_RE.finditer(raw_cite, cite.start("body"), cite.end("body")):
        if match.group(1) == key:
            return match
    return None


def replace_field(raw_cite: str, key: str, new_value: str) -> str:
    token = _format_field(key, new_value)
    match = _field_match(raw_cite, key)
    if match is not None:
        return raw_cite[: match.start()] + token + raw_cite[match.end() :]
    return raw_cite[:-1].rstrip() + " " + token + "⟧"


def remove_field(raw_cite: str, key: str) -> str:
    match = _field_match(raw_cite, key)
    if match is None:
        return raw_cite
    start = match.start()
    while start > len("⟦cite") and raw_cite[start - 1].isspace():
        start -= 1
    return raw_cite[:start] + raw_cite[match.end() :]


def parse_range(value: str) -> tuple[int, int]:
    match = RANGE_RE.fullmatch(value)
    if match is None:
        raise KctxError("malformed", f"bad line range {value!r}, expected 'a-b'")
    first, last = int(match.group(1)), int(match.group(2))
    if first < 1 or last < first:
        raise KctxError("malformed", f"bad line range {value!r}")
    return first, last


def normalize_span(lines: Sequence[str]) -> str:
    joined = "\n".join(line.strip() for line in lines if line.strip())
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
