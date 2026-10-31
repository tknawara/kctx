"""Invocation-local options shared by native Click command families."""

from dataclasses import dataclass, field
from pathlib import Path

from kctx.adapters.files.roots import find_root


@dataclass
class CliState:
    as_json: bool = False
    verbose: bool = False
    color: bool | None = None
    protocol_mode: bool = False
    _root: Path | None = field(default=None, init=False, repr=False)

    _logging_started: bool = field(default=False, init=False, repr=False)

    def start_logging(self, *, machine: bool = False) -> None:
        if not self._logging_started:
            from kctx.observability import init_logging

            init_logging(verbose=self.verbose, machine=machine or self.as_json, color=self.color)
            self._logging_started = True

    @property
    def root(self) -> Path:
        if self._root is None:
            self._root = find_root()
        return self._root
