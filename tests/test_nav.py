import os

from _base import KctxTestCase, no_cite_available as _no_cite_available, set_config, clear_config

import corrections as corrections_mod
import dossiers as dossiers_mod
import inventory
import investigations as inv_mod
import ktlo
import nav
import proposals as proposals_mod
import runs as runs_mod
import signatures as sig_mod
import validate as validate_mod
from errors import KctxError
from storage import today

GATES_TABLE = (
    "| id | claim | check | when | by |\n"
    "|---|---|---|---|---|\n"
    "| G1 | it works | `true` | land | agent |\n"
)
TWO_ALTERNATIVES = "- A. do nothing\n- B. do the thing\n"


class HomeTest(KctxTestCase):
    def test_no_match_reports_empty_candidates_with_boundary_note(self):
        result = nav.home(self.root, "nothing-tracks-this")
        self.assertEqual(result["candidates"], [])
        self.assertIn("note", result)

    def test_asset_projects_field_yields_a_project_candidate(self):
        inventory.asset_add(
            self.root,
            kind="service",
            name="pbpsvc",
            id="service-pbpsvc",
            projects=["demo-project"],
        )
        result = nav.home(self.root, "pbpsvc")
        self.assertEqual(len(result["candidates"]), 1)
        c = result["candidates"][0]
        self.assertEqual(c["type"], "project")
        self.assertEqual(c["target"], "demo-project")
        self.assertIn("service-pbpsvc", c["evidence"])

    def test_project_grep_candidate_from_inventory_md(self):
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "inventory.md").write_text("| pbprpsvc | done | |\n", encoding="utf-8")
        result = nav.home(self.root, "pbprpsvc")
        self.assertEqual(
            [(c["type"], c["target"]) for c in result["candidates"]],
            [("project", "demo-project")],
        )

    def test_asset_and_grep_candidates_for_same_project_are_deduped(self):
        inventory.asset_add(
            self.root,
            kind="service",
            name="pbpsvc",
            id="service-pbpsvc",
            projects=["demo-project"],
        )
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "README.md").write_text("owns pbpsvc\n", encoding="utf-8")

        result = nav.home(self.root, "pbpsvc")
        self.assertEqual(len(result["candidates"]), 1)
        self.assertIn("projects includes", result["candidates"][0]["evidence"])
        self.assertIn("README.md references", result["candidates"][0]["evidence"])

    def test_ktlo_ticket_and_asset_candidates(self):
        inventory.asset_add(self.root, kind="service", name="svc", id="service-svc")
        ktlo.new(self.root, ticket="DRQS 1", title="ticket matches by ticket")
        ktlo.new(
            self.root,
            ticket="DRQS 2",
            title="ticket matches by asset",
            assets=["service-svc"],
        )

        by_ticket = nav.home(self.root, "DRQS 1")
        self.assertEqual(len(by_ticket["candidates"]), 1)
        self.assertEqual(by_ticket["candidates"][0]["type"], "ktlo")

        by_asset = nav.home(self.root, "service-svc")
        ktlo_hits = [c for c in by_asset["candidates"] if c["type"] == "ktlo"]
        self.assertEqual(len(ktlo_hits), 1)
        self.assertIn("ticket-matches-by-asset", ktlo_hits[0]["target"])

    def test_investigation_ticket_and_asset_candidates(self):
        by_ticket = inv_mod.new(
            self.root, "by-ticket", trigger="drqs", tickets=["DRQS-7"]
        )
        by_asset = inv_mod.new(
            self.root, "by-asset", trigger="adhoc", assets=["service-svc"]
        )

        result = nav.home(self.root, "DRQS 7")
        self.assertEqual(
            [(c["type"], c["target"]) for c in result["candidates"]],
            [("investigation", by_ticket["id"])],
        )

        result = nav.home(self.root, "service-svc")
        inv_hits = [c for c in result["candidates"] if c["type"] == "investigation"]
        self.assertEqual([h["target"] for h in inv_hits], [by_asset["id"]])

    def test_multiple_distinct_candidates_all_reported(self):
        inventory.asset_add(
            self.root,
            kind="service",
            name="sharedname",
            id="service-sharedname",
            projects=["project-a"],
        )
        proj_b = self.root / "project-b"
        proj_b.mkdir()
        (proj_b / "README.md").write_text(
            "mentions sharedname here\n", encoding="utf-8"
        )

        result = nav.home(self.root, "sharedname")
        targets = sorted(c["target"] for c in result["candidates"])
        self.assertEqual(targets, ["project-a", "project-b"])


