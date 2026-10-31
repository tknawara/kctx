"""Lossless citation token locations in Markdown and JSON source text."""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass

from kctx.domain.json import JsonObject, JsonValue, json_value, texts
from kctx.errors import KctxError


@dataclass(frozen=True)
class SourceText:
    """Decoded JSON string with boundaries into the original source text."""

    text: str
    start: int
    boundaries: tuple[int, ...] | None = None

    def offset(self, index: int) -> int:
        return self.start + index if self.boundaries is None else self.boundaries[index]


@dataclass(frozen=True)
class SourceToken:
    body: str
    raw: str
    src_line: int
    ordinal: int
    complete: bool


_JSON_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"', re.DOTALL)
_CITE_TOKEN_RE = re.compile(r"⟦cite(?P<body>.*?)(?:⟧|(?=⟦cite)|\Z)", re.DOTALL)


def _json_object(pairs: list[tuple[str, JsonValue]]) -> JsonObject:
    result: JsonObject = {}
    for key, value in pairs:
        if key in result:
            raise KctxError("malformed", f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def decode_json_source(text: str) -> JsonValue:
    """Reject duplicate object keys and values outside the JSON wire boundary."""
    return json_value(json.loads(text, object_pairs_hook=_json_object))


def source_texts(text: str, *, is_json: bool) -> Iterator[SourceText]:
    """Decode strings but scan malformed JSON gaps literally, without omissions."""
    if not is_json:
        yield SourceText(text, 0)
        return
    cursor = 0
    for match in _JSON_STRING_RE.finditer(text):
        if match.start() > cursor:
            yield SourceText(text[cursor : match.start()], cursor)
        raw = match.group(0)
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            yield SourceText(raw, match.start())
        else:
            if not isinstance(decoded, str):
                raise KctxError("malformed", "JSON string scanner produced a non-string")
            boundaries: list[int] = []
            index = 1
            while index < len(raw) - 1:
                boundaries.append(match.start() + index)
                if raw[index] != "\\":
                    index += 1
                elif raw[index + 1] != "u":
                    index += 2
                else:
                    codepoint = int(raw[index + 2 : index + 6], 16)
                    index += 6
                    if (
                        0xD800 <= codepoint <= 0xDBFF
                        and raw[index : index + 2] == "\\u"
                        and 0xDC00 <= int(raw[index + 2 : index + 6], 16) <= 0xDFFF
                    ):
                        index += 6
            boundaries.append(match.end() - 1)
            yield SourceText(decoded, match.start() + 1, tuple(boundaries))
        cursor = match.end()
    if cursor < len(text):
        yield SourceText(text[cursor:], cursor)


def _skip_json_whitespace(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def json_field_string_sources(text: str, field: str) -> Iterator[SourceText]:
    """Locate strings in a top-level array field through JSON grammar positions.

    Callers validate the complete record first. Keys and nonselected values are
    decoded as complete JSON values, so a nested key or unrelated string equal
    to the selected field name cannot masquerade as that top-level field.
    """
    decoder = json.JSONDecoder(object_pairs_hook=_json_object)
    index = _skip_json_whitespace(text, 0)
    if text[index : index + 1] != "{":
        raise KctxError("malformed", "JSON field source requires an object")
    index = _skip_json_whitespace(text, index + 1)
    while text[index : index + 1] != "}":
        key, index = decoder.raw_decode(text, index)
        if not isinstance(key, str):
            raise KctxError("malformed", "JSON object key must be a string")
        index = _skip_json_whitespace(text, index)
        if text[index : index + 1] != ":":
            raise KctxError("malformed", "JSON object key requires a colon")
        value_start = _skip_json_whitespace(text, index + 1)
        value, index = decoder.raw_decode(text, value_start)
        if key == field:
            values = texts(value, field)
            item_start = _skip_json_whitespace(text, value_start + 1)
            for item in values:
                _, item_end = decoder.raw_decode(text, item_start)
                source = next(source_texts(text[item_start:item_end], is_json=True))
                boundaries = (
                    tuple(item_start + boundary for boundary in source.boundaries)
                    if source.boundaries is not None
                    else None
                )
                yield SourceText(item, item_start + source.start, boundaries)
                item_start = _skip_json_whitespace(text, item_end)
                if text[item_start : item_start + 1] == ",":
                    item_start = _skip_json_whitespace(text, item_start + 1)
            return
        index = _skip_json_whitespace(text, index)
        if text[index : index + 1] == "}":
            return
        if text[index : index + 1] != ",":
            raise KctxError("malformed", "JSON object fields require a comma")
        index = _skip_json_whitespace(text, index + 1)


def iter_source_tokens(path: str, text: str) -> Iterator[SourceToken]:
    """Return authored raw spelling and physical line, with decoded token bodies.

    Ordinals include malformed tokens and are zero-based across the entire file.
    A missing closing delimiter produces a token with ``complete=False`` so the
    caller can retain an explicit diagnostic rather than lose the source input.
    """
    ordinal = 0
    for source in source_texts(text, is_json=path.endswith(".json")):
        for match in _CITE_TOKEN_RE.finditer(source.text):
            start = source.offset(match.start())
            yield SourceToken(
                body=match.group("body"),
                raw=text[start : source.offset(match.end())],
                src_line=text.count("\n", 0, start) + 1,
                ordinal=ordinal,
                complete=match.group(0).endswith("⟧"),
            )
            ordinal += 1
