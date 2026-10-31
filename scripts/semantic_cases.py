"""Finite v2 fixtures with independently authored expected outcomes.

Expected decisions never call the production checker. Constructors/encoders only
supply data; full responses and stateful journals are compared by the harness.
"""
from __future__ import annotations

from dataclasses import replace
from itertools import product

from kctx.domain.ids import (
    AttestationId, ClaimId, ClaimRevision, CorrectionId, DerivationId, EnumerationId,
    ObservationId, OperationId, ReceiptId, SnapshotId,
    SourceId, SourceRevision, ContentId, ProjectId, ActorId, CheckerId, ProposalMaterialRevision, TargetRevision,
)
from kctx.semantics import model as M
from kctx.semantics import wire
from tests.semantics.examples import REF, SCOPE, STATEMENT, WITNESS, context, negative_kb, plan, valid_kb


def envelope(ident: str, operation: str, **fields: object) -> dict[str, object]:
    return {"schema_version": 2, "semantic_version": "2.0.0", "id": ident, "op": operation, **fields}


def case(ident: str, operation: str, expected: object, **fields: object) -> dict[str, object]:
    return {**envelope(ident, operation, **fields), "expected": expected}


def semantic(ident: str, operation: str, expected: object, *, kb: M.KB | None = None,
             ctx: M.Context | None = None, **fields: object) -> dict[str, object]:
    return case(ident, operation, expected, kb=wire.enc_kb(valid_kb() if kb is None else kb),
                context=wire.enc_context(context() if ctx is None else ctx), **fields)


def assessment(*, support: str = "positive", applicable: bool = True, freshness: str = "fresh",
               validated: bool = False, contested: bool = False, available: bool = True,
               usable: bool = True) -> dict[str, object]:
    return {"support": support, "applicable": applicable, "freshness": freshness, "validated": validated,
            "contested": contested, "available": available, "usable": usable}


def leaf_dependencies(kb: M.KB, ctx: M.Context) -> tuple[M.Dependency, ...]:
    """Authored expected footprint of this one exact attestation, not checker output."""
    return (M.ObservationDependency(kb.observations[0]), M.ClaimDependency(kb.claims[0]),
            M.AttestationDependency(kb.attestations[0]), M.CorrectionsDependency(REF, ()),
            M.ContextDependency(replace(ctx, now=0)))


def receipt(kb: M.KB, ctx: M.Context) -> M.Receipt:
    return M.Receipt(ReceiptId("receipt-1"), REF, ctx, WITNESS, leaf_dependencies(kb, ctx), M.ReceiptResult.PASS, 120)


