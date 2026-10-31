"""Citation timestamps are UTC; expiration is strictly after the TTL boundary."""

from collections.abc import Mapping
from datetime import UTC, datetime

from kctx.domain.time import ttl_seconds
from kctx.errors import KctxError


def iso_now_minute() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")


def today_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def parse_seen(seen: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(seen, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise KctxError("malformed", f"bad seen= timestamp {seen!r}")


def parse_ttl_seconds(ttl: str | None) -> int | None:
    return ttl_seconds(ttl)


def is_expired(seen: str, ttl: str | None, now: datetime | None = None) -> bool:
    seconds = parse_ttl_seconds(ttl)
    if seconds is None:
        return False
    # Preserve subsecond ages, unlike integer-second record recency assessment.
    return ((now or datetime.now(UTC)) - parse_seen(seen)).total_seconds() > seconds


def due_for_touch(fields: Mapping[str, str], now: datetime) -> bool:
    # Check cadence is independent of the immutable observation age.
    seen = fields.get("checked_at") or fields.get("seen")
    if not seen:
        return False
    try:
        seconds = parse_ttl_seconds(fields.get("ttl"))
        return seconds is not None and (now - parse_seen(seen)).total_seconds() > seconds / 2
    except KctxError:
        return False
