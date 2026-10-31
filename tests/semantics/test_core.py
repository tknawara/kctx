import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from kctx.semantics import (  # noqa: E402
    SEMANTIC_VERSION,
    Atom,
    Binding,
    Claim,
    ClaimProp,
    ClaimRef,
    Correction,
    CorrectionKind,
    CoverageWitness,
    Dep,
    DepKind,
    Derivation,
    EvalCtx,
    Freshness,
    HypStatus,
    Hypothesis,
    Investigation,
    JournalEntry,
    KB,
    ObsOutcome,
    Op,
    Proposal,
    ProposalStatus,
    RuleId,
    Scope,
    SupportRole,
    Ttl,
    add_correction,
    assess_fresh,
    can_conclude,
    check_derivation_v,
    commit_op,
    legal_transition,
    plan_transition,
    ready_for_proposed,
    supported,
    usable_for,
)
from kctx.semantics import wire  # noqa: E402


def demo_parts():
    scope = Scope("payments", "")
    prop = ClaimProp.of_atom(Atom("batch-limit", "is", ("500",)))
    obs = type("O", (), {})()  # placeholder, replaced below
    from kctx.semantics.model import Observation

    observation = Observation(
        id="o1",
        outcome=ObsOutcome.OK,
        observed_at=100,
        ttl=Ttl("expireAfter", 50),
        system="git",
        locator="repo",
    )
    claim = Claim("c1", "r1", prop, scope)
    ref = ClaimRef("c1", "r1")
    binding = Binding("o1", ref, SupportRole.SUPPORTS)
    deriv = Derivation(
        id="d1",
        rule=RuleId.OBS_SUPPORTS,
        premise_groups=(),
        conclusion=ref,
        conclusion_prop=prop,
        scope=scope,
        footprint=(
            Dep(DepKind.KB_RECORD, "c1", ""),
            Dep(DepKind.KB_RECORD, "o1", ""),
        ),
        evidence="o1",
        witness=None,
    )
    kb = KB(
        head="h0",
        observations=(observation,),
        claims=(claim,),
        bindings=(binding,),
        derivations=(deriv,),
    )
    return kb, deriv, ref, scope, prop


class FreshnessTests(unittest.TestCase):
    """Q16: TTL boundaries, no-expiry, missing policy, future clock."""

    def test_inclusive_boundary(self):
        t = Ttl("expireAfter", 50)
        self.assertIs(assess_fresh(t, 100, 100), Freshness.FRESH)
        self.assertIs(assess_fresh(t, 100, 150), Freshness.FRESH)  # inclusive
        self.assertIs(assess_fresh(t, 100, 151), Freshness.STALE)

    def test_missing_policy_never_fresh(self):
        self.assertIs(assess_fresh(Ttl("missing"), 100, 120), Freshness.UNKNOWN)

    def test_no_expiry_fresh_when_not_future(self):
        self.assertIs(assess_fresh(Ttl("noExpiry"), 100, 10_000), Freshness.FRESH)

    def test_future_observation_unknown(self):
        t = Ttl("expireAfter", 50)
        self.assertIs(assess_fresh(t, 200, 100), Freshness.UNKNOWN)

    def test_stale_stays_stale_as_time_advances(self):
        t = Ttl("expireAfter", 50)
        self.assertIs(assess_fresh(t, 100, 200), Freshness.STALE)
        self.assertIs(assess_fresh(t, 100, 300), Freshness.STALE)


