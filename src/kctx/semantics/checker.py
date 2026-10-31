"""Recursive, finite support checking. Acquisition success alone proves nothing."""

from __future__ import annotations

from dataclasses import replace

from kctx.domain.ids import ContentId
from kctx.semantics.model import (
    KB,
    Absent,
    AbsentWitness,
    All,
    AndWitness,
    Assessment,
    Atomic,
    AttestationDependency,
    AttestWitness,
    Checked,
    ClaimDependency,
    ClaimRef,
    Conjunction,
    Context,
    ContextDependency,
    CorrectionKind,
    CorrectionsDependency,
    Dependency,
    EnumerationDependency,
    Freshness,
    Inventory,
    Observation,
    ObservationDependency,
    ObsOutcome,
    Polarity,
    Receipt,
    ReceiptResult,
    SpecializeWitness,
    Statement,
    Support,
    Truth,
    TruthWitness,
    Witness,
    find_claim,
    find_observation,
    member_formula,
    narrower,
)
from kctx.semantics.time import assess_fresh
from kctx.semantics.wellformed import context_wf


def context_matches(kb: KB, context: Context) -> bool:
    return kb.snapshot == context.snapshot and context_wf(context)


def source_selected(context: Context, observation: Observation) -> bool:
    return any(
        source.source == observation.source
        and source.revision == observation.revision
        and source.content == observation.content
        for source in context.sources
    )


def inventory_content(members: tuple[str, ...]) -> ContentId:
    return ContentId(
        "inventory:" + "".join(f"{len(member.encode('utf-8'))}:{member}" for member in members)
    )


def retracted(kb: KB, context: Context, ref: ClaimRef) -> bool:
    return any(
        c.kind is CorrectionKind.RETRACT and c.target == ref and c.recorded_at <= context.now
        for c in kb.corrections
    )


def dependencies_union(
    left: tuple[Dependency, ...], right: tuple[Dependency, ...]
) -> tuple[Dependency, ...]:
    return tuple(dict.fromkeys((*left, *right)))


def _check(kb: KB, context: Context, witness: Witness) -> Checked | None:
    if not context_matches(kb, context):
        return None
    if isinstance(witness, AttestWitness):
        attestation = next((a for a in kb.attestations if a.id == witness.attestation), None)
        if attestation is None or retracted(kb, context, attestation.claim):
            return None
        claim = find_claim(kb, attestation.claim)
        observation = find_observation(kb, attestation.observation)
        if (
            claim is None
            or claim.statement != attestation.statement
            or not isinstance(attestation.statement.formula, (Atomic, Inventory))
            or not attestation.authority.val
            or observation is None
            or observation.outcome is not ObsOutcome.OK
            or observation.observed_at > context.now
            or not source_selected(context, observation)
        ):
            return None
        dependencies: tuple[Dependency, ...] = (
            ObservationDependency(observation),
            ClaimDependency(claim),
            AttestationDependency(attestation),
            correction_dependency(kb, context, attestation.claim),
        )
        formula = attestation.statement.formula
        if isinstance(formula, Inventory):
            enumeration = next((e for e in kb.enumerations if e.id == formula.enumeration), None)
            if (
                enumeration is None
                or attestation.statement.polarity is not Polarity.POSITIVE
                or attestation.observation != enumeration.observation
                or attestation.statement.scope != enumeration.scope
            ):
                return None
            dependencies = (*dependencies, EnumerationDependency(enumeration))
        return Checked(attestation.statement, dependencies)
    if isinstance(witness, TruthWitness):
        return Checked(Statement(Truth(), witness.scope), ())
    if isinstance(witness, AndWitness):
        left = _check(kb, context, witness.left)
        right = _check(kb, context, witness.right)
        if (
            left is None
            or right is None
            or left.statement.scope != right.statement.scope
            or left.statement.polarity is not Polarity.POSITIVE
            or right.statement.polarity is not Polarity.POSITIVE
        ):
            return None
        return Checked(
            Statement(
                Conjunction(left.statement.formula, right.statement.formula), left.statement.scope
            ),
            dependencies_union(left.dependencies, right.dependencies),
        )
    if isinstance(witness, SpecializeWitness):
        premise = _check(kb, context, witness.premise)
        if premise is None or not narrower(witness.scope, premise.statement.scope):
            return None
        return Checked(replace(premise.statement, scope=witness.scope), premise.dependencies)
    enumeration = next((e for e in kb.enumerations if e.id == witness.enumeration), None)
    if enumeration is None:
        return None
    observation = find_observation(kb, enumeration.observation)
    if (
        observation is None
        or observation.outcome is not ObsOutcome.OK
        or observation.observed_at > context.now
        or not source_selected(context, observation)
        or observation.content != inventory_content(enumeration.universe)
        or observation.source != enumeration.source
        or observation.revision != enumeration.revision
        or enumeration.members != enumeration.universe
        or len(set(enumeration.members)) != len(enumeration.members)
        or not enumeration.method
        or not enumeration.query
    ):
        return None
    if isinstance(witness, AbsentWitness):
        premise = _check(kb, context, witness.premise)
        if (
            enumeration.members
            or premise is None
            or premise.statement != Statement(Inventory(enumeration.id), enumeration.scope)
        ):
            return None
        return Checked(
            Statement(Absent(enumeration.id), enumeration.scope),
            dependencies_union(
                premise.dependencies,
                (ObservationDependency(observation), EnumerationDependency(enumeration)),
            ),
        )
    premise = _check(kb, context, witness.premise)
    expected = Statement(
        Conjunction(
            Inventory(enumeration.id), member_formula(enumeration.members, witness.predicate)
        ),
        enumeration.scope,
    )
    if premise is None or premise.statement != expected or not witness.predicate:
        return None
    return Checked(
        Statement(All(enumeration.id, witness.predicate), enumeration.scope),
        dependencies_union(
            premise.dependencies,
            (ObservationDependency(observation), EnumerationDependency(enumeration)),
        ),
    )


