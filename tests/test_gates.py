from pathlib import Path

from _base import KctxTestCase

import gates
from errors import KctxError

TABLE = (
    "| id | claim | check | when | by |\n"
    "|---|---|---|---|---|\n"
    "| G1 | lands clean | `true` | land | agent |\n"
    "| G2 | deployed | `curl -f x` | deploy | agent |\n"
)


class ParseGatesTableTest(KctxTestCase):
    def test_parses_rows_into_dicts(self):
        parsed = gates.parse_gates_table(TABLE)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(
            parsed[0],
            {
                "id": "G1",
                "claim": "lands clean",
                "check": "`true`",
                "when": "land",
                "by": "agent",
            },
        )
        self.assertEqual(parsed[1]["id"], "G2")
        self.assertEqual(parsed[1]["when"], "deploy")

    def test_empty_section_returns_empty_list(self):
        self.assertEqual(gates.parse_gates_table(""), [])

    def test_free_prose_without_a_table_returns_empty_list(self):
        self.assertEqual(
            gates.parse_gates_table("No gates defined yet, just prose."), []
        )

    def test_table_missing_required_columns_returns_empty_list(self):
        bad = "| claim | check |\n|---|---|\n| x | y |\n"
        self.assertEqual(gates.parse_gates_table(bad), [])

    def test_dict_input_uses_top_level_acceptance_gates_section(self):
        body = {"Context": "intro", "Acceptance gates": TABLE, "Other": "x"}
        parsed = gates.parse_gates_table(body)
        self.assertEqual([g["id"] for g in parsed], ["G1", "G2"])

    def test_dict_input_finds_nested_heading_at_any_level(self):
        for marker in ("##", "###", "####"):
            with self.subTest(marker=marker):
                body = {
                    "Context": "intro",
                    "Proposed change": (
                        f"some prose\n\n{marker} Acceptance gates\n\n{TABLE}\n"
                        f"{marker} References\n\nmore prose\n"
                    ),
                }
                parsed = gates.parse_gates_table(body)
                self.assertEqual([g["id"] for g in parsed], ["G1", "G2"])

    def test_dict_input_first_match_anywhere_in_body(self):
        body = {
            "Context": "no gates here",
            "Proposed change": f"### 1. Setup\n\n### Acceptance gates\n\n{TABLE}",
            "Impact": "none",
        }
        parsed = gates.parse_gates_table(body)
        self.assertEqual([g["id"] for g in parsed], ["G1", "G2"])

    def test_dict_input_no_heading_returns_empty_list(self):
        body = {"Context": "no gates anywhere", "Proposed change": "just prose"}
        self.assertEqual(gates.parse_gates_table(body), [])


class GatesJsonPathTest(KctxTestCase):
    def test_directory_home_uses_sibling_gates_json(self):
        p = self.root / "proposals" / "config" / "2026-10-25-x" / "proposal.md"
        self.assertEqual(gates.gates_json_path(p), p.parent / "gates.json")

    def test_legacy_file_uses_stem_gates_json(self):
        p = self.root / "proposals" / "skill" / "2026-10-25-x.md"
        self.assertEqual(gates.gates_json_path(p), p.parent / "2026-10-25-x.gates.json")


class GateResultsTest(KctxTestCase):
    def test_load_results_on_missing_file_is_empty(self):
        p = self.root / "proposals" / "config" / "2026-10-25-x" / "proposal.md"
        self.assertEqual(gates.load_results(p), [])

    def test_append_and_load_round_trip(self):
        p = self.root / "proposals" / "config" / "2026-10-25-x" / "proposal.md"
        p.parent.mkdir(parents=True)
        gates.append_result(p, gate="G1", outcome="pass", evidence="obs:1", by="a")
        gates.append_result(p, gate="G2", outcome="fail", evidence="obs:2")
        results = gates.load_results(p)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["gate"], "G1")
        self.assertEqual(results[0]["by"], "a")
        self.assertNotIn("by", results[1])

    def test_append_rejects_bad_outcome(self):
        p = self.root / "proposals" / "config" / "2026-10-25-x" / "proposal.md"
        with self.assertRaises(KctxError):
            gates.append_result(p, gate="G1", outcome="maybe", evidence="obs:1")

    def test_latest_outcomes_last_write_wins(self):
        results = [
            {"gate": "G1", "outcome": "fail"},
            {"gate": "G1", "outcome": "pass"},
            {"gate": "G2", "outcome": "unk"},
        ]
        self.assertEqual(gates.latest_outcomes(results), {"G1": "pass", "G2": "unk"})

    def test_pending_for_when(self):
        table = [
            {"id": "G1", "when": "land"},
            {"id": "G2", "when": "deploy"},
            {"id": "G3", "when": "use"},
        ]
        results = [{"gate": "G1", "outcome": "pass"}, {"gate": "G2", "outcome": "fail"}]
        self.assertEqual(
            gates.pending_for_when(table, results, {"deploy", "use"}),
            ["G2", "G3"],
        )
        self.assertEqual(gates.pending_for_when(table, results, {"land"}), [])