class ContextTest(KctxTestCase):
    def _build_fixture(self):
        inventory.asset_add(
            self.root,
            kind="service",
            name="pbpsvc",
            id="service-pbpsvc",
            projects=["demo-project"],
            verified_at="2020-01-01T00:00:00Z",
        )
        inventory.asset_add(self.root, kind="doc", name="runbook", id="doc-runbook")
        inventory.rel_add(
            self.root,
            type="documents",
            from_="doc-runbook",
            to="service-pbpsvc",
        )
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "README.md").write_text("pbpsvc lives here\n", encoding="utf-8")

    def test_context_unknown_asset_is_not_found(self):
        with self.assertRaises(KctxError) as ctx:
            nav.context(self.root, "no-such-asset")
        self.assertEqual(ctx.exception.category, "not-found")

    def test_context_assembles_impact_projects_and_linked_docs(self):
        self._build_fixture()
        with _no_cite_available():
            result = nav.context(self.root, "service-pbpsvc")

        self.assertEqual(result["asset"], "service-pbpsvc")
        self.assertEqual(result["projects"], ["demo-project"])
        self.assertIn("note", result["impact"])  # coverage-boundary note passthrough
        linked_ids = {d["asset"] for d in result["linked_docs"]}
        self.assertIn("doc-runbook", linked_ids)

    def test_context_freshness_reflects_ttl_and_cite_unavailable(self):
        self._build_fixture()
        inventory.asset_add(
            self.root,
            kind="service",
            name="pastttl",
            id="service-pastttl",
            projects=["demo-project"],
            verified_at="2020-01-01T00:00:00Z",
            ttl="1d",
        )
        with _no_cite_available():
            result = nav.context(self.root, "service-pastttl")

        self.assertTrue(result["freshness"]["asset_past_ttl"])
        self.assertFalse(result["freshness"]["citations"]["available"])

    def test_context_cite_available_surfaces_stub_results(self):
        self._build_fixture()
        stub = self.write_cite_stub(
            {
                "results": [
                    {"file": "x", "line_no": 1, "status": "changed", "fields": {}}
                ],
                "warnings": [],
                "exit_code": 2,
            },
            exit_code=2,
        )
        set_config(cite_bin=str(stub))
        try:
            result = nav.context(self.root, "service-pbpsvc")
        finally:
            clear_config("cite_bin")

        citations = result["freshness"]["citations"]
        self.assertTrue(citations["available"])
        self.assertEqual(citations["results"][0]["status"], "changed")

    def test_context_includes_investigations_signatures_and_runbooks(self):
        self._build_fixture()
        result = inv_mod.new(
            self.root, "touches-pbpsvc", trigger="adhoc", assets=["service-pbpsvc"]
        )
        found = inv_mod.load(self.root, result["id"])
        fm = found["frontmatter"]
        fm["signatures"] = ["known-sig"]
        found["path"].write_text(inv_mod.render(fm, found["body"]), encoding="utf-8")
        sig_mod.new(self.root, "known-sig", title="a known failure")

        runbook_dir = self.root / "runbooks" / "workflow"
        runbook_dir.mkdir(parents=True)
        (runbook_dir / "b1-response.md").write_text(
            "---\nlayer: workflow\nassets: [service-pbpsvc]\n---\n\n# B1 response\n",
            encoding="utf-8",
        )

        with _no_cite_available():
            ctx = nav.context(self.root, "service-pbpsvc")

        self.assertEqual([h["id"] for h in ctx["investigations"]], [result["id"]])
        self.assertEqual([s["id"] for s in ctx["signatures"]], ["known-sig"])
        self.assertEqual(
            [r["path"] for r in ctx["runbooks"]],
            ["runbooks/workflow/b1-response.md"],
        )


class TimelineTest(KctxTestCase):
    def test_timeline_lists_investigations_touching_ident_in_date_order(self):
        later = inv_mod.new(
            self.root,
            "later",
            trigger="adhoc",
            alerts=["alert-b1"],
            created="2026-10-21",
        )
        earlier = inv_mod.new(
            self.root,
            "earlier",
            trigger="wp",
            alerts=["alert-b1"],
            created="2026-09-22",
        )
        inv_mod.new(self.root, "unrelated", trigger="adhoc")

        result = nav.timeline(self.root, "alert-b1")
        self.assertEqual(
            [h["id"] for h in result["investigations"]],
            [earlier["id"], later["id"]],
        )

    def test_timeline_matches_signature_and_ticket(self):
        by_sig = inv_mod.new(self.root, "by-sig", trigger="adhoc")
        found = inv_mod.load(self.root, by_sig["id"])
        fm = found["frontmatter"]
        fm["signatures"] = ["sig-x"]
        found["path"].write_text(inv_mod.render(fm, found["body"]), encoding="utf-8")
        by_ticket = inv_mod.new(
            self.root, "by-ticket", trigger="drqs", tickets=["DRQS-1"]
        )

        self.assertEqual(
            [h["id"] for h in nav.timeline(self.root, "sig-x")["investigations"]],
            [by_sig["id"]],
        )
        self.assertEqual(
            [h["id"] for h in nav.timeline(self.root, "DRQS-1")["investigations"]],
            [by_ticket["id"]],
        )

    def test_timeline_no_hits_is_empty_list(self):
        result = nav.timeline(self.root, "nothing-tracks-this")
        self.assertEqual(result["investigations"], [])


