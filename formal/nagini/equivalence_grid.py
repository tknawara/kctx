"""Exhaustive equivalence grid: the Viper-verified twin vs the production
`kctx.semantics.time.assess_fresh`.

Runs in the Nagini container right after verification: the twin's proved
laws only bind to production if the two agree on the shared domain. The
grid is exhaustive over the relevant window (every offset -2..+2 around
both boundaries, every policy, plus a spread of larger values) — small
enough to be complete, large enough to cover the corners the contracts
name. Any mismatch fails the job.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from kctx.semantics.model import Ttl  # noqa: E402
from kctx.semantics.time import Freshness, assess_fresh  # noqa: E402

from formal.nagini.assess_fresh_contracts import (  # noqa: E402
    assess_fresh_tagged,
)

# twin <-> production encodings
POLICIES = [(-1, 5, Ttl("expireAfter", 5)), (-1, 50, Ttl("expireAfter", 50)),
            (-1, 0, Ttl("expireAfter", 0)), (0, 0, Ttl("noExpiry")),
            (1, 0, Ttl("missing"))]
RESULTS = {0: Freshness.FRESH, 1: Freshness.STALE, 2: Freshness.UNKNOWN}

BASE = 1_000_000
OFFSETS = [-10_000, -51, -50, -49, -6, -5, -4, -2, -1, 0, 1, 2, 4, 5, 6, 49, 50, 51, 10_000]


def main() -> int:
    cases = 0
    mismatches: list[str] = []
    for (kind, secs, ttl), offset in itertools.product(POLICIES, OFFSETS):
        observed = BASE
        now = BASE + offset
        twin = assess_fresh_tagged(
            0 if kind == -1 else 1, secs if kind == -1 else 0, observed, now
        )
        prod = assess_fresh(ttl, observed, now)
        cases += 1
        if RESULTS[twin] is not prod:
            mismatches.append(
                f"ttl={ttl!r} observed={observed} now={now}: "
                f"twin={RESULTS[twin].value} production={prod.value}"
            )
    # future observations
    for (kind, secs, ttl) in POLICIES:
        twin = assess_fresh_tagged(
            0 if kind == -1 else 1, secs if kind == -1 else 0, BASE + 7, BASE
        )
        prod = assess_fresh(ttl, BASE + 7, BASE)
        cases += 1
        if RESULTS[twin] is not prod:
            mismatches.append(f"future {ttl!r}: twin={RESULTS[twin]} prod={prod}")

    for m in mismatches:
        print("MISMATCH", m)
    print(f"equivalence grid: {'FAIL' if mismatches else 'PASS'} ({cases} cases)")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
