"""Construct citations from exact committed bytes, never dirty worktree bytes."""

from __future__ import annotations

import hashlib

from kctx.adapters.git.citations import (
    git_blob_sha,
    git_file_content,
    git_rev_parse,
    resolve_default_branch_rev,
    resolve_repo_for_make,
    run_git,
    validate_git_path,
)
from kctx.citations.models import MadeCitation
from kctx.citations.syntax import format_cite, normalize_span, parse_range
from kctx.citations.time import iso_now_minute, parse_ttl_seconds
from kctx.config import Config
from kctx.errors import KctxError

CODE_FIELD_ORDER = (
    "kind",
    "repo",
    "rev",
    "path",
    "L",
    "blob",
    "span",
    "sym",
    "seen",
    "ttl",
    "url",
    "dirty",
    "sens",
    "redact",
)


def make_code(
    repo_arg: str,
    path: str,
    line_range: str,
    sym: str | None = None,
    rev: str | None = None,
    ttl: str = "14d",
    allow_dirty: bool = False,
    sens: str | None = None,
    redact: str | None = None,
    *,
    config: Config | None = None,
) -> MadeCitation:
    a, b = parse_range(line_range)
    validate_git_path(path)
    parse_ttl_seconds(ttl)
    info = resolve_repo_for_make(repo_arg, config=config)
    dirty_diff: str | None = None
    if info.mode == "local":
        bare = run_git(["rev-parse", "--is-bare-repository"], cwd=info.path)
        if bare.returncode != 0:
            raise KctxError("not-found", f"cannot inspect repository {info.path}")
        if bare.stdout.strip() != "true":
            diff = run_git(
                ["diff", "--no-ext-diff", "--no-textconv", "HEAD", "--", path], cwd=info.path
            )
            if diff.returncode != 0:
                raise KctxError("not-found", f"git diff failed: {diff.stderr.strip()[:1000]}")
            if diff.stdout.strip():
                if not allow_dirty:
                    raise KctxError(
                        "stale",
                        f"{path} has uncommitted changes in {info.path}; pass --allow-dirty",
                    )
                dirty_diff = diff.stdout
    full_rev = (
        git_rev_parse(info.path, f"{rev}^{{commit}}")
        if rev
        else resolve_default_branch_rev(info.path)
    )
    if not full_rev:
        raise KctxError(
            "not-found", f"revision {rev or 'default branch'!r} not found in {info.path}"
        )
    content = git_file_content(info.path, full_rev, path)
    blob = git_blob_sha(info.path, full_rev, path)
    if content is None or blob is None:
        raise KctxError("not-found", f"{path} not found at {full_rev} in {info.path}")
    lines = content.splitlines()
    if b > len(lines):
        raise KctxError(
            "malformed",
            f"line range {line_range} out of bounds ({path} has {len(lines)} lines at {full_rev})",
        )
    fields: dict[str, str] = {
        "kind": "code",
        "repo": info.repo_field,
        "rev": full_rev,
        "path": path,
        "L": f"{a}-{b}",
        "blob": blob,
        "span": normalize_span(lines[a - 1 : b]),
        "seen": iso_now_minute(),
        "ttl": ttl,
    }
    if sym:
        fields["sym"] = sym
    if info.url_field:
        fields["url"] = info.url_field
    if dirty_diff is not None:
        fields["dirty"] = hashlib.sha256(dirty_diff.encode("utf-8")).hexdigest()[:12]
    if sens:
        fields["sens"] = sens
    if redact:
        fields["redact"] = redact
    return MadeCitation(format_cite(fields, CODE_FIELD_ORDER), fields)