class MatchTest(KctxTestCase):
    def test_signature_hit_ranked_first_with_owner_group(self):
        sig_mod.new(
            self.root,
            "pedl001-duplicate-element-customer-sql",
            match=["PEDL001", "duplicate element:"],
            owner_group="group-2423",
        )
        result = nav.match(self.root, "PEDL001 duplicate element: 110002187")
        self.assertEqual(
            result["signatures"][0]["id"], "pedl001-duplicate-element-customer-sql"
        )
        self.assertEqual(result["signatures"][0]["owner_group"], "group-2423")

    def test_no_hit_anywhere_carries_boundary_note(self):
        result = nav.match(self.root, "a string nothing should ever match")
        self.assertEqual(result["signatures"], [])
        self.assertEqual(result["investigations"], [])
        self.assertEqual(result["ktlo"], [])
        self.assertIn("note", result)

    def test_investigation_full_text_hit(self):
        inv = inv_mod.new(self.root, "x", trigger="adhoc")
        found = inv_mod.load(self.root, inv["id"])
        fm, body = found["frontmatter"], found["body"]
        body["Trigger and symptom"] = "saw a rare marker string zzqq-marker"
        found["path"].write_text(inv_mod.render(fm, body), encoding="utf-8")

        result = nav.match(self.root, "zzqq-marker")
        self.assertEqual([h["id"] for h in result["investigations"]], [inv["id"]])

    def test_ktlo_symptom_hit(self):
        ktlo.new(self.root, ticket="DRQS 1", title="x")
        found = ktlo.load_by_ticket(self.root, "DRQS 1")
        fm, body = found["frontmatter"], found["body"]
        body["Symptom"] = "saw a rare marker string yyzz-marker"
        found["path"].write_text(ktlo.render(fm, body), encoding="utf-8")

        result = nav.match(self.root, "yyzz-marker")
        self.assertEqual(len(result["ktlo"]), 1)
        self.assertEqual(result["ktlo"][0]["ticket"], "DRQS-1")


class RegressionFlagTest(KctxTestCase):
    def test_investigation_after_fixed_at_is_flagged(self):
        sig_mod.new(self.root, "fixed-sig", status="fixed", fixed_at="2026-01-01")
        inv_mod.new(self.root, "after-fix", trigger="adhoc", created="2026-06-01")
        after = inv_mod.load(self.root, "2026/2026-06-01-after-fix")
        fm = after["frontmatter"]
        fm["signatures"] = ["fixed-sig"]
        after["path"].write_text(inv_mod.render(fm, after["body"]), encoding="utf-8")

        flags = nav.regression_flags(self.root)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["signature"], "fixed-sig")
        self.assertEqual(flags[0]["investigation"], "2026/2026-06-01-after-fix")

    def test_investigation_before_fixed_at_is_not_flagged(self):
        sig_mod.new(self.root, "fixed-sig", status="fixed", fixed_at="2026-06-01")
        inv_mod.new(self.root, "before-fix", trigger="adhoc", created="2026-01-01")
        before = inv_mod.load(self.root, "2026/2026-01-01-before-fix")
        fm = before["frontmatter"]
        fm["signatures"] = ["fixed-sig"]
        before["path"].write_text(inv_mod.render(fm, before["body"]), encoding="utf-8")

        self.assertEqual(nav.regression_flags(self.root), [])

    def test_stale_surfaces_regression_flags(self):
        sig_mod.new(self.root, "fixed-sig", status="fixed", fixed_at="2026-01-01")
        inv_mod.new(self.root, "after-fix", trigger="adhoc", created="2026-06-01")
        after = inv_mod.load(self.root, "2026/2026-06-01-after-fix")
        fm = after["frontmatter"]
        fm["signatures"] = ["fixed-sig"]
        after["path"].write_text(inv_mod.render(fm, after["body"]), encoding="utf-8")

        with _no_cite_available():
            result = nav.stale(self.root)
        self.assertEqual(len(result["regressions"]), 1)


