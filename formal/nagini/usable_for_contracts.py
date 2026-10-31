"""Viper-verified twin of kctx.semantics.checker.policy_allows.

This is only the seven-input Boolean conjunction leaf of v2 usability.
Recursive evidence checking, applicability, context and receipt computation
are NOT proved by this twin. Lean/Python conformance covers that composition.
The runtime twin remains token-identical to this function after contracts are
removed; the exhaustive grid compares all 128 inputs to production policy_allows.
"""

from nagini_contracts.contracts import *


def usable_for_tagged(
    supported: int,
    fresh_evidence: int,
    validation_current: int,
    uncontested: int,
    require_fresh: int,
    require_validated: int,
    require_uncontested: int,
) -> int:
    """Primitive mandatory-policy conjunction, not the full assessment engine."""
    Requires(
        (supported == 0 or supported == 1)
        and (fresh_evidence == 0 or fresh_evidence == 1)
        and (validation_current == 0 or validation_current == 1)
        and (uncontested == 0 or uncontested == 1)
    )
    Requires(
        (require_fresh == 0 or require_fresh == 1)
        and (require_validated == 0 or require_validated == 1)
        and (require_uncontested == 0 or require_uncontested == 1)
    )
    # result is a Bool
    Ensures(Result() == 0 or Result() == 1)
    # T17: no support -> never usable, whatever the conditions say
    Ensures(Implies(supported == 0, Result() == 0))
    # all mandatory conditions met -> usable
    Ensures(
        Implies(
            supported == 1
            and (require_fresh == 0 or fresh_evidence == 1)
            and (require_validated == 0 or validation_current == 1)
            and (require_uncontested == 0 or uncontested == 1),
            Result() == 1,
        )
    )
    # a required condition unmet blocks usability
    Ensures(Implies(require_fresh == 1 and fresh_evidence == 0, Result() == 0))
    Ensures(
        Implies(require_validated == 1 and validation_current == 0, Result() == 0)
    )
    Ensures(Implies(require_uncontested == 1 and uncontested == 0, Result() == 0))

    if supported == 0:
        return 0
    if require_fresh == 1 and fresh_evidence == 0:
        return 0
    if require_validated == 1 and validation_current == 0:
        return 0
    if require_uncontested == 1 and uncontested == 0:
        return 0
    return 1
