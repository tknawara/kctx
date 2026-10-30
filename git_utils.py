"""Git introspection for observation auto-capture.

When an observation's source system is git and its locator is a local repo
path, kctx resolves the current HEAD revision and, if the worktree is dirty,
the sha256 of `git diff HEAD` — so a test or inspection run on a dirty
checkout is never silently attributed to the clean commit alone.
"""

import subprocess
from pathlib import Path
from typing import Optional, Tuple

from storage import sha256_bytes


def is_local_git_repo(locator: str) -> bool:
    try:
        p = Path(locator)
    except TypeError:
        return False
    return p.is_dir() and (p / ".git").exists()


def resolve_git_state(repo_path: str) -> Tuple[str, bool, Optional[str]]:
    """Return (revision, dirty, dirty_diff_sha256). The digest is None when clean."""
    repo_path = str(repo_path)
    revision = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "-C", repo_path, "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    dirty = bool(status.strip())
    digest = None
    if dirty:
        diff = subprocess.run(
            ["git", "-C", repo_path, "diff", "HEAD"],
            capture_output=True,
            check=True,
        ).stdout
        digest = sha256_bytes(diff)
    return revision, dirty, digest
