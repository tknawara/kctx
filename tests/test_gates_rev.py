"""Revision-bound gate-result selection (handover 8.1).

A pass recorded against an older Acceptance-gates table must not win merely
because its gate id matches: results are bound to a digest of the gate
definitions, and selection within a revision skips results bound to a
different one. Legacy results (no `rev`) keep their old semantics.
Unrelated edits — status flips, Decision-log lines — must NOT invalidate
gate results.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import proposals  # noqa: E402
from gates import latest_outcomes  # noqa: E402
from tests import _base  # noqa: E402
from tests.test_proposals import (  # noqa: E402
    GATES_TABLE_FULL,
    GATES_TABLE_LAND,
    TWO_ALTERNATIVES,
    _add,
)


class RevisionBoundSelectionTest(_base.KctxTestCase):
    def test_pass_on_older_table_does_not_win(self):
        added = _add(self.root, gates=GATES_TABLE_LAND)
        pid = added["id"]
        proposals.gate(self.root, pid, "G1", outcome="pass", evidence="ev1")
        found = proposals.load(self.root, pid)
        path = found["path"]
        text = path.read_text(encoding="utf-8")
        # the gate definition changes (check cell edit) — the earlier pass
        # was recorded against the old table and must stop winning
        text = text.replace("| G1 | it works | `true` | land | agent |",
                            "| G1 | it works | `false` | land | agent |", 1)
        path.write_text(text)

        found2 = proposals.load(self.root, pid)
        results = proposals.gates_mod.load_results(found2["path"])
        table = proposals.gates_mod.parse_gates_table(found2["body"])
        pending = proposals.gates_mod.pending_for_when(
            table, results, {"land"}, rev=proposals._gate_rev(found2["body"])
        )
        self.assertIn("G1", pending)

    def test_unrelated_edit_does_not_invalidate(self):
        added = _add(self.root, gates=GATES_TABLE_LAND)
        pid = added["id"]
        proposals.gate(self.root, pid, "G1", outcome="pass", evidence="ev1")
        # a status flip + decision-log line (unrelated to the definitions)
        proposals.set_status(self.root, pid, status="accepted", by="user")
        found = proposals.load(self.root, pid)
        results = proposals.gates_mod.load_results(found["path"])
        table = proposals.gates_mod.parse_gates_table(found["body"])
        pending = proposals.gates_mod.pending_for_when(
            table, results, {"land"}, rev=proposals._gate_rev(found["body"])
        )
        self.assertEqual(pending, [])

    def test_latest_outcomes_rev_semantics(self):
        results = [
            {"gate": "G1", "outcome": "pass", "rev": "aaa"},
            {"gate": "G1", "outcome": "fail", "rev": "bbb"},  # newer, other rev
        ]
        # within rev aaa: the pass (recorded under aaa) wins; bbb entry skipped
        self.assertEqual(latest_outcomes(results, rev="aaa"), {"G1": "pass"})
        # within rev bbb: only the fail counts
        self.assertEqual(latest_outcomes(results, rev="bbb"), {"G1": "fail"})
        # unbound (legacy/display) keeps old last-wins semantics
        self.assertEqual(latest_outcomes(results), {"G1": "fail"})
        # legacy entries (no rev) are consulted regardless
        legacy = [
            {"gate": "G2", "outcome": "pass"},
            {"gate": "G1", "outcome": "pass", "rev": "zzz"},
        ]
        self.assertEqual(latest_outcomes(legacy, rev="other"), {"G2": "pass"})


if __name__ == "__main__":
    unittest.main()
