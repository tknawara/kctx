"""Well-formedness mirroring ``formal/Kctx/WellFormed.lean``.

Structural predicate only — never "the checker accepted". Decoding success
must imply well-formedness (T01), and committed operations must preserve it
(T03)."""

from __future__ import annotations

from typing import Tuple

from kctx.semantics.model import (
    Claim,
    ClaimRef,
    Correction,
    Derivation,
    KbView,
    Observation,
    RuleId,
    find_claim,
    find_obs,
)


def _all_unique(items) -> bool:
    seen = set()
    for x in items:
        if x in seen:
            return False
        seen.add(x)
    return True


def record_wf_observation(o: Observation) -> bool:
    return bool(o.id) and bool(o.system) and bool(o.locator)


def record_wf_claim(c: Claim) -> bool:
    return bool(c.id) and bool(c.rev) and bool(c.scope.project)


def record_wf_derivation(d: Derivation) -> bool:
    if not d.id or not d.conclusion.id or not d.conclusion.rev:
        return False
    for group in d.premise_groups:
        for r in group:
            if not r.id or not r.rev:
                return False
    if d.witness is not None and not d.witness.scope.project:
        return False
    return True


def record_wf_correction(c: Correction) -> bool:
    return bool(c.target.id) and bool(c.target.rev)


def premises_of(v: KbView, ref: ClaimRef) -> Tuple[ClaimRef, ...]:
    out: list[ClaimRef] = []
    for d in v.derivations:
        if d.conclusion == ref:
            for group in d.premise_groups:
                out.extend(group)
    return tuple(out)


def reachable_in(v: KbView, fuel: int, ref: ClaimRef) -> Tuple[ClaimRef, ...]:
    if fuel <= 0:
        return ()
    ps = premises_of(v, ref)
    out = list(ps)
    for p in ps:
        out.extend(reachable_in(v, fuel - 1, p))
    return tuple(out)


def acyclic_deriv(v: KbView, d: Derivation) -> bool:
    return d.conclusion not in reachable_in(v, len(v.derivations) + 1, d.conclusion)


def view_well_formed(v: KbView) -> bool:
    if not _all_unique(o.id for o in v.observations):
        return False
    if not _all_unique((c.id, c.rev) for c in v.claims):
        return False
    if not _all_unique(d.id for d in v.derivations):
        return False
    if not all(record_wf_observation(o) for o in v.observations):
        return False
    if not all(record_wf_claim(c) for c in v.claims):
        return False
    if not all(record_wf_derivation(d) for d in v.derivations):
        return False
    if not all(record_wf_correction(c) for c in v.corrections):
        return False
    for b in v.bindings:
        if find_obs(v, b.obs) is None or find_claim(v, b.ref) is None:
            return False
    for c in v.corrections:
        if find_claim(v, c.target) is None:
            return False
    for d in v.derivations:
        if find_claim(v, d.conclusion) is None:
            return False
        if any(
            find_claim(v, r) is None
            for group in d.premise_groups
            for r in group
        ):
            return False
        if d.evidence is not None:
            if find_obs(v, d.evidence) is None:
                return False
        elif d.rule is RuleId.OBS_SUPPORTS:
            return False
        if not acyclic_deriv(v, d):
            return False
    for ref, _digest in v.validations:
        if find_claim(v, ref) is None:
            return False
    return True
