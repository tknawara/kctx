"""KB-root resolution (handover §7.3).

The baseline's `find_root()` walked up from the *script's own location* to
any `.git` — correct when kctx lived inside the KB repo, wrong for this
standalone code repo (it would locate the code checkout, not the user's
knowledge workspace). The precedence here is the one the handover mandates:

1. an explicit `--root` argument (passed in by the CLI dispatcher),
2. `$KCTX_ROOT`,
3. a documented installed configuration (`$XDG_CONFIG_HOME/kctx/root` or
   `~/.config/kctx/root`, holding a path),
4. a **recognized KB marker** discovered from the caller's working
   directory: the nearest ancestor containing `inventory/assets/` — the
   corpus's own canonical directory, not a generic marker any Git repo
   would trip.

Never any arbitrary Git repository. Every resolution is absolute; an
explicit root that doesn't exist is refused immediately.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from errors import KctxError

MARKER = Path("inventory") / "assets"


def _from_config() -> Optional[Path]:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    cfg = Path(base) / "kctx" / "root"
    if cfg.is_file():
        text = cfg.read_text(encoding="utf-8").strip()
        if text:
            return Path(text).expanduser()
    return None


def _from_marker(start: Optional[Path] = None) -> Optional[Path]:
    here = (start or Path.cwd()).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / MARKER).is_dir():
            return candidate
    return None


def resolve_root(
    root_arg: Optional[str] = None,
    *,
    env: Optional[dict] = None,
    cwd: Optional[Path] = None,
) -> Path:
    """Resolve the KB root with the documented precedence. `env`/`cwd` are
    injectable for tests; production passes nothing (real environ/cwd)."""
    env = dict(os.environ) if env is None else env
    if root_arg:
        p = Path(root_arg).expanduser()
        if not p.is_dir():
            raise KctxError(
                "not-found", f"--root {root_arg!r} is not an existing directory"
            )
        return p.resolve()
    env_root = env.get("KCTX_ROOT")
    if env_root:
        return Path(env_root).resolve()
    configured = _from_config()
    if configured is not None:
        if not configured.is_dir():
            raise KctxError(
                "not-found",
                f"configured kctx root {str(configured)!r} does not exist",
            )
        return configured.resolve()
    marked = _from_marker(cwd)
    if marked is not None:
        return marked
    raise KctxError(
        "not-found",
        "could not locate a knowledge workspace: pass --root, set KCTX_ROOT, "
        "configure ~/.config/kctx/root, or run from inside a workspace "
        "(identified by inventory/assets/, not by any Git repo)",
    )
