"""Encoded command replies and explicit text presentation choices."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Reply:
    payload: object
    code: int = 0
    presentation: Literal[
        "default",
        "proposal-list",
        "proposal-single",
        "drain",
        "diff-impact",
        "graph",
        "cite-make",
        "cite-render",
        "logs",
    ] = "default"
    path: str = ""
