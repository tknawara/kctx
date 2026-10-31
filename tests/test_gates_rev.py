"""Gate-definition revision binding preserves historical unbound outcomes."""

from _base import KctxTestCase
from test_proposals import GATES_TABLE_LAND, _add

from kctx.domain.ids import GateId
from kctx.domain.proposals import GateResult
from kctx.domain.vocabulary import GateOutcome, GateWhen, ProposalStatus
from kctx.services import gates, proposals


class RevisionBoundSelectionTest(KctxTestCase):
    def test_pass_on_older_table_does_not_win(self):
        added = _add(self.root, gates=GATES_TABLE_LAND)
        proposals.gate(self.root, added.id, GateId("G1"), outcome=GateOutcome.PASS, evidence="ev1", checker="fixture-checker", expires_at=4102444800, by="agent")
        found = proposals.load(self.root, added.id)
        text = found.path.read_text().replace("| G1 | it works | `true` | land | agent |", "| G1 | it works | `false` | land | agent |", 1)
        found.path.write_text(text)
        updated = proposals.load(self.root, added.id)
        pending = gates.pending_for_when(gates.parse_gates_table(updated.document.sections), gates.load_results(updated.path), frozenset((GateWhen.LAND,)), rev=gates.gates_rev(updated.document.sections))
        self.assertIn(GateId("G1"), pending)

    def test_unrelated_edit_does_not_invalidate(self):
        added = _add(self.root, gates=GATES_TABLE_LAND)
        proposals.gate(self.root, added.id, GateId("G1"), outcome=GateOutcome.PASS, evidence="ev1", checker="fixture-checker", expires_at=4102444800, by="agent")
        proposals.set_status(self.root, added.id, status=ProposalStatus.ACCEPTED, by="user")
        found = proposals.load(self.root, added.id)
        pending = gates.pending_for_when(gates.parse_gates_table(found.document.sections), gates.load_results(found.path), frozenset((GateWhen.LAND,)), rev=gates.gates_rev(found.document.sections))
        self.assertEqual(pending, ())

    def test_latest_outcomes_rev_semantics(self):
        results = (GateResult(GateId("G1"), GateOutcome.PASS, "", "", rev="aaa"), GateResult(GateId("G1"), GateOutcome.FAIL, "", "", rev="bbb"))
        self.assertEqual(gates.latest_outcomes(results, rev="aaa"), {GateId("G1"): GateOutcome.PASS})
        self.assertEqual(gates.latest_outcomes(results, rev="bbb"), {GateId("G1"): GateOutcome.FAIL})
        self.assertEqual(gates.latest_outcomes(results), {GateId("G1"): GateOutcome.FAIL})
        legacy = (GateResult(GateId("G2"), GateOutcome.PASS, "", ""), GateResult(GateId("G1"), GateOutcome.PASS, "", "", rev="zzz"))
        self.assertEqual(gates.latest_outcomes(legacy, rev="other"), {GateId("G2"): GateOutcome.PASS})
