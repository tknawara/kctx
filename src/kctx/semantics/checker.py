"""Executable derivation checker mirroring ``formal/Kctx/Checker.lean``.

The rejection order is a wire contract with the Lean reference: the same
derivation must be rejected with the same code in the same order on both
sides. Guard order (mirrors ``checkDerivationV``):

1. ruleNotEnabled
2. missingPremise        (any premise ref unresolvable)
3. missingConclusion
4. conclusionPropMismatch
5. contestedConclusion
6. contestedPremise

then per-rule shape checks in the order written in each ``_check_*``
function. Do not reorder without a semantic-version bump.
"""

from __future__ import annotations

from typing import Optional, Tuple

from kctx.semantics.model import (
    ENABLED_RULES,
    Binding,
    Claim,
    ClaimProp,
    ClaimRef,
    CoverageWitness,
    Dep,
    DepKind,
    Derivation,
    EvalCtx,
    KbView,
    ObsOutcome,
    RuleId,
    Scope,
    SupportRole,
    find_claim,
    prop_of,
    scope_of,
    specializes,
)
from kctx.semantics.time import assess_fresh


class Rejection(Exception):
    """Structured rejection (wire name mirrors Lean ``Rejection``)."""

    NAMES = (
        "ruleNotEnabled",
        "missingPremise",
        "missingConclusion",
        "conclusionPropMismatch",
        "contestedConclusion",
        "contestedPremise",
        "ruleShapeMismatch",
        "evidenceNotOk",
        "evidenceNotFresh",
        "missingCoverage",
        "coverageIncomplete",
        "footprintIncomplete",
    )

    def __init__(self, name: str):
        assert name in self.NAMES, name
        super().__init__(name)
        self.name = name


def _premises_resolve(v: KbView, d: Derivation) -> bool:
    return all(
        find_claim(v, ref) is not None for group in d.premise_groups for ref in group
    )


def _conclusion_matches(v: KbView, d: Derivation) -> bool:
    c = find_claim(v, d.conclusion)
    return c is not None and c.prop == d.conclusion_prop


def _has_kb_record_dep(d: Derivation, target: str) -> bool:
    return Dep(DepKind.KB_RECORD, target, "") in d.footprint


def _has_discovery_dep(d: Derivation, target: str) -> bool:
    return Dep(DepKind.DISCOVERY, target, "") in d.footprint


def footprint_declares(v: KbView, d: Derivation) -> bool:
    """Every consulted record identity must be declared in the footprint
    (T12). Mirrors Lean ``footprintDeclares``."""
    conclusion_dep = _has_kb_record_dep(d, d.conclusion.id)
    if d.rule is RuleId.AND_INTRO:
        return conclusion_dep and all(
            _has_kb_record_dep(d, ref.id)
            for group in d.premise_groups
            for ref in group
        )
    if d.rule is RuleId.SPECIALIZE:
        if len(d.premise_groups) == 1 and len(d.premise_groups[0]) == 1:
            return conclusion_dep and _has_kb_record_dep(d, d.premise_groups[0][0].id)
        return False
    if d.rule is RuleId.OBS_SUPPORTS:
        return conclusion_dep and (
            d.evidence is not None and Dep(DepKind.KB_RECORD, d.evidence, "") in d.footprint
        )
    if d.rule is RuleId.ALL_CHECKED:
        return conclusion_dep and (
            d.witness is not None and _has_discovery_dep(d, d.witness.scope.project)
        )
    raise AssertionError(d.rule)


def and_intro_atoms(v: KbView, group: Tuple[ClaimRef, ...]) -> Tuple:
    from kctx.semantics.model import Atom

    out = []
    for ref in group:
        a = prop_of(v, ref).as_atom()
        if a is not None:
            out.append(a)
    return tuple(out)


def _check_and_intro(v: KbView, d: Derivation) -> None:
    if len(d.premise_groups) != 1:
        raise Rejection("ruleShapeMismatch")
    group = d.premise_groups[0]
    if not group:
        raise Rejection("ruleShapeMismatch")
    if any(
        (a := prop_of(v, ref).as_atom()) is None for ref in group
    ):
        raise Rejection("ruleShapeMismatch")
    if any(scope_of(v, ref) != d.scope for ref in group):
        raise Rejection("ruleShapeMismatch")
    if d.conclusion_prop != ClaimProp.conj(and_intro_atoms(v, group)):
        raise Rejection("ruleShapeMismatch")
    if not footprint_declares(v, d):
        raise Rejection("footprintIncomplete")


def _check_specialize(v: KbView, d: Derivation) -> None:
    if not (
        len(d.premise_groups) == 1 and len(d.premise_groups[0]) == 1
    ):
        raise Rejection("ruleShapeMismatch")
    ref = d.premise_groups[0][0]
    src = find_claim(v, ref)
    tgt = find_claim(v, d.conclusion)
    if src is None or tgt is None:
        raise Rejection("missingPremise")
    if src.prop != tgt.prop:
        raise Rejection("ruleShapeMismatch")
    if not specializes(tgt.scope, src.scope):
        raise Rejection("ruleShapeMismatch")
    if d.scope != tgt.scope:
        raise Rejection("ruleShapeMismatch")
    if not footprint_declares(v, d):
        raise Rejection("footprintIncomplete")


