"""Two pinned local endpoints, with no acquisition or working-tree fallback."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from kctx.adapters.git.citations import get_origin_url, repo_from_url, run_git
from kctx.domain.diff import DiffFile, DiffHunk, LocalDiff
from kctx.errors import KctxError

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$")
_SHA = re.compile(r"[0-9a-fA-F]{4,64}\Z")


def _git(repo: Path, *args: str) -> str:
    result = run_git(args, cwd=repo, local_only=True)
    if result.returncode:
        raise KctxError("not-found", f"git {args[0]} failed: {result.stderr.strip()[:1000]}")
    return result.stdout


def _remote_identity(value: str, *, locator: bool = True) -> tuple[str, str] | None:
    """Normalize transport without dropping the remote host identity."""
    if "://" in value:
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"ssh", "git", "https", "http"}
                or not parsed.hostname
                or parsed.query
                or parsed.fragment
            ):
                return None
            host = parsed.hostname.lower()
            if parsed.port is not None:
                host += f":{parsed.port}"
            path = parsed.path.strip("/")
        except ValueError:
            return None
    elif locator and re.fullmatch(r"(?:[A-Za-z0-9-]+\.)+[A-Za-z0-9-]+(?::\d+)?/[^?#]+", value):
        host, _, path = value.partition("/")
        host, path = host.lower(), path.strip("/")
    else:
        match = re.fullmatch(r"(?:[^/@:]+@)?([^/:]+):(.+)", value)
        if match is None:
            return None
        host, path = match.group(1).lower(), match.group(2).strip("/")
    return host, path.removesuffix(".git")


def repository_matches(value: str, diff: LocalDiff) -> bool:
    """Match a complete identity, never a checkout basename or URL substring."""
    if not value:
        return False
    if value in diff.identities:
        return True
    try:
        remote = _remote_identity(value)
        if remote is not None:
            return any(_remote_identity(identity) == remote for identity in diff.identities)
        if value.startswith("file://"):
            parsed = urlsplit(value)
            if parsed.netloc not in {"", "localhost"}:
                return False
            local = Path(unquote(parsed.path))
        elif Path(value).is_absolute() or value.startswith(("./", "../", "~/")):
            local = Path(value).expanduser()
        else:
            return False
        return local.resolve() == diff.repo_path
    except (OSError, ValueError, RuntimeError):
        return False


def resolve_local_pin(repo: Path, revision: str) -> str | None:
    """Resolve only authored SHA pins, including uniquely abbreviated object IDs."""
    if _SHA.fullmatch(revision) is None:
        return None
    result = run_git(
        ["rev-parse", "--verify", "-q", "--end-of-options", f"{revision}^{{commit}}"],
        cwd=repo,
        local_only=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _paths(raw: str) -> list[tuple[str, str | None, str | None]]:
    if not raw:
        return []
    records = raw.split("\x00")
    if records.pop() != "":
        raise KctxError("malformed", "git diff returned unterminated path records")
    files: list[tuple[str, str | None, str | None]] = []
    index = 0
    while index < len(records):
        status = records[index]
        if re.fullmatch(r"(?:[ADMTUXB]|[RC]\d+)", status) is None:
            raise KctxError("malformed", "git diff returned an invalid change status")
        count = 2 if status[0] in "RC" else 1
        if index + count >= len(records):
            raise KctxError("malformed", "git diff returned incomplete path records")
        paths = records[index + 1 : index + count + 1]
        if not all(paths):
            raise KctxError("malformed", "git diff returned an empty path")
        try:
            for path in paths:
                path.encode("utf-8")
        except UnicodeError as error:
            raise KctxError(
                "malformed", "Git path is not UTF-8; cannot represent exact identity"
            ) from error
        old = None if status == "A" else paths[0]
        new = None if status == "D" else paths[-1]
        files.append((status[0], old, new))
        index += count + 1
    return files


def _patches(raw: str, statuses: tuple[str, ...]) -> list[tuple[tuple[DiffHunk, ...], bool]]:
    patches: list[tuple[tuple[DiffHunk, ...], bool]] = []
    hunks: list[DiffHunk] = []
    binary = False
    started = False
    header = ""
    deleted = False
    for line in raw.split("\n"):
        if line.startswith("diff --git "):
            # Git renders a type change as a deletion and addition with the
            # same header, although its NUL name-status record is one T entry.
            if (
                started
                and deleted
                and line == header
                and len(patches) < len(statuses)
                and statuses[len(patches)] == "T"
            ):
                deleted = False
                continue
            if started:
                patches.append((tuple(hunks), binary))
            started, hunks, binary = True, [], False
            header, deleted = line, False
        elif line.startswith("deleted file mode "):
            deleted = True
        elif line.startswith("@@"):
            match = _HUNK.fullmatch(line)
            if not started or match is None:
                raise KctxError("malformed", "git diff returned an invalid hunk header")
            old_start, old_count, new_start, new_count = match.groups()
            hunk = DiffHunk(
                int(old_start),
                int(old_count) if old_count is not None else 1,
                int(new_start),
                int(new_count) if new_count is not None else 1,
            )
            if (hunk.old_count and not hunk.old_start) or (hunk.new_count and not hunk.new_start):
                raise KctxError("malformed", "git diff returned a zero-based line interval")
            hunks.append(hunk)
        elif line.startswith("Binary files ") or line == "GIT binary patch":
            binary = True
    if started:
        patches.append((tuple(hunks), binary))
    return patches


def read_local_diff(diff: str, repo: Path | None = None) -> LocalDiff:
    """Read exactly base..head; every Git operation is local and helper-free."""
    if diff.count("..") != 1 or "..." in diff:
        raise KctxError("malformed", "diff must be a nonempty base..head range (not triple-dot)")
    base_ref, head_ref = diff.split("..")
    if not base_ref.strip() or not head_ref.strip():
        raise KctxError("malformed", "diff requires both base and head")
    selected = (repo if repo is not None else Path.cwd()).expanduser().resolve()
    root = Path(_git(selected, "rev-parse", "--show-toplevel").removesuffix("\n")).resolve()
    # Resolve both user-supplied revisions once; all subsequent reads use full IDs.
    base, head = (
        _git(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").strip()
        for ref in (base_ref, head_ref)
    )
    options = (
        "--no-color",
        "--no-relative",
        "--no-renames",
        "--find-renames=50%",
        "-l0",
        "--ignore-submodules=none",
        "--submodule=short",
        "--diff-algorithm=myers",
        "--no-indent-heuristic",
        "--unified=0",
        "--inter-hunk-context=0",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        "-O/dev/null",
    )
    paths = _paths(_git(root, "diff", *options, "--name-status", "-z", base, head, "--"))
    patches = _patches(
        _git(root, "diff", *options, "--patch", base, head, "--"),
        tuple(status for status, _, _ in paths),
    )
    if len(paths) != len(patches):
        raise KctxError("malformed", "git diff path and patch records disagree")
    files = tuple(
        DiffFile(old, new, status, hunks, binary)
        for (status, old, new), (hunks, binary) in zip(paths, patches, strict=True)
    )
    origin = get_origin_url(root, local_only=True)
    remote_identity = _remote_identity(origin, locator=False) if origin else None
    remote = repo_from_url(origin) if origin and remote_identity is not None else None
    canonical = "/".join(remote) if remote else None
    repository = (
        canonical
        if canonical and remote_identity and remote_identity[1] == canonical
        else str(root)
    )
    if origin and remote_identity is None and ":" not in origin:
        # A relative local origin is not a globally meaningful basename.
        origin = str((root / Path(origin).expanduser()).resolve())
    identities = tuple(dict.fromkeys(value for value in (repository, origin, str(root)) if value))
    try:
        for identity in identities:
            identity.encode("utf-8")
    except UnicodeError as error:
        raise KctxError("malformed", "repository identity is not UTF-8") from error
    return LocalDiff(root, repository, identities, base, head, files)
