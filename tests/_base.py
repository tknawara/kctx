"""Isolated knowledge workspaces and config files for CLI/adapter fixtures."""

import contextlib
import json
import os
import stat
import subprocess
import sys

import tempfile
import unittest
from pathlib import Path


_KCTX_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _KCTX_DIR not in sys.path:
    sys.path.insert(0, _KCTX_DIR)
# src must precede the repo root on sys.path: the root kctx.py entry script
# otherwise shadows the kctx package (load-bearing order; see test files).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Both ``_base`` and ``tests._base`` import this one state owner.
from tests import _config_state
from kctx.config import KEYS, write_config

_CFG_VALUES = _config_state.values
_CFG_FILE = _config_state.file


def set_config(**keys: str | int) -> Path:
    """Merge keys into the session config and rewrite the file."""
    bad = sorted(set(keys) - set(KEYS))
    if bad:
        raise AssertionError(f"unknown config keys {bad}")
    _CFG_VALUES.update(keys)
    write_config(_CFG_FILE, **_CFG_VALUES)
    return _CFG_FILE


def clear_config(*keys: str) -> None:
    """Remove keys (or all when none given) from the session config."""
    if keys:
        for k in keys:
            _CFG_VALUES.pop(k, None)
    else:
        _CFG_VALUES.clear()
    write_config(_CFG_FILE, **_CFG_VALUES)


class KctxTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self._prior_cfg = dict(_CFG_VALUES)
        set_config(root=str(self.root))

    def tearDown(self):
        clear_config()
        _CFG_VALUES.update(self._prior_cfg)
        set_config()
        self._tmpdir.cleanup()

    def set_config(self, **keys: str | int) -> Path:
        return set_config(**keys)


    def make_git_repo(self, name: str = "repo") -> Path:
        """Create a synthetic git repo with one committed file, for Q10/Q17 fixtures."""
        repo = self.root / f"_fixture-{name}"
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "kctx-test@example.invalid")
        _git(repo, "config", "user.name", "kctx tests")
        (repo / "tracked.txt").write_text(
            "synthetic fixture content\n", encoding="utf-8"
        )
        _git(repo, "add", "tracked.txt")
        _git(repo, "commit", "-q", "-m", "synthetic initial commit")
        return repo

    @contextlib.contextmanager
    def cache_backed_repo(self, org: str = "acme", repo: str = "widget"):
        """Exercise built-in citation acquisition against a real local Git remote."""
        remotes_dir = self.root / "_fixture-remotes"
        remote = remotes_dir / org / repo
        remote.mkdir(parents=True)
        _git(remote, "init", "-q")
        _git(remote, "config", "user.email", "kctx-test@example.invalid")
        _git(remote, "config", "user.name", "kctx tests")
        _git(remote, "checkout", "-q", "-b", "main")
        saved_cfg = dict(_CFG_VALUES)
        set_config(
            git_url_template=str(remotes_dir) + "/{org}/{repo}",
            cache_dir=str(self.root / "_fixture-cache"),
            fetch_interval_seconds=0,
        )
        try:
            yield remote
        finally:
            clear_config()
            _CFG_VALUES.update(saved_cfg)
            set_config()

    def commit_file(
        self, repo: Path, filename: str, content: str, message: str = "update"
    ) -> str:
        path = repo / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        _git(repo, "add", filename)
        _git(repo, "commit", "-q", "-m", message)
        return _git_head(repo)

    def run_git(self, repo: Path, *args: str) -> None:
        _git(repo, *args)

    def rename_file(
        self, repo: Path, old: str, new: str, message: str = "rename"
    ) -> str:
        _git(repo, "mv", old, new)
        _git(repo, "commit", "-q", "-m", message)
        return _git_head(repo)

    def write_gh_stub(self, payloads: dict) -> str:
        """Fake the PR provider with deterministic responses indexed by PR number."""
        stub = self.root / "_fixture-gh-stub"
        lines = ["#!/usr/bin/env bash", "set -e", 'args="$*"', 'case "$args" in']
        for n, payload in payloads.items():
            lines.append(f'  *"pulls/{n}"*)')
            lines.append("    cat <<'EOF'")
            lines.append(json.dumps(payload))
            lines.append("EOF")
            lines.append("    ;;")
        lines.append("  *)")
        lines.append(
            "    echo 'gh stub: no stubbed response for' \"$args\" >&2; exit 1"
        )
        lines.append("    ;;")
        lines.append("esac")
        stub.write_text("\n".join(lines) + "\n", encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        set_config(gh_bin=str(stub))
        return str(stub)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _git_head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
