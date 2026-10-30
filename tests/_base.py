"""Shared test scaffolding: puts tools/kctx on sys.path and gives each test
its own throwaway KCTX_ROOT, so tests never touch the real knowledge
workspace and run with no network access.
"""

import contextlib
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional

_KCTX_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _KCTX_DIR not in sys.path:
    sys.path.insert(0, _KCTX_DIR)

# The deployed ~/.claude/skills/grounding/cite is whatever a session last
# redeployed and can lag the dotfiles checkout (e.g. missing `stale`/`--mark`
# until a redeploy picks up Part 1 of the admit proposal). Tests that need
# real cite.py behavior (not a stub) pin CITE_BIN at the checkout instead of
# trusting the deploy to be current.
DOTFILES_CITE_BIN = (
    Path.home() / "workspace" / "dotfiles" / ".claude" / "skills" / "grounding" / "cite"
)


def dotfiles_cite_available() -> bool:
    return DOTFILES_CITE_BIN.is_file()


@contextlib.contextmanager
def use_dotfiles_cite():
    saved = os.environ.get("CITE_BIN")
    os.environ["CITE_BIN"] = str(DOTFILES_CITE_BIN)
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("CITE_BIN", None)
        else:
            os.environ["CITE_BIN"] = saved


@contextlib.contextmanager
def no_cite_available():
    """Point HOME at an empty temp dir and unset CITE_BIN/CLAUDE_CONFIG_DIR,
    so locate_cite_bin() genuinely finds nothing -- including the laptop's
    own dotfiles checkout, which would otherwise satisfy the last fallback
    and defeat the 'missing script' scenario this is meant to test."""
    keys = ("CITE_BIN", "CLAUDE_CONFIG_DIR", "HOME")
    saved = {k: os.environ.get(k) for k in keys}
    tmp_home = tempfile.mkdtemp()
    os.environ.pop("CITE_BIN", None)
    os.environ.pop("CLAUDE_CONFIG_DIR", None)
    os.environ["HOME"] = tmp_home
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp_home, ignore_errors=True)


class KctxTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self._old_kctx_root = os.environ.get("KCTX_ROOT")
        os.environ["KCTX_ROOT"] = str(self.root)

    def tearDown(self):
        if self._old_kctx_root is None:
            os.environ.pop("KCTX_ROOT", None)
        else:
            os.environ["KCTX_ROOT"] = self._old_kctx_root
        self._tmpdir.cleanup()

    def write_cite_stub(
        self, payload: dict, exit_code: int = 0, argv_log: Optional[Path] = None
    ) -> str:
        """Fake the `cite` script for nav.py's run_cite_check/run_cite_stale:
        a tiny shell wrapper that prints a canned `cite --json <subcommand>`
        payload regardless of its args, so nav/ktlo tests never touch the
        real grounding skill or the network. Returns the stub path; point
        CITE_BIN at it. Pass `argv_log` to additionally append each
        invocation's `"$*"` to that file, for tests asserting which flags
        (`--touch`, `--mark`, `--offline`, ...) nav.py actually passed."""
        stub = self.root / "_fixture-cite-stub"
        lines = ["#!/usr/bin/env bash"]
        if argv_log is not None:
            lines.append(f"printf '%s\\n' \"$*\" >> {shlex.quote(str(argv_log))}")
        lines.append("cat <<'EOF'")
        lines.append(json.dumps(payload))
        lines.append("EOF")
        lines.append(f"exit {exit_code}")
        stub.write_text("\n".join(lines) + "\n", encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        return str(stub)

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
        """Point admit's cache-clone plumbing (reused from the grounding cite
        module) at a throwaway local 'remote' instead of bbgithub, via
        KCTX_GIT_URL_TEMPLATE/KCTX_CACHE -- so admit tests exercise real git
        diff/blob logic against a local fixture repo, no network involved.
        Yields the remote repo path; commit to it with commit_file/rename_file
        below. CITE_FETCH_INTERVAL_MIN=0 makes every ensure_cache_clone call
        refetch, so a later commit to the remote is always picked up."""
        remotes_dir = self.root / "_fixture-remotes"
        remote = remotes_dir / org / repo
        remote.mkdir(parents=True)
        _git(remote, "init", "-q")
        _git(remote, "config", "user.email", "kctx-test@example.invalid")
        _git(remote, "config", "user.name", "kctx tests")
        _git(remote, "checkout", "-q", "-b", "main")
        keys = (
            "KCTX_GIT_URL_TEMPLATE",
            "KCTX_CACHE",
            "CITE_FETCH_INTERVAL_MIN",
            "CITE_BIN",
        )
        saved = {k: os.environ.get(k) for k in keys}
        os.environ["KCTX_GIT_URL_TEMPLATE"] = str(remotes_dir) + "/{org}/{repo}"
        os.environ["KCTX_CACHE"] = str(self.root / "_fixture-cache")
        os.environ["CITE_FETCH_INTERVAL_MIN"] = "0"
        os.environ["CITE_BIN"] = str(DOTFILES_CITE_BIN)
        try:
            yield remote
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

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
        """Fake `gh` for admit.fetch_pr: `payloads` maps a PR number (str) to
        the JSON object `gh api repos/.../pulls/<n>` would return. Returns the
        stub path; point KCTX_GH at it. A PR number with no stubbed response
        makes the stub fail loudly rather than return a plausible-looking
        default."""
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