class StaleTest(KctxTestCase):
    def test_stale_assets_past_ttl_are_reported_and_others_are_not(self):
        inventory.asset_add(
            self.root,
            kind="service",
            name="expired",
            id="service-expired",
            verified_at="2020-01-01T00:00:00Z",
            ttl="1d",
        )
        inventory.asset_add(
            self.root,
            kind="service",
            name="fresh",
            id="service-fresh",
            verified_at="2020-01-01T00:00:00Z",
            ttl="none",
        )
        inventory.asset_add(self.root, kind="service", name="unset", id="service-unset")

        with _no_cite_available():
            result = nav.stale(self.root)

        stale_ids = {a["asset"] for a in result["stale_assets"]}
        self.assertEqual(stale_ids, {"service-expired"})

    def test_stale_project_filter(self):
        inventory.asset_add(
            self.root,
            kind="service",
            name="a",
            id="service-a",
            projects=["proj-a"],
            verified_at="2020-01-01T00:00:00Z",
            ttl="1d",
        )
        inventory.asset_add(
            self.root,
            kind="service",
            name="b",
            id="service-b",
            projects=["proj-b"],
            verified_at="2020-01-01T00:00:00Z",
            ttl="1d",
        )
        with _no_cite_available():
            result = nav.stale(self.root, project="proj-a")
        self.assertEqual([a["asset"] for a in result["stale_assets"]], ["service-a"])

    def test_stale_cite_script_missing_is_unverifiable_not_fresh(self):
        with _no_cite_available():
            result = nav.stale(self.root)
        self.assertFalse(result["citations"]["available"])
        self.assertIsNotNone(result["citations"]["note"])

    def test_stale_surfaces_entries_from_cite_stale_stub(self):
        stub = self.write_cite_stub(
            {
                "entries": [
                    {
                        "file": "a.md",
                        "line_no": 3,
                        "kind": "ticket",
                        "reason": "expired",
                        "stale": None,
                        "seen": "2020-01-01T00:00Z",
                        "age_days": 2000.0,
                        "group": "demo-project",
                    }
                ],
                "groups": {"demo-project": {"count": 1, "oldest_age_days": 2000.0}},
                "total": 1,
                "oldest_age_days": 2000.0,
                "exit_code": 2,
            },
            exit_code=2,
        )
        set_config(cite_bin=str(stub))
        try:
            result = nav.stale(self.root)
        finally:
            clear_config("cite_bin")

        self.assertTrue(result["citations"]["available"])
        self.assertEqual(result["citations"]["total"], 1)
        self.assertEqual(result["citations"]["entries"][0]["reason"], "expired")

    def test_stale_offline_passes_offline_flag_to_cite_stale(self):
        argv_log = self.root / "_argv.log"
        stub = self.write_cite_stub(
            {"entries": [], "groups": {}, "total": 0, "oldest_age_days": 0.0},
            argv_log=argv_log,
        )
        set_config(cite_bin=str(stub))
        try:
            result = nav.stale(self.root, offline=True)
        finally:
            clear_config("cite_bin")

        self.assertTrue(result["offline"])
        self.assertIn("--offline", argv_log.read_text(encoding="utf-8"))

    def test_stale_online_default_omits_offline_flag(self):
        argv_log = self.root / "_argv.log"
        stub = self.write_cite_stub(
            {"entries": [], "groups": {}, "total": 0, "oldest_age_days": 0.0},
            argv_log=argv_log,
        )
        set_config(cite_bin=str(stub))
        try:
            result = nav.stale(self.root)
        finally:
            clear_config("cite_bin")

        self.assertFalse(result["offline"])
        self.assertNotIn("--offline", argv_log.read_text(encoding="utf-8"))

    def test_stale_reports_runs_with_needs_recheck_coverage(self):
        repo = self.make_git_repo("stale-run")
        run_id = runs_mod.new_run(
            self.root, project="demo-project", mode="review", task="t"
        )["run_id"]
        obs = runs_mod.add_observation(
            self.root, run_id, system="git", locator=str(repo), role="code"
        )
        runs_mod.cover(
            self.root, run_id, item="q1", outcome="supported", evidence=[obs["id"]]
        )
        (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        import subprocess

        subprocess.run(
            ["git", "-C", str(repo), "commit", "-aqm", "second"],
            check=True,
            capture_output=True,
        )
        runs_mod.check(self.root, run_id)  # downgrades q1 to needs-recheck

        with _no_cite_available():
            result = nav.stale(self.root)

        stale_run_ids = {r["run"] for r in result["stale_runs"]}
        self.assertIn(run_id, stale_run_ids)


class DrainTest(KctxTestCase):
    def test_drain_requires_project_or_paths(self):
        with self.assertRaises(KctxError) as ctx:
            nav.drain(self.root)
        self.assertEqual(ctx.exception.category, "incomplete")

    def test_drain_runs_cite_check_with_touch_and_mark(self):
        proj = self.root / "demo-project"
        proj.mkdir()
        argv_log = self.root / "_argv.log"
        stub = self.write_cite_stub(
            {"results": [], "warnings": [], "skipped": [], "exit_code": 0},
            argv_log=argv_log,
        )
        set_config(cite_bin=str(stub))
        try:
            result = nav.drain(self.root, project="demo-project")
        finally:
            clear_config("cite_bin")

        logged = argv_log.read_text(encoding="utf-8")
        self.assertIn("--touch", logged)
        self.assertIn("--mark", logged)
        self.assertEqual(result["total_remaining"], 0)
        self.assertTrue(result["citations_available"])

    def test_drain_buckets_remaining_judgment_items(self):
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
                    },
                    {
                        "file": "demo-project/notes/a.md",
                        "line_no": 9,
                        "status": "changed",
                        "fields": {"kind": "code"},
                        "head": "abc1234",
                    },
                    {
                        "file": "demo-project/notes/a.md",
                        "line_no": 15,
                        "status": "gone",
                        "fields": {"kind": "proposal"},
                    },
                    {
                        "file": "demo-project/notes/a.md",
                        "line_no": 21,
                        "status": "unverifiable",
                        "fields": {"kind": "code"},
                        "reason": "could not resolve repo/remote",
                    },
                ],
                "warnings": [],
                "skipped": [],
                "exit_code": 2,
            },
            exit_code=2,
        )
        set_config(cite_bin=str(stub))
        try:
            result = nav.drain(self.root, project="demo-project")
        finally:
            clear_config("cite_bin")

        remaining = result["remaining"]
        self.assertEqual([i["line_no"] for i in remaining["expired_noncode"]], [3])
        self.assertEqual([i["line_no"] for i in remaining["changed_gone_code"]], [9])
        self.assertEqual([i["line_no"] for i in remaining["changed_gone_other"]], [15])
        self.assertEqual([i["line_no"] for i in remaining["unverifiable"]], [21])
        self.assertEqual(result["total_remaining"], 4)
        # the stub never writes to disk, so nothing should show up as touched
        self.assertEqual(result["touched_files"], [])

    def test_drain_reports_lines_the_write_back_actually_changed(self):
        """`cite check`'s directory-scan JSON carries no `touched_line` per
        result (only its single `--line` form does), so drain() has to prove
        a write-back happened by diffing file content before/after -- this
        exercises that path with a stub that actually rewrites the file, the
        same way the real `cite --touch --mark` would."""
        proj = self.root / "demo-project" / "notes"
        proj.mkdir(parents=True)
        target = proj / "a.md"
        target.write_text(
            'before line\n⟦cite kind=ticket id="DRQS 1" seen=2020-01-01T00:00Z ttl=3d⟧\n',
            encoding="utf-8",
        )
        stub = self.root / "_fixture-cite-stub"
        stub.write_text(
            "#!/usr/bin/env bash\n"
            f"sed -i 's/⟦cite kind=ticket.*/⟦cite kind=ticket id=\"DRQS 1\" seen=2020-01-01T00:00Z ttl=3d stale=expired@2026-01-01⟧/' {target}\n"
            "cat <<'EOF'\n"
            '{"results": [{"file": "'
            + str(target)
            + '", "line_no": 2, "status": "expired", "fields": {"kind": "ticket"}}], '
            '"warnings": [], "skipped": [], "exit_code": 2}\n'
            "EOF\n"
            "exit 2\n",
            encoding="utf-8",
        )
        stub.chmod(stub.stat().st_mode | 0o111)
        set_config(cite_bin=str(stub))
        try:
            result = nav.drain(self.root, project="demo-project")
        finally:
            clear_config("cite_bin")

        self.assertEqual(len(result["touched_files"]), 1)
        touched = result["touched_files"][0]
        self.assertEqual(touched["file"], str(target))
        self.assertEqual(len(touched["changes"]), 1)
        self.assertEqual(touched["changes"][0]["line_no"], 2)
        self.assertIn("stale=expired", touched["changes"][0]["after"])
        self.assertNotIn("stale=", touched["changes"][0]["before"])

    def test_drain_explicit_paths_used_when_given(self):
        extra = self.root / "elsewhere"
        extra.mkdir()
        argv_log = self.root / "_argv.log"
        stub = self.write_cite_stub(
            {"results": [], "warnings": [], "skipped": [], "exit_code": 0},
            argv_log=argv_log,
        )
        set_config(cite_bin=str(stub))
        try:
            result = nav.drain(self.root, paths=[str(extra)])
        finally:
            clear_config("cite_bin")

        self.assertEqual(result["paths"], [str(extra)])
        self.assertIn(str(extra), argv_log.read_text(encoding="utf-8"))

    def test_drain_cite_unavailable_is_reported_not_silently_clean(self):
        proj = self.root / "demo-project"
        proj.mkdir()
        with _no_cite_available():
            result = nav.drain(self.root, project="demo-project")
        self.assertFalse(result["citations_available"])
        self.assertEqual(result["total_remaining"], 0)
        self.assertIsNotNone(result["note"])

    def test_drain_surfaces_open_corrections(self):
        """Resume protocol visibility: `kctx stale --drain` must surface an
        open correction the same way `kctx stale` already does -- a session
        that only ran `--drain` shouldn't walk away unaware one is pending."""
        inventory.asset_add(
            self.root, kind="service", name="pbpsvc", id="service-pbpsvc"
        )
        dossiers_mod.new(self.root, "service-pbpsvc")
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "README.md").write_text(
            "relies on service-pbpsvc\n", encoding="utf-8"
        )
        retract_result = corrections_mod.retract(
            self.root,
            "service-pbpsvc",
            reason="found to be wrong",
            kind="dispute",
        )

        stub = self.write_cite_stub(
            {"results": [], "warnings": [], "skipped": [], "exit_code": 0}
        )
        set_config(cite_bin=str(stub))
        try:
            result = nav.drain(self.root, project="demo-project")
        finally:
            clear_config("cite_bin")

        self.assertEqual(result["open_corrections_total"], 1)
        row = result["open_corrections"][0]
        self.assertEqual(row["file"], retract_result["corrections_file"])
        self.assertEqual(row["target"], "service-pbpsvc")
        self.assertEqual(row["referrer"], "demo-project/README.md")
        self.assertEqual(row["status"], "pending")


