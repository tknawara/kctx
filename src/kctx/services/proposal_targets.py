"""Resolve authored landed references against actual retained file/Git objects.

A resolved target is source evidence for workflow eligibility, not authority to
publish knowledge. Remote Git sources use the existing configured citation
mirror transport; authored shell commands are never executed.
"""

import hashlib
import re
from pathlib import Path

from kctx.adapters.git.citations import (
    ORG_REPO_RE,
    git_rev_parse,
    looks_like_git_repo,
    repo_from_url,
    resolve_repo_for_make,
)
from kctx.domain.ids import SourceId, TargetRevision
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


def resolve_source(root: Path, source: SourceId) -> SourceId:
    """Canonicalize intended source identity without requiring an implementation."""
    value = source.val.strip()
    if not value or value.lower() in {"unknown", "unk"}:
        raise KctxError("incomplete", "target_source must name an explicit source")
    local = Path(value).expanduser()
    if not local.is_absolute():
        local = root / local
    if local.exists() or value.startswith(("/", "./", "../", "~")):
        return SourceId(str(local.resolve()))
    try:
        asset = resolve_asset(root, value)
    except KctxError as exc:
        if exc.category != "not-found":
            raise
    else:
        if asset.kind is not AssetKind.REPO or not asset.locator.strip():
            raise KctxError("malformed", "target_source asset must name a repository")
        value = asset.locator.strip()
        local = Path(value).expanduser()
        if not local.is_absolute():
            local = root / local
        if local.exists() or value.startswith(("/", "./", "../", "~")):
            return SourceId(str(local.resolve()))
    remote = repo_from_url(value)
    if remote is not None:
        return SourceId(f"{remote[0]}/{remote[1]}")
    if ORG_REPO_RE.fullmatch(value):
        return SourceId(value)
    # A relative intended local file/repository need not have been created yet.
    return SourceId(str(local.resolve()))


def source_of_target(revision: TargetRevision) -> SourceId:
    source, separator, _ = revision.val.rpartition("@")
    if not separator or not source:
        raise KctxError("malformed", "target revision must name source@revision")
    return SourceId(source)


def design_target(
    root: Path, source: SourceId | None, target: TargetRevision | None
) -> tuple[SourceId, TargetRevision | None]:
    resolved = resolve_target(root, target) if target is not None else None
    intended = resolve_source(root, source) if source is not None else None
    if resolved is not None:
        actual = source_of_target(resolved)
        if intended is not None and intended != actual:
            raise KctxError("conflict", "target revision source differs from target_source")
        intended = actual
    if intended is None:
        raise KctxError("incomplete", "proposal requires --target-source or --target-revision")
    return intended, resolved
