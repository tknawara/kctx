"""Freshness semantics mirroring ``formal/Kctx/Time.lean``.

Clock convention: recency holds iff
``observed_at <= now <= observed_at + ttl`` (inclusive boundary). Future
observations are ``unknown``, never ``fresh``. A missing TTL policy is never
an implicit freshness proof.
"""

from __future__ import annotations

from typing import Optional

from kctx.semantics.model import Freshness, Ttl


def fresh_at(ttl: Ttl, observed_at: int, now: int) -> bool:
    """Prop twin of :func:`assess_fresh` (Lean ``FreshAt``)."""
    if observed_at > now:
        return False
    if ttl.tag == "expireAfter":
        assert ttl.secs is not None
        return now <= observed_at + ttl.secs
    if ttl.tag == "noExpiry":
        return True
    return False  # missing policy: never fresh


def assess_fresh(ttl: Ttl, observed_at: int, now: int) -> Freshness:
    if observed_at <= now:
        if ttl.tag == "missing":
            return Freshness.UNKNOWN
        if ttl.tag == "noExpiry":
            return Freshness.FRESH
        assert ttl.secs is not None
        if now <= observed_at + ttl.secs:
            return Freshness.FRESH
        return Freshness.STALE
    return Freshness.UNKNOWN