class UsesTest(KctxTestCase):
    """G1/Q43: `kctx uses` is a reverse lookup over the citation graph --
    find every tracked file that literally mentions a durable id, grouped by
    kind, with the id's own home file marked `self` rather than a referrer."""

    def _make_investigation_with_evidence(self):
        inv = inv_mod.new(self.root, "spike", trigger="adhoc", created="2026-10-21")
        inv_id = inv["id"]
        ev_dir = self.root / "investigations" / inv_id / "evidence"
        ev_dir.mkdir(parents=True, exist_ok=True)
        ev_id = f"ev:{inv_id}/failure-paths"
        (ev_dir / "failure-paths.md").write_text(
            "---\nid: x\n---\n\nbody text\n\n## Corrections\n\nnone\n",
            encoding="utf-8",
        )
        found = inv_mod.load(self.root, inv_id)
        fm, body = found["frontmatter"], found["body"]
        body["Findings"] = f"three failure paths -- {ev_id}."
        found["path"].write_text(inv_mod.render(fm, body), encoding="utf-8")
        return inv_id, ev_id

    def test_ev_id_referrers_grouped_with_home_marked_self(self):
        inv_id, ev_id = self._make_investigation_with_evidence()

        sig_mod.new(self.root, "sig-a")
        sig_a = sig_mod.load(self.root, "sig-a")
        sig_a["body"]["Mechanism"] = f"traced via {ev_id}."
        sig_a["path"].write_text(
            sig_mod.render(sig_a["frontmatter"], sig_a["body"]), encoding="utf-8"
        )

        other_inv = inv_mod.new(self.root, "unrelated", trigger="adhoc")
        found_other = inv_mod.load(self.root, other_inv["id"])
        found_other["path"].write_text(
            inv_mod.render(found_other["frontmatter"], found_other["body"]),
            encoding="utf-8",
        )

        result = nav.uses(self.root, ev_id)
        self.assertIn("note", result)
        files = {r["file"]: r for r in result["referrers"]}

        home_rel = f"investigations/{inv_id}/README.md"
        self.assertIn(home_rel, files)
        self.assertTrue(files[home_rel].get("self"))
        self.assertEqual(files[home_rel]["kind"], "investigation")

        sig_rel = "signatures/sig-a.md"
        self.assertIn(sig_rel, files)
        self.assertNotIn("self", files[sig_rel])
        self.assertEqual(files[sig_rel]["kind"], "signature")

        other_rel = f"investigations/{other_inv['id']}/README.md"
        self.assertNotIn(other_rel, files)
        self.assertEqual(set(result["by_kind"].keys()), {"investigation", "signature"})

    def test_proposal_referrer_grouped_separately_in_bare_or_prefixed_form(self):
        proposals_mod.add(
            self.root,
            kind="config",
            origin="user-request",
            title="Widget",
            context="ctx",
            evidence="ev",
            change="chg",
            why="why",
            research="researched",
            alternatives=TWO_ALTERNATIVES,
            gates=GATES_TABLE,
        )
        proposal_id = f"config/{today()}-widget"
        found = proposals_mod.load(self.root, proposal_id)
        fm, body = found["frontmatter"], found["body"]
        body["Context"] = f"see {proposal_id} for background"
        found["path"].write_text(proposals_mod.render(fm, body), encoding="utf-8")

        result = nav.uses(self.root, f"proposal/{proposal_id}")
        self.assertEqual(
            [r["kind"] for r in result["referrers"]], ["proposal"] * len(result["referrers"])
        )
        self.assertTrue(result["referrers"])

    def test_no_match_still_returns_boundary_note(self):
        result = nav.uses(self.root, "sig:nothing-cites-this")
        self.assertEqual(result["referrers"], [])
        self.assertIn("note", result)

    def test_asset_target_resolves_by_alias(self):
        inventory.asset_add(
            self.root,
            kind="service",
            name="pbpsvc",
            id="service-pbpsvc",
            aliases=["pbp-svc"],
        )
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "README.md").write_text("owns pbp-svc\n", encoding="utf-8")

        result = nav.uses(self.root, "service-pbpsvc")
        non_self = [r for r in result["referrers"] if not r.get("self")]
        self.assertEqual([r["file"] for r in non_self], ["demo-project/README.md"])
        self_files = {r["file"] for r in result["referrers"] if r.get("self")}
        self.assertEqual(self_files, {"inventory/assets/service-pbpsvc.json"})

    def test_code_locator_matches_citation_path_and_line(self):
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "notes.md").write_text(
            "see ⟦cite kind=code repo=tnawara/kb rev=abc1234567 "
            "path=tools/kctx/runs.py L=167-206⟧\n",
            encoding="utf-8",
        )
        result = nav.uses(self.root, "tnawara/kb@abc1234:tools/kctx/runs.py:180")
        self.assertEqual(
            [r["file"] for r in result["referrers"]], ["demo-project/notes.md"]
        )

        miss = nav.uses(self.root, "tnawara/kb@abc1234:tools/kctx/runs.py:999")
        self.assertEqual(miss["referrers"], [])

    def test_ev_id_is_not_matched_by_a_longer_id_sharing_its_prefix(self):
        inv_id, ev_id = self._make_investigation_with_evidence()
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "notes.md").write_text(
            f"see {ev_id}-extended for background\n", encoding="utf-8"
        )

        result = nav.uses(self.root, ev_id)
        files = {r["file"] for r in result["referrers"]}
        self.assertNotIn("demo-project/notes.md", files)

    def test_asset_id_is_not_matched_by_a_longer_id_sharing_its_prefix(self):
        inventory.asset_add(self.root, kind="service", name="pbp", id="repo-pbp")
        inventory.asset_add(
            self.root, kind="service", name="pbp-lua", id="repo-pbp-lua"
        )
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "notes.md").write_text("owned by repo-pbp-lua\n", encoding="utf-8")

        result = nav.uses(self.root, "repo-pbp")
        non_self = [r["file"] for r in result["referrers"] if not r.get("self")]
        self.assertEqual(non_self, [])
        self_files = {r["file"] for r in result["referrers"] if r.get("self")}
        self.assertEqual(self_files, {"inventory/assets/repo-pbp.json"})

    def test_boundary_pattern_matches_at_punctuation_space_sentence_end_and_eol(
        self,
    ):
        """`_uses_boundary_pattern` must not reject a true match merely
        because it's directly followed by ordinary surrounding punctuation --
        only by a character that would continue the same id."""
        pattern = nav._uses_boundary_pattern("repo-pbp")
        for label, text in {
            "close-paren": "(repo-pbp)",
            "comma": "repo-pbp, and others",
            "cite-close": "see repo-pbp⟧",
            "space": "repo-pbp here",
            "sentence-end": "mentions repo-pbp.",
            "eol": "repo-pbp",
        }.items():
            with self.subTest(label=label):
                self.assertIsNotNone(pattern.search(text))

    def test_locator_substring_resolved_asset_is_marked_self(self):
        """A target that only resolves via the locator-substring fallback
        (not a direct id/alias/name match) must still have the resolved
        asset's own record -- and dossier, if one exists -- marked `self`,
        not listed as an ordinary referrer."""
        inventory.asset_add(
            self.root,
            kind="service",
            name="widget",
            id="repo-widget",
            locator="bbgithub.dev.bloomberg.com/org/widget-repo",
        )
        dossiers_mod.new(self.root, "repo-widget")
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "README.md").write_text("depends on repo-widget\n", encoding="utf-8")

        result = nav.uses(self.root, "widget-repo")
        files = {r["file"]: r for r in result["referrers"]}

        asset_file = "inventory/assets/repo-widget.json"
        self.assertIn(asset_file, files)
        self.assertTrue(files[asset_file].get("self"))

        dossier_file = "inventory/dossiers/repo-widget.md"
        self.assertIn(dossier_file, files)
        self.assertTrue(files[dossier_file].get("self"))

        non_self = [r["file"] for r in result["referrers"] if not r.get("self")]
        self.assertEqual(non_self, ["demo-project/README.md"])


