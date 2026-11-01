"""End-to-end v2 regressions through the production boundary and typed API."""
from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError, replace

from kctx.domain.ids import ClaimId, ClaimRevision, DerivationId, ObservationId, ReceiptId, SnapshotId
from kctx.domain.ids import ActorId, ContentId, SourceId, SourceRevision, TargetRevision, ProposalMaterialRevision
from kctx.errors import KctxError
from kctx.semantics import checker, model as M, wire, workflow
from kctx.semantics.time import assess_fresh
from kctx.semantics.wellformed import well_formed, context_wf
from scripts.semantic_cases import generated_cases, reviewed_cases, stateful_cases, receipt, authored_example
from scripts.semantic_mutations import mutation_campaign
from scripts.conformance_check import python_handle
from tests.semantics.examples import REF, SCOPE, STATEMENT, WITNESS, context, negative_kb, plan, valid_kb


class GoldenDecisionTests(unittest.TestCase):
    def test_reviewed_generated_and_stateful_responses(self) -> None:
        for fixture in (*reviewed_cases(), *generated_cases(), *stateful_cases()):
            with self.subTest(case=fixture["id"]):
                expected = fixture.get("expected_response", {"id": fixture["id"], "ok": True, "result": fixture.get("expected")})
                self.assertEqual(python_handle(fixture), expected)

    def test_production_decision_mutants_are_killed(self) -> None:
        report = mutation_campaign()
        self.assertEqual(report["result"], "pass", report)


class CodecTests(unittest.TestCase):
    def test_nominal_ids_do_not_compare_across_kinds(self) -> None:
        self.assertNotEqual(ClaimId("same"), ObservationId("same"))
        self.assertNotEqual(SourceId("same"), SourceRevision("same"))
        self.assertNotEqual(ContentId("same"), SourceId("same"))
        self.assertNotEqual(TargetRevision("same"), ProposalMaterialRevision("same"))
        with self.assertRaises(FrozenInstanceError):
            setattr(REF, "id", ClaimId("new"))

    def test_full_kb_plan_receipt_roundtrips(self) -> None:
        kb = valid_kb()
        kb = replace(kb, receipts=(receipt(kb, context()),))
        self.assertEqual(wire.dec_kb(wire.enc_kb(kb)), kb)
        self.assertEqual(wire.dec_plan(wire.enc_plan(plan())), plan())
        self.assertTrue(well_formed(kb))

    def test_unknown_identities_are_none_not_empty_ids(self) -> None:
        for constructor in (ActorId, SourceId, SourceRevision, ContentId, TargetRevision, ProposalMaterialRevision):
            with self.subTest(kind=constructor.__name__):
                with self.assertRaises(KctxError):
                    constructor("")
        proposal = replace(authored_example(), actor=None, verifier=None, accepted_revision=None,
                           target_revision=None, proposal_revision=None)
        encoded = wire.enc_authored_proposal(proposal)
        self.assertEqual(encoded["actor"], "")
        self.assertEqual(encoded["target_revision"], "")
        self.assertEqual(wire.dec_authored_proposal(encoded), proposal)

    def test_ttl_policy_sum_has_three_distinct_roundtrips(self) -> None:
        for ttl, encoded in ((M.ttl_expire_after(10), 10), (M.TTL_MISSING, None),
                             (M.TTL_NO_EXPIRY, {"tag": "noExpiry"})):
            with self.subTest(ttl=ttl):
                self.assertEqual(wire.dec_ttl(encoded), ttl)
                self.assertEqual(wire.enc_ttl(ttl), encoded)
                ctx = replace(context(), policy=replace(context().policy, ttl=ttl))
                self.assertEqual(wire.dec_context(wire.enc_context(ctx)), ctx)
        for invalid in (True, -1, "noExpiry", {"tag": "unknown"}, {"tag": "noExpiry", "secs": 0}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    wire.dec_ttl(invalid)
        negative = replace(context(), policy=replace(context().policy, ttl=M.ttl_expire_after(-1)))
        self.assertFalse(context_wf(negative))
        self.assertEqual(assess_fresh(M.TTL_NO_EXPIRY, 100, 99), M.Freshness.UNKNOWN)

    def test_duplicate_json_keys_rejected_before_mapping(self) -> None:
        for raw in (
            '{"id":"x","id":"y","op":"semantic_version","schema_version":2,"semantic_version":"2.0.0"}',
            '{"id":"x","op":"fresh","schema_version":2,"semantic_version":"2.0.0","now":1,"observed_at":0,"ttl":1,"ttl":2}',
        ):
            result = json.loads(wire.evaluate_json(raw))
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "invalid_request")

    def test_unpaired_unicode_rejected_at_raw_and_object_boundaries(self) -> None:
        malformed = r'{"schema_version":2,"semantic_version":"2.0.0","id":"\ud800","op":"semantic_version"}'
        self.assertEqual(json.loads(wire.evaluate_json(malformed)),
                         {"id": "", "ok": False, "error": "invalid_request"})
        direct: dict[str, object] = {"schema_version": 2, "semantic_version": "2.0.0",
                                    "id": "\ud800", "op": "semantic_version"}
        self.assertEqual(wire.evaluate_request(direct), {"id": "", "ok": False, "error": "invalid_request"})
        with self.assertRaises(ValueError):
            wire.loads_request(r'{"list":["\udc00"]}')
        self.assertEqual(wire.loads_request(r'{"text":"\ud840\udc00"}'), {"text": "\U00020000"})

    def test_strict_tags_fields_versions_and_naturals(self) -> None:
        base: dict[str, object] = {"schema_version": 2, "semantic_version": "2.0.0", "id": "strict", "op": "fresh", "now": 1, "observed_at": 0, "ttl": 1}
        for request in ({**base, "schema_version": True}, {**base, "semantic_version": "1.0.1"},
                        {**base, "unused": True}, {**base, "ttl": -1}, {**base, "now": True},
                        {**base, "ttl": "forever"}):
            with self.subTest(request=request):
                self.assertFalse(wire.evaluate_request(request)["ok"])
        with self.assertRaises(ValueError):
            wire.dec_witness({"tag": "contextualizes", "attestation": "attestation-1"})

    def test_direct_union_decoders_reject_missing_or_malformed_tags(self) -> None:
        for decoder in (wire.dec_formula, wire.dec_witness, wire.dec_dependency):
            for malformed in ({}, {"unexpected": "value"}, {"tag": None}, {"tag": 7},
                              {"tag": []}, {"tag": "unrecognized"}):
                with self.subTest(decoder=decoder.__name__, malformed=malformed):
                    with self.assertRaisesRegex(ValueError, "^invalid_request$"):
                        decoder(malformed)

    def test_nested_missing_tags_raise_documented_codec_errors(self) -> None:
        malformed_formula: dict[str, object] = {
            "tag": "and", "left": {}, "right": {"tag": "truth"},
        }
        with self.assertRaisesRegex(ValueError, "^invalid_request$"):
            wire.dec_formula(malformed_formula)
        with self.assertRaisesRegex(ValueError, "^invalid_request$"):
            wire.dec_witness({"tag": "specialize", "scope": wire.enc_scope(SCOPE), "premise": {}})
        malformed_claim = {
            **wire.enc_claim(valid_kb().claims[0]),
            "statement": {**wire.enc_statement(STATEMENT), "formula": {}},
        }
        with self.assertRaisesRegex(ValueError, "^invalid_request$"):
            wire.dec_dependency({"tag": "claim", "value": malformed_claim})
        malformed_kb = wire.enc_kb(valid_kb())
        malformed_kb["claims"] = [malformed_claim]
        with self.assertRaisesRegex(ValueError, "^invalid_request$"):
            wire.dec_kb(malformed_kb)

    def test_dangling_and_duplicate_global_records_reject(self) -> None:
        kb = valid_kb()
        for invalid in (replace(kb, observations=()), replace(kb, claims=kb.claims * 2),
                        replace(kb, attestations=()), replace(kb, derivations=kb.derivations * 2)):
            self.assertFalse(well_formed(invalid))
            with self.assertRaises(ValueError):
                wire.dec_kb(wire.enc_kb(invalid))


