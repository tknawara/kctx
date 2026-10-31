"""Locates and loads the grounding skill's cite.py so the graph package
parses ⟦cite ...⟧ tokens with the one real parser instead of a reimplemented
copy, and reuses its repo-identity resolution (see identity.py).

Lookup order mirrors nav.locate_cite_bin()'s search for the `cite` script,
plus a config.toml cite_py override (see src/kctx/config.py):

  1. config.toml cite_py, if set -- points directly at a cite.py file.
  2. $CLAUDE_CONFIG_DIR/skills/grounding/cite.py (a Space's deployed skill).
  3. ~/.claude/skills/grounding/cite.py (the laptop's deployed skill).
  4. ~/workspace/dotfiles/.claude/skills/grounding/cite.py (a dev checkout,
     for working on kctx from the dotfiles repo itself without a deploy).
"""

import importlib.util
import os
import types
from pathlib import Path

from errors import KctxError


def locate_cite_py() -> Path:
    from kctx.config import Config

    cfg = Config.load()
    if cfg.cite_py is not None:
        if cfg.cite_py.is_file():
            return cfg.cite_py
        raise KctxError(
            "not-found",
            f"config cite_py {str(cfg.cite_py)!r} does not point at an existing file",
        )

    candidates = []
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        candidates.append(Path(config_dir) / "skills" / "grounding" / "cite.py")
    candidates.append(Path.home() / ".claude" / "skills" / "grounding" / "cite.py")
    candidates.append(
        Path.home()
        / "workspace"
        / "dotfiles"
        / ".claude"
        / "skills"
        / "grounding"
        / "cite.py"
    )
    for c in candidates:
        if c.is_file():
            return c

    tried = ", ".join(str(c) for c in candidates)
    raise KctxError(
        "not-found",
        "cite.py not found (tried: "
        f"{tried}); set KCTX_CITE_PY or deploy the grounding skill",
    )


_cached_module: types.ModuleType = None


def load_cite_module() -> types.ModuleType:
    """Import cite.py by file path (not via sys.path/package import -- the
    grounding skill is not installed as a package) and cache it for the
    process lifetime. KCTX_CITE_PY can point tests at a stub module."""
    global _cached_module
    if _cached_module is not None:
        return _cached_module
    path = locate_cite_py()
    spec = importlib.util.spec_from_file_location("kctx_graph_cite", path)
    if spec is None or spec.loader is None:
        raise KctxError("malformed", f"could not load cite.py spec from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _cached_module = module
    return module


def reset_cache() -> None:
    """Test-only: forces the next load_cite_module() call to re-resolve and
    re-import, so a test can point KCTX_CITE_PY at a different module."""
    global _cached_module
    _cached_module = None
