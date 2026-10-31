"""Scanned-through cursors and durable, idempotent pending judgments."""

from pathlib import Path
from typing import TypedDict

from kctx.adapters.files.storage import atomic_write_json, read_json
from kctx.domain.json import integer, object_value, text
from kctx.domain.time import iso_now
from kctx.errors import KctxError


class Judgment(TypedDict):
    file: str
    line_no: int
    reason: str
    excerpt: str


class Cursor(TypedDict):
    repo: str
    sha: str
    admitted_at: str
    by: str
    pending: list[Judgment]


def cursors_dir(root: Path) -> Path:
    return root / "inventory" / "cursors"


def cursor_path(root: Path, org: str, name: str) -> Path:
    return cursors_dir(root) / f"{org}__{name}.json"


def load_cursor(root: Path, org: str, name: str) -> Cursor | None:
    path = cursor_path(root, org, name)
    if not path.exists():
        return None
    fields = object_value(read_json(path), "admit cursor")
    unknown = fields.keys() - {"repo", "sha", "admitted_at", "by", "pending"}
    if unknown:
        raise KctxError("malformed", f"unknown cursor fields: {sorted(unknown)}")
    pending: list[Judgment] = []
    raw_pending = fields.get("pending", [])
    if not isinstance(raw_pending, list):
        raise KctxError("malformed", "pending judgments must be an array")
    for raw in raw_pending:
        item = object_value(raw, "judgment")
        unknown = item.keys() - {"file", "line_no", "line", "reason", "excerpt"}
        if unknown:
            raise KctxError("malformed", f"unknown judgment fields: {sorted(unknown)}")
        pending.append(
            {
                "file": text(item.get("file"), "judgment file"),
                "line_no": integer(item.get("line_no", item.get("line", 1)), "judgment line"),
                "reason": text(item.get("reason", ""), "judgment reason"),
                "excerpt": text(item.get("excerpt", ""), "judgment excerpt"),
            }
        )
    return {
        "repo": text(fields.get("repo"), "cursor repo"),
        "sha": text(fields.get("sha"), "cursor sha"),
        "admitted_at": text(fields.get("admitted_at"), "cursor admitted_at"),
        "by": text(fields.get("by"), "cursor by"),
        "pending": pending,
    }


def save_cursor(
    root: Path,
    org: str,
    name: str,
    sha: str,
    by: str = "kctx admit",
    pending: list[Judgment] | None = None,
) -> None:
    cursor: Cursor = {
        "repo": f"{org}/{name}",
        "sha": sha,
        "admitted_at": iso_now(),
        "by": by,
        "pending": pending or [],
    }
    atomic_write_json(cursor_path(root, org, name), cursor)


def merge_pending(prior: list[Judgment] | None, new: list[Judgment]) -> list[Judgment]:
    seen: set[tuple[str, int, str, str]] = set()
    result: list[Judgment] = []
    for item in (*(prior or []), *new):
        key = (item["file"], item["line_no"], item["reason"], item["excerpt"])
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result
