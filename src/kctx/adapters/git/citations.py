"""Bounded Git acquisition and exact object access for built-in citations.

Object retrieval is historical; resolving a default-branch head is deliberately
separate and only answers questions about the current repository state.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from kctx.config import Config
from kctx.errors import KctxError

ORG_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
GIT_NETWORK_TIMEOUT_S = 60


@dataclass(frozen=True, slots=True)
class ResolvedRepository:
    mode: Literal["local", "cache"]
    path: Path
    repo_field: str
    url_field: str | None


def run_git(
    args: Sequence[str],
    cwd: Path | None = None,
    timeout: float = 15,
    *,
    local_only: bool = False,
) -> subprocess.CompletedProcess[str]:
    # These operations inspect source; repository-configured programs must not
    # execute as a side effect of reading it. Replacement objects are likewise
    # inappropriate when retrieving the exact historical object named by a cite.
    command = [
        "git",
        "--no-replace-objects",
        "--literal-pathspecs",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
    ]
    if cwd is not None:
        command.extend(("-C", str(cwd)))
    if args and args[0] == "diff":
        command.extend(("diff", "--no-ext-diff", "--no-textconv", *args[1:]))
    else:
        command.extend(args)
    environment = None
    if local_only:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key
            not in {
                "GIT_DIR",
                "GIT_WORK_TREE",
                "GIT_INDEX_FILE",
                "GIT_COMMON_DIR",
                "GIT_OBJECT_DIRECTORY",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                "GIT_DIFF_OPTS",
            }
            and not key.startswith("GIT_CONFIG_")
        }
        environment.update(GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")
    try:
        if local_only:
            # Text mode's universal-newline conversion corrupts CR in NUL path
            # records. Keep local Git bytes lossless, including non-UTF8 names.
            raw = subprocess.run(command, capture_output=True, timeout=timeout, env=environment)
            return subprocess.CompletedProcess(
                raw.args,
                raw.returncode,
                raw.stdout.decode("utf-8", errors="surrogateescape"),
                raw.stderr.decode("utf-8", errors="surrogateescape"),
            )
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            env=environment,
        )
    except subprocess.TimeoutExpired as error:
        raise KctxError(
            "timeout", f"git {args[0] if args else ''} exceeded {timeout:g}s"
        ) from error
    except (OSError, UnicodeError) as error:
        raise KctxError("not-found", f"could not read Git result: {str(error)[:500]}") from error


def _git_failure(operation: str, result: subprocess.CompletedProcess[str]) -> KctxError:
    return KctxError("not-found", f"git {operation} failed: {result.stderr.strip()[:1000]}")


def git_rev_parse(repo_path: Path, rev: str) -> str | None:
    result = run_git(["rev-parse", "--verify", "-q", "--end-of-options", rev], cwd=repo_path)
    return result.stdout.strip() or None if result.returncode == 0 else None


def resolve_default_branch_rev(repo_path: Path) -> str:
    sha = git_rev_parse(repo_path, "origin/HEAD^{commit}")
    if sha:
        return sha
    result = run_git(["remote", "show", "origin"], cwd=repo_path, timeout=GIT_NETWORK_TIMEOUT_S)
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if line.strip().startswith("HEAD branch:"):
                branch = line.split(":", 1)[1].strip()
                if branch and branch != "(unknown)":
                    sha = git_rev_parse(repo_path, f"origin/{branch}^{{commit}}")
                    if sha:
                        return sha
    sha = git_rev_parse(repo_path, "HEAD^{commit}")
    if sha:
        return sha
    raise KctxError("not-found", f"could not resolve a default-branch HEAD for {repo_path}")


def validate_git_path(path: str) -> None:
    pure = PurePosixPath(path)
    if not path or path == "." or pure.is_absolute() or ".." in pure.parts or "\x00" in path:
        raise KctxError("malformed", f"{path!r} is not a repository-relative file path")


def git_blob_sha(repo_path: Path, rev: str, path: str) -> str | None:
    validate_git_path(path)
    commit = git_rev_parse(repo_path, f"{rev}^{{commit}}")
    if commit is None:
        raise KctxError("not-found", f"revision {rev!r} is unavailable in {repo_path}")
    canonical_path = str(PurePosixPath(path))
    listing = run_git(["ls-tree", "-z", "--full-tree", commit, "--", canonical_path], cwd=repo_path)
    if listing.returncode != 0:
        raise _git_failure("ls-tree", listing)
    sha: str | None = None
    for entry in listing.stdout.split("\x00"):
        if not entry:
            continue
        metadata, separator, entry_path = entry.partition("\t")
        parts = metadata.split()
        if not separator or len(parts) != 3:
            raise KctxError("malformed", "git ls-tree returned an invalid entry")
        if entry_path == canonical_path:
            if parts[1] != "blob":
                return None
            sha = parts[2]
            break
    if sha is None:
        return None
    kind = run_git(["cat-file", "-t", sha], cwd=repo_path)
    if kind.returncode != 0:
        raise _git_failure("cat-file", kind)
    return sha if kind.stdout.strip() == "blob" else None


def git_file_content(repo_path: Path, rev: str, path: str) -> str | None:
    """Read the exact named blob, without substituting current worktree bytes."""
    sha = git_blob_sha(repo_path, rev, path)
    if sha is None:
        return None
    result = run_git(["cat-file", "blob", sha], cwd=repo_path)
    if result.returncode != 0:
        raise _git_failure("cat-file", result)
    return result.stdout


def get_origin_url(repo_path: Path, *, local_only: bool = False) -> str | None:
    result = run_git(["remote", "get-url", "origin"], cwd=repo_path, local_only=local_only)
    return result.stdout.strip() or None if result.returncode == 0 else None


def _validate_repository(org: str, repo: str) -> None:
    if not ORG_REPO_RE.fullmatch(f"{org}/{repo}") or org in (".", "..") or repo in (".", ".."):
        raise KctxError("malformed", f"invalid org/repo: {org}/{repo}")


def get_cache_path(org: str, repo: str, *, config: Config | None = None) -> Path:
    _validate_repository(org, repo)
    settings = config if config is not None else Config.load()
    root = settings.cache_dir or Path.home() / ".cache" / "kctx"
    return root / "repos" / org / repo


def looks_like_git_repo(path: Path) -> bool:
    return path.is_dir() and ((path / ".git").exists() or (path / "HEAD").is_file())


def ensure_cache_clone(path: Path, org: str, repo: str, *, config: Config | None = None) -> None:
    _validate_repository(org, repo)
    settings = config if config is not None else Config.load()
    try:
        url = settings.git_url_template.format(org=org, repo=repo)
    except (KeyError, ValueError, IndexError) as error:
        raise KctxError("malformed", f"invalid git_url_template: {error}") from error
    try:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            result = run_git(
                ["clone", "--filter=blob:none", "--quiet", "--", url, str(path)],
                timeout=GIT_NETWORK_TIMEOUT_S,
            )
            if result.returncode != 0:
                raise _git_failure("clone", result)
            return
        if not looks_like_git_repo(path):
            raise KctxError("not-found", f"citation cache is not a Git repository: {path}")
        fetch_head = path / ".git" / "FETCH_HEAD"
        if (
            not fetch_head.exists()
            or time.time() - fetch_head.stat().st_mtime > settings.fetch_interval_seconds
        ):
            result = run_git(
                ["fetch", "--quiet", "origin"], cwd=path, timeout=GIT_NETWORK_TIMEOUT_S
            )
            if result.returncode != 0:
                raise _git_failure("fetch", result)
    except OSError as error:
        raise KctxError(
            "not-found", f"cannot access citation cache {path}: {str(error)[:500]}"
        ) from error


def repo_from_url(url: str) -> tuple[str, str] | None:
    match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", url)
    if match is None:
        return None
    org, repo = match.group(1), match.group(2)
    if not ORG_REPO_RE.fullmatch(f"{org}/{repo}") or org in (".", "..") or repo in (".", ".."):
        return None
    return org, repo


def resolve_repo_for_make(repo_arg: str, *, config: Config | None = None) -> ResolvedRepository:
    path = Path(repo_arg)
    if looks_like_git_repo(path):
        path = path.resolve()
        return ResolvedRepository("local", path, path.name, get_origin_url(path) or str(path))
    if ORG_REPO_RE.fullmatch(repo_arg):
        org, repo = repo_arg.split("/", 1)
        path = get_cache_path(org, repo, config=config)
        ensure_cache_clone(path, org, repo, config=config)
        return ResolvedRepository("cache", path, repo_arg, None)
    raise KctxError(
        "not-found", f"{repo_arg!r} is neither a local git checkout nor an org/repo spec"
    )


def resolve_repo_for_check(
    fields: Mapping[str, str], *, config: Config | None = None
) -> Path | None:
    repo = fields.get("repo")
    if not repo:
        return None
    try:
        if ORG_REPO_RE.fullmatch(repo):
            org, name = repo.split("/", 1)
            path = get_cache_path(org, name, config=config)
            ensure_cache_clone(path, org, name, config=config)
            return path
        url = fields.get("url")
        if url:
            path = Path(url.removeprefix("file://"))
            if looks_like_git_repo(path):
                return path
            parts = repo_from_url(url)
            if parts:
                org, name = parts
                path = get_cache_path(org, name, config=config)
                ensure_cache_clone(path, org, name, config=config)
                return path
        path = Path(repo)
        if looks_like_git_repo(path):
            return path
    except (KctxError, OSError):
        return None
    return None