class CheckerTests(unittest.TestCase):
    def test_obs_supports_accepted(self):
        kb, deriv, ref, _, _ = demo_parts()
        ctx = EvalCtx(now=120, require_validated=False)
        self.assertEqual(check_derivation_v(kb.view(), ctx, deriv), "accepted")
        self.assertTrue(supported(kb.view(), ctx, ref))
        self.assertTrue(usable_for(kb.view(), ctx, ref))

    def test_stale_evidence_rejected_with_code(self):
        kb, deriv, _, _, _ = demo_parts()
        ctx = EvalCtx(now=200, require_validated=False)
        self.assertEqual(
            check_derivation_v(kb.view(), ctx, deriv),
            ["rejected", "evidenceNotFresh"],
        )
        self.assertFalse(usable_for(kb.view(), ctx, deriv.conclusion))

    def test_contextualizes_role_is_not_support(self):
        from kctx.semantics import KbView

        kb, deriv, _, _, _ = demo_parts()
        v = kb.view()
        v2 = KbView(
            observations=v.observations,
            claims=v.claims,
            bindings=(Binding("o1", deriv.conclusion, SupportRole.CONTEXTUALIZES),),
            corrections=v.corrections,
            derivations=v.derivations,
            validations=v.validations,
        )
        ctx = EvalCtx(now=120)
        self.assertEqual(
            check_derivation_v(v2, ctx, deriv), ["rejected", "evidenceNotOk"]
        )

    def test_correction_blocks_but_never_confers_support(self):
        from kctx.semantics import KbView

        kb, deriv, ref, _, _ = demo_parts()
        v = kb.view()
        corrected = KbView(
            observations=v.observations,
            claims=v.claims,
            bindings=v.bindings,
            corrections=(Correction(CorrectionKind.DISPUTE, ref, 300),),
            derivations=v.derivations,
            validations=v.validations,
        )
        ctx = EvalCtx(now=120, require_validated=False, require_uncontested=False)
        self.assertEqual(
            check_derivation_v(corrected, ctx, deriv),
            ["rejected", "contestedConclusion"],
        )
        empty = KbView(
            observations=v.observations,
            claims=v.claims,
            bindings=v.bindings,
            corrections=corrected.corrections,
            derivations=(),
            validations=v.validations,
        )
        # T16 flavor: the supersede edge does not create support.
        self.assertFalse(supported(empty, ctx, ref))

    def test_footprint_must_declare_consulted_ids(self):
        from kctx.semantics import KbView

        kb, deriv, _, _, _ = demo_parts()
        v = kb.view()
        import dataclasses
        stripped = dataclasses.replace(
            deriv, footprint=(Dep(DepKind.KB_RECORD, "c1", ""),)
        )
        ctx = EvalCtx(now=120)
        self.assertEqual(
            check_derivation_v(v, ctx, stripped),
            ["rejected", "footprintIncomplete"],
        )

    def test_missing_conclusion_rejected(self):
        from kctx.semantics import Derivation as D, KbView

        kb, deriv, _, _, _ = demo_parts()
        v = kb.view()
        ghost = ClaimRef("nope", "r1")
        import dataclasses
        d2 = dataclasses.replace(deriv, conclusion=ghost)
        ctx = EvalCtx(now=120)
        self.assertEqual(
            check_derivation_v(v, ctx, d2), ["rejected", "missingConclusion"]
        )