def reviewed_cases() -> list[dict[str, object]]:
    kb, ctx = valid_kb(), context()
    ref = wire.enc_ref(REF)
    result = [
        semantic("positive-attestation", "assess", assessment(), claim=ref),
        semantic("both-polarities-remain-visible", "assess", assessment(support="both", contested=True, usable=False), kb=negative_kb(), claim=ref),
        semantic("inclusive-evidence-ttl", "usable", True, claim=ref),
        semantic("expired-evidence-does-not-erase-support", "assess", assessment(freshness="stale", usable=False), ctx=replace(ctx, now=111), claim=ref),
        semantic("unknown-ttl-not-fresh", "usable", False, ctx=replace(ctx, policy=replace(ctx.policy, ttl=M.TTL_MISSING)), claim=ref),
        semantic("explicit-noexpiry-remains-fresh", "usable", True,
                 ctx=replace(ctx, now=10**12, policy=replace(ctx.policy, ttl=M.TTL_NO_EXPIRY)), claim=ref),
        semantic("missing-policy-never-becomes-noexpiry", "usable", False,
                 ctx=replace(ctx, now=10**12, policy=replace(ctx.policy, ttl=M.TTL_MISSING)), claim=ref),
        semantic("noexpiry-does-not-admit-future-acquisition", "usable", False,
                 ctx=replace(ctx, now=99, policy=replace(ctx.policy, ttl=M.TTL_NO_EXPIRY)), claim=ref),
        semantic("target-scope-must-apply", "usable", False, ctx=replace(ctx, target=M.Scope(ProjectId("other"), "")), claim=ref),
        semantic("snapshot-must-match", "usable", False, ctx=replace(ctx, snapshot=SnapshotId("other")), claim=ref),
        semantic("unsupported-atom-remains-false", "supported", False, kb=replace(kb, derivations=()), claim=ref, polarity="positive"),
        semantic("acquisition-alone-not-truth", "supported", False, kb=replace(kb, attestations=(), derivations=()), claim=ref, polarity="positive"),
        semantic("retained-footprint-complete", "check", {"statement": wire.enc_statement(STATEMENT),
                 "dependencies": [wire.enc_dependency(d) for d in leaf_dependencies(kb, ctx)]}, witness=wire.enc_witness(WITNESS)),
        semantic("unsupported-premise-specialize", "check", None, witness=wire.enc_witness(M.SpecializeWitness(SCOPE, M.AttestWitness(AttestationId("missing"))))),
        semantic("scope-widening-rejected", "check", None, witness=wire.enc_witness(M.SpecializeWitness(M.Scope(ProjectId("other"), ""), WITNESS))),
        semantic("receipt-exact-inputs", "reuse", True, claim=ref, receipt=wire.enc_receipt(receipt(kb, ctx))),
        semantic("receipt-dropped-dependency", "reuse", False, claim=ref, receipt=wire.enc_receipt(replace(receipt(kb, ctx), dependencies=leaf_dependencies(kb, ctx)[1:]))),
        semantic("receipt-swapped-target", "reuse", False, claim=ref, receipt=wire.enc_receipt(replace(receipt(kb, ctx), context=replace(ctx, target=M.Scope(ProjectId("payments"), "staging"))))),
        semantic("receipt-expired", "reuse", False, claim=ref, receipt=wire.enc_receipt(replace(receipt(kb, ctx), expires_at=109))),
        semantic("receipt-failed", "reuse", False, claim=ref, receipt=wire.enc_receipt(replace(receipt(kb, ctx), result=M.ReceiptResult.FAIL))),
    ]
    dispute = M.Correction(CorrectionId("dispute-1"), M.CorrectionKind.DISPUTE, REF, None, 105)
    result.append(semantic("dispute-preserves-support", "assess", assessment(contested=True, usable=False), kb=replace(kb, corrections=(dispute,)), claim=ref))
    retract = replace(dispute, kind=M.CorrectionKind.RETRACT)
    result.append(semantic("retract-exact-support", "assess", assessment(support="none", freshness="unknown", available=False, usable=False), kb=replace(kb, corrections=(retract,)), claim=ref))
    result.append(semantic("historical-selection-excludes-later-correction", "usable", True, kb=replace(kb, corrections=(replace(retract, recorded_at=111),)), claim=ref))
    result.append(semantic("future-acquisition-excluded", "supported", False, ctx=replace(ctx, now=99), claim=ref, polarity="positive"))
    replacement = M.Claim(ClaimId("replacement"), ClaimRevision("r1"), replace(STATEMENT, formula=M.Atomic(M.Atom("new", "claim"))))
    superseded = replace(kb, claims=(*kb.claims, replacement), corrections=(M.Correction(CorrectionId("supersede-1"), M.CorrectionKind.SUPERSEDE, REF, replacement.ref, 105),))
    result.append(semantic("supersession-transfers-no-support", "supported", False, kb=superseded, claim=wire.enc_ref(replacement.ref), polarity="positive"))
    result.append(semantic("supersession-does-not-retract-source", "supported", True, kb=superseded, claim=ref, polarity="positive"))
    identical = replace(kb.claims[0], revision=ClaimRevision("r2"))
    identical_kb = replace(kb, claims=(*kb.claims, identical), corrections=(
        M.Correction(CorrectionId("same-statement-supersede"), M.CorrectionKind.SUPERSEDE, REF, identical.ref, 105),))
    result.append(semantic("identical-statement-revision-needs-own-support", "supported", False,
                           kb=identical_kb, claim=wire.enc_ref(identical.ref), polarity="positive"))
    result.append(semantic("identical-statement-revision-does-not-inherit-validation", "assess",
                           assessment(support="none", freshness="unknown", available=False, usable=False),
                           kb=replace(identical_kb, receipts=(receipt(kb, ctx),)), claim=wire.enc_ref(identical.ref)))
    # Scope mismatch on a stored conclusion remains a candidate, not support.
    widened = M.Claim(ClaimId("widened"), ClaimRevision("r1"),
                      M.Statement(M.Conjunction(STATEMENT.formula, STATEMENT.formula), SCOPE))
    staging = M.SpecializeWitness(M.Scope(ProjectId("payments"), "staging"), WITNESS)
    scope_kb = replace(kb, claims=(*kb.claims, widened), derivations=(*kb.derivations,
                       M.Derivation(DerivationId("widened-d"), widened.ref, M.AndWitness(staging, staging))))
    result.append(semantic("andintro-conclusion-scope-widening", "supported", False, kb=scope_kb, claim=wire.enc_ref(widened.ref), polarity="positive"))
    # Finite inventory requires independent exact completeness attestation.
    enum_id = EnumerationId("inventory-1")
    inventory_obs = M.Observation(ObservationId("inventory-observation"), SourceId("index:payments"), SourceRevision("index-1"), ContentId("inventory:5:batch"), 100, M.ObsOutcome.OK)
    enumeration = M.Enumeration(enum_id, inventory_obs.source, inventory_obs.revision, "all batches", SCOPE, inventory_obs.id, ("batch",), ("batch",), "finite-index")
    coverage_ctx = replace(ctx, sources=(*ctx.sources, M.SourceSelection(inventory_obs.source, inventory_obs.revision, inventory_obs.content)))
    certificate = M.Claim(ClaimId("inventory-certificate"), ClaimRevision("r1"), M.Statement(M.Inventory(enum_id), SCOPE))
    certificate_attestation = M.Attestation(AttestationId("inventory-certificate-attestation"), certificate.ref, inventory_obs.id, certificate.statement, ActorId("inventory-reviewer"))
    certificate_witness = M.AttestWitness(certificate_attestation.id)
    enum_kb = replace(kb, observations=(*kb.observations, inventory_obs), enumerations=(enumeration,),
                      claims=(*kb.claims, certificate), attestations=(*kb.attestations, certificate_attestation))
    result.append(semantic("coverage-assertion-without-member-evidence", "check", None, kb=enum_kb, ctx=coverage_ctx,
                           witness=wire.enc_witness(M.AllWitness(enum_id, "checked", M.AndWitness(certificate_witness, M.TruthWitness(SCOPE))))))
    result.append(semantic("nonempty-enumeration-not-absence", "check", None, kb=enum_kb, ctx=coverage_ctx,
                           witness=wire.enc_witness(M.AbsentWitness(enum_id, certificate_witness))))
    empty_enum = replace(enumeration, members=(), universe=())
    empty_obs = replace(inventory_obs, content=ContentId("inventory:"))
    empty_ctx = replace(ctx, sources=(*ctx.sources, M.SourceSelection(empty_obs.source, empty_obs.revision, empty_obs.content)))
    empty_kb = replace(enum_kb, observations=(*kb.observations, empty_obs), enumerations=(empty_enum,))
    certificate_dependencies: tuple[M.Dependency, ...] = (
        M.ObservationDependency(empty_obs), M.ClaimDependency(certificate), M.AttestationDependency(certificate_attestation),
        M.CorrectionsDependency(certificate.ref, ()), M.EnumerationDependency(empty_enum), M.ContextDependency(replace(empty_ctx, now=0)),
    )
    expected_empty = {"statement": wire.enc_statement(M.Statement(M.Absent(enum_id), SCOPE)),
                      "dependencies": [wire.enc_dependency(d) for d in certificate_dependencies]}
    result.append(semantic("certified-empty-domain-proves-scoped-absence", "check", expected_empty, kb=empty_kb, ctx=empty_ctx,
                           witness=wire.enc_witness(M.AbsentWitness(enum_id, certificate_witness))))
    result.append(semantic("empty-retained-list-alone-not-absence", "check", None, kb=empty_kb, ctx=empty_ctx,
                           witness=wire.enc_witness(M.AbsentWitness(enum_id, M.TruthWitness(SCOPE)))))
    result.append(semantic("unbound-inventory-does-not-prove-absence", "check", None,
                           kb=replace(empty_kb, observations=(*kb.observations, inventory_obs)), ctx=coverage_ctx,
                           witness=wire.enc_witness(M.AbsentWitness(enum_id, certificate_witness))))
    member = M.Claim(ClaimId("member"), ClaimRevision("r1"), M.Statement(M.Atomic(M.Atom("batch", "checked")), SCOPE))
    member_attestation = M.Attestation(AttestationId("member-attestation"), member.ref, kb.observations[0].id, member.statement, ActorId("reviewer-key"))
    member_witness = M.AttestWitness(member_attestation.id)
    full_kb = replace(enum_kb, claims=(*enum_kb.claims, member), attestations=(*enum_kb.attestations, member_attestation))
    member_proof = M.AndWitness(member_witness, M.TruthWitness(SCOPE))
    all_witness = M.AllWitness(enum_id, "checked", M.AndWitness(certificate_witness, member_proof))
    all_dependencies: tuple[M.Dependency, ...] = (
        M.ObservationDependency(inventory_obs), M.ClaimDependency(certificate), M.AttestationDependency(certificate_attestation),
        M.CorrectionsDependency(certificate.ref, ()), M.EnumerationDependency(enumeration),
        M.ObservationDependency(kb.observations[0]), M.ClaimDependency(member),
        M.AttestationDependency(member_attestation), M.CorrectionsDependency(member.ref, ()),
        M.ContextDependency(replace(coverage_ctx, now=0)),
    )
    result.append(semantic("all-members-and-completeness-recursively-proven", "check",
                           {"statement": wire.enc_statement(M.Statement(M.All(enum_id, "checked"), SCOPE)),
                            "dependencies": [wire.enc_dependency(d) for d in all_dependencies]},
                           kb=full_kb, ctx=coverage_ctx, witness=wire.enc_witness(all_witness)))
    result.append(semantic("member-evidence-without-inventory-certificate-rejected", "check", None,
                           kb=full_kb, ctx=coverage_ctx, witness=wire.enc_witness(M.AllWitness(enum_id, "checked", member_proof))))
    narrow_scope = M.Scope(ProjectId("payments"), "staging")
    result.append(semantic("explicit-specialization-retains-origin", "check",
                           {"statement": wire.enc_statement(replace(STATEMENT, scope=narrow_scope)),
                            "dependencies": [wire.enc_dependency(d) for d in leaf_dependencies(kb, ctx)]},
                           witness=wire.enc_witness(M.SpecializeWitness(narrow_scope, WITNESS))))
    strict_ctx = replace(ctx, policy=replace(ctx.policy, require_validation=True))
    forged = replace(receipt(kb, strict_ctx), dependencies=())
    result.append(semantic("validation-digest-empty-and-contradiction-ignored", "usable", False,
                           kb=replace(negative_kb(), receipts=(forged,)), ctx=strict_ctx, claim=ref))
    result.append(semantic("unobserved-required-source-still-usable", "usable", False,
                           kb=replace(kb, receipts=(forged,)), ctx=strict_ctx, claim=ref))
    proposal: dict[str, object] = {"id": "proposal-1", "revision": "r1", "target": ref, "status": "approved", "actor": "reviewer", "executor": "builder", "acceptor": "approver", "gates": []}
    result.append(semantic("skipped-gate-not-applied", "transition", False, proposal=proposal, target_status="applied"))
    result.append(semantic("empty-actor-not-applied", "transition", False, proposal={**proposal, "actor": ""}, target_status="applied"))
    gated = replace(kb, receipts=(receipt(kb, ctx),))
    result.append(semantic("bound-gate-applies", "transition", True, kb=gated, proposal={**proposal, "gates": ["receipt-1"]}, target_status="applied"))
    result.append(semantic("executor-cannot-self-accept", "transition", False, kb=gated, proposal={**proposal, "status": "applied", "acceptor": "builder", "gates": ["receipt-1"]}, target_status="verified"))
    result.append(semantic("whitespace-actor-not-applied", "transition", False, kb=gated,
                           proposal={**proposal, "actor": " \t", "gates": ["receipt-1"]}, target_status="applied"))
    investigation = {"checked_against": "commit-1", "scope_and_limits": "payments only", "hypotheses": [{"text": "Checked source limits", "status": "supported"}]}
    result.append(case("investigation-structurally-complete", "conclude", True, investigation=investigation))
    result.append(case("investigation-open-blocked", "conclude", False, investigation={**investigation, "hypotheses": [{"text": "Unresolved", "status": "open"}]}))
    result.append(case("investigation-whitespace-blocked", "conclude", False, investigation={**investigation, "checked_against": " "}))
    result.append(case("investigation-unknown-permitted", "conclude", True, investigation={**investigation, "hypotheses": [{"text": "Uncertain", "status": "unk"}]}))
    result.append(case("investigation-empty-hypotheses-permitted", "conclude", True, investigation={**investigation, "hypotheses": []}))
    result.append(semantic("retrieval-pins-and-discloses-omissions", "retrieve", {"snapshot": "snapshot-1", "records": [], "omitted": 1, "complete": False, "next_offset": 0}, offset=0, limit=0))
    result.append(semantic("retrieval-complete-page", "retrieve", {"snapshot": "snapshot-1", "records": [{"claim": wire.enc_claim(kb.claims[0]), "assessment": assessment()}], "omitted": 0, "complete": True, "next_offset": None}, offset=0, limit=1))
    invalid: list[dict[str, object]] = [
        {**envelope("unchecked-envelope-version", "fresh", now=100, observed_at=100, ttl=1), "schema_version": 999},
        envelope("unknown-operation-rejected", "assess_fresh", now=100, observed_at=100, ttl=1),
        envelope("duplicate-identity-rejected", "validate", kb=wire.enc_kb(replace(kb, observations=kb.observations * 2))),
        semantic("unknown-checker-rejected", "usable", False, claim=ref),
        envelope("cyclic-specialize-tag-rejected", "check", kb=wire.enc_kb(kb), context=wire.enc_context(ctx), witness={"tag": "reference", "derivation": "self"}),
        envelope("retrieval-wrong-snapshot-rejected", "retrieve", kb=wire.enc_kb(kb),
                 context=wire.enc_context(replace(ctx, snapshot=SnapshotId("other"))), offset=0, limit=1),
        envelope("sequence-wrong-snapshot-rejected", "sequence", kb=wire.enc_kb(kb),
                 context=wire.enc_context(replace(ctx, snapshot=SnapshotId("other"))), journal=[], plans=[]),
        envelope("request-cannot-self-issue-trust", "admit", kb=wire.enc_kb(M.KB(SnapshotId("snapshot-0"))),
                 context=wire.enc_context(context("snapshot-0")), plan=wire.enc_plan(plan()), trusted_approvals=[wire.enc_plan(plan())]),
        envelope("noncanonical-context-dependency-rejected", "validate", kb=wire.enc_kb(replace(
            kb, receipts=(replace(receipt(kb, ctx), dependencies=(
                *leaf_dependencies(kb, ctx)[:-1], M.ContextDependency(ctx))),)))),
    ]
    unknown_context = dict(wire.enc_context(ctx)); unknown_context["checker"] = "unknown"
    invalid[3]["context"] = unknown_context
    invalid[3].pop("expected", None)
    for request in invalid:
        request["expected_response"] = {"id": request["id"], "ok": False, "error": "invalid_request"}
    current_observation = replace(kb.observations[0], id=ObservationId("capture-r2"), revision=SourceRevision("commit-2"), content=ContentId("sha256:changed"))
    current_kb = replace(kb, observations=(*kb.observations, current_observation))
    current_ctx = replace(ctx, sources=(M.SourceSelection(current_observation.source, current_observation.revision, current_observation.content),))
    result.append(semantic("selected-r2-does-not-reuse-retained-r1", "supported", False, kb=current_kb, ctx=current_ctx, claim=ref, polarity="positive"))
    result.append(semantic("historically-selected-r1-retains-own-support", "supported", True, kb=current_kb, ctx=ctx, claim=ref, polarity="positive"))
    result.append(semantic("empty-source-selection-proves-no-captured-claim", "supported", False, ctx=replace(ctx, sources=()), claim=ref, polarity="positive"))
    return result + invalid + authored_cases() + raw_cases()


