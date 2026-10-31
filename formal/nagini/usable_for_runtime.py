"""Runtime twin of kctx.semantics.checker.usable_for (plain, executable).

Executed by the equivalence grid; twin_drift_check.py asserts this body is
token-identical to the Viper-verified one in usable_for_contracts.py.

Encoding: booleans as 0/1 (see usable_for_contracts.py). Result 1 = usable.
"""

from __future__ import annotations


def usable_for_tagged(
    supported: int,
    fresh_evidence: int,
    validation_current: int,
    uncontested: int,
    require_fresh: int,
    require_validated: int,
    require_uncontested: int,
) -> int:
    if supported == 0:
        return 0
    if require_fresh == 1 and fresh_evidence == 0:
        return 0
    if require_validated == 1 and validation_current == 0:
        return 0
    if require_uncontested == 1 and uncontested == 0:
        return 0
    return 1
