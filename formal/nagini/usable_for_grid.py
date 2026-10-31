"""Exhaustive twin linkage for the v2 policy conjunction leaf, not all T17.

The verified twin proves the seven-input Boolean conjunction only. The real
checker computes these inputs from recursive witnesses, exact receipts and
context, then calls policy_allows. Its input computation is covered separately
by Lean/Python full-response conformance and semantic golden tests. No corner is
silently skipped and no claim is made that this leaf verifies the whole engine.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from kctx.semantics.checker import policy_allows
from usable_for_runtime import usable_for_tagged


def main() -> int:
    cases = 0
    mismatches: list[str] = []
    for values in itertools.product((0, 1), repeat=7):
        supported, fresh, validated, uncontested, require_fresh, require_validated, require_uncontested = values
        twin = usable_for_tagged(supported, fresh, validated, uncontested,
                                 require_fresh, require_validated, require_uncontested)
        production = policy_allows(bool(supported), bool(fresh), bool(validated), bool(uncontested),
                                   bool(require_fresh), bool(require_validated), bool(require_uncontested))
        cases += 1
        if twin != int(production):
            mismatches.append(f"inputs={values}: twin={twin} production={production}")
    for mismatch in mismatches:
        print("MISMATCH", mismatch)
    print(f"v2 policy conjunction leaf: {'FAIL' if mismatches else 'PASS'} ({cases}/128 inputs; no skipped corners)")
    return int(bool(mismatches))


if __name__ == "__main__":
    raise SystemExit(main())