def generated_cases() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    policies = (M.TTL_MISSING, M.TTL_NO_EXPIRY, M.ttl_expire_after(0), M.ttl_expire_after(10))
    for outcome, now, ttl in product(tuple(M.ObsOutcome), (99, 100, 110, 111), policies):
        kb = valid_kb()
        kb = replace(kb, observations=(replace(kb.observations[0], outcome=outcome),))
        ctx = replace(context(now=now), policy=replace(context().policy, ttl=ttl))
        expected = outcome is M.ObsOutcome.OK and now >= 100 and (
            ttl.tag is M.TtlTag.NO_EXPIRY or ttl.tag is M.TtlTag.EXPIRE_AFTER and ttl.secs is not None and now <= 100 + ttl.secs)
        result.append(semantic(f"generated-{outcome.value}-{now}-{ttl.tag.value}-{ttl.secs}", "usable", expected,
                               kb=kb, ctx=ctx, claim=wire.enc_ref(REF)))
    for field, invalid_value in product(("schema_version", "semantic_version", "now", "ttl"), (True, -1, "unknown")):
        request = envelope(f"generated-invalid-{field}-{invalid_value}", "fresh", now=110, observed_at=100, ttl=10)
        request[field] = invalid_value
        request["expected_response"] = {"id": request["id"], "ok": False, "error": "invalid_request"}
        result.append(request)
    return result + depth_cases()


