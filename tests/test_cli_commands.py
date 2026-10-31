"""CLI outcomes across authored records, navigation and citation workflows."""

import io
import json
import subprocess
from contextlib import redirect_stdout

from _base import KctxTestCase

from kctx.cli import app as cli
from kctx.services import inventory
from kctx.domain.ids import AssetId
from kctx.domain.vocabulary import AssetKind


def _run(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, json.loads(buf.getvalue())


class CliCommandsTest(KctxTestCase):
    def test_home_no_match_exits_2(self):
        code, payload = _run(["--json", "home", "nothing-here"])
        self.assertEqual(code, 2)
        self.assertEqual(payload["candidates"], [])

    def test_home_match_exits_0(self):
        inventory.asset_add(
            self.root,
            kind=AssetKind.SERVICE,
            name="pbpsvc",
            id=AssetId("service-pbpsvc"),
            projects=("demo-project",),
        )
        code, payload = _run(["--json", "home", "pbpsvc"])
        self.assertEqual(code, 0)
        self.assertEqual(len(payload["candidates"]), 1)

    def test_context_exits_0(self):
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name="svc", id=AssetId("service-svc"))
        code, payload = _run(["--json", "context", "service-svc", "--depth", "1"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["asset"], "service-svc")

    def test_stale_exits_0(self):
        code, payload = _run(["--json", "stale"])
        self.assertEqual(code, 0)

    def test_stale_drain_requires_project_or_paths(self):
        code, payload = _run(["--json", "stale", "--drain"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "incomplete")

    def test_stale_drain_exits_0_when_nothing_remains(self):
        proj = self.root / "demo-project"
        proj.mkdir()
        code, payload = _run(
            ["--json", "stale", "--drain", "--project", "demo-project"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(payload["total_remaining"], 0)

    def test_stale_drain_exits_2_when_items_remain(self):
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "note.md").write_text('⟦cite kind=ticket seen=2020-01-01T00:00Z ttl=1d⟧\n', encoding="utf-8")
        code, payload = _run(
            ["--json", "stale", "--drain", "--project", "demo-project"]
        )
        self.assertEqual(code, 2)
        self.assertEqual(payload["total_remaining"], 1)

    def test_stale_drain_reports_unverifiable_sources_as_remaining(self):
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "note.md").write_text(
            f'⟦cite kind=code repo=local:{self.root / "missing"} path=x L=1-1⟧\n',
            encoding="utf-8",
        )
        code, payload = _run(
            ["--json", "stale", "--drain", "--project", "demo-project"]
        )
        self.assertEqual(code, 2)
        self.assertEqual(len(payload["remaining"]["unverifiable"]), 1)

    def test_cite_make_check_stale_render_round_trip(self):
        code, made = _run(["--json", "cite", "make", "ticket", "id=DRQS 1", "q=why", "ttl=1d"])
        self.assertEqual(code, 0)
        code, checked = _run(["--json", "cite", "check", "--line", made["line"]])
        self.assertEqual(code, 0)
        self.assertEqual(checked["results"][0]["status"], "fresh")
        code, rendered = _run(["--json", "cite", "render", made["line"]])
        self.assertEqual(code, 0)
        self.assertTrue(rendered["rendered"])
        path = self.root / "note.md"
        path.write_text('⟦cite kind=ticket seen=2020-01-01T00:00Z ttl=1d⟧\n', encoding="utf-8")
        code, stale = _run(["--json", "cite", "stale", str(path), "--offline"])
        self.assertEqual(code, 2)
        self.assertEqual(stale["entries"][0]["reason"], "due")

    def test_cite_check_unavailable_source_exits_three(self):
        code, checked = _run(["--json", "cite", "check", "--line", f'⟦cite kind=code repo=local:{self.root / "missing"} path=x L=1-1⟧'])
        self.assertEqual(code, 3)
        self.assertEqual(checked["results"][0]["status"], "unverifiable")

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
        target = self.root / "target"
        subprocess.run(["git", "init", "-q", str(target)], check=True)
        subprocess.run(["git", "-C", str(target), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "retained target"], check=True)
        revision = subprocess.check_output(["git", "-C", str(target), "rev-parse", "HEAD"], text=True).strip()
        gates_table = (
            "| id | claim | check | when | by | checker |\n"
            "|---|---|---|---|---|---|\n"
            "| G1 | it works | `true` | land | agent | fixture-checker |\n"
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
                "--target-revision", f"target@{revision}",
                "--environment", "local-fixture", "--scope", str(target),
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
                "--by", "agent", "--checker", "fixture-checker",
                "--expires-at", "4102444800",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(gate_result["outcome"], "pass")

        code, fm = _run(
            ["--json", "proposal", "set", pid, "--status", "applied", "--by", "agent", "--landed", f"target@{revision}"]
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

    def test_proposal_missing_review_sections_remains_draft(self):
        code, added = _run([
            "--json", "proposal", "add", "--kind", "other", "--origin", "unk",
            "--title", "Needs review", "--context", "c", "--evidence", "e",
            "--change", "ch", "--why", "w",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(added["frontmatter"]["status"], "draft")

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

    def test_run_capture_coverage_and_resume_preserve_provenance(self):
        code, manifest = _run([
            "--json", "run", "new", "--project", "demo", "--mode", "advice",
            "--task", "Capture a CLI investigation",
        ])
        self.assertEqual(code, 0)
        run_id = manifest["run_id"]
        code, observation = _run([
            "--json", "observe", run_id, "--system", "other", "--locator", "source-a",
            "--environment", "fixture", "--cmd", "inspect", "--note", "First source",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(observation["environment"], "fixture")
        self.assertEqual(observation["command"], "inspect")
        code, derived = _run([
            "--json", "observe", run_id, "--system", "other", "--locator", "source-b",
            "--derived-from", observation["id"],
        ])
        self.assertEqual(code, 0)
        self.assertEqual(derived["derived_from"], [observation["id"]])
        code, coverage = _run([
            "--json", "cover", run_id, "--item", "question", "--outcome", "inconclusive",
            "--evidence", derived["id"], "--reason", "Needs independent corroboration",
            "--policy", "independent-origins",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(coverage["policy"], "independent-origins")
        self.assertEqual(coverage["evidence"], [derived["id"]])
        code, checkpoint = _run(["--json", "checkpoint", run_id, "--note", "Continue later"])
        self.assertEqual(code, 0)
        self.assertEqual(checkpoint["run"], run_id)
        code, resumed = _run(["--json", "resume", run_id])
        self.assertEqual(code, 0)
        self.assertEqual(resumed["manifest"]["run_id"], run_id)
        self.assertEqual(resumed["coverage_summary"], {"inconclusive": 1})

    def test_correction_recovery_without_operations_is_empty(self):
        code, recovered = _run(["--json", "correction", "recover"])
        self.assertEqual(code, 0)
        self.assertEqual(recovered, {"operations": []})

    def test_invalid_asset_vocabulary_is_a_domain_error(self):
        code, error = _run(["--json", "asset", "add", "--kind", "not-a-kind", "--name", "Invalid"])
        self.assertEqual(code, 1)
        self.assertEqual(error["error"], "malformed")