class RecursiveWitnessTests(unittest.TestCase):
    def test_composition_retains_age_and_all_dependencies(self) -> None:
        kb, ctx = valid_kb(), context()
        compound = M.AndWitness(WITNESS, WITNESS)
        result = checker.check(kb, ctx, compound)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(sum(isinstance(d, M.ObservationDependency) for d in result.dependencies), 1)
        self.assertEqual(checker.witness_freshness(replace(ctx, now=111), result.dependencies), M.Freshness.STALE)
        self.assertEqual(result.statement, M.Statement(M.Conjunction(STATEMENT.formula, STATEMENT.formula), SCOPE))

    def test_negative_claim_can_be_admitted_independently(self) -> None:
        both = negative_kb()
        candidate = replace(both, observations=both.observations[1:], claims=both.claims[1:], attestations=both.attestations[1:], derivations=both.derivations[1:])
        claim, derivation = candidate.claims[0], candidate.derivations[0]
        authority = M.Authority(ActorId("independent-reviewer"), claim.ref, "review", context().policy.id,
                                claim.statement, candidate, candidate.claims, context("snapshot-0"))
        operation = replace(plan(), candidate=candidate, authority=authority, claim=claim.ref, witness=derivation.witness)
        result = workflow.apply_plan(M.KB(SnapshotId("snapshot-0")), context("snapshot-0"), (), operation,
                                     trusted_approvals=(M.VerifiedApproval(operation),))
        self.assertEqual(result.outcome, M.CommitOutcome.APPLIED)
        self.assertEqual(checker.assess(candidate, context(), claim.ref).support, M.Support.NEGATIVE)

    def test_stale_alternative_does_not_poison_surviving_path(self) -> None:
        kb, ctx = valid_kb(), context()
        old_observation = replace(kb.observations[0], id=ObservationId("old"), observed_at=0)
        from kctx.domain.ids import AttestationId
        old_attestation = replace(kb.attestations[0], id=AttestationId("old-attestation"), observation=old_observation.id)
        old_derivation = M.Derivation(DerivationId("old-derivation"), REF, M.AttestWitness(old_attestation.id))
        kb = replace(kb, observations=(old_observation, *kb.observations), attestations=(old_attestation, *kb.attestations), derivations=(old_derivation, *kb.derivations))
        self.assertTrue(checker.assess(kb, ctx, REF).usable)

    def test_root_corrections_and_claim_enter_computed_footprint(self) -> None:
        kb = valid_kb()
        root = M.Claim(ClaimId("compound"), ClaimRevision("r1"), M.Statement(M.Conjunction(STATEMENT.formula, STATEMENT.formula), SCOPE))
        kb = replace(kb, claims=(*kb.claims, root), derivations=(*kb.derivations, M.Derivation(DerivationId("compound"), root.ref, M.AndWitness(WITNESS, WITNESS))))
        checked = checker.accepted(kb, context(), root.ref)[0][1]
        self.assertIn(M.ClaimDependency(root), checked.dependencies)
        self.assertIn(M.CorrectionsDependency(root.ref, ()), checked.dependencies)
        self.assertIsInstance(checked.dependencies[-1], M.ContextDependency)


