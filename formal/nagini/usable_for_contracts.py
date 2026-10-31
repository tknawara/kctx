"""Viper-verified twin of kctx.semantics.checker.usable_for (T17 leaf).

WHAT THIS IS: the same twin+guard+grid pattern as the freshness leaf
(formal/nagini/). The production decision core stays stdlib-only; Viper
verifies an annotated primitive twin here, ``twin_drift_check.py`` asserts
the executed runtime body is token-identical to the verified one, and the
equivalence grid ties it to production ``usable_for``.

Encoding (policy booleans → ints 0/1): supported, fresh_evidence,
validation_current, uncontested, require_fresh, require_validated,
require_uncontested. Result: 1 = usable, 0 = not usable.

The contract is exactly T17: usable iff supported and every enabled
mandatory condition holds. Notably: a condition that is not required
imposes no constraint — and the theorem proves usable can never be true
when support is absent, regardless of the other inputs.
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
    """Twin of kctx.semantics.checker.usable_for: exactly the conjunction of
    support and the policy's mandatory conditions."""
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