def _check_obs_supports(v: KbView, ctx: EvalCtx, d: Derivation) -> None:
    if d.premise_groups:
        raise Rejection("ruleShapeMismatch")
    if d.evidence is None:
        raise Rejection("ruleShapeMismatch")
    o = next((x for x in v.observations if x.id == d.evidence), None)
    if o is None:
        raise Rejection("missingPremise")
    if scope_of(v, d.conclusion) != d.scope:
        raise Rejection("ruleShapeMismatch")
    if d.conclusion_prop.as_atom() is None:
        raise Rejection("ruleShapeMismatch")
    if o.outcome is not ObsOutcome.OK:
        raise Rejection("evidenceNotOk")
    wanted = Binding(d.evidence, d.conclusion, SupportRole.SUPPORTS)
    if wanted not in v.bindings:
        raise Rejection("evidenceNotOk")
    if assess_fresh(o.ttl, o.observed_at, ctx.now).value != "fresh":
        raise Rejection("evidenceNotFresh")
    if not footprint_declares(v, d):
        raise Rejection("footprintIncomplete")


def _check_all_checked(v: KbView, d: Derivation) -> None:
    if d.premise_groups:
        raise Rejection("ruleShapeMismatch")
    w = d.witness
    if w is None:
        raise Rejection("missingCoverage")
    if not w.complete:
        raise Rejection("coverageIncomplete")
    if not w.members:
        raise Rejection("coverageIncomplete")
    if d.conclusion_prop.tag != "allChecked":
        raise Rejection("ruleShapeMismatch")
    if d.conclusion_prop.members != w.members:
        raise Rejection("ruleShapeMismatch")
    if w.scope != d.scope:
        raise Rejection("ruleShapeMismatch")
    if not footprint_declares(v, d):
        raise Rejection("footprintIncomplete")


def check_derivation_v(v: KbView, ctx: EvalCtx, d: Derivation) -> str:
    """Executable checker. Returns ``"accepted"`` or ``["rejected", code]``
    (exactly the Lean ``Verdict`` wire form)."""
    try:
        if d.rule not in ENABLED_RULES:
            raise Rejection("ruleNotEnabled")
        if not _premises_resolve(v, d):
            raise Rejection("missingPremise")
        if find_claim(v, d.conclusion) is None:
            raise Rejection("missingConclusion")
        if not _conclusion_matches(v, d):
            raise Rejection("conclusionPropMismatch")
        if any(c.target == d.conclusion for c in v.corrections):
            raise Rejection("contestedConclusion")
        if any(
            c.target in group for c in v.corrections for group in d.premise_groups
        ):
            raise Rejection("contestedPremise")
        if d.rule is RuleId.AND_INTRO:
            _check_and_intro(v, d)
        elif d.rule is RuleId.SPECIALIZE:
            _check_specialize(v, d)
        elif d.rule is RuleId.OBS_SUPPORTS:
            _check_obs_supports(v, ctx, d)
        else:
            _check_all_checked(v, d)
    except Rejection as r:
        return ["rejected", r.name]
    return "accepted"


def supported(v: KbView, ctx: EvalCtx, ref: ClaimRef) -> bool:
    return any(
        d.conclusion == ref and check_derivation_v(v, ctx, d) == "accepted"
        for d in v.derivations
    )


def has_fresh_evidence(v: KbView, ctx: EvalCtx, ref: ClaimRef) -> bool:
    return any(
        d.conclusion == ref
        and d.rule is RuleId.OBS_SUPPORTS
        and check_derivation_v(v, ctx, d) == "accepted"
        for d in v.derivations
    )


def contested(v: KbView, ref: ClaimRef) -> bool:
    return any(c.target == ref for c in v.corrections)


def validation_current(v: KbView, ref: ClaimRef) -> bool:
    return any(p[0] == ref for p in v.validations)


def usable_for(v: KbView, ctx: EvalCtx, ref: ClaimRef) -> bool:
    """T17: ``UsableFor`` is exactly the conjunction of the policy's
    mandatory conditions."""
    return (
        supported(v, ctx, ref)
        and (not ctx.require_fresh_evidence or has_fresh_evidence(v, ctx, ref))
        and (not ctx.require_validated or validation_current(v, ref))
        and (not ctx.require_uncontested or not contested(v, ref))
    )


def deps_satisfied(observed: list[Dep], required: Tuple[Dep, ...]) -> bool:
    return all(dep in observed for dep in required)


def reusable(v: KbView, ctx: EvalCtx, d: Derivation, observed: list[Dep]) -> bool:
    """T06: accepted check + complete declared footprint matched."""
    return check_derivation_v(v, ctx, d) == "accepted" and deps_satisfied(
        observed, d.footprint
    )
