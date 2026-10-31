import json

from _base import KctxTestCase

import kctx.services.gates as gates
from kctx.codecs.gates import decode_gate_result
from kctx.domain.ids import GateId
from kctx.domain.proposals import GateDefinition, GateResult
from kctx.domain.vocabulary import GateOutcome, GateWhen
from kctx.errors import KctxError

TABLE = (
    "| id | claim | check | when | by |\n"
    "|---|---|---|---|---|\n"
    "| G1 | lands clean | `true` | land | agent |\n"
    "| G2 | deployed | `curl -f x` | deploy | agent |\n"
)


class ParseGatesTableTest(KctxTestCase):
    def test_parses_rows_into_records(self):
        parsed = gates.parse_gates_table(TABLE)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0], GateDefinition(GateId("G1"), GateWhen.LAND, "lands clean", "`true`", "agent"))
        self.assertEqual(parsed[1].id, GateId("G2"))
        self.assertIs(parsed[1].when, GateWhen.DEPLOY)

    def test_empty_section_returns_empty_tuple(self):
        self.assertEqual(gates.parse_gates_table(""), ())

    def test_free_prose_without_a_table_returns_empty_tuple(self):
        self.assertEqual(gates.parse_gates_table("No gates defined yet, just prose."), ())

    def test_table_missing_required_columns_is_malformed(self):
        with self.assertRaises(KctxError):
            gates.parse_gates_table("| claim | check |\n|---|---|\n| x | y |\n")

    def test_mapping_input_uses_top_level_acceptance_gates_section(self):
        body = {"Context": "intro", "Acceptance gates": TABLE, "Other": "x"}
        self.assertEqual(tuple(g.id for g in gates.parse_gates_table(body)), (GateId("G1"), GateId("G2")))

    def test_mapping_input_finds_nested_heading_at_any_level(self):
        for marker in ("##", "###", "####"):
            with self.subTest(marker=marker):
                body = {"Context": "intro", "Proposed change": f"some prose\n\n{marker} Acceptance gates\n\n{TABLE}\n{marker} References\n\nmore prose\n"}
                self.assertEqual(tuple(g.id for g in gates.parse_gates_table(body)), (GateId("G1"), GateId("G2")))

    def test_mapping_input_first_match_anywhere_in_body(self):
        body = {"Context": "no gates here", "Proposed change": f"### 1. Setup\n\n### Acceptance gates\n\n{TABLE}", "Impact": "none"}
        self.assertEqual(tuple(g.id for g in gates.parse_gates_table(body)), (GateId("G1"), GateId("G2")))

    def test_mapping_input_no_heading_returns_empty_tuple(self):
        self.assertEqual(gates.parse_gates_table({"Context": "no gates anywhere", "Proposed change": "just prose"}), ())

    def test_fenced_tables_and_headings_are_not_gates(self):
        self.assertEqual(gates.parse_gates_table(f"```markdown\n{TABLE}```\n"), ())
        self.assertEqual(gates.parse_gates_table({"Context": f"~~~\n### Acceptance gates\n{TABLE}~~~\n"}), ())

    def test_malformed_gate_records_are_diagnosed(self):
        for table in (TABLE.replace("deploy", "someday"), TABLE.replace("G2", "G1"), TABLE + "| G3 | land |\n"):
            with self.subTest(table=table), self.assertRaises(KctxError):
                gates.parse_gates_table(table)


class GatesJsonPathTest(KctxTestCase):
    def test_directory_home_uses_sibling_gates_json(self):
        path = self.root / "proposals/config/2026-10-25-x/proposal.md"
        self.assertEqual(gates.gates_json_path(path), path.parent / "gates.json")

    def test_legacy_file_uses_stem_gates_json(self):
        path = self.root / "proposals/skill/2026-10-25-x.md"
        self.assertEqual(gates.gates_json_path(path), path.parent / "2026-10-25-x.gates.json")


class GateResultsTest(KctxTestCase):
    def test_load_results_on_missing_file_is_empty(self):
        self.assertEqual(gates.load_results(self.root / "proposal.md"), ())

    def test_append_and_load_round_trip(self):
        path = self.root / "proposals/config/2026-10-25-x/proposal.md"
        path.parent.mkdir(parents=True)
        gates.append_result(path, gate=GateId("G1"), outcome=GateOutcome.PASS, evidence="obs:1", by="a")
        gates.append_result(path, gate=GateId("G2"), outcome=GateOutcome.FAIL, evidence="obs:2")
        results = gates.load_results(path)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].gate, GateId("G1"))
        self.assertEqual(results[0].by, "a")
        self.assertIsNone(results[1].by)
        wire = json.loads(gates.gates_json_path(path).read_text())
        self.assertEqual(wire[0]["gate"], "G1")
        self.assertNotIn("by", wire[1])

    def test_decoder_rejects_bad_outcome(self):
        with self.assertRaises(KctxError):
            decode_gate_result({"gate": "G1", "outcome": "maybe", "evidence": "obs:1", "at": "now"})

    def test_latest_outcomes_last_write_wins(self):
        results = (GateResult(GateId("G1"), GateOutcome.FAIL, "", ""), GateResult(GateId("G1"), GateOutcome.PASS, "", ""), GateResult(GateId("G2"), GateOutcome.UNK, "", ""))
        self.assertEqual(gates.latest_outcomes(results), {GateId("G1"): GateOutcome.PASS, GateId("G2"): GateOutcome.UNK})

    def test_pending_for_when(self):
        table = (GateDefinition(GateId("G1"), GateWhen.LAND), GateDefinition(GateId("G2"), GateWhen.DEPLOY), GateDefinition(GateId("G3"), GateWhen.USE))
        results = (GateResult(GateId("G1"), GateOutcome.PASS, "", ""), GateResult(GateId("G2"), GateOutcome.FAIL, "", ""))
        self.assertEqual(gates.pending_for_when(table, results, frozenset((GateWhen.DEPLOY, GateWhen.USE))), (GateId("G2"), GateId("G3")))
        self.assertEqual(gates.pending_for_when(table, results, frozenset((GateWhen.LAND,))), ())

    def test_malformed_history_is_rejected_before_append(self):
        path = self.root / "proposal.md"
        target = gates.gates_json_path(path)
        for bad in ({"gate": "G1", "outcome": "pass"}, [], {"gate": "G1", "outcome": "pass", "evidence": [], "at": "now"}, {"gate": "G1", "outcome": "pass", "evidence": "x", "at": "now", "unknown": 1}):
            original = json.dumps([bad])
            target.write_text(original)
            with self.subTest(bad=bad), self.assertRaises(KctxError):
                gates.append_result(path, gate=GateId("G1"), outcome=GateOutcome.PASS, evidence="x")
            self.assertEqual(target.read_text(), original)
