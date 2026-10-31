"""Human-only Rich results and diagnostics; machine replies bypass this module."""

import json
from collections.abc import Mapping
from typing import TypeGuard, cast

from rich import box
from rich.console import Console, Group, RenderableType
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from kctx.cli.result import Reply
from kctx.errors import Diagnostic, DiagnosticLabel
from kctx.presentation import console, literal


def _is_mapping(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _is_items(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TypeError("expected an encoded object")
    return cast(Mapping[str, object], value)


def _items(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("expected an encoded array")
    return cast(list[object], value)


def _scalar(value: object) -> Text:
    if value is None:
        return Text("—", style="dim")
    if isinstance(value, bool):
        return Text("true" if value else "false", style="cyan")
    text = str(value)
    style = ""
    if text in {"pass", "passed", "fresh", "accepted", "applied", "verified", "ok", "synced"}:
        style = "green"
    elif text in {
        "unknown",
        "incomplete",
        "blocked",
        "stale",
        "expired",
        "unverifiable",
        "partial",
        "both",
    }:
        style = "yellow"
    elif text in {"fail", "failed", "error", "rejected", "gone"}:
        style = "red"
    return literal(text, style=style)


def _cell(value: object) -> Text:
    if isinstance(value, (dict, list, tuple)):
        return literal(json.dumps(value, ensure_ascii=False, allow_nan=False))
    return _scalar(value)


def _table(rows: list[Mapping[str, object]], columns: list[str] | None = None) -> Table:
    keys = (
        columns
        if columns is not None
        else list(dict.fromkeys(key for row in rows for key in row if key != "warnings"))
    )
    table = Table(box=box.SIMPLE, show_edge=False, padding=(0, 1), header_style="bold cyan")
    for key in keys:
        table.add_column(literal(key.replace("_", " ").upper()))
    for row in rows:
        table.add_row(*(_cell(row.get(key)) for key in keys))
    return table


def _render(value: object) -> RenderableType:
    if _is_mapping(value):
        elements: list[RenderableType] = []
        for key, item in _mapping(value).items():
            if key == "warnings":
                continue
            label = literal(key.replace("_", " "), style="bold")
            if (_is_mapping(item) or _is_items(item)) and item:
                elements.extend((label, Padding(_render(item), (0, 0, 0, 2))))
            else:
                label.append(": ")
                label.append(_cell(item))
                elements.append(label)
        return Group(*elements) if elements else Text("(none)", style="dim")
    if _is_items(value):
        values = _items(value)
        if not values:
            return Text("(none)", style="dim")
        if all(_is_mapping(item) for item in values):
            rows = [_mapping(item) for item in values]
            keys = {key for row in rows for key in row if key != "warnings"}
            if len(keys) <= 6:
                return _table(rows)
            return Group(*(Padding(_render(row), (0, 0, 1, 0)) for row in rows))
        return Group(*(_render(item) for item in values))
    return _scalar(value)


def render_diagnostic(diagnostic: Diagnostic, *, color: bool | None = None) -> None:
    output = console(stderr=True, color=color)
    style = "bold red" if diagnostic.severity == "error" else "bold yellow"
    line = Text(f"{diagnostic.severity}[{diagnostic.code}]: ", style=style)
    line.append(literal(diagnostic.message))
    output.print(line)
    for label in diagnostic.labels:
        output.print(Text("  --> ", style="cyan") + literal(label.location))
        if label.note:
            output.print(Text("   = ", style="dim") + literal(label.note))
    if diagnostic.help:
        output.print(Text(" help: ", style="bold cyan") + literal(diagnostic.help))


def _warnings(value: object, *, color: bool | None) -> None:
    if _is_mapping(value):
        record = _mapping(value)
        warnings = record.get("warnings")
        if _is_items(warnings):
            for warning in _items(warnings):
                labels: tuple[DiagnosticLabel, ...] = ()
                if _is_mapping(warning):
                    fields = _mapping(warning)
                    message = str(
                        fields.get("message", fields.get("text", fields.get("reason", warning)))
                    )
                    if fields.get("file"):
                        location = str(fields["file"])
                        if fields.get("line_no") is not None:
                            location += f":{fields['line_no']}"
                        labels = (DiagnosticLabel(location),)
                else:
                    message = str(warning)
                render_diagnostic(Diagnostic("W101", "warning", message, labels), color=color)
        for key, item in record.items():
            if key != "warnings":
                _warnings(item, color=color)
    elif _is_items(value):
        for item in _items(value):
            _warnings(item, color=color)


def _drain(output: Console, result: Mapping[str, object]) -> None:
    touched = _items(result.get("touched_files", []))
    output.print(Text(f"Updated {len(touched)} file(s)", style="bold"))
    for raw_file in touched:
        file = _mapping(raw_file)
        for raw_change in _items(file["changes"]):
            change = _mapping(raw_change)
            output.print(literal(f"{file['file']}:{change['line_no']}", style="cyan"))
            output.print(Text("  - ", style="red") + literal(change["before"]))
            output.print(Text("  + ", style="green") + literal(change["after"]))
    output.print(
        _render(
            {
                key: value
                for key, value in result.items()
                if key not in {"touched_files", "warnings"}
            }
        )
    )


def render_text(reply: Reply, *, color: bool | None = None) -> None:
    output = console(color=color)
    result = reply.payload
    if reply.presentation == "cite-make":
        output.print(literal(_mapping(result)["line"]), soft_wrap=True)
    elif reply.presentation == "cite-render":
        for value in _items(_mapping(result)["rendered"]):
            output.print(literal(value, multiline=True), soft_wrap=True)
    elif reply.presentation == "proposal-list" and _is_items(result) and result:
        output.print(
            _table(
                [_mapping(row) for row in _items(result)],
                ["status", "created", "type", "origin", "id"],
            )
        )
    elif reply.presentation == "proposal-single":
        proposal = _mapping(result)
        output.print(_render({"id": proposal.get("id"), "path": reply.path}))
        for missing in _items(proposal.get("missing", [])):
            output.print(Text("Missing for review: ", style="yellow") + literal(missing))
    elif reply.presentation == "drain":
        _drain(output, _mapping(result))
    elif reply.presentation == "logs":
        for raw_event in _items(result):
            event = _mapping(raw_event)
            line = literal(event.get("timestamp", ""), style="dim")
            level = str(event.get("level", "info"))
            line.append(" ")
            line.append(
                literal(
                    level.upper(),
                    style={"error": "red", "warning": "yellow", "debug": "dim"}.get(level, "cyan"),
                )
            )
            line.append(" ")
            line.append(literal(event.get("event", ""), style="bold"))
            for key, value in event.items():
                if key not in {"timestamp", "level", "event", "run_id", "logger"}:
                    line.append(" ")
                    line.append(literal(f"{key}=", style="dim"))
                    line.append(_cell(value))
            output.print(line, soft_wrap=True)
        if not result:
            output.print(Text("(no events)", style="dim"))
    else:
        output.print(_render(result))
    _warnings(result, color=color)