def stateful_cases() -> list[dict[str, object]]:
    initial = M.KB(SnapshotId("snapshot-0"))
    valid = plan()
    base_fields: dict[str, object] = {"kb": wire.enc_kb(initial), "context": wire.enc_context(context("snapshot-0")), "journal": []}
    applied_kb = wire.enc_kb(valid.candidate)
    journal = [wire.enc_journal_entry(M.JournalEntry(valid))]
    result = [case("stateful-apply-replay", "sequence", {"kb": applied_kb, "journal": journal, "outcomes": ["applied", "already_applied"]},
                   **base_fields, plans=[wire.enc_plan(valid), wire.enc_plan(valid)])]
    changed = replace(valid, authority=replace(valid.authority, actor=ActorId("other-reviewer")))
    result.append(case("stateful-replay-input-conflict", "sequence", {"kb": applied_kb, "journal": journal, "outcomes": ["applied", "input_conflict"]},
                       **base_fields, plans=[wire.enc_plan(valid), wire.enc_plan(changed)]))
    invalid = replace(valid, authority=replace(valid.authority, approvals=()))
    result.append(case("stateful-rejection-not-journaled", "sequence", {"kb": applied_kb, "journal": journal, "outcomes": ["rejected", "applied"]},
                       **base_fields, plans=[wire.enc_plan(invalid), wire.enc_plan(valid)]))
    conflict = replace(valid, id=OperationId("admit-2"))
    result.append(case("stateful-predecessor-conflict", "sequence", {"kb": applied_kb, "journal": journal, "outcomes": ["applied", "predecessor_conflict"]},
                       **base_fields, plans=[wire.enc_plan(valid), wire.enc_plan(conflict)]))
    for fixture in result:
        fixture["trusted_environment"] = trusted_environment(plans=(valid, invalid, conflict))
    result.append(case("stateful-self-issued-authority-rejected", "sequence",
                       {"kb": wire.enc_kb(initial), "journal": [], "outcomes": ["rejected"]},
                       **base_fields, plans=[wire.enc_plan(valid)]))
    result.append(case("stateful-changed-plan-not-approved", "sequence",
                       {"kb": wire.enc_kb(initial), "journal": [], "outcomes": ["rejected"]},
                       **base_fields, plans=[wire.enc_plan(changed)],
                       trusted_environment=trusted_environment(plans=(valid,))))
    next_candidate = replace(valid.candidate, snapshot=SnapshotId("snapshot-2"))
    next_plan = replace(valid, id=OperationId("next-publication"), expected_snapshot=valid.candidate.snapshot,
                        candidate=next_candidate, authority=replace(valid.authority, approved=next_candidate, approvals=(), context=context("snapshot-1")))
    result.append(case("stateful-two-publications-newest-first-journal", "sequence",
                       {"kb": wire.enc_kb(next_candidate),
                        "journal": [wire.enc_journal_entry(M.JournalEntry(next_plan)), *journal],
                        "outcomes": ["applied", "applied", "already_applied"]},
                       **base_fields, plans=[wire.enc_plan(valid), wire.enc_plan(next_plan), wire.enc_plan(valid)],
                       trusted_environment=trusted_environment(plans=(valid, next_plan))))
    weaker = replace(context("snapshot-0"), policy=replace(context().policy, require_fresh=False))
    result.append(case("signed-context-same-policy-id-cannot-weaken", "admit",
                       {"kb": wire.enc_kb(initial), "journal": [], "outcome": "rejected"},
                       kb=wire.enc_kb(initial), context=wire.enc_context(weaker), plan=wire.enc_plan(valid),
                       trusted_environment=trusted_environment(plans=(valid,))))
    return result + selection_cases()


