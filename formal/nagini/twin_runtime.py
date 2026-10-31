"""Runtime twin of kctx.semantics.time.assess_fresh (plain, executable).

The annotated twin in ``assess_fresh_contracts.py`` is what Viper verifies;
Nagini's contract constructs are overload stubs that raise at runtime, so the
equivalence grid executes *this* file instead. ``scripts/nagini_check.sh``
asserts the two function bodies are token-identical (contracts stripped), so
the executed twin and the verified twin cannot drift.

Encoding: ttl_kind — 0 = expireAfter(secs), 1 = noExpiry, 2 = missing.
Result: 0 = fresh · 1 = stale · 2 = unknown.
"""

from __future__ import annotations


def assess_fresh_tagged(
    ttl_kind: int, ttl_secs: int, observed_at: int, now: int
) -> int:
    if observed_at > now:
        return 2
    if ttl_kind == 2:
        return 2
    if ttl_kind == 1:
        return 0
    if now <= observed_at + ttl_secs:
        return 0
    return 1