class RetractTest(KctxTestCase):
    """G2/G4: retracting a claim appends a dated Corrections/Decision-log
    entry to the target's own record, writes a tracked reassessment list, and
    never edits a referrer."""

    def test_retract_dossier_writes_corrections_file_and_marks_open(self):
        inventory.asset_add(
            self.root, kind="service", name="pbpsvc", id="service-pbpsvc"
        )
        dossiers_mod.new(self.root, "service-pbpsvc")
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "README.md").write_text("relies on service-pbpsvc\n", encoding="utf-8")

        before = {
            p: p.read_text(encoding="utf-8")
            for p in self.root.rglob("*")
            if p.is_file()
        }

        result = corrections_mod.retract(
            self.root,
            "service-pbpsvc",
            reason="found to be wrong",
            kind="dispute",
        )

        self.assertEqual(result["target_kind"], "dossier")
        corrections_path = self.root / result["corrections_file"]
        self.assertTrue(corrections_path.is_file())
        parsed = corrections_mod.parse(corrections_path.read_text(encoding="utf-8"))
        self.assertEqual(parsed["frontmatter"]["target"], "service-pbpsvc")
        self.assertEqual(
            [r["file"] for r in parsed["rows"]], ["demo-project/README.md"]
        )
        self.assertEqual(parsed["rows"][0]["status"], "pending")

        for p, text in before.items():
            if p == self.root / "inventory" / "dossiers" / "service-pbpsvc.md":
                continue  # the retraction target itself is meant to change
            self.assertEqual(
                p.read_text(encoding="utf-8"), text, f"referrer {p} was edited"
            )

        context = nav.context(self.root, "service-pbpsvc")
        self.assertTrue(context["dossier"]["open_corrections"])

        self.assertEqual(validate_mod.validate(self.root)["problems"], [])

    def test_retract_signature_appends_corrections_section(self):
        sig_mod.new(self.root, "sig-a")

        corrections_mod.retract(
            self.root, "sig:sig-a", reason="root cause was different", kind="retract"
        )
        found = sig_mod.load(self.root, "sig-a")
        self.assertIn("root cause was different", found["body"]["Corrections"])

    def test_retract_ev_target_replaces_none_placeholder_under_corrections(self):
        inv = inv_mod.new(self.root, "spike", trigger="adhoc", created="2026-10-21")
        inv_id = inv["id"]
        ev_dir = self.root / "investigations" / inv_id / "evidence"
        ev_dir.mkdir(parents=True, exist_ok=True)
        ev_path = ev_dir / "x.md"
        ev_path.write_text(
            "---\nid: x\n---\n\nbody text\n\n## Corrections\n\nnone\n",
            encoding="utf-8",
        )
        ev_id = f"ev:{inv_id}/x"

        result = corrections_mod.retract(
            self.root, ev_id, reason="found stale", kind="dispute"
        )
        self.assertEqual(result["target_kind"], "ev")
        text = ev_path.read_text(encoding="utf-8")
        self.assertNotIn("none", text)
        self.assertIn("found stale", text)
        self.assertEqual(text.count("## Corrections"), 1)

    def test_retract_proposal_appends_decision_log(self):
        proposals_mod.add(
            self.root,
            kind="config",
            origin="user-request",
            title="Widget",
            context="ctx",
            evidence="ev",
            change="chg",
            why="why",
            research="researched",
            alternatives=TWO_ALTERNATIVES,
            gates=GATES_TABLE,
        )
        proposal_id = f"config/{today()}-widget"

        corrections_mod.retract(
            self.root,
            f"proposal/{proposal_id}",
            reason="superseded by a later filing",
            kind="supersede",
            by_replacement="config/2026-11-01-widget-v2",
        )
        found = proposals_mod.load(self.root, proposal_id)
        self.assertIn("superseded by a later filing", found["body"]["Decision log"])
        self.assertIn("config/2026-11-01-widget-v2", found["body"]["Decision log"])

    def test_retract_inv_target_is_rejected(self):
        inv_mod.new(self.root, "x", trigger="adhoc")
        with self.assertRaises(KctxError) as ctx:
            corrections_mod.retract(
                self.root, "inv:2026/2026-01-01-x", reason="x", kind="retract"
            )
        self.assertEqual(ctx.exception.category, "malformed")