def authored_example() -> M.AuthoredProposal:
    from kctx.domain.ids import GateId, ProposalId
    definition = M.AuthoredGateDefinition(GateId("land-check"), "release built", "run build", M.GateWhen.LAND, ActorId("reviewer"), CheckerId("ci-v1"))
    result = M.AuthoredGateResult(definition, TargetRevision("target-r1"), CheckerId("ci-v1"), M.GateOutcome.PASS, 100, 110, ProposalMaterialRevision("proposal-material-1"), "test-environment", "payments", ("ev:build-result",), ActorId("gate-reviewer"))
    return M.AuthoredProposal(M.AuthoredStatus.LANDING, M.AuthoredProfile.MODERN, True, 2, TargetRevision("target-r1"),
                              (definition,), (result,), ActorId("actor"), ActorId("acceptor"), ActorId("executor"), ActorId("verifier"),
                              ("commit:target-r1",), "", ProposalId("proposal-1"), ProposalId("replacement"),
                              (M.AuthoredReplacement(ProposalId("proposal-1"), None), M.AuthoredReplacement(ProposalId("replacement"), None)),
                              ProposalMaterialRevision("proposal-material-1"), ProposalMaterialRevision("proposal-material-1"), "test-environment", "payments",
                              (M.AuthoredLanded("commit:target-r1", TargetRevision("target-r1")),))


