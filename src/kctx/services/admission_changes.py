"""Changed-path acquisition through the built-in shared Git cache."""

from pathlib import Path
from typing import NotRequired, TypedDict

from kctx.adapters.git.citations import git_rev_parse, run_git
from kctx.errors import KctxError


class ChangedPath(TypedDict):
    status: str
    path: NotRequired[str]
    old: NotRequired[str]
    new: NotRequired[str]


def diff_name_status(repo_path: Path, base: str, head: str) -> list[ChangedPath]:
    r = run_git(
        ["diff", "--name-status", "-M", f"{base}..{head}"],
        cwd=repo_path,
        timeout=60,
    )
    if r.returncode != 0:
        raise KctxError("not-found", f"git diff {base}..{head} failed: {r.stderr.strip()}")
    changes: list[ChangedPath] = []
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R") and len(parts) == 3:
            changes.append({"status": "R", "old": parts[1], "new": parts[2]})
        elif len(parts) == 2:
            changes.append({"status": status, "path": parts[1]})
    return changes


def changed_path_set(changes: list[ChangedPath]) -> set[str]:
    out: set[str] = set()
    for c in changes:
        if "path" in c:
            out.add(c["path"])
        if "old" in c:
            out.add(c["old"])
        if "new" in c:
            out.add(c["new"])
    return out


def resolve_since(repo_path: Path, since: str, head: str) -> str:
    sha = git_rev_parse(repo_path, since)
    if sha:
        return sha
    r = run_git(["rev-list", "-1", f"--before={since}", head], cwd=repo_path)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    raise KctxError(
        "malformed",
        f"--since {since!r} did not resolve to a revision or a date on {head}",
    )


def is_ancestor(repo_path: Path, maybe_ancestor: str, rev: str) -> bool:
    r = run_git(["merge-base", "--is-ancestor", maybe_ancestor, rev], cwd=repo_path)
    return r.returncode == 0
