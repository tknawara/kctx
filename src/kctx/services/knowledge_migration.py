"""Accounted legacy ingestion: preserve authored bytes, never infer prose truth."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path, PurePosixPath

from kctx.adapters.files.knowledge import canonical, decode, digest
from kctx.adapters.git.citations import (
    get_cache_path,
    git_blob_sha,
    looks_like_git_repo,
    validate_git_path,
)
from kctx.citations.models import CitationKind
from kctx.citations.syntax import CITE_LINE_RE, is_illustrative, parse_cite_body
from kctx.codecs.documents import parse_document, unfenced_lines
from kctx.codecs.frontmatter import parse_frontmatter
from kctx.codecs.proposals import decode_proposal
from kctx.codecs.records import (
    decode_asset,
    decode_coverage,
    decode_observation,
    decode_relationship,
    decode_run_manifest,
    decode_run_receipt,
)
from kctx.domain.ids import ContentDigest, PlanId
from kctx.domain.json import JsonObject, text
from kctx.errors import KctxError


class Disposition(Enum):
    EXACT = "exact"
    UNIQUE = "uniquely_resolvable"
    AMBIGUOUS = "ambiguous"
    UNAVAILABLE = "unavailable"
    MALFORMED = "malformed"


@dataclass(frozen=True, slots=True)
class MigrationItem:
    path: str
    kind: str
    disposition: Disposition
    authored_id: str | None
    content: ContentDigest
    reason: str | None = None
    resolved: str | None = None
    offset: int | None = None

    def wire(self) -> JsonObject:
        return {
            "path": self.path,
            "kind": self.kind,
            "disposition": self.disposition.value,
            "authored_id": self.authored_id,
            "content": self.content.val,
            "reason": self.reason,
            "resolved": self.resolved,
            "offset": self.offset,
        }


@dataclass(frozen=True, slots=True)
class RetainedFile:
    path: str
    data: bytes


@dataclass(frozen=True, slots=True)
class LegacyImport:
    id: PlanId
    files: tuple[RetainedFile, ...]
    items: tuple[MigrationItem, ...]
    resolved_sources: tuple[RetainedFile, ...]

    def report(self) -> JsonObject:
        counts: JsonObject = {
            status.value: sum(item.disposition is status for item in self.items)
            for status in Disposition
        }
        return {
            "schema_version": 2,
            "migration": self.id.val,
            "counts": counts,
            "accepted": sum(
                item.disposition in (Disposition.EXACT, Disposition.UNIQUE) for item in self.items
            ),
            "quarantined": sum(
                item.disposition not in (Disposition.EXACT, Disposition.UNIQUE)
                for item in self.items
            ),
            "items": [item.wire() for item in self.items],
            "files": [
                {"path": item.path, "content": digest(item.data), "bytes": len(item.data)}
                for item in self.files
            ],
            "published": False,
            "historical_identity_inferred": False,
        }


def _record(value: JsonObject) -> tuple[str, str, tuple[str, ...]]:
    if {"id", "kind", "name"} <= value.keys():
        asset = decode_asset(value)
        return "asset", asset.id.val, tuple(dict.fromkeys((*asset.aliases, asset.name)))
    if {"id", "from", "to", "type"} <= value.keys():
        relationship = decode_relationship(value)
        return "relationship", relationship.id.val, ()
    if {"source", "id", "observed_at", "run"} <= value.keys():
        observation = decode_observation(value)
        return "observation", observation.id.val, ()
    if {"created", "project", "run_id", "task", "mode"} <= value.keys():
        manifest = decode_run_manifest(value)
        return "run", manifest.run_id.val, ()
    if {"run", "receipt", "checked_at", "readiness"} <= value.keys():
        decode_run_receipt(value)
        return "receipt", text(value["receipt"], "receipt"), ()
    if "entries" in value:
        decode_coverage(value)
        return "coverage", "", ()
    raise KctxError("malformed", "unsupported legacy JSON record schema")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)


def _repository(fields: dict[str, str], root: Path) -> Path | None:
    for raw in (fields.get("url", ""), fields.get("repo", "")):
        if not raw:
            continue
        candidate = Path(raw.removeprefix("file://"))
        if not candidate.is_absolute():
            candidate = root / candidate
        if looks_like_git_repo(candidate):
            return candidate
    name = fields.get("repo", "")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name):
        org, repository = name.split("/")
        candidate = get_cache_path(org, repository)
        if looks_like_git_repo(candidate):
            return candidate
    return None


def _citation(
    fields: dict[str, str],
    root: Path,
    identities: dict[str, list[str]],
    aliases: dict[str, list[str]],
) -> tuple[Disposition, str, str | None, bytes | None]:
    kind = CitationKind(fields.get("kind", ""))
    if kind in (CitationKind.CODE, CitationKind.COMMIT, CitationKind.GATE):
        revision = fields.get("rev", "")
        if "@" in revision:
            repository_name, revision = revision.rsplit("@", 1)
            fields = {**fields, "repo": fields.get("repo", repository_name)}
        if not re.fullmatch(r"[0-9a-fA-F]{4,64}", revision):
            return (
                Disposition.UNAVAILABLE,
                "citation has no immutable hexadecimal revision; HEAD is never substituted",
                None,
                None,
            )
        repository = _repository(fields, root)
        if repository is None:
            return (
                Disposition.UNAVAILABLE,
                "named source repository is not locally retained",
                None,
                None,
            )
        matches = _git(repository, "rev-parse", "--disambiguate=" + revision.lower())
        if matches.returncode:
            return Disposition.UNAVAILABLE, "revision lookup failed", None, None
        commits: list[str] = []
        for candidate in matches.stdout.decode().splitlines():
            kind_result = _git(repository, "cat-file", "-t", candidate)
            if kind_result.returncode == 0 and kind_result.stdout.strip() == b"commit":
                commits.append(candidate)
        if len(commits) > 1:
            return (
                Disposition.AMBIGUOUS,
                "short revision names multiple retained commits",
                None,
                None,
            )
        if not commits:
            return Disposition.UNAVAILABLE, "named historical commit is unavailable", None, None
        resolved = commits[0]
        status = Disposition.EXACT if revision.lower() == resolved else Disposition.UNIQUE
        path = fields.get("path")
        if path:
            validate_git_path(path)
            blob = git_blob_sha(repository, resolved, path)
            if blob is None:
                return (
                    Disposition.UNAVAILABLE,
                    "named historical blob is unavailable",
                    resolved,
                    None,
                )
            if fields.get("blob") and fields["blob"] != blob:
                return (
                    Disposition.MALFORMED,
                    "authored blob identity disagrees with exact revision/path",
                    resolved,
                    None,
                )
            result = _git(repository, "cat-file", "blob", blob)
            if result.returncode:
                return Disposition.UNAVAILABLE, "historical blob bytes unavailable", resolved, None
            return (
                status,
                "exact retained historical bytes",
                repository.resolve().as_uri() + "#" + resolved + ":" + path,
                result.stdout,
            )
        result = _git(repository, "cat-file", "commit", resolved)
        return (
            status,
            "exact retained commit object",
            repository.resolve().as_uri() + "#" + resolved,
            result.stdout if result.returncode == 0 else None,
        )
    identity = fields.get("id")
    if identity:
        candidates = identities.get(identity, [])
        if len(candidates) == 1:
            return Disposition.EXACT, "authored identity retained", candidates[0], None
        if len(candidates) > 1:
            return Disposition.AMBIGUOUS, "duplicate authored identity", None, None
        candidates = aliases.get(identity, [])
        if len(candidates) == 1:
            return (
                Disposition.UNIQUE,
                "unique alias resolves to retained authored identity",
                candidates[0],
                None,
            )
        if len(candidates) > 1:
            return Disposition.AMBIGUOUS, "alias names multiple authored identities", None, None
    return (
        Disposition.UNAVAILABLE,
        "citation source lacks a retained exact revision or uniquely resolvable record",
        None,
        None,
    )


def inspect_legacy(source: Path) -> LegacyImport:
    source = source.resolve()
    root = source if source.is_dir() else source.parent
    paths = (
        sorted(
            path
            for path in source.rglob("*")
            if path.is_file()
            and not any(
                part in {".git", ".dolt", ".venv", "__pycache__"}
                for part in path.relative_to(source).parts
            )
        )
        if source.is_dir()
        else [source]
    )
    files: list[RetainedFile] = []
    items: list[MigrationItem] = []
    identities: dict[str, list[str]] = {}
    aliases: dict[str, list[str]] = {}
    documents: list[RetainedFile] = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            data = str(path.readlink()).encode()
            files.append(RetainedFile(relative, data))
            items.append(
                MigrationItem(
                    relative,
                    "symlink",
                    Disposition.UNAVAILABLE,
                    None,
                    ContentDigest(digest(data)),
                    "symlink targets are not implicitly imported",
                )
            )
            continue
        raw = path.read_bytes()
        files.append(RetainedFile(relative, raw))
        content = ContentDigest(digest(raw))
        kind = "source"
        identity: str | None = None
        try:
            names: tuple[str, ...] = ()
            if path.suffix == ".json":
                kind, identity, names = _record(decode(raw))
            elif path.suffix.lower() in (".md", ".markdown"):
                kind = "document"
                text_value = raw.decode("utf-8")
                frontmatter = parse_frontmatter(text_value).entries
                identity = frontmatter.get("id")
                if text_value.startswith("---"):
                    document = parse_document(text_value)
                    if "/proposals/" in "/" + relative or (
                        frontmatter.get("kind") in ("proposal", "change", "investigation")
                        and "status" in frontmatter
                    ):
                        decode_proposal(document)
                else:
                    # Exercise the same duplicate-section parser while retaining
                    # the original frontmatter-free authored bytes unchanged.
                    parse_document("---\n---\n" + text_value)
                documents.append(RetainedFile(relative, raw))
            if identity:
                identities.setdefault(identity, []).append(relative)
            for alias in names:
                aliases.setdefault(alias, []).append(identity or relative)
            items.append(
                MigrationItem(
                    relative,
                    kind,
                    Disposition.EXACT,
                    identity,
                    content,
                    "exact imported bytes; no historical revision or truth inferred",
                )
            )
        except (KctxError, ValueError, UnicodeError) as exc:
            items.append(
                MigrationItem(relative, kind, Disposition.MALFORMED, identity, content, str(exc))
            )
    for index, item in enumerate(items):
        if item.authored_id and len(identities.get(item.authored_id, [])) > 1:
            items[index] = replace(
                item,
                disposition=Disposition.AMBIGUOUS,
                reason="duplicate authored identity across input files",
            )
    retained: list[RetainedFile] = []
    for document in documents:
        value = document.data.decode("utf-8")
        for offset, line in unfenced_lines(value):
            for match in CITE_LINE_RE.finditer(line):
                content = ContentDigest(digest(match.group().encode()))
                try:
                    fields = parse_cite_body(match.group("body"))
                    if is_illustrative(match.group("body")):
                        status, reason, resolved, data = (
                            Disposition.EXACT,
                            "illustrative citation preserved without evidentiary admission",
                            None,
                            None,
                        )
                    else:
                        status, reason, resolved, data = _citation(
                            fields, root, identities, aliases
                        )
                    items.append(
                        MigrationItem(
                            document.path,
                            "citation",
                            status,
                            fields.get("id"),
                            content,
                            reason,
                            resolved,
                            offset + match.start(),
                        )
                    )
                    if data is not None and resolved is not None:
                        retained.append(RetainedFile(resolved, data))
                except (KctxError, ValueError) as exc:
                    items.append(
                        MigrationItem(
                            document.path,
                            "citation",
                            Disposition.MALFORMED,
                            None,
                            content,
                            str(exc),
                            offset=offset + match.start(),
                        )
                    )
    identity_value: JsonObject = {
        "files": [{"path": item.path, "content": digest(item.data)} for item in files],
        "format": "legacy-authored-import-2",
    }
    distinct_sources = tuple({(item.path, digest(item.data)): item for item in retained}.values())
    return LegacyImport(
        PlanId(digest(canonical(identity_value))), tuple(files), tuple(items), distinct_sources
    )


def safe_restore_path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise KctxError("malformed", "unsafe retained migration path")
    return root.joinpath(*pure.parts)
