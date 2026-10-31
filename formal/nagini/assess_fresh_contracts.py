"""Nagini contracts for the time semantics (handover §5.2 upgrade path).

WHAT THIS IS — precisely:

The production decision core (`src/kctx/semantics`) is stdlib-only and must
stay importable without Nagini, so it cannot carry Nagini imports in place.
This file is therefore a **primitive contract twin** of
`kctx.semantics.time.assess_fresh`, verified by Viper here, and tied to the
production function by an exhaustive equivalence grid
(`formal/nagini/equivalence_grid.py`) run in the same container.

Together (verified twin + exhaustive equivalence on the shared domain) this
upgrades the freshness semantics from "conformance checked" toward
implementation verification for this leaf. It is *not* a refinement proof of
the whole Python core, and the T-number registry in `formal/theorems.json`
still rests on the Lean model.

TTL encoding in the twin: `ttl_kind` — 0 = expireAfter(secs),
1 = noExpiry, 2 = missing. Result: 0 = fresh · 1 = stale · 2 = unknown.
"""

from nagini_contracts.contracts import *


def assess_fresh_tagged(
    ttl_kind: int, ttl_secs: int, observed_at: int, now: int
) -> int:
    """Twin of kctx.semantics.time.assess_fresh with the proved laws:

    - future observations are unknown, never fresh;
    - a missing policy is unknown, never fresh;
    - no-expiry (with a non-future observation) is fresh;
    - expire-after: inclusive window [observed, observed+secs] is fresh,
      anything later is stale;
    - stale arises only from expire-after past its window.
    """
    Requires(0 <= ttl_kind and ttl_kind <= 2)
    Requires(Implies(ttl_kind == 0, ttl_secs >= 0))
    Ensures(Result() == 0 or Result() == 1 or Result() == 2)
    # future observation -> unknown
    Ensures(Implies(now < observed_at, Result() == 2))
    # missing policy -> unknown
    Ensures(Implies(ttl_kind == 2, Result() == 2))
    # no-expiry, not-future -> fresh
    Ensures(Implies(ttl_kind == 1 and observed_at <= now, Result() == 0))
    # expire-after: inclusive window fresh
    Ensures(Implies(ttl_kind == 0 and observed_at <= now and now <= observed_at + ttl_secs, Result() == 0))
    # expire-after: past the window stale
    Ensures(Implies(ttl_kind == 0 and now > observed_at + ttl_secs, Result() == 1))
    # stale only from expire-after past its window
    Ensures(Implies(Result() == 1, ttl_kind == 0 and now > observed_at + ttl_secs))
    # fresh implies a non-future observation
    Ensures(Implies(Result() == 0, observed_at <= now))

    if observed_at > now:
        return 2
    if ttl_kind == 2:
        return 2
    if ttl_kind == 1:
        return 0
    if now <= observed_at + ttl_secs:
        return 0
    return 1

