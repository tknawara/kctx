"""Resolve authored landed references against actual retained file/Git objects.

A resolved target is source evidence for workflow eligibility, not authority to
publish knowledge. Remote Git sources use the existing configured citation
mirror transport; authored shell commands are never executed.
"""

import hashlib
import re
from pathlib import Path

from kctx.adapters.git.citations import (
    git_rev_parse,
    looks_like_git_repo,
    repo_from_url,
    resolve_repo_for_make,
)
from kctx.domain.ids import TargetRevision
from kctx.domain.vocabulary import AssetKind
from kctx.errors import KctxError
from kctx.semantics.model import AuthoredLanded
from kctx.services.inventory import resolve_asset

_COMMIT = re.compile(r"[0-9a-f]{7,64}\Z")
_DIGEST = re.compile(r"sha256:([0-9a-f]{64})\Z")


def resolve_landed(root: Path, references: tuple[str, ...]) -> tuple[AuthoredLanded, ...]:
    resolved: list[AuthoredLanded] = []
    for reference in references:
        source, separator, revision = reference.rpartition("@")
        if not separator or not source:
            raise KctxError("malformed", f"landed reference {reference!r} must be source@revision")
        local = Path(source).expanduser()
        if not local.is_absolute():
            local = root / local
        digest = _DIGEST.fullmatch(revision)
        if digest:
            try:
                actual = hashlib.sha256(local.read_bytes()).hexdigest()
            except OSError as exc:
                raise KctxError(
                    "not-found", f"landed file {source!r} does not resolve: {exc}"
                ) from exc
            if actual != digest[1]:
                raise KctxError(
                    "conflict", f"landed file {source!r} does not match its retained digest"
                )
            resolved.append(
                AuthoredLanded(reference, TargetRevision(f"{local.resolve()}@sha256:{actual}"))
            )
            continue
        if not _COMMIT.fullmatch(revision):
            raise KctxError(
                "malformed",
                f"landed Git reference {reference!r} must name a commit object, not a movable ref",
            )
        locator = str(local) if looks_like_git_repo(local) else source
        if locator == source:
            try:
                asset = resolve_asset(root, source)
            except KctxError as exc:
                if exc.category != "not-found":
                    raise
            else:
                if asset.kind is not AssetKind.REPO:
                    raise KctxError(
                        "malformed", f"landed source {source!r} is not a repository asset"
                    )
                if not asset.locator.strip():
                    raise KctxError(
                        "incomplete", f"repository asset {source!r} has no source locator"
                    )
                candidate = Path(asset.locator).expanduser()
                if not candidate.is_absolute():
                    candidate = root / candidate
                remote = repo_from_url(asset.locator)
                locator = (
                    f"{remote[0]}/{remote[1]}"
                    if remote is not None and not looks_like_git_repo(candidate)
                    else str(candidate)
                )
        repository = resolve_repo_for_make(locator)
        actual_commit = git_rev_parse(repository.path, f"{revision}^{{commit}}")
        if actual_commit is None or not actual_commit.startswith(revision):
            raise KctxError("not-found", f"landed commit {reference!r} does not resolve exactly")
        canonical_source = (
            str(repository.path.resolve()) if repository.mode == "local" else repository.repo_field
        )
        resolved.append(
            AuthoredLanded(reference, TargetRevision(f"{canonical_source}@{actual_commit}"))
        )
    return tuple(resolved)


def resolve_target(root: Path, revision: TargetRevision) -> TargetRevision:
    """Decode a nominal target only at the source-reference I/O boundary."""
    return resolve_landed(root, (revision.val,))[0].target_revision