def authored_cases() -> list[dict[str, object]]:
    proposal = authored_example()
    gate = proposal.gate_results[0]
    fixtures: tuple[tuple[str, M.AuthoredProposal, M.AuthoredStatus, int, bool], ...] = (
        ("authored-applied-boundary", proposal, M.AuthoredStatus.APPLIED, 110, True),
        ("authored-expired-gate", proposal, M.AuthoredStatus.APPLIED, 111, False),
        ("authored-skipped-gate", replace(proposal, gate_results=()), M.AuthoredStatus.APPLIED, 110, False),
        ("authored-swapped-target", replace(proposal, target_revision=TargetRevision("other")), M.AuthoredStatus.APPLIED, 110, False),
        ("authored-definition-changed", replace(proposal, gate_definitions=(replace(gate.definition, check="other command"),)), M.AuthoredStatus.APPLIED, 110, False),
        ("authored-no-research", replace(proposal, research_present=False), M.AuthoredStatus.APPLIED, 110, False),
        ("authored-no-alternative", replace(proposal, alternatives_count=1), M.AuthoredStatus.APPLIED, 110, False),
        ("authored-no-landed-ref", replace(proposal, landed_refs=()), M.AuthoredStatus.APPLIED, 110, False),
        ("authored-legacy-still-needs-gate", replace(proposal, profile=M.AuthoredProfile.LEGACY_LIMITED, gate_results=()), M.AuthoredStatus.APPLIED, 110, False),
        ("authored-latest-fail-overrides-pass", replace(proposal, gate_results=(gate, replace(gate, result=M.GateOutcome.FAIL, observed_at=105))), M.AuthoredStatus.APPLIED, 110, False),
        ("authored-historical-prefilter", replace(proposal, gate_results=(gate, replace(gate, result=M.GateOutcome.FAIL, observed_at=111))), M.AuthoredStatus.APPLIED, 110, True),
        ("authored-other-target-result-independent", replace(proposal, gate_results=(gate, replace(gate, target_revision=TargetRevision("other"), result=M.GateOutcome.FAIL, observed_at=105))), M.AuthoredStatus.APPLIED, 110, True),
        ("authored-verified-needs-deploy-use", replace(proposal, status=M.AuthoredStatus.APPLIED), M.AuthoredStatus.VERIFIED, 110, False),
        ("authored-regressed-needs-note", replace(proposal, status=M.AuthoredStatus.APPLIED), M.AuthoredStatus.REGRESSED, 110, False),
        ("authored-regressed-with-note", replace(proposal, status=M.AuthoredStatus.APPLIED, regression_note="Observed regression"), M.AuthoredStatus.REGRESSED, 110, True),
        ("authored-supersession-explicit", proposal, M.AuthoredStatus.SUPERSEDED, 110, True),
    )
    from kctx.domain.ids import GateId
    deploy = replace(gate.definition, id=GateId("deploy-check"), when=M.GateWhen.DEPLOY)
    use = replace(gate.definition, id=GateId("use-check"), when=M.GateWhen.USE)
    verified = replace(proposal, status=M.AuthoredStatus.APPLIED,
                       gate_definitions=(*proposal.gate_definitions, deploy, use),
                       gate_results=(gate, replace(gate, definition=deploy), replace(gate, definition=use)))
    optional_checker = replace(gate.definition, checker=None)
    compatible = replace(proposal, gate_definitions=(optional_checker,),
                         gate_results=(replace(gate, definition=optional_checker),))
    fixtures += (
        ("authored-verified-all-gates", verified, M.AuthoredStatus.VERIFIED, 110, True),
        ("authored-role-fields-same-person", replace(verified, verifier=verified.executor), M.AuthoredStatus.VERIFIED, 110, True),
        ("authored-verified-no-new-actor-requirement", replace(verified, actor=None, verifier=None), M.AuthoredStatus.VERIFIED, 110, True),
        ("authored-five-column-gate-compatible", compatible, M.AuthoredStatus.APPLIED, 110, True),
        ("authored-proposed-no-decision-actor", replace(proposal, status=M.AuthoredStatus.DRAFT, actor=None), M.AuthoredStatus.PROPOSED, 110, True),
    )
    fixtures += (
        ("authored-verified-can-regress", replace(verified, status=M.AuthoredStatus.VERIFIED, regression_note="new failure"), M.AuthoredStatus.REGRESSED, 110, True),
        ("authored-supersession-missing-replacement", replace(proposal, superseded_by=None), M.AuthoredStatus.SUPERSEDED, 110, False),
        ("authored-supersession-unresolved-replacement", replace(proposal, proposals=proposal.proposals[:1]), M.AuthoredStatus.SUPERSEDED, 110, False),
        ("authored-supersession-cycle-rejected", replace(proposal, proposals=(
            proposal.proposals[0], replace(proposal.proposals[1], superseded_by=proposal.id))), M.AuthoredStatus.SUPERSEDED, 110, False),
        ("authored-approval-cannot-transfer-material-revision", replace(proposal, proposal_revision=ProposalMaterialRevision("changed-material")), M.AuthoredStatus.APPLIED, 110, False),
    )
    fixtures += (
        ("authored-unknown-environment-blocked", replace(proposal, environment=""), M.AuthoredStatus.APPLIED, 110, False),
        ("authored-swapped-environment-blocked", replace(proposal, environment="other"), M.AuthoredStatus.APPLIED, 110, False),
        ("authored-swapped-scope-blocked", replace(proposal, scope="other"), M.AuthoredStatus.APPLIED, 110, False),
        ("authored-gate-without-retained-evidence", replace(proposal, gate_results=(replace(gate, evidence_refs=()),)), M.AuthoredStatus.APPLIED, 110, False),
        ("authored-gate-without-attestor", replace(proposal, gate_results=(replace(gate, actor=None),)), M.AuthoredStatus.APPLIED, 110, False),
        ("authored-gate-old-material-revision", replace(proposal, gate_results=(replace(gate, proposal_revision=ProposalMaterialRevision("old")),)), M.AuthoredStatus.APPLIED, 110, False),
        ("authored-landed-ref-must-resolve", replace(proposal, resolved_landed=()), M.AuthoredStatus.APPLIED, 110, False),
        ("authored-landed-ref-must-match-target", replace(proposal, resolved_landed=(M.AuthoredLanded("commit:target-r1", TargetRevision("other")),)), M.AuthoredStatus.APPLIED, 110, False),
        ("authored-unlisted-resolution-cannot-authorize-target", replace(proposal, resolved_landed=(
            M.AuthoredLanded("commit:target-r1", TargetRevision("other")), M.AuthoredLanded("unlisted", TargetRevision("target-r1")))), M.AuthoredStatus.APPLIED, 110, False),
    )
    result = [case(ident, "authored_transition", expected, proposal=wire.enc_authored_proposal(p),
                   target_status=target.value, now=now) for ident, p, target, now, expected in fixtures]
    result.extend(case(ident + "-candidate", "authored_candidate_valid", expected,
                       proposal=wire.enc_authored_proposal(replace(p, status=target)),
                       target_status=target.value, now=now) for ident, p, target, now, expected in fixtures)
    return result


