"""Whole-candidate invariants, independent of support and policy admission."""

from __future__ import annotations

from kctx.semantics.model import (
    KB,
    SEMANTIC_VERSION,
    All,
    AllWitness,
    AndWitness,
    Atomic,
    AttestationDependency,
    AttestWitness,
    ClaimDependency,
    ClaimRef,
    Conjunction,
    Context,
    CorrectionKind,
    CorrectionsDependency,
    Dependency,
    EnumerationDependency,
    Formula,
    Inventory,
    ObservationDependency,
    Polarity,
    Scope,
    SpecializeWitness,
    Statement,
    Truth,
    TruthWitness,
    Ttl,
    TtlTag,
    Witness,
    find_claim,
    find_observation,
)


def nonempty(value: str) -> bool:
    return bool(value)


def natural(value: int) -> bool:
    return type(value) is int and value >= 0


def ttl_wf(ttl: Ttl) -> bool:
    if ttl.tag is TtlTag.EXPIRE_AFTER:
        return ttl.secs is not None and natural(ttl.secs)
    return ttl.secs is None


def scope_wf(scope: Scope) -> bool:
    return nonempty(scope.project.val)


def formula_wf(formula: Formula, kb: KB) -> bool:
    if isinstance(formula, Atomic):
        return bool(formula.atom.subject and formula.atom.predicate)
    if isinstance(formula, Truth):
        return True
    if isinstance(formula, Conjunction):
        return formula_wf(formula.left, kb) and formula_wf(formula.right, kb)
    return any(e.id == formula.enumeration for e in kb.enumerations) and (
        not isinstance(formula, All) or bool(formula.predicate)
    )


def statement_wf(statement: Statement, kb: KB) -> bool:
    return (
        scope_wf(statement.scope)
        and formula_wf(statement.formula, kb)
        and (statement.polarity is Polarity.POSITIVE or isinstance(statement.formula, Atomic))
    )


def context_wf(context: Context) -> bool:
    return (
        context.semantic_version == SEMANTIC_VERSION
        and natural(context.now)
        and context.ruleset.val == "core-2"
        and context.checker.val == "kctx-2"
        and scope_wf(context.target)
        and bool(context.intended_use)
        and len({source.source for source in context.sources}) == len(context.sources)
        and all(
            source.source.val and source.revision.val and source.content.val
            for source in context.sources
        )
        and len(set(context.policy.authorized_actors)) == len(context.policy.authorized_actors)
        and all(actor.val for actor in context.policy.authorized_actors)
        and ttl_wf(context.policy.ttl)
    )


def witness_wf(witness: Witness, kb: KB) -> bool:
    if isinstance(witness, AttestWitness):
        return any(a.id == witness.attestation for a in kb.attestations)
    if isinstance(witness, TruthWitness):
        return scope_wf(witness.scope)
    if isinstance(witness, AndWitness):
        return witness_wf(witness.left, kb) and witness_wf(witness.right, kb)
    if isinstance(witness, SpecializeWitness):
        return scope_wf(witness.scope) and witness_wf(witness.premise, kb)
    return (
        any(e.id == witness.enumeration for e in kb.enumerations)
        and (not isinstance(witness, AllWitness) or bool(witness.predicate))
        and witness_wf(witness.premise, kb)
    )


def dependency_wf(dependency: Dependency, kb: KB) -> bool:
    if isinstance(dependency, ObservationDependency):
        return dependency.value in kb.observations
    if isinstance(dependency, ClaimDependency):
        return dependency.value in kb.claims
    if isinstance(dependency, AttestationDependency):
        return dependency.value in kb.attestations
    if isinstance(dependency, EnumerationDependency):
        return dependency.value in kb.enumerations
    if isinstance(dependency, CorrectionsDependency):
        return find_claim(kb, dependency.target) is not None and all(
            event in kb.corrections and event.target == dependency.target
            for event in dependency.events
        )
    return context_wf(dependency.value) and dependency.value.now == 0


def well_formed(kb: KB) -> bool:
    """Unsupported claims are valid candidates, never automatically admissions."""
    keys = (
        tuple(o.id for o in kb.observations),
        tuple(c.ref for c in kb.claims),
        tuple(a.id for a in kb.attestations),
        tuple(e.id for e in kb.enumerations),
        tuple(d.id for d in kb.derivations),
        tuple(c.id for c in kb.corrections),
        tuple(r.id for r in kb.receipts),
    )
    if any(len(set(group)) != len(group) for group in keys):
        return False
    if any(
        not (o.source.val and o.revision.val and o.content.val and natural(o.observed_at))
        for o in kb.observations
    ):
        return False
    if any(not statement_wf(c.statement, kb) for c in kb.claims):
        return False
    for attestation in kb.attestations:
        claim = find_claim(kb, attestation.claim)
        if (
            claim is None
            or claim.statement != attestation.statement
            or not isinstance(attestation.statement.formula, (Atomic, Inventory))
            or not attestation.authority.val
            or find_observation(kb, attestation.observation) is None
        ):
            return False
        formula = attestation.statement.formula
        if isinstance(formula, Inventory):
            enumeration = next((e for e in kb.enumerations if e.id == formula.enumeration), None)
            if (
                enumeration is None
                or attestation.statement.polarity is not Polarity.POSITIVE
                or attestation.observation != enumeration.observation
                or attestation.statement.scope != enumeration.scope
            ):
                return False
    for enumeration in kb.enumerations:
        observation = find_observation(kb, enumeration.observation)
        if (
            observation is None
            or observation.source != enumeration.source
            or observation.revision != enumeration.revision
            or not enumeration.query
            or not enumeration.method
            or not scope_wf(enumeration.scope)
            or enumeration.members != enumeration.universe
            or len(set(enumeration.members)) != len(enumeration.members)
            or any(not member for member in enumeration.members)
        ):
            return False
    if any(
        find_claim(kb, d.claim) is None or not witness_wf(d.witness, kb) for d in kb.derivations
    ):
        return False
    for correction in kb.corrections:
        if find_claim(kb, correction.target) is None or not natural(correction.recorded_at):
            return False
        if correction.kind is CorrectionKind.SUPERSEDE:
            if correction.replacement is None or find_claim(kb, correction.replacement) is None:
                return False
        elif correction.replacement is not None:
            return False
    for start in (c.ref for c in kb.claims):
        frontier = [start]
        seen: set[ClaimRef] = set()
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            for correction in kb.corrections:
                if correction.kind is CorrectionKind.SUPERSEDE and correction.target == current:
                    if correction.replacement == start:
                        return False
                    if correction.replacement is not None:
                        frontier.append(correction.replacement)
    for receipt in kb.receipts:
        if (
            find_claim(kb, receipt.claim) is None
            or not context_wf(receipt.context)
            or not witness_wf(receipt.witness, kb)
            or not natural(receipt.expires_at)
            or any(not dependency_wf(dependency, kb) for dependency in receipt.dependencies)
        ):
            return False
    return True