def correction_dependency(kb: KB, context: Context, ref: ClaimRef) -> CorrectionsDependency:
    return CorrectionsDependency(
        ref, tuple(c for c in kb.corrections if c.target == ref and c.recorded_at <= context.now)
    )


def check(kb: KB, context: Context, witness: Witness) -> Checked | None:
    result = _check(kb, context, witness)
    if result is None:
        return None
    return replace(
        result,
        dependencies=dependencies_union(
            result.dependencies, (ContextDependency(replace(context, now=0)),)
        ),
    )


def accepted(kb: KB, context: Context, ref: ClaimRef) -> tuple[tuple[Witness, Checked], ...]:
    claim = find_claim(kb, ref)
    if claim is None or retracted(kb, context, ref):
        return ()
    results: list[tuple[Witness, Checked]] = []
    for derivation in kb.derivations:
        if derivation.claim == ref:
            result = _check(kb, context, derivation.witness)
            if result is not None and result.statement == claim.statement:
                result = replace(
                    result,
                    dependencies=dependencies_union(
                        result.dependencies,
                        (
                            ClaimDependency(claim),
                            correction_dependency(kb, context, ref),
                            ContextDependency(replace(context, now=0)),
                        ),
                    ),
                )
                results.append((derivation.witness, result))
    return tuple(results)


def supported(kb: KB, context: Context, ref: ClaimRef, polarity: Polarity) -> bool:
    claim = find_claim(kb, ref)
    if claim is None:
        return False
    if polarity is claim.statement.polarity:
        return bool(accepted(kb, context, ref))
    if not isinstance(claim.statement.formula, Atomic):
        return False
    statement = replace(claim.statement, polarity=polarity)
    return any(c.statement == statement and accepted(kb, context, c.ref) for c in kb.claims)


def same_context(left: Context, right: Context) -> bool:
    return replace(left, now=right.now) == right


def reusable(kb: KB, context: Context, ref: ClaimRef, receipt: Receipt) -> bool:
    if (
        receipt.claim != ref
        or receipt.result is not ReceiptResult.PASS
        or not same_context(receipt.context, context)
        or not receipt.context.now <= context.now <= receipt.expires_at
    ):
        return False
    return any(
        witness == receipt.witness and checked.dependencies == receipt.dependencies
        for witness, checked in accepted(kb, context, ref)
    )


def witness_freshness(context: Context, dependencies: tuple[Dependency, ...]) -> Freshness:
    observations = tuple(d.value for d in dependencies if isinstance(d, ObservationDependency))
    if not observations:
        return Freshness.UNKNOWN
    states = tuple(
        assess_fresh(context.policy.ttl, o.observed_at, context.now) for o in observations
    )
    if Freshness.STALE in states:
        return Freshness.STALE
    if Freshness.UNKNOWN in states:
        return Freshness.UNKNOWN
    return Freshness.FRESH


def policy_allows(
    supported_positive: bool,
    fresh: bool,
    validated: bool,
    uncontested: bool,
    require_fresh: bool,
    require_validated: bool,
    require_uncontested: bool,
) -> bool:
    """T17 Boolean leaf; Nagini verifies only this leaf, not recursive checking."""
    if not supported_positive:
        return False
    if require_fresh and not fresh:
        return False
    if require_validated and not validated:
        return False
    if require_uncontested and not uncontested:
        return False
    return True


def assess(kb: KB, context: Context, ref: ClaimRef) -> Assessment:
    claim = find_claim(kb, ref)
    positive = supported(kb, context, ref, Polarity.POSITIVE)
    negative = supported(kb, context, ref, Polarity.NEGATIVE)
    support = (
        Support.BOTH
        if positive and negative
        else Support.POSITIVE
        if positive
        else Support.NEGATIVE
        if negative
        else Support.NONE
    )
    applicable = (
        claim is not None
        and context_matches(kb, context)
        and narrower(context.target, claim.statement.scope)
    )
    alternatives = tuple(result for _, result in accepted(kb, context, ref))
    states = tuple(witness_freshness(context, result.dependencies) for result in alternatives)
    freshness = (
        Freshness.FRESH
        if Freshness.FRESH in states
        else Freshness.STALE
        if states and all(s is Freshness.STALE for s in states)
        else Freshness.UNKNOWN
    )
    validated = any(reusable(kb, context, ref, r) for r in kb.receipts)
    selected_support = (
        negative
        if claim is not None and claim.statement.polarity is Polarity.NEGATIVE
        else positive
    )
    contrary_support = (
        positive
        if claim is not None and claim.statement.polarity is Polarity.NEGATIVE
        else negative
    )
    contested = contrary_support or any(
        c.target == ref and c.kind is CorrectionKind.DISPUTE and c.recorded_at <= context.now
        for c in kb.corrections
    )
    available = positive or negative
    usable = applicable and policy_allows(
        selected_support,
        freshness is Freshness.FRESH,
        validated,
        not contested,
        context.policy.require_fresh,
        context.policy.require_validation,
        context.policy.require_uncontested,
    )
    return Assessment(support, applicable, freshness, validated, contested, available, usable)


def usable_for(kb: KB, context: Context, ref: ClaimRef) -> bool:
    return assess(kb, context, ref).usable
