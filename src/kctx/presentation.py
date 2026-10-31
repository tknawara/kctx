"""Literal terminal text and stream-local color policy; never used for JSON."""

import os
import sys
import unicodedata
from typing import TextIO

from rich.console import Console
from rich.text import Text


def terminal_text(value: object, *, multiline: bool = False) -> str:
    text = str(value)
    return "".join(
        character.encode("unicode_escape").decode("ascii")
        if (
            unicodedata.category(character) in {"Cc", "Cf", "Cs"}
            and not (multiline and character == "\n")
        )
        else character
        for character in text
    )


def literal(value: object, *, style: str = "", multiline: bool = False) -> Text:
    return Text(terminal_text(value, multiline=multiline), style=style)


def color_enabled(stream: TextIO, choice: bool | None = None) -> bool:
    if choice is not None:
        return choice
    return bool(
        stream.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"
    )


def console(*, stderr: bool = False, color: bool | None = None) -> Console:
    stream = sys.stderr if stderr else sys.stdout
    enabled = color_enabled(stream, color)
    return Console(
        file=stream, force_terminal=enabled, no_color=not enabled, markup=False, highlight=False
    )
