"""UTC timestamps and legacy TTL spelling at the authored-record boundary."""

import re
from datetime import UTC, date, datetime

from kctx.errors import KctxError
from kctx.semantics.model import Freshness, ttl_expire_after
from kctx.semantics.time import assess_fresh

TTL_RE = re.compile(r"^(\d+)([dh])$")


def iso_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def compact_now() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def today() -> str:
    return date.today().isoformat()


def parse_flexible_timestamp(value: str) -> datetime:
    """A bare date means midnight UTC; timestamps without a zone are UTC."""
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise KctxError("malformed", f"bad timestamp {value!r}") from exc
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def ttl_seconds(ttl: str | None) -> int | None:
    if not ttl or ttl == "none":
        return None
    match = TTL_RE.fullmatch(ttl)
    if match is None:
        raise KctxError("malformed", f"bad ttl {ttl!r}, expected '<N>d', '<N>h', or 'none'")
    count, unit = int(match.group(1)), match.group(2)
    return count * (3600 if unit == "h" else 86400)


def is_past_ttl(verified_at: str, ttl: str | None, now: datetime | None = None) -> bool:
    seconds = ttl_seconds(ttl)
    if seconds is None:
        return False
    observed_at = int(parse_flexible_timestamp(verified_at).timestamp())
    at = int((now or datetime.now(UTC)).timestamp())
    return assess_fresh(ttl_expire_after(seconds), observed_at, at) is Freshness.STALE
