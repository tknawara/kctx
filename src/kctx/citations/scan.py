"""Citation scans with advisory receipts; pinned observations are never retargeted."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import NotRequired, TypedDict

from kctx.adapters.files.contained import ContainedFile, contained_markdown
from kctx.citations.classification import classify
from kctx.citations.models import CitationStatus, Classification
from kctx.citations.syntax import (
    CITE_LINE_RE,
    UNPINNED_RE,
    is_illustrative,
    iter_cite_tokens,
    parse_cite_body,
    remove_field,
    replace_field,
)
from kctx.citations.time import due_for_touch, parse_seen, parse_ttl_seconds
from kctx.config import Config
from kctx.domain.json import JsonObject, object_value
from kctx.errors import KctxError


class CitationResult(TypedDict):
    file: str | None
    line_no: int | None
    fields: dict[str, str]
    status: str
    reason: NotRequired[str]
    head: NotRequired[str]
    L: NotRequired[str]
    sym_line: NotRequired[int]
    state: NotRequired[str]
    q: NotRequired[str]
    touched_line: NotRequired[str]


class CitationLocation(TypedDict):
    file: str | None
    line_no: int | None


class CitationWarning(TypedDict):
    file: str
    line_no: int
    text: str


class CitationCheck(TypedDict):
    available: bool
    results: list[CitationResult]
    warnings: list[CitationWarning]
    skipped: list[CitationLocation]
    exit_code: int
    note: NotRequired[str | None]


class StaleEntry(TypedDict):
    file: str
    line_no: int
    kind: str | None
    reason: str
    stale: str | None
    seen: str | None
    age_days: float | None
    group: str


class StaleGroup(TypedDict):
    count: int
    oldest_age_days: float


class StaleAggregate(TypedDict):
    entries: list[StaleEntry]
    groups: dict[str, StaleGroup]
    total: int
    oldest_age_days: float


class CitationStale(StaleAggregate):
    available: bool
    exit_code: int
    note: NotRequired[str | None]


def check_to_wire(result: CitationCheck) -> JsonObject:
    return object_value(
        {key: value for key, value in result.items() if key not in ("available", "note")}
    )


def stale_to_wire(result: CitationStale) -> JsonObject:
    return object_value(
        {key: value for key, value in result.items() if key not in ("available", "note")}
    )


def _rewrite(
    raw: str,
    fields: Mapping[str, str],
    status: Classification,
    now: datetime,
    touch: bool,
    touch_all: bool,
    mark: bool,
) -> str | None:
    rewritten = raw
    changed = False
    if touch and status.status in (CitationStatus.FRESH, CitationStatus.MOVED):
        changed = touch_all or due_for_touch(fields, now)
    if mark:
        if status.status in (CitationStatus.CHANGED, CitationStatus.GONE) or (
            status.status is CitationStatus.EXPIRED and fields.get("kind") != "code"
        ):
            rewritten = replace_field(rewritten, "stale", f"{status.status.value}@{now:%Y-%m-%d}")
            if fields.get("kind") == "code" and status.head:
                rewritten = replace_field(rewritten, "head", status.head[:7])
            changed = True
        elif status.status in (CitationStatus.FRESH, CitationStatus.MOVED):
            for key in ("stale", "head"):
                if fields.get(key):
                    rewritten = remove_field(rewritten, key)
                    changed = True
    if not changed:
        return None
    # These are the latest check's advisory results, not a successor citation.
    # In particular, current_L belongs to current_rev, never to the pinned rev.
    rewritten = replace_field(rewritten, "checked_at", now.strftime("%Y-%m-%dT%H:%MZ"))
    rewritten = replace_field(rewritten, "check_status", status.status.value)
    current_range = status.line_range
    if status.status is CitationStatus.FRESH and fields.get("kind") == "code":
        current_range = fields.get("L")
    for key, value in (
        ("current_rev", status.head),
        ("current_L", current_range),
        ("current_state", status.state),
    ):
        if value is not None:
            rewritten = replace_field(rewritten, key, value)
        elif key in fields:
            rewritten = remove_field(rewritten, key)
    return rewritten


def _entry(
    file: str | None, line_no: int | None, fields: dict[str, str], status: Classification
) -> CitationResult:
    result: CitationResult = {
        "file": file,
        "line_no": line_no,
        "fields": fields,
        "status": status.status.value,
    }
    if status.reason is not None:
        result["reason"] = status.reason
    if status.head is not None:
        result["head"] = status.head
    if status.line_range is not None:
        result["L"] = status.line_range
    if status.sym_line is not None:
        result["sym_line"] = status.sym_line
    if status.state is not None:
        result["state"] = status.state
    if status.query is not None:
        result["q"] = status.query
    return result


def run_check(
    paths: Sequence[str] | None = None,
    inline_line: str | None = None,
    touch: bool = False,
    touch_all: bool = False,
    mark: bool = False,
    *,
    config: Config | None = None,
) -> CitationCheck:
    touch = touch or touch_all
    now = datetime.now(UTC)
    results: list[CitationResult] = []
    warnings: list[CitationWarning] = []
    skipped: list[CitationLocation] = []
    if inline_line is not None:
        match = CITE_LINE_RE.search(inline_line)
        if match is None:
            raise KctxError("malformed", "no ⟦cite …⟧ found in --line")
        if is_illustrative(match.group("body")):
            skipped.append({"file": None, "line_no": None})
        else:
            fields = parse_cite_body(match.group("body"))
            status = classify(fields, now=now, config=config)
            entry = _entry(None, None, fields, status)
            rewritten = _rewrite(match.group(0), fields, status, now, touch, touch_all, mark)
            if rewritten is not None:
                entry["touched_line"] = rewritten
            results.append(entry)
    else:
        with contained_markdown(paths or (), writable=touch or mark) as sources:
            updates: list[tuple[ContainedFile, str]] = []
            for source in sources:
                path = source.path
                text = source.text()
                pieces: list[str] = []
                end = 0
                for token in iter_cite_tokens(text):
                    line_no = token.line_no
                    if is_illustrative(token.body):
                        skipped.append({"file": str(path), "line_no": line_no})
                        continue
                    try:
                        if not token.complete:
                            raise KctxError("malformed", "unterminated citation token")
                        fields = parse_cite_body(token.body)
                    except KctxError as error:
                        # One bad token is reported in place, never a whole-scan abort.
                        results.append(
                            {
                                "file": str(path),
                                "line_no": line_no,
                                "fields": {},
                                "status": CitationStatus.UNVERIFIABLE.value,
                                "reason": str(error),
                            }
                        )
                        continue
                    status = classify(fields, now=now, config=config)
                    results.append(_entry(str(path), line_no, fields, status))
                    rewritten = _rewrite(token.raw, fields, status, now, touch, touch_all, mark)
                    if rewritten is not None:
                        pieces.extend((text[end : token.start], rewritten))
                        end = token.end
                for match in UNPINNED_RE.finditer(text):
                    warnings.append(
                        {
                            "file": str(path),
                            "line_no": text.count("\n", 0, match.start()) + 1,
                            "text": match.group(0),
                        }
                    )
                if pieces:
                    pieces.append(text[end:])
                    updated = "".join(pieces)
                    if updated != text:
                        updates.append((source, updated))
            ContainedFile.write_updates(updates)
    statuses = {entry["status"] for entry in results}
    code = (
        3
        if "unverifiable" in statuses
        else (2 if statuses & {"moved", "expired", "changed", "gone"} else 0)
    )
    return {
        "available": True,
        "results": results,
        "warnings": warnings,
        "skipped": skipped,
        "exit_code": code,
    }


def _age_days(seen: str | None, now: datetime) -> float | None:
    if not seen:
        return None
    try:
        return (now - parse_seen(seen)).total_seconds() / 86400.0
    except KctxError:
        return None


def _past_ttl(fields: Mapping[str, str], now: datetime) -> bool:
    age = _age_days(fields.get("seen"), now)
    try:
        seconds = parse_ttl_seconds(fields.get("ttl"))
    except KctxError:
        return False
    return age is not None and seconds is not None and age * 86400 > seconds


def _group_for(source: ContainedFile) -> str:
    root = source.root
    if source.root_is_file:
        return root.parent.name or str(root.parent)
    relative = source.path.relative_to(root)
    return relative.parts[0] if relative.parts else (root.name or str(root))


def run_stale(
    paths: Sequence[str] | None = None,
    offline: bool = False,
    now: datetime | None = None,
    *,
    config: Config | None = None,
) -> CitationStale:
    now = now or datetime.now(UTC)
    entries: list[StaleEntry] = []
    with contained_markdown(paths or ()) as sources:
        for source in sources:
            path = source.path
            text = source.text()
            for token in iter_cite_tokens(text):
                if is_illustrative(token.body):
                    continue
                try:
                    if not token.complete:
                        raise KctxError("malformed", "unterminated citation token")
                    fields = parse_cite_body(token.body)
                except KctxError as error:
                    entries.append(
                        {
                            "file": str(path),
                            "line_no": token.line_no,
                            "kind": None,
                            "reason": f"malformed: {error}",
                            "stale": None,
                            "seen": None,
                            "age_days": None,
                            "group": _group_for(source),
                        }
                    )
                    continue
                reason: str | None = None
                if offline:
                    if fields.get("stale"):
                        reason = "marked"
                    elif _past_ttl(fields, now):
                        reason = "due"
                else:
                    status = classify(fields, now=now, config=config)
                    if status.status in (
                        CitationStatus.CHANGED,
                        CitationStatus.GONE,
                        CitationStatus.EXPIRED,
                    ):
                        reason = status.status.value
                    elif fields.get("stale"):
                        reason = "marked"
                if reason is not None:
                    entries.append(
                        {
                            "file": str(path),
                            "line_no": token.line_no,
                            "kind": fields.get("kind"),
                            "reason": reason,
                            "stale": fields.get("stale"),
                            "seen": fields.get("seen"),
                            "age_days": _age_days(fields.get("seen"), now),
                            "group": _group_for(source),
                        }
                    )
    groups: dict[str, StaleGroup] = {}
    for entry in entries:
        group = groups.setdefault(entry["group"], {"count": 0, "oldest_age_days": 0.0})
        group["count"] += 1
        age = entry["age_days"]
        if age is not None:
            group["oldest_age_days"] = max(group["oldest_age_days"], age)
    ages = [entry["age_days"] for entry in entries if entry["age_days"] is not None]
    return {
        "available": True,
        "entries": entries,
        "groups": groups,
        "total": len(entries),
        "oldest_age_days": max(ages) if ages else 0.0,
        "exit_code": 2 if entries else 0,
    }