class AdmissionGuardTests(unittest.TestCase):
    def test_authority_cannot_smuggle_second_supported_claim(self) -> None:
        operation = plan()
        extra = replace(operation.candidate.claims[0], id=ClaimId("unapproved"))
        derivation = M.Derivation(DerivationId("extra"), extra.ref, WITNESS)
        candidate = replace(operation.candidate, claims=(*operation.candidate.claims, extra), derivations=(*operation.candidate.derivations, derivation))
        invalid = replace(operation, candidate=candidate)
        result = workflow.apply_plan(M.KB(SnapshotId("snapshot-0")), context("snapshot-0"), (), invalid,
                                     trusted_approvals=(M.VerifiedApproval(invalid),))
        self.assertEqual(result.outcome, M.CommitOutcome.REJECTED)
        self.assertEqual(result.journal, ())

    def test_forged_receipt_cannot_skip_validation(self) -> None:
        kb = valid_kb()
        ctx = replace(context(), policy=replace(context().policy, require_validation=True))
        forged = replace(receipt(kb, ctx), id=ReceiptId("forged"), dependencies=())
        self.assertFalse(checker.assess(replace(kb, receipts=(forged,)), ctx, REF).usable)

    def test_immutable_prefix_cannot_be_rewritten(self) -> None:
        operation = plan()
        base = operation.candidate
        rewritten = replace(base, snapshot=SnapshotId("next"), observations=(replace(base.observations[0], content=ContentId("changed")),))
        authority = replace(operation.authority, approved=rewritten, approvals=(), context=context())
        invalid = replace(operation, expected_snapshot=base.snapshot, candidate=rewritten, authority=authority)
        self.assertEqual(workflow.apply_plan(base, context(), (), invalid,
                                            trusted_approvals=(M.VerifiedApproval(invalid),)).outcome, M.CommitOutcome.REJECTED)

    def test_inclusive_freshness_factory_compatibility(self) -> None:
        self.assertEqual(assess_fresh(M.ttl_expire_after(10), 100, 110), M.Freshness.FRESH)
        self.assertEqual(assess_fresh(M.TTL_NO_EXPIRY, 100, 110), M.Freshness.FRESH)
        self.assertEqual(assess_fresh(M.TTL_MISSING, 100, 110), M.Freshness.UNKNOWN)


class AssessmentGapTests(unittest.TestCase):
    def test_gaps_name_each_failed_requirement(self) -> None:
        kb = valid_kb()
        self.assertEqual(checker.assessment_gaps(kb, context(), REF), ())
        stale = checker.assessment_gaps(kb, context(now=200), REF)
        self.assertTrue(any("observations are stale under policy ttl" == gap for gap in stale), stale)
        unsupported = replace(kb, attestations=(), derivations=())
        gaps = checker.assessment_gaps(unsupported, context(), REF)
        self.assertTrue(any("support=none" in gap for gap in gaps), gaps)
        self.assertTrue(any("observations are unknown under policy ttl" == gap for gap in gaps), gaps)
        elsewhere = replace(context(), target=M.Scope(M.ProjectId("other"), ""))
        self.assertIn(
            "claim is not applicable to the context target",
            checker.assessment_gaps(kb, elsewhere, REF),
        )
