"""kctx configuration: one `config.toml`, no layering.

The agent (or human) driving kctx writes a config file and starts the tool —
that's the whole model. There is exactly one way to point kctx at anything:

- **Where the config lives**: ``$KCTX_CONFIG`` (a path to the file — the knob
  tests and containers use) else ``$XDG_CONFIG_HOME/kctx/config.toml`` else
  ``~/.config/kctx/config.toml``. Nothing else.
- **What's in it** (all keys optional; absent = built-in discovery):

::

    root      = "/path/to/kb"          # the knowledge workspace
    cite_py   = "/path/to/cite.py"     # grounding-skill citation parser
    cite_bin  = "/path/to/cite"        # deployed cite script
    dolt_bin  = "/usr/bin/dolt"        # dolt CLI override
    graph_dir = "/path/to/kb-graph"    # shadow-graph home
    log_dir   = "/path/to/logs"        # structured-log home

Unknown keys are rejected (a typo must never silently mean "default").
Never credentials: kctx reads locations only.

Why a file and not env vars: the config is the *steady state* of a machine —
versionable, diffable, readable by any agent picking up the harness, and one
artifact to write in a container. Env-per-setting was unportable sprawl (see
docs/kctx/config.md for the decision trace).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import sys as _sys
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parents[2]
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

from errors import KctxError  # noqa: E402

KEYS = ("root", "cite_py", "cite_bin", "dolt_bin", "graph_dir", "log_dir")


def config_path(env: Optional[dict] = None) -> Optional[Path]:
    """Where config.toml lives, if anywhere. ``$KCTX_CONFIG`` (a file path)
    wins; else the XDG location. A KCTX_CONFIG pointing at a missing file is
    an error, not a silent skip."""
    env = os.environ if env is None else env
    explicit = env.get("KCTX_CONFIG")
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_file():
            raise KctxError(
                "not-found", f"KCTX_CONFIG={explicit!r} does not point at a file"
            )
        return p
    base = env.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    candidate = Path(base) / "kctx" / "config.toml"
    return candidate if candidate.is_file() else None


@dataclass(frozen=True, slots=True)
class Config:
    """Loaded config values (None = not configured → built-in discovery)."""

    root: Optional[Path]
    cite_py: Optional[Path]
    cite_bin: Optional[Path]
    dolt_bin: Optional[Path]
    graph_dir: Optional[Path]
    log_dir: Optional[Path]
    source: Optional[Path]

    @classmethod
    def load(cls, env: Optional[dict] = None) -> "Config":
        env = os.environ if env is None else env
        path = config_path(env)
        if path is None:
            return cls(None, None, None, None, None, None, None)
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError) as e:
            raise KctxError("malformed", f"config {path}: {e}") from e
        unknown = sorted(set(data) - set(KEYS))
        if unknown:
            raise KctxError(
                "malformed",
                f"config {path}: unknown keys {unknown}; supported: {list(KEYS)}",
            )
        values: dict = {"source": path}
        for k in KEYS:
            v = data.get(k)
            if v is None:
                values[k] = None
            elif isinstance(v, str) and v.strip():
                values[k] = Path(v).expanduser()
            else:
                raise KctxError(
                    "malformed", f"config {path}: key {k!r} must be a path string"
                )
        return cls(**values)

    def get(self, key: str) -> Optional[Path]:
        """One setting, or None when unconfigured (caller discovers)."""
        if key not in KEYS:
            raise KctxError("malformed", f"unknown config key {key!r}")
        return getattr(self, key)

    def effective(self) -> dict:
        """The `doctor` surface: every setting and whether it came from the
        config file or from built-in discovery."""
        out: dict = {"config_file": str(self.source) if self.source else None}
        for k in KEYS:
            v = getattr(self, k)
            out[k] = (
                {"origin": "config", "value": str(v)}
                if v is not None
                else {"origin": "discovery", "value": None}
            )
        return out


def write_config(path: Path, **keys: str) -> Path:
    """Write a config file (tests, containers, and agents bootstrapping a
    harness). Only known keys; paths stored verbatim."""
    bad = sorted(set(keys) - set(KEYS))
    if bad:
        raise KctxError("malformed", f"unknown config keys {bad}; supported: {list(KEYS)}")
    lines = [f'{k} = "{v}"' for k, v in keys.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
