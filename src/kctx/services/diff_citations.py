"""Located authored citations, not claim admission or source classification."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from kctx.adapters.files.contained import contained_markdown
from kctx.adapters.git.citations import run_git, validate_git_path
from kctx.adapters.git.diff import repository_matches, resolve_local_pin
from kctx.citations.syntax import (
    FIELD_RE,
    is_illustrative,
    iter_cite_tokens,
    parse_cite_body,
    parse_range,
)
from kctx.domain.diff import DiffFile, LocalDiff
from kctx.domain.json import JsonObject, object_value
from kctx.errors import KctxError


class _Revisions:
    def __init__(self, diff: LocalDiff) -> None:
        self.repo = diff.repo_path
        self.pins: dict[str, str | None] = {diff.base: diff.base, diff.head: diff.head}
        self.blobs: dict[tuple[str, str], str | None] = {}
        self.objects: dict[str, bool] = {}

    def pin(self, revision: str) -> str | None:
        if revision not in self.pins:
            self.pins[revision] = resolve_local_pin(self.repo, revision)
        return self.pins[revision]

    def blob(self, commit: str, path: str) -> str | None:
        key = commit, path
        if key in self.blobs:
            return self.blobs[key]
        validate_git_path(path)
        listing = run_git(
            ["ls-tree", "-z", "--full-tree", commit, "--", path],
            cwd=self.repo,
            local_only=True,
        )
        blob = None
        if listing.returncode == 0:
            for entry in listing.stdout.split("\x00"):
                metadata, separator, name = entry.partition("\t")
                fields = metadata.split()
                if separator and name == path and len(fields) == 3 and fields[1] == "blob":
                    candidate = fields[2]
                    if candidate not in self.objects:
                        result = run_git(
                            ["cat-file", "-e", candidate], cwd=self.repo, local_only=True
                        )
                        self.objects[candidate] = result.returncode == 0
                    if self.objects[candidate]:
                        blob = candidate
                    break
        self.blobs[key] = blob
        return blob


def _matches(fields: dict[str, str], diff: LocalDiff) -> bool:
    repo = fields.get("repo", "")
    url = fields.get("url")
    if url:
        if not repository_matches(url, diff):
            return False
        # make_code's local form uses an arbitrary checkout basename, with its
        # URL carrying the actual identity. A basename alone never suffices.
        return repository_matches(repo, diff) or (
            bool(repo) and repo not in {".", ".."} and "/" not in repo and "\\" not in repo
        )
    return repository_matches(repo, diff)


def _fields(body: str) -> dict[str, str]:
    fields = parse_cite_body(body)
    end = 0
    for match in FIELD_RE.finditer(body):
        raw = match.group(0).partition("=")[2]
        if body[end : match.start()].strip() or (raw.startswith('"') and not raw.endswith('"')):
            raise KctxError("malformed", "invalid citation field syntax")
        end = match.end()
    if body[end:].strip() or not fields.get("kind"):
        raise KctxError("malformed", "citation requires well-formed fields and kind")
    if fields["kind"] == "code":
        missing = [key for key in ("repo", "path") if not fields.get(key)]
        if missing:
            raise KctxError("malformed", f"code citation missing fields: {', '.join(missing)}")
    return fields


def _ranges(
    fields: dict[str, str], file: DiffFile, diff: LocalDiff, revisions: _Revisions
) -> tuple[str, list[JsonObject], str | None]:
    try:
        first, last = parse_range(fields.get("L", ""))
    except KctxError as error:
        return "invalid_range", [], str(error)
    pin = revisions.pin(fields.get("rev", ""))
    if pin is None:
        return "unmapped_revision", [], "citation pin is not a unique available local commit SHA"
    blob = revisions.blob(pin, fields["path"])
    sides: list[str] = []
    for side, commit, path in (
        ("old", diff.base, file.old_path),
        ("new", diff.head, file.new_path),
    ):
        if path is not None and blob is not None and revisions.blob(commit, path) == blob:
            sides.append(side)
    if not sides:
        return (
            "unmapped_revision",
            [],
            "citation path/revision has no available blob identical to either endpoint",
        )
    if file.binary:
        return "unmapped_binary", [], "binary changes have no comparable textual line intervals"
    overlaps: list[JsonObject] = []
    for index, hunk in enumerate(file.hunks):
        for side in sides:
            start, count = (
                (hunk.old_start, hunk.old_count)
                if side == "old"
                else (hunk.new_start, hunk.new_count)
            )
            # A zero count denotes a gap, never a changed line at start.
            if count and first <= start + count - 1 and start <= last:
                overlaps.append({"hunk_index": index, "side": side})
    return "overlap" if overlaps else "nonoverlap", overlaps, None


def citations_for_diff(
    root: Path, diff: LocalDiff
) -> tuple[dict[str, tuple[JsonObject, ...]], tuple[str, ...]]:
    """Return all exact-repository same-file assertions, including unmapped pins."""
    paths: dict[str, list[DiffFile]] = defaultdict(list)
    citations: dict[str, list[JsonObject]] = {}
    for file in diff.files:
        key = file.new_path if file.new_path is not None else file.old_path
        if key is None:
            continue
        citations[key] = []
        for path in dict.fromkeys((file.old_path, file.new_path)):
            if path is not None:
                paths[path].append(file)
    warnings: list[str] = []
    revisions = _Revisions(diff)
    try:
        with contained_markdown([str(root)]) as sources:
            for source in sources:
                location = str(source.path.relative_to(root))
                try:
                    location.encode("utf-8")
                except UnicodeError:
                    warnings.append(f"{location!r}: citation filename is not UTF-8; source omitted")
                    continue
                try:
                    text = source.text()
                except KctxError as error:
                    warnings.append(f"{location}: citation scan unavailable: {error}")
                    continue
                for token in iter_cite_tokens(text):
                    located = f"{location}:{token.line_no}"
                    if is_illustrative(token.body):
                        continue
                    try:
                        if not token.complete:
                            raise KctxError("malformed", "unterminated citation token")
                        fields = _fields(token.body)
                    except KctxError as error:
                        warnings.append(f"{located}: malformed citation: {error}")
                        continue
                    if fields["kind"] != "code" or not _matches(fields, diff):
                        continue
                    for file in paths.get(fields["path"], ()):
                        key = file.new_path if file.new_path is not None else file.old_path
                        if key is None:
                            continue
                        try:
                            status, overlaps, warning = _ranges(fields, file, diff, revisions)
                        except KctxError as error:
                            status, overlaps, warning = "unmapped_revision", [], str(error)
                        entry = object_value(
                            {
                                "file": location,
                                "line_no": token.line_no,
                                "fields": fields,
                                "cited_range": fields.get("L"),
                                "range_status": status,
                                "overlaps": overlaps,
                            }
                        )
                        citations[key].append(entry)
                        if warning is not None:
                            warnings.append(f"{located}: {status}: {warning}")
    except KctxError as error:
        warnings.append(f"authored citation scan incomplete: {error}")
    return {key: tuple(entries) for key, entries in citations.items()}, tuple(
        dict.fromkeys(warnings)
    )
