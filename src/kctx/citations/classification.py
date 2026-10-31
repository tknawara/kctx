"""Current-state citation checks, not historical truth or semantic admission."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from kctx.adapters.git.citations import (
    git_blob_sha,
    git_file_content,
    resolve_default_branch_rev,
    resolve_repo_for_check,
)
from kctx.citations.models import CitationKind, CitationStatus, Classification
from kctx.citations.records import load_proposal_record, load_record_status
from kctx.citations.syntax import normalize_span, parse_range
from kctx.citations.time import is_expired
from kctx.config import Config
from kctx.errors import KctxError

GATE_REV_RE = re.compile(r"^(?P<repo>[^@]+)@(?P<sha>[0-9a-fA-F]{7,40})$")


def parse_gate_rev(rev: str) -> tuple[str, str]:
    match = GATE_REV_RE.fullmatch(rev)
    if match is None:
        raise KctxError("malformed", f"bad rev= {rev!r}, expected '<repo>@<sha>'")
    return match["repo"], match["sha"]


def locate_span(
    lines: Sequence[str], width: int, target_span: str | None, sym: str | None
) -> int | None:
    if target_span is None or width <= 0 or width > len(lines):
        return None
    max_start = len(lines) - width
    if sym:
        short_sym = sym.split("::")[-1].split(".")[-1]
        for index, line in enumerate(lines):
            if short_sym in line:
                for start in range(max(0, index - width), min(max_start, index + width) + 1):
                    if normalize_span(lines[start : start + width]) == target_span:
                        return start
    for start in range(max_start + 1):
        if normalize_span(lines[start : start + width]) == target_span:
            return start
    return None


def classify_code(
    fields: Mapping[str, str],
    now: datetime | None = None,
    *,
    config: Config | None = None,
) -> Classification:
    del now
    repo_path = resolve_repo_for_check(fields, config=config)
    if repo_path is None:
        return Classification(CitationStatus.UNVERIFIABLE, reason="could not resolve repo/remote")
    try:
        head = resolve_default_branch_rev(repo_path)
        path = fields.get("path", "")
        content = git_file_content(repo_path, head, path)
        if content is None:
            return Classification(CitationStatus.GONE, head=head)
        blob = git_blob_sha(repo_path, head, path)
        if blob is not None and blob == fields.get("blob"):
            return Classification(CitationStatus.FRESH, head=head)
        a, b = parse_range(fields.get("L", ""))
    except KctxError as error:
        return Classification(CitationStatus.UNVERIFIABLE, reason=str(error))
    lines = content.splitlines()
    sym = fields.get("sym")
    width = b - a + 1
    found = locate_span(lines, width, fields.get("span"), sym)
    if found is not None:
        return Classification(
            CitationStatus.MOVED, head=head, line_range=f"{found + 1}-{found + width}"
        )
    sym_line: int | None = None
    if sym:
        short_sym = sym.split("::")[-1].split(".")[-1]
        sym_line = next((i + 1 for i, line in enumerate(lines) if short_sym in line), None)
    return Classification(CitationStatus.CHANGED, head=head, sym_line=sym_line)


def classify_noncode(fields: Mapping[str, str], now: datetime | None = None) -> Classification:
    seen = fields.get("seen")
    if not seen:
        return Classification(CitationStatus.UNVERIFIABLE, reason="missing seen=")
    try:
        expired = is_expired(seen, fields.get("ttl", "none"), now or datetime.now(UTC))
    except KctxError as error:
        return Classification(CitationStatus.UNVERIFIABLE, reason=str(error))
    if expired:
        return Classification(CitationStatus.EXPIRED, query=fields.get("q"))
    return Classification(CitationStatus.FRESH)


def classify_proposal(
    fields: Mapping[str, str],
    now: datetime | None = None,
    *,
    config: Config | None = None,
) -> Classification:
    del now
    identity = fields.get("id")
    if not identity:
        return Classification(CitationStatus.UNVERIFIABLE, reason="missing id=")
    try:
        record = load_proposal_record(identity, config=config)
    except KctxError as error:
        return Classification(CitationStatus.UNVERIFIABLE, reason=str(error))
    if record is None:
        return Classification(CitationStatus.GONE)
    if not record.status:
        return Classification(CitationStatus.UNVERIFIABLE, reason="proposal has no status")
    cited_state = fields.get("state")
    status = (
        CitationStatus.CHANGED
        if cited_state and record.status != cited_state
        else CitationStatus.FRESH
    )
    return Classification(status, state=record.status)


def classify_gate(
    fields: Mapping[str, str],
    now: datetime | None = None,
    *,
    config: Config | None = None,
) -> Classification:
    del now
    rev = fields.get("rev")
    if not rev:
        return Classification(CitationStatus.UNVERIFIABLE, reason="missing rev=")
    try:
        repo, sha = parse_gate_rev(rev)
        repo_fields = {"repo": repo}
        if fields.get("url"):
            repo_fields["url"] = fields["url"]
        repo_path = resolve_repo_for_check(repo_fields, config=config)
        if repo_path is None:
            return Classification(
                CitationStatus.UNVERIFIABLE, reason="could not resolve repo/remote"
            )
        head = resolve_default_branch_rev(repo_path)
    except KctxError as error:
        return Classification(CitationStatus.UNVERIFIABLE, reason=str(error))
    status = CitationStatus.FRESH if head.startswith(sha.lower()) else CitationStatus.CHANGED
    return Classification(status, head=head)


def classify_record(
    fields: Mapping[str, str],
    now: datetime | None = None,
    *,
    config: Config | None = None,
) -> Classification:
    del now
    path = fields.get("path")
    if not path:
        return Classification(CitationStatus.UNVERIFIABLE, reason="missing path=")
    try:
        current = load_record_status(path, config=config)
    except KctxError as error:
        return Classification(CitationStatus.UNVERIFIABLE, reason=str(error))
    if current is None:
        return Classification(CitationStatus.GONE)
    cited_state = fields.get("state")
    status = (
        CitationStatus.CHANGED if cited_state and current != cited_state else CitationStatus.FRESH
    )
    return Classification(status, state=current)


def classify(
    fields: Mapping[str, str],
    now: datetime | None = None,
    *,
    config: Config | None = None,
) -> Classification:
    raw_kind = fields.get("kind")
    if not raw_kind:
        return Classification(CitationStatus.UNVERIFIABLE, reason="missing kind=")
    try:
        kind = CitationKind(raw_kind)
    except ValueError:
        return Classification(CitationStatus.UNVERIFIABLE, reason=f"unknown kind={raw_kind}")
    match kind:
        case CitationKind.CODE:
            return classify_code(fields, now, config=config)
        case CitationKind.PROPOSAL:
            return classify_proposal(fields, now, config=config)
        case CitationKind.GATE:
            return classify_gate(fields, now, config=config)
        case CitationKind.RECORD:
            return classify_record(fields, now, config=config)
        case _:
            return classify_noncode(fields, now)