def trusted_environment(*, plans: tuple[M.Plan, ...] = (),
                        selections: tuple[M.SelectionPlan, ...] = (),
                        retained: tuple[M.KB, ...] = ()) -> dict[str, object]:
    return {"approvals": [{"plan": wire.enc_plan(plan)} for plan in plans],
            "selections": [{"plan": wire.enc_selection_plan(plan)} for plan in selections],
            "retained": [wire.enc_kb(kb) for kb in retained]}


def selection_cases() -> list[dict[str, object]]:
    target = valid_kb()
    extra = replace(target.claims[0], id=ClaimId("later-claim"))
    correction = M.Correction(CorrectionId("later-retraction"), M.CorrectionKind.RETRACT, REF, None, 105)
    current = replace(target, snapshot=SnapshotId("snapshot-2"), claims=(*target.claims, extra),
                      derivations=(*target.derivations, M.Derivation(DerivationId("later-derivation"), extra.ref, WITNESS)),
                      corrections=(correction,))
    state = M.SelectionState(current, tuple(claim.ref for claim in current.claims))
    selected_plan = M.SelectionPlan(OperationId("select-1"), current.snapshot, target.snapshot, SnapshotId("snapshot-3"), (REF,), ActorId("reviewer-key"), context().policy.id, "review", context("snapshot-2"))
    selected_state = M.SelectionState(replace(current, snapshot=selected_plan.new_snapshot), (REF,))
    entry = M.SelectionJournalEntry(selected_plan)
    fields: dict[str, object] = {"state": wire.enc_selection_state(state), "context": wire.enc_context(context("snapshot-2")), "journal": []}
    expected = {"state": wire.enc_selection_state(selected_state), "journal": [wire.enc_selection_journal_entry(entry)], "outcome": "applied"}
    rejected = {"state": wire.enc_selection_state(state), "journal": [], "outcome": "rejected"}
    env = trusted_environment(selections=(selected_plan,), retained=(target,))
    cases = [
        case("selection-forward-keeps-current-corrections", "select", expected, **fields, plan=wire.enc_selection_plan(selected_plan), trusted_environment=env),
        case("selection-no-self-approval", "select", rejected, **fields, plan=wire.enc_selection_plan(selected_plan)),
        case("selection-needs-trusted-retained-target", "select", rejected, **fields, plan=wire.enc_selection_plan(selected_plan),
             trusted_environment=trusted_environment(selections=(selected_plan,))),
        case("selection-replay-idempotent", "select", {**expected, "outcome": "already_applied"},
             state=wire.enc_selection_state(selected_state), context=wire.enc_context(context("snapshot-3")),
             journal=[wire.enc_selection_journal_entry(entry)], plan=wire.enc_selection_plan(selected_plan)),
        case("selection-current-retraction-still-blocks", "retrieve_selected",
             {"snapshot": "snapshot-3", "records": [{"claim": wire.enc_claim(target.claims[0]),
               "assessment": assessment(support="none", freshness="unknown", available=False, usable=False)}],
              "omitted": 0, "complete": True, "next_offset": None},
             state=wire.enc_selection_state(selected_state), context=wire.enc_context(context("snapshot-3")), offset=0, limit=10),
    ]
    for ident, invalid in (
        ("selection-exact-target-membership", replace(selected_plan, selected=())),
        ("selection-cannot-reuse-retained-snapshot-id", replace(selected_plan, new_snapshot=target.snapshot)),
        ("selection-unknown-retained-target", replace(selected_plan, target_snapshot=SnapshotId("unknown"))),
        ("selection-policy-mismatch", replace(selected_plan, intended_use="deploy")),
    ):
        cases.append(case(ident, "select", rejected, **fields, plan=wire.enc_selection_plan(invalid),
                          trusted_environment=trusted_environment(selections=(invalid,), retained=(target,))))
    conflicting = replace(selected_plan, new_snapshot=SnapshotId("different"))
    cases.append(case("selection-replay-conflict", "select", {**expected, "outcome": "input_conflict"},
                      state=wire.enc_selection_state(selected_state), context=wire.enc_context(context("snapshot-3")),
                      journal=[wire.enc_selection_journal_entry(entry)], plan=wire.enc_selection_plan(conflicting)))
    weakened_context = replace(context("snapshot-2"), policy=replace(context().policy, require_uncontested=False))
    cases.append(case("selection-signature-binds-complete-context", "select", rejected,
                      state=wire.enc_selection_state(state), context=wire.enc_context(weakened_context), journal=[],
                      plan=wire.enc_selection_plan(selected_plan), trusted_environment=env))
    return cases


