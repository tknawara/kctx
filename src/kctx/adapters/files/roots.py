"""Resolve a KB from the single config file or its own workspace marker."""

from pathlib import Path

from kctx.config import Config
from kctx.errors import KctxError

MARKER = Path("inventory") / "assets"


def find_root() -> Path:
    config = Config.load()
    if config.root is not None:
        if not config.root.is_dir():
            raise KctxError(
                "not-found",
                f"config root {str(config.root)!r} (from {str(config.source)!r}) does not exist",
            )
        return config.root.resolve()
    cwd = Path.cwd()
    for candidate in (cwd, *cwd.parents):
        if (candidate / MARKER).is_dir():
            return candidate
    raise KctxError(
        "not-found",
        'could not locate a knowledge workspace: write a config.toml (root = "/path/to/kb") '
        "or run from inside the workspace (identified by inventory/assets/, not by any Git repo)",
    )
