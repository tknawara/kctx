"""Flat-frontmatter Markdown with byte-preserving, fence-aware targeted edits.

Parsing is deliberately not admission: unfinished authored drafts are valid
unless a consumer explicitly requests required fields or sections.
"""

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from kctx.errors import KctxError


@dataclass(frozen=True, slots=True)
class _Span:
    name: str
    start: int
    end: int


def unfenced_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield original line offsets and lines outside backtick/tilde fences."""
    fence = ""
    width = 0
    offset = 0
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence:
            if (
                marker
                and marker[1][0] == fence
                and len(marker[1]) >= width
                and not marker[2].strip()
            ):
                fence = ""
        elif marker and not (marker[1][0] == "`" and "`" in marker[2]):
            fence, width = marker[1][0], len(marker[1])
        else:
            yield offset, line
        offset += len(line)


@dataclass(frozen=True, slots=True)
class MarkdownDocument:
    text: str
    _fields: tuple[_Span, ...]
    _sections: tuple[_Span, ...]
    _frontmatter_end: int

    @property
    def newline(self) -> str:
        match = re.search(r"\r\n|\n|\r", self.text)
        return match[0] if match else "\n"

    @property
    def body(self) -> str:
        """Authored bytes after the closing frontmatter delimiter."""
        closing_line = re.compile(r"\r\n|\n|\r").search(self.text, self._frontmatter_end)
        return self.text[closing_line.end() :] if closing_line is not None else ""

    @property
    def frontmatter(self) -> Mapping[str, str]:
        return MappingProxyType({s.name: self.text[s.start : s.end].strip() for s in self._fields})

    @property
    def sections(self) -> Mapping[str, str]:
        return MappingProxyType(
            {s.name: self.text[s.start : s.end].strip() for s in self._sections}
        )

    def unfenced_lines(self) -> tuple[str, ...]:
        closing = self.text.find("\n", self._frontmatter_end)
        body = self.text[closing + 1 :] if closing >= 0 else ""
        return tuple(line.rstrip("\r\n") for _, line in unfenced_lines(body))

    def update_fields(self, changes: Mapping[str, str | None]) -> "MarkdownDocument":
        patches: list[tuple[int, int, str]] = []
        remaining = dict(changes)
        for span in self._fields:
            if span.name not in remaining:
                continue
            value = remaining.pop(span.name) or ""
            if "\n" in value or "\r" in value:
                raise KctxError(
                    "malformed", f"frontmatter field {span.name!r} must occupy one line"
                )
            patches.append((span.start, span.end, value))
        if remaining:
            lines: list[str] = []
            for key, value in remaining.items():
                if (
                    not key
                    or any(c in key for c in ":\r\n")
                    or any(c in (value or "") for c in "\r\n")
                ):
                    raise KctxError("malformed", f"invalid frontmatter field {key!r}")
                lines.append(f"{key}: {value or ''}{self.newline}")
            patches.append((self._frontmatter_end, self._frontmatter_end, "".join(lines)))
        text = self.text
        for start, end, value in sorted(patches, reverse=True):
            text = text[:start] + value + text[end:]
        return parse_document(text)

    def update_section(self, name: str, content: str) -> "MarkdownDocument":
        content = content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", self.newline)
        for span in self._sections:
            if span.name != name:
                continue
            raw = self.text[span.start : span.end]
            if raw.strip():
                start = span.start + len(raw) - len(raw.lstrip())
                end = span.end - (len(raw) - len(raw.rstrip()))
                return parse_document(self.text[:start] + content.strip() + self.text[end:])
            prefix = raw if raw else self.newline
            suffix = self.newline * 2 if span.end < len(self.text) else self.newline
            return parse_document(
                self.text[: span.start] + prefix + content.strip() + suffix + self.text[span.end :]
            )
        if "\n" in name or "\r" in name:
            raise KctxError("malformed", "section heading must occupy one line")
        separator = (
            ""
            if self.text.endswith(self.newline * 2)
            else self.newline
            if self.text.endswith(self.newline)
            else self.newline * 2
        )
        return parse_document(
            self.text
            + separator
            + f"## {name}{self.newline}{self.newline}{content.strip()}{self.newline}"
        )

    def append_section(self, name: str, content: str) -> "MarkdownDocument":
        """Append content without replacing any previously authored bytes."""
        content = content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", self.newline)
        for span in self._sections:
            if span.name == name:
                raw = self.text[span.start : span.end]
                end = span.end - (len(raw) - len(raw.rstrip("\r\n"))) if raw.strip() else span.end
                prefix = (
                    self.newline
                    if raw.strip()
                    else ""
                    if self.text[:end].endswith(self.newline)
                    else self.newline
                )
                suffix = "" if self.text[end:].startswith(("\n", "\r")) else self.newline
                return parse_document(
                    self.text[:end] + prefix + content.strip() + suffix + self.text[end:]
                )
        return self.update_section(name, content)

    def write(self, path: Path) -> None:
        path.write_bytes(self.text.encode("utf-8"))


def parse_document(
    text: str, *, required_keys: tuple[str, ...] = (), required_sections: tuple[str, ...] = ()
) -> MarkdownDocument:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise KctxError("malformed", "document file missing frontmatter")
    fields: list[_Span] = []
    names: set[str] = set()
    offset = len(lines[0])
    for line in lines[1:]:
        if line.strip() == "---":
            frontmatter_end = offset
            body_start = offset + len(line)
            break
        if ":" in line and not line.lstrip().startswith("#"):
            key, _, raw = line.partition(":")
            key = key.strip()
            if key in names:
                raise KctxError("malformed", f"duplicate frontmatter key {key!r}")
            names.add(key)
            value = raw.rstrip("\r\n")
            leading = len(value) - len(value.lstrip())
            start = offset + line.index(":") + 1 + leading
            end = start + len(value.strip())
            fields.append(_Span(key, start, end))
        offset += len(line)
    else:
        raise KctxError("malformed", "document file frontmatter never closes")
    headings: list[tuple[str, int, int]] = []
    names = set()
    for relative, line in unfenced_lines(text[body_start:]):
        match = re.match(r"^##\s+(.+?)\s*#*\s*$", line.rstrip("\r\n"))
        if match:
            name = match[1].strip()
            if name in names:
                raise KctxError("malformed", f"duplicate section heading {name!r}")
            names.add(name)
            start = body_start + relative
            headings.append((name, start, start + len(line)))
    sections = tuple(
        _Span(name, end, headings[i + 1][1] if i + 1 < len(headings) else len(text))
        for i, (name, _, end) in enumerate(headings)
    )
    document = MarkdownDocument(text, tuple(fields), sections, frontmatter_end)
    for key in required_keys:
        if not document.frontmatter.get(key):
            raise KctxError("malformed", f"missing required frontmatter key {key!r}")
    for name in required_sections:
        if name not in document.sections:
            raise KctxError("malformed", f"missing required section {name!r}")
    return document


def read_document(
    path: Path, *, required_keys: tuple[str, ...] = (), required_sections: tuple[str, ...] = ()
) -> MarkdownDocument:
    return parse_document(
        path.read_bytes().decode("utf-8"),
        required_keys=required_keys,
        required_sections=required_sections,
    )


def render_document(
    frontmatter: Mapping[str, str | None], sections: Mapping[str, str], *, title: str = ""
) -> MarkdownDocument:
    lines = ["---", *(f"{key}: {value or ''}" for key, value in frontmatter.items()), "---"]
    if title:
        lines.extend(("", f"# {title}"))
    for name, content in sections.items():
        lines.extend(("", f"## {name}", "", content.strip()))
    return parse_document("\n".join((*lines, "")))
