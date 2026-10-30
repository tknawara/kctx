"""Thin CLI-wiring checks for the new subcommands: the module-level tests in
test_nav.py and test_ktlo.py cover behavior, this only guards against an
argparse/dispatch mismatch (wrong dest, missing branch, wrong exit code)."""

import io
import json
import os
from contextlib import redirect_stdout

from _base import KctxTestCase, no_cite_available

import cli
import inventory


def _run(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, json.loads(buf.getvalue())


class CliWiringTest(KctxTestCase):
    def test_home_no_match_exits_2(self):
        code, payload = _run(["--json", "home", "nothing-here"])
        self.assertEqual(code, 2)
        self.assertEqual(payload["candidates"], [])

    def test_home_match_exits_0(self):
        inventory.asset_add(
            self.root,
            kind="service",
            name="pbpsvc",
            id="service-pbpsvc",
            projects=["demo-project"],
        )
        code, payload = _run(["--json", "home", "pbpsvc"])
        self.assertEqual(code, 0)
        self.assertEqual(len(payload["candidates"]), 1)

    def test_context_exits_0(self):
        inventory.asset_add(self.root, kind="service", name="svc", id="service-svc")
        code, payload = _run(["--json", "context", "service-svc", "--depth", "1"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["asset"], "service-svc")

    def test_stale_exits_0(self):
        # Pin CITE_BIN to a path that can't resolve so this stays
        # host-independent -- it must not depend on whether this machine
        # happens to have the real grounding cite script deployed.
        old = os.environ.get("CITE_BIN")
        os.environ["CITE_BIN"] = "/nonexistent/cite"
        try:
            code, payload = _run(["--json", "stale"])
        finally:
            if old is None:
                os.environ.pop("CITE_BIN", None)
            else:
                os.environ["CITE_BIN"] = old
        self.assertEqual(code, 0)

    def test_stale_drain_requires_project_or_paths(self):
        code, payload = _run(["--json", "stale", "--drain"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "incomplete")

    def test_stale_drain_exits_0_when_nothing_remains(self):
        proj = self.root / "demo-project"
        proj.mkdir()
        stub = self.write_cite_stub(
            {"results": [], "warnings": [], "skipped": [], "exit_code": 0}
        )
        os.environ["CITE_BIN"] = stub
        try:
            code, payload = _run(
                ["--json", "stale", "--drain", "--project", "demo-project"]
            )
        finally:
            os.environ.pop("CITE_BIN", None)
        self.assertEqual(code, 0)
        self.assertEqual(payload["total_remaining"], 0)

    def test_stale_drain_exits_2_when_items_remain(self):
        proj = self.root / "demo-project"
        proj.mkdir()
        stub = self.write_cite_stub(
            {
                "results": [
                    {
                        "file": "demo-project/notes/a.md",
                        "line_no": 3,
                        "status": "expired",
                        "fields": {"kind": "ticket"},
                    }
                ],
                "warnings": [],
                "skipped": [],
                "exit_code": 2,
            },
            exit_code=2,
        )
        os.environ["CITE_BIN"] = stub
        try:
            code, payload = _run(
                ["--json", "stale", "--drain", "--project", "demo-project"]
            )
        finally:
            os.environ.pop("CITE_BIN", None)
        self.assertEqual(code, 2)
        self.assertEqual(payload["total_remaining"], 1)

    def test_stale_drain_exits_3_when_citations_unavailable(self):
        proj = self.root / "demo-project"
        proj.mkdir()
        with no_cite_available():
            code, payload = _run(
                ["--json", "stale", "--drain", "--project", "demo-project"]
            )
        self.assertEqual(code, 3)
        self.assertFalse(payload["citations_available"])

    def test_ktlo_new_then_promote_round_trip(self):
        code, payload = _run(
            ["--json", "ktlo", "new", "DRQS 1", "--title", "a cli round trip"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(payload["ticket"], "DRQS-1")

        code, payload = _run(["--json", "ktlo", "promote", "DRQS 1", "demo-project"])
        self.assertEqual(code, 0)
        self.assertFalse(payload["already_promoted"])

        code, payload = _run(["--json", "ktlo", "promote", "DRQS 1", "demo-project"])
        self.assertEqual(code, 0)
        self.assertTrue(payload["already_promoted"])

    def test_proposal_add_list_set_gate_show_round_trip(self):
        gates_table = (
            "| id | claim | check | when | by |\n"
            "|---|---|---|---|---|\n"
            "| G1 | it works | `true` | land | agent |\n"
        )
        code, added = _run(
            [
                "--json",
                "proposal",
                "add",
                "--kind",
                "config",
                "--origin",
                "user-request",
                "--title",
                "CLI round trip",
                "--context",
                "c",
                "--evidence",
                "e",
                "--change",
                "ch",
                "--why",
                "w",
                "--research",
                "researched",
                "--alternatives",
                "- A\n- B",
                "--gates",
                gates_table,
                "--type",
                "agent",
                "--type",
                "module",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(added["frontmatter"]["status"], "proposed")
        self.assertEqual(added["frontmatter"]["type"], ["agent", "module"])
        pid = added["id"]

        code, listed = _run(["--json", "proposal", "list"])
        self.assertEqual(code, 0)
        self.assertEqual(len(listed), 1)

        code, _ = _run(
            ["--json", "proposal", "set", pid, "--status", "accepted", "--by", "user"]
        )
        self.assertEqual(code, 0)
        code, _ = _run(
            ["--json", "proposal", "set", pid, "--status", "landing", "--by", "agent"]
        )
        self.assertEqual(code, 0)

        code, gate_result = _run(
            [
                "--json",
                "proposal",
                "gate",
                pid,
                "G1",
                "--outcome",
                "pass",
                "--evidence",
                "obs:1",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(gate_result["outcome"], "pass")

        code, fm = _run(
            ["--json", "proposal", "set", pid, "--status", "applied", "--by", "agent"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(fm["status"], "applied")

        code, shown = _run(["--json", "proposal", "show", pid])
        self.assertEqual(code, 0)
        self.assertEqual(shown["id"], pid)
        self.assertEqual(shown["gates"][0]["outcome"], "pass")

    def test_proposal_set_illegal_transition_exits_1(self):
        code, added = _run(
            [
                "--json",
                "proposal",
                "add",
                "--kind",
                "other",
                "--origin",
                "unk",
                "--title",
                "Illegal jump",
                "--context",
                "c",
                "--evidence",
                "e",
                "--change",
                "ch",
                "--why",
                "w",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(added["frontmatter"]["status"], "draft")

        code, payload = _run(
            [
                "--json",
                "proposal",
                "set",
                added["id"],
                "--status",
                "applied",
                "--by",
                "user",
            ]
        )
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "malformed")

    def test_proposal_add_missing_review_sections_lists_them_in_text_mode(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(
                [
                    "proposal",
                    "add",
                    "--kind",
                    "other",
                    "--origin",
                    "unk",
                    "--title",
                    "Needs review",
                    "--context",
                    "c",
                    "--evidence",
                    "e",
                    "--change",
                    "ch",
                    "--why",
                    "w",
                ]
            )
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("missing for review", out)

    def test_inv_new_list_show_conclude(self):
        code, result = _run(
            ["--json", "inv", "new", "x", "--trigger", "adhoc", "--title", "X"]
        )
        self.assertEqual(code, 0)
        inv_id = result["id"]

        code, _ = _run(["--json", "inv", "list"])
        self.assertEqual(code, 0)

        code, shown = _run(["--json", "inv", "show", inv_id])
        self.assertEqual(code, 0)
        self.assertEqual(shown["id"], inv_id)

        code, _ = _run(["--json", "inv", "conclude", inv_id])
        self.assertEqual(code, 1)  # missing Checked against / Scope and limits

    def test_inv_new_accepts_backfilled_created_date(self):
        code, result = _run(
            [
                "--json",
                "inv",
                "new",
                "x",
                "--trigger",
                "adhoc",
                "--created",
                "2026-09-22",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["id"], "2026/2026-09-22-x")

    def test_inv_promote(self):
        code, result = _run(["--json", "inv", "new", "x", "--trigger", "adhoc"])
        self.assertEqual(code, 0)
        code, promoted = _run(
            ["--json", "inv", "promote", result["id"], "demo-project"]
        )
        self.assertEqual(code, 0)
        self.assertFalse(promoted["already_promoted"])

    def test_sig_new_list_show(self):
        code, result = _run(
            ["--json", "sig", "new", "x", "--match", "PEDL001", "--owner-group", "g1"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["id"], "x")

        code, _ = _run(["--json", "sig", "list"])
        self.assertEqual(code, 0)

        code, shown = _run(["--json", "sig", "show", "x"])
        self.assertEqual(code, 0)
        self.assertEqual(shown["id"], "x")

    def test_match_exits_2_on_no_hit_and_0_on_hit(self):
        code, result = _run(["--json", "match", "nothing-should-match-this"])
        self.assertEqual(code, 2)
        self.assertIn("note", result)

        _run(["--json", "sig", "new", "x", "--match", "PEDL001"])
        code, result = _run(["--json", "match", "PEDL001 duplicate element"])
        self.assertEqual(code, 0)
        self.assertEqual(result["signatures"][0]["id"], "x")

    def test_timeline_exits_0(self):
        _run(
            [
                "--json",
                "inv",
                "new",
                "x",
                "--trigger",
                "adhoc",
                "--alert",
                "alert-b1",
            ]
        )
        code, result = _run(["--json", "timeline", "alert-b1"])
        self.assertEqual(code, 0)
        self.assertEqual(len(result["investigations"]), 1)

    def test_asset_add_with_ttl_and_validate(self):
        code, _ = _run(
            [
                "--json",
                "asset",
                "add",
                "--kind",
                "service",
                "--name",
                "ttl-svc",
                "--id",
                "service-ttl-svc",
                "--verified-at",
                "2020-01-01T00:00:00Z",
                "--ttl",
                "1d",
            ]
        )
        self.assertEqual(code, 0)
        code, payload = _run(["--json", "validate"])
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