class WorkflowTests(unittest.TestCase):
    """Q25/Q26: one readiness predicate; legacy gate exemptions explicit."""

    def _ready_proposal(self) -> Proposal:
        return Proposal(
            id="p1",
            research_present=True,
            alternatives_count=2,
            gates_table_present=True,
        )

    def test_not_ready_rejected_for_filing_and_promotion(self):
        p = Proposal(id="p1")  # nothing filled in
        self.assertEqual(
            plan_transition(p, ProposalStatus.PROPOSED, None, (), True),
            ["refused", "notReady"],
        )

    def test_ready_proposal_accepted_without_actor(self):
        p = self._ready_proposal()
        out = plan_transition(p, ProposalStatus.PROPOSED, None, (), True)
        self.assertEqual(out[0], "planned")
        self.assertIs(out[1].status, ProposalStatus.PROPOSED)

    def test_accepted_requires_actor(self):
        p = self._ready_proposal()
        p2 = plan_transition(p, ProposalStatus.PROPOSED, None, (), True)[1]
        self.assertEqual(
            plan_transition(p2, ProposalStatus.ACCEPTED, None, (), True),
            ["refused", "missingActor"],
        )

    def test_applied_requires_land_gates_and_landed_refs(self):
        p = self._ready_proposal()
        p2 = plan_transition(p, ProposalStatus.PROPOSED, None, (), True)[1]
        p3 = plan_transition(p2, ProposalStatus.ACCEPTED, "t", (), True)[1]
        p4 = plan_transition(p3, ProposalStatus.LANDING, "t", (), True)[1]
        self.assertEqual(
            plan_transition(p4, ProposalStatus.APPLIED, "t", (), True),
            ["refused", "gatesNotPassed"],
        )
        import dataclasses
        p5 = dataclasses.replace(p4, land_gates_passed=True)
        self.assertEqual(
            plan_transition(p5, ProposalStatus.APPLIED, "t", (), True),
            ["refused", "gatesNotPassed"],
        )
        p6 = p5
        out = plan_transition(p6, ProposalStatus.APPLIED, "t", ("sha1",), True)
        self.assertEqual(out[0], "planned")

    def test_illegal_transition(self):
        p = self._ready_proposal()
        self.assertFalse(legal_transition(ProposalStatus.DRAFT, ProposalStatus.ACCEPTED))

    def test_conclude_requires_sections_and_no_open_hypotheses(self):
        good = Investigation(
            id="i1",
            checked_against="logs",
            scope_and_limits="scope",
            hypotheses=(Hypothesis("h", HypStatus.SUPPORTED),),
        )
        self.assertTrue(can_conclude(good))
        open_h = Investigation(
            id="i1",
            checked_against="logs",
            scope_and_limits="scope",
            hypotheses=(Hypothesis("h", HypStatus.OPEN),),
        )
        self.assertFalse(can_conclude(open_h))
        malformed = Investigation(
            id="i1",
            checked_against="logs",
            scope_and_limits="scope",
            hypotheses=(Hypothesis("h", HypStatus.MALFORMED),),
        )
        self.assertFalse(can_conclude(malformed))
        empty = Investigation(id="i1", checked_against="", scope_and_limits="", hypotheses=())
        self.assertFalse(can_conclude(empty))


class CommitTests(unittest.TestCase):
    """T20/T21 semantics on the modeled store."""

    def test_predecessor_conflict_leaves_state_unchanged(self):
        kb = KB(head="h0")
        op = Op(id="op1", expected_head="hX", changes=(), input_digest="d")
        kb2, outcome = commit_op(kb, (), op)
        self.assertEqual(outcome, "predecessorConflict")
        self.assertEqual(kb2, kb)

    def test_replay_same_is_idempotent_and_conflict_detected(self):
        kb = KB(head="h0")
        op = Op(id="op1", expected_head="h0", changes=(), input_digest="d")
        entry = JournalEntry(id="op1", head="h0", digest="d")
        _, outcome = commit_op(kb, (entry,), op)
        self.assertEqual(outcome, "alreadyCommitted")
        bad = JournalEntry(id="op1", head="h0", digest="other")
        _, outcome = commit_op(kb, (bad,), op)
        self.assertEqual(outcome, "inputConflict")

    def test_commit_advances_head(self):
        kb = KB(head="h0")
        op = Op(id="op1", expected_head="h0", changes=(), input_digest="d")
        kb2, outcome = commit_op(kb, (), op)
        self.assertEqual(outcome, "committed")
        self.assertEqual(kb2.head, "op1")


class WireTests(unittest.TestCase):
    """T01/T02 semantics on the Python side."""

    def test_roundtrip_kb(self):
        kb, _, _, _, _ = demo_parts()
        j = wire.enc_kb(kb)
        kb2 = wire.dec_kb(j)
        self.assertEqual(kb, kb2)

    def test_decode_rejects_empty_ids(self):
        with self.assertRaises(wire.WireError):
            wire.dec_observation(["", "ok", 100, ["expireAfter", 5], "s", "l"])

    def test_decode_rejects_wrong_arity(self):
        with self.assertRaises(wire.WireError):
            wire.dec_claim(["c1"])

    def test_decode_rejects_bool_as_int(self):
        with self.assertRaises(wire.WireError):
            wire.dec_eval_ctx([True, False, False, False])

    def test_semantic_version_matches_lean(self):
        self.assertEqual(SEMANTIC_VERSION, "1.0.0")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