def depth_cases() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for depth in (256, 257):
        witness: dict[str, object] = {"tag": "truth", "scope": wire.enc_scope(SCOPE)}
        formula: dict[str, object] = {"tag": "truth"}
        for _ in range(depth - 1):
            witness = {"tag": "specialize", "scope": wire.enc_scope(SCOPE), "premise": witness}
            formula = {"tag": "and", "left": {"tag": "truth"}, "right": formula}
        witness_request = semantic(f"witness-depth-{depth}", "check",
                                  {"statement": wire.enc_statement(M.Statement(M.Truth(), SCOPE)),
                                   "dependencies": [wire.enc_dependency(M.ContextDependency(replace(context(), now=0)))]},
                                  witness=witness)
        kb = wire.enc_kb(M.KB(SnapshotId("depth")))
        kb["claims"] = [{"id": "depth-claim", "revision": "r1",
                         "statement": {"formula": formula, "scope": wire.enc_scope(SCOPE), "polarity": "positive"}}]
        formula_request = case(f"formula-depth-{depth}", "validate", True, kb=kb)
        for request in (witness_request, formula_request):
            if depth == 257:
                request.pop("expected")
                request["expected_response"] = {"id": request["id"], "ok": False, "error": "invalid_request"}
            cases.append(request)
    return cases


def raw_cases() -> list[dict[str, object]]:
    raw_values = (
        ("duplicate-ttl-key", '{"schema_version":2,"semantic_version":"2.0.0","id":"duplicate","op":"fresh","now":1,"observed_at":0,"ttl":1,"ttl":1}'),
        ("duplicate-envelope-key", '{"schema_version":2,"schema_version":2,"semantic_version":"2.0.0","id":"duplicate","op":"semantic_version"}'),
        ("nonobject-request", '[]'),
        ("unpaired-high-surrogate-rejected", r'{"schema_version":2,"semantic_version":"2.0.0","id":"\ud800","op":"semantic_version"}'),
        ("unpaired-low-surrogate-rejected", r'{"schema_version":2,"semantic_version":"2.0.0","id":"\udc00","op":"semantic_version"}'),
        ("high-surrogate-without-low-pair-rejected", r'{"schema_version":2,"semantic_version":"2.0.0","id":"\ud800A","op":"semantic_version"}'),
    )
    cases = [{**envelope(ident, "raw"), "raw_request": raw,
              "expected_response": {"id": "", "ok": False, "error": "invalid_request"}}
             for ident, raw in raw_values]
    cases.append({**envelope("paired-surrogate-scalar-accepted", "raw"),
                  "raw_request": r'{"schema_version":2,"semantic_version":"2.0.0","id":"\ud840\udc00","op":"semantic_version"}',
                  "expected_response": {"id": "\U00020000", "ok": True, "result": "2.0.0"}})
    return cases
