from _base import KctxTestCase
from kctx.citations.code import make_code
from kctx.citations.syntax import replace_field

import kctx.services.corrections as corrections_mod
import kctx.services.dossiers as dossiers_mod
import kctx.services.inventory as inventory
import kctx.services.investigations as inv_mod
import kctx.services.ktlo as ktlo
from kctx.services import backlinks, discovery, freshness, context as context_mod
import kctx.services.proposals as proposals_mod
import kctx.services.runs as runs_mod
import kctx.services.signatures as sig_mod
import kctx.services.validate as validate_mod
from kctx.errors import KctxError
from kctx.domain.time import today
from dataclasses import replace
from kctx.domain.ids import AssetId, InvestigationId, ProposalId, SignatureId, TicketId
from kctx.domain.targets import parse_fix_reference, parse_use_target
from kctx.domain.vocabulary import AssetKind, RelationshipType, InvestigationTrigger, SignatureStatus, ProposalKind, ProposalOrigin, RunMode, ObservationSystem, ObservationRole, CoverageOutcome, CorrectionKind

GATES_TABLE = (
    "| id | claim | check | when | by |\n"
    "|---|---|---|---|---|\n"
    "| G1 | it works | `true` | land | agent |\n"
)
TWO_ALTERNATIVES = "- A. do nothing\n- B. do the thing\n"


class HomeTest(KctxTestCase):
    def test_ambiguous_alias_is_not_hidden_by_navigation_fallbacks(self):
        for ident in ("first", "second"):
            inventory.asset_add(
                self.root, kind=AssetKind.SERVICE, name=ident,
                id=AssetId(ident), aliases=("shared",), locator="acme/shared",
            )
        for lookup in (
            lambda: discovery.home(self.root, "shared"),
            lambda: context_mod.context(self.root, "shared"),
            lambda: backlinks.uses(self.root, parse_use_target("shared")),
        ):
            with self.subTest(lookup=lookup):
                with self.assertRaises(KctxError) as raised:
                    lookup()
                self.assertEqual(raised.exception.category, "conflict")
                self.assertIn("first", raised.exception.message)
                self.assertIn("second", raised.exception.message)

    def test_no_match_reports_empty_candidates_with_boundary_note(self):
        result = discovery.home(self.root, "nothing-tracks-this")
        self.assertEqual(result["candidates"], [])
        self.assertIn("note", result)

    def test_asset_projects_field_yields_a_project_candidate(self):
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name='pbpsvc', id=AssetId('service-pbpsvc'), projects=('demo-project',))
        result = discovery.home(self.root, "pbpsvc")
        self.assertEqual(len(result["candidates"]), 1)
        c = result["candidates"][0]
        self.assertEqual(c["type"], "project")
        self.assertEqual(c["target"], "demo-project")
        self.assertIn("service-pbpsvc", c["evidence"])

    def test_project_grep_candidate_from_inventory_md(self):
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "inventory.md").write_text("| pbprpsvc | done | |\n", encoding="utf-8")
        result = discovery.home(self.root, "pbprpsvc")
        self.assertEqual(
            [(c["type"], c["target"]) for c in result["candidates"]],
            [("project", "demo-project")],
        )

    def test_asset_and_grep_candidates_for_same_project_are_deduped(self):
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name='pbpsvc', id=AssetId('service-pbpsvc'), projects=('demo-project',))
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "README.md").write_text("owns pbpsvc\n", encoding="utf-8")

        result = discovery.home(self.root, "pbpsvc")
        self.assertEqual(len(result["candidates"]), 1)
        self.assertIn("projects includes", result["candidates"][0]["evidence"])
        self.assertIn("README.md references", result["candidates"][0]["evidence"])

    def test_ktlo_ticket_and_asset_candidates(self):
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name='svc', id=AssetId('service-svc'))
        ktlo.new(self.root, ticket=ktlo.normalize_ticket('DRQS 1'), title='ticket matches by ticket')
        ktlo.new(self.root, ticket=ktlo.normalize_ticket('DRQS 2'), title='ticket matches by asset', assets=(AssetId('service-svc'),))

        by_ticket = discovery.home(self.root, "DRQS 1")
        self.assertEqual(len(by_ticket["candidates"]), 1)
        self.assertEqual(by_ticket["candidates"][0]["type"], "ktlo")

        by_asset = discovery.home(self.root, "service-svc")
        ktlo_hits = [c for c in by_asset["candidates"] if c["type"] == "ktlo"]
        self.assertEqual(len(ktlo_hits), 1)
        self.assertIn("ticket-matches-by-asset", ktlo_hits[0]["target"])

    def test_investigation_ticket_and_asset_candidates(self):
        by_ticket = inv_mod.new(self.root, 'by-ticket', trigger=InvestigationTrigger.DRQS, tickets=(TicketId('DRQS-7'),))
        by_asset = inv_mod.new(self.root, 'by-asset', trigger=InvestigationTrigger.ADHOC, assets=(AssetId('service-svc'),))

        result = discovery.home(self.root, "DRQS 7")
        self.assertEqual(
            [(c["type"], c["target"]) for c in result["candidates"]],
            [("investigation", by_ticket.id.val)],
        )

        result = discovery.home(self.root, "service-svc")
        inv_hits = [c for c in result["candidates"] if c["type"] == "investigation"]
        self.assertEqual([h["target"] for h in inv_hits], [by_asset.id.val])

    def test_multiple_distinct_candidates_all_reported(self):
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name='sharedname', id=AssetId('service-sharedname'), projects=('project-a',))
        proj_b = self.root / "project-b"
        proj_b.mkdir()
        (proj_b / "README.md").write_text(
            "mentions sharedname here\n", encoding="utf-8"
        )

        result = discovery.home(self.root, "sharedname")
        targets = sorted(c["target"] for c in result["candidates"])
        self.assertEqual(targets, ["project-a", "project-b"])


class ContextTest(KctxTestCase):
    def test_ambiguous_locator_refuses_first_match_and_preserves_exact_id(self):
        for ident in ("first", "second"):
            inventory.asset_add(
                self.root, kind=AssetKind.SERVICE, name=ident, id=AssetId(ident),
                locator=f"https://shared.example/{ident}",
            )
        with self.assertRaises(KctxError) as raised:
            context_mod.context(self.root, "shared.example")
        self.assertEqual(raised.exception.category, "conflict")
        self.assertIn("first", raised.exception.message)
        self.assertIn("second", raised.exception.message)
        self.assertEqual(context_mod.context(self.root, "first")["asset"], "first")

    def _build_fixture(self):
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name='pbpsvc', id=AssetId('service-pbpsvc'), projects=('demo-project',), verified_at='2020-01-01T00:00:00Z')
        inventory.asset_add(self.root, kind=AssetKind.DOC, name='runbook', id=AssetId('doc-runbook'))
        inventory.rel_add(self.root, type=RelationshipType.DOCUMENTS, from_=AssetId('doc-runbook'), to=AssetId('service-pbpsvc'))
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "README.md").write_text("pbpsvc lives here\n", encoding="utf-8")

    def test_context_unknown_asset_is_not_found(self):
        with self.assertRaises(KctxError) as ctx:
            context_mod.context(self.root, "no-such-asset")
        self.assertEqual(ctx.exception.category, "not-found")

    def test_context_assembles_impact_projects_and_linked_docs(self):
        self._build_fixture()
        result = context_mod.context(self.root, "service-pbpsvc")

        self.assertEqual(result["asset"], "service-pbpsvc")
        self.assertEqual(result["projects"], ["demo-project"])
        self.assertIn("note", result["impact"])  # coverage-boundary note passthrough
        linked_ids = {d["asset"] for d in result["linked_docs"]}
        self.assertIn("doc-runbook", linked_ids)

    def test_context_freshness_reflects_ttl_and_unavailable_source(self):
        self._build_fixture()
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name='pastttl', id=AssetId('service-pastttl'), projects=('demo-project',), verified_at='2020-01-01T00:00:00Z', ttl='1d')
        (self.root / "demo-project" / "README.md").write_text(
            f'⟦cite kind=code repo=local:{self.root / "missing"} path=x rev=abcdef0 blob=abcdef0 L=1-1⟧\n',
            encoding="utf-8",
        )
        result = context_mod.context(self.root, "service-pastttl")
        self.assertTrue(result["freshness"]["asset_past_ttl"])
        self.assertEqual(result["freshness"]["citations"]["results"][0]["status"], "unverifiable")

    def test_context_surfaces_changed_code_from_real_git(self):
        self._build_fixture()
        with self.cache_backed_repo("acme", "widget") as remote:
            sha = self.commit_file(remote, "f.py", "old\n", "initial")
            line = make_code("acme/widget", "f.py", "1-1", rev=sha).line
            (self.root / "demo-project" / "README.md").write_text(line + "\n", encoding="utf-8")
            self.commit_file(remote, "f.py", "new\n", "changed")
            result = context_mod.context(self.root, "service-pbpsvc")
        citations = result["freshness"]["citations"]
        self.assertTrue(citations["available"])
        self.assertEqual(citations["results"][0]["status"], "changed")

    def test_context_includes_investigations_signatures_and_runbooks(self):
        self._build_fixture()
        result = inv_mod.new(self.root, 'touches-pbpsvc', trigger=InvestigationTrigger.ADHOC, assets=(AssetId('service-pbpsvc'),))
        found = inv_mod.load(self.root, result.id)
        fm = found.frontmatter
        fm = replace(fm, signatures=tuple(SignatureId(value) for value in ["known-sig"]))
        found.path.write_text(inv_mod.render(fm, dict(found.document.sections)), encoding="utf-8")
        sig_mod.new(self.root, "known-sig", title="a known failure")

        runbook_dir = self.root / "runbooks" / "workflow"
        runbook_dir.mkdir(parents=True)
        (runbook_dir / "b1-response.md").write_text(
            "---\nlayer: workflow\nassets: [service-pbpsvc]\n---\n\n# B1 response\n",
            encoding="utf-8",
        )

        ctx = context_mod.context(self.root, "service-pbpsvc")

        self.assertEqual([h["id"] for h in ctx["investigations"]], [result.id.val])
        self.assertEqual([s["id"] for s in ctx["signatures"]], ["known-sig"])
        self.assertEqual(
            [r["path"] for r in ctx["runbooks"]],
            ["runbooks/workflow/b1-response.md"],
        )


class TimelineTest(KctxTestCase):
    def test_timeline_lists_investigations_touching_ident_in_date_order(self):
        later = inv_mod.new(self.root, 'later', trigger=InvestigationTrigger.ADHOC, alerts=(AssetId('alert-b1'),), created='2026-10-21')
        earlier = inv_mod.new(self.root, 'earlier', trigger=InvestigationTrigger.WP, alerts=(AssetId('alert-b1'),), created='2026-09-22')
        inv_mod.new(self.root, 'unrelated', trigger=InvestigationTrigger.ADHOC)

        result = discovery.timeline(self.root, "alert-b1")
        self.assertEqual(
            [h["id"] for h in result["investigations"]],
            [earlier.id.val, later.id.val],
        )

    def test_timeline_matches_signature_and_ticket(self):
        by_sig = inv_mod.new(self.root, 'by-sig', trigger=InvestigationTrigger.ADHOC)
        found = inv_mod.load(self.root, by_sig.id)
        fm = found.frontmatter
        fm = replace(fm, signatures=tuple(SignatureId(value) for value in ["sig-x"]))
        found.path.write_text(inv_mod.render(fm, dict(found.document.sections)), encoding="utf-8")
        by_ticket = inv_mod.new(self.root, 'by-ticket', trigger=InvestigationTrigger.DRQS, tickets=(TicketId('DRQS-1'),))

        self.assertEqual(
            [h["id"] for h in discovery.timeline(self.root, "sig-x")["investigations"]],
            [by_sig.id.val],
        )
        self.assertEqual(
            [h["id"] for h in discovery.timeline(self.root, "DRQS-1")["investigations"]],
            [by_ticket.id.val],
        )

    def test_timeline_no_hits_is_empty_list(self):
        result = discovery.timeline(self.root, "nothing-tracks-this")
        self.assertEqual(result["investigations"], [])


class MatchTest(KctxTestCase):
    def test_signature_hit_ranked_first_with_owner_group(self):
        sig_mod.new(self.root, 'pedl001-duplicate-element-customer-sql', match=('PEDL001', 'duplicate element:'), owner_group='group-2423')
        result = discovery.match(self.root, "PEDL001 duplicate element: 110002187")
        self.assertEqual(
            result["signatures"][0]["id"], "pedl001-duplicate-element-customer-sql"
        )
        self.assertEqual(result["signatures"][0]["owner_group"], "group-2423")

    def test_no_hit_anywhere_carries_boundary_note(self):
        result = discovery.match(self.root, "a string nothing should ever match")
        self.assertEqual(result["signatures"], [])
        self.assertEqual(result["investigations"], [])
        self.assertEqual(result["ktlo"], [])
        self.assertIn("note", result)

    def test_investigation_full_text_hit(self):
        inv = inv_mod.new(self.root, 'x', trigger=InvestigationTrigger.ADHOC)
        found = inv_mod.load(self.root, inv.id)
        fm, body = found.frontmatter, dict(found.document.sections)
        body["Trigger and symptom"] = "saw a rare marker string zzqq-marker"
        found.path.write_text(inv_mod.render(fm, body), encoding="utf-8")

        result = discovery.match(self.root, "zzqq-marker")
        self.assertEqual([h["id"] for h in result["investigations"]], [inv.id.val])

    def test_ktlo_symptom_hit(self):
        ktlo.new(self.root, ticket=ktlo.normalize_ticket('DRQS 1'), title='x')
        found = ktlo.load_by_ticket(self.root, ktlo.normalize_ticket('DRQS 1'))
        fm, body = found.frontmatter, dict(found.document.sections)
        body["Symptom"] = "saw a rare marker string yyzz-marker"
        found.path.write_text(ktlo.render(fm, body), encoding="utf-8")

        result = discovery.match(self.root, "yyzz-marker")
        self.assertEqual(len(result["ktlo"]), 1)
        self.assertEqual(result["ktlo"][0]["ticket"], "DRQS-1")


class RegressionFlagTest(KctxTestCase):
    def test_evidence_fixes_preserve_explicit_strict_regression_date_rule(self):
        fixes = (
            parse_fix_reference("ev:project/fixing-pr"),
            parse_fix_reference("acme/widget@abcdef1234:src/fix.py:10-20"),
        )
        for index, fix in enumerate(fixes):
            sig_mod.new(
                self.root, f"fixed-{index}", fix=(fix,), fixed_at="2026-06-01",
                status=SignatureStatus.SUSPECTED,
            )
            sig_mod.new(self.root, f"undated-{index}", fix=(fix,), status=SignatureStatus.FIXED)
        ids = tuple(SignatureId(f"{prefix}-{index}") for prefix in ("fixed", "undated") for index in range(2))
        for label, date in (("before", "2026-05-31"), ("equal", "2026-06-01"), ("after", "2026-06-02")):
            created = inv_mod.new(self.root, label, trigger=InvestigationTrigger.ADHOC, created=date)
            loaded = inv_mod.load(self.root, created.id)
            loaded.path.write_text(
                inv_mod.render(replace(loaded.frontmatter, signatures=ids), dict(loaded.body)),
                encoding="utf-8",
            )
        flags = freshness.regression_flags(self.root)
        self.assertEqual({flag["signature"] for flag in flags}, {"fixed-0", "fixed-1"})
        self.assertEqual({flag["investigation"] for flag in flags}, {"2026/2026-06-02-after"})

    def test_investigation_after_fixed_at_is_flagged(self):
        sig_mod.new(self.root, 'fixed-sig', status=SignatureStatus.FIXED, fixed_at='2026-01-01')
        inv_mod.new(self.root, 'after-fix', trigger=InvestigationTrigger.ADHOC, created='2026-06-01')
        after = inv_mod.load(self.root, InvestigationId('2026/2026-06-01-after-fix'))
        fm = after.frontmatter
        fm = replace(fm, signatures=tuple(SignatureId(value) for value in ["fixed-sig"]))
        after.path.write_text(inv_mod.render(fm, dict(after.document.sections)), encoding="utf-8")

        flags = freshness.regression_flags(self.root)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["signature"], "fixed-sig")
        self.assertEqual(flags[0]["investigation"], "2026/2026-06-01-after-fix")

    def test_investigation_before_fixed_at_is_not_flagged(self):
        sig_mod.new(self.root, 'fixed-sig', status=SignatureStatus.FIXED, fixed_at='2026-06-01')
        inv_mod.new(self.root, 'before-fix', trigger=InvestigationTrigger.ADHOC, created='2026-01-01')
        before = inv_mod.load(self.root, InvestigationId('2026/2026-01-01-before-fix'))
        fm = before.frontmatter
        fm = replace(fm, signatures=tuple(SignatureId(value) for value in ["fixed-sig"]))
        before.path.write_text(inv_mod.render(fm, dict(before.document.sections)), encoding="utf-8")

        self.assertEqual(freshness.regression_flags(self.root), [])

    def test_stale_surfaces_regression_flags(self):
        sig_mod.new(self.root, 'fixed-sig', status=SignatureStatus.FIXED, fixed_at='2026-01-01')
        inv_mod.new(self.root, 'after-fix', trigger=InvestigationTrigger.ADHOC, created='2026-06-01')
        after = inv_mod.load(self.root, InvestigationId('2026/2026-06-01-after-fix'))
        fm = after.frontmatter
        fm = replace(fm, signatures=tuple(SignatureId(value) for value in ["fixed-sig"]))
        after.path.write_text(inv_mod.render(fm, dict(after.document.sections)), encoding="utf-8")

        result = freshness.stale(self.root)
        self.assertEqual(len(result["regressions"]), 1)


class StaleTest(KctxTestCase):
    def test_stale_assets_past_ttl_are_reported_and_others_are_not(self):
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name='expired', id=AssetId('service-expired'), verified_at='2020-01-01T00:00:00Z', ttl='1d')
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name='fresh', id=AssetId('service-fresh'), verified_at='2020-01-01T00:00:00Z', ttl='none')
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name='unset', id=AssetId('service-unset'))

        result = freshness.stale(self.root)

        stale_ids = {a["asset"] for a in result["stale_assets"]}
        self.assertEqual(stale_ids, {"service-expired"})

    def test_stale_project_filter(self):
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name='a', id=AssetId('service-a'), projects=('proj-a',), verified_at='2020-01-01T00:00:00Z', ttl='1d')
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name='b', id=AssetId('service-b'), projects=('proj-b',), verified_at='2020-01-01T00:00:00Z', ttl='1d')
        result = freshness.stale(self.root, project="proj-a")
        self.assertEqual([a["asset"] for a in result["stale_assets"]], ["service-a"])

    def test_stale_retains_marked_unavailable_source(self):
        (self.root / "note.md").write_text(
            f'⟦cite kind=code repo=local:{self.root / "missing"} path=x L=1-1 stale=changed@2020-01-01⟧\n',
            encoding="utf-8",
        )
        result = freshness.stale(self.root)
        self.assertEqual(result["citations"]["entries"][0]["reason"], "marked")

    def test_stale_surfaces_expired_citations(self):
        (self.root / "note.md").write_text(
            '⟦cite kind=ticket id="DRQS 1" seen=2020-01-01T00:00Z ttl=1d⟧\n',
            encoding="utf-8",
        )
        result = freshness.stale(self.root)
        self.assertTrue(result["citations"]["available"])
        self.assertEqual(result["citations"]["total"], 1)
        self.assertEqual(result["citations"]["entries"][0]["reason"], "expired")

    def test_stale_offline_reports_due_without_resolving_repo(self):
        (self.root / "note.md").write_text(
            f'⟦cite kind=code repo=local:{self.root / "missing"} seen=2020-01-01T00:00Z ttl=1d⟧\n',
            encoding="utf-8",
        )
        result = freshness.stale(self.root, offline=True)
        self.assertTrue(result["offline"])
        self.assertEqual(result["citations"]["entries"][0]["reason"], "due")

    def test_stale_online_reclassifies_code_not_just_age(self):
        with self.cache_backed_repo("acme", "widget") as remote:
            sha = self.commit_file(remote, "f.py", "old\n", "initial")
            line = make_code("acme/widget", "f.py", "1-1", rev=sha).line
            (self.root / "note.md").write_text(line + "\n", encoding="utf-8")
            self.commit_file(remote, "f.py", "new\n", "changed")
            result = freshness.stale(self.root)
        self.assertFalse(result["offline"])
        self.assertEqual(result["citations"]["entries"][0]["reason"], "changed")

    def test_stale_reports_runs_with_needs_recheck_coverage(self):
        repo = self.make_git_repo("stale-run")
        run_id = runs_mod.new_run(self.root, project='demo-project', mode=RunMode.REVIEW, task='t').run_id
        obs = runs_mod.add_observation(self.root, run_id, system=ObservationSystem.GIT, locator=str(repo), role=ObservationRole.CODE)
        runs_mod.cover(self.root, run_id, item='q1', outcome=CoverageOutcome.SUPPORTED, evidence=(obs.id,))
        (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        import subprocess

        subprocess.run(
            ["git", "-C", str(repo), "commit", "-aqm", "second"],
            check=True,
            capture_output=True,
        )
        runs_mod.check(self.root, run_id)  # downgrades q1 to needs-recheck

        result = freshness.stale(self.root)

        stale_run_ids = {r["run"] for r in result["stale_runs"]}
        self.assertIn(run_id.val, stale_run_ids)


class DrainTest(KctxTestCase):
    def test_drain_requires_project_or_paths(self):
        with self.assertRaises(KctxError) as ctx:
            freshness.drain(self.root)
        self.assertEqual(ctx.exception.category, "incomplete")

    def test_drain_touches_fresh_code_and_clears_stale_marks(self):
        proj = self.root / "demo-project"
        proj.mkdir()
        with self.cache_backed_repo("acme", "widget") as remote:
            sha = self.commit_file(remote, "f.py", "content\n", "initial")
            line = make_code("acme/widget", "f.py", "1-1", rev=sha).line
            line = replace_field(line, "seen", "2020-01-01T00:00Z")
            line = replace_field(line, "stale", "changed@2020-01-01")
            path = proj / "note.md"
            path.write_text(line + "\n", encoding="utf-8")
            result = freshness.drain(self.root, project="demo-project")
        updated = path.read_text(encoding="utf-8")
        self.assertIn("seen=2020-01-01T00:00Z", updated)
        self.assertIn("checked_at=", updated)
        self.assertNotIn("stale=", updated)
        self.assertEqual(result["total_remaining"], 0)
        self.assertTrue(result["citations_available"])

    def test_drain_buckets_remaining_judgment_items(self):
        proj = self.root / "demo-project"
        proj.mkdir()
        with self.cache_backed_repo("acme", "widget") as remote:
            sha = self.commit_file(remote, "f.py", "old\n", "initial")
            code = make_code("acme/widget", "f.py", "1-1", rev=sha).line
            lines = [""] * 21
            lines[2] = '⟦cite kind=ticket id="DRQS 1" seen=2020-01-01T00:00Z ttl=1d⟧'
            lines[8] = code
            lines[14] = '⟦cite kind=record path=missing-record.md state=active⟧'
            lines[20] = f'⟦cite kind=code repo=local:{self.root / "missing"} path=x L=1-1⟧'
            (proj / "notes.md").write_text("\n".join(lines), encoding="utf-8")
            self.commit_file(remote, "f.py", "new\n", "changed")
            result = freshness.drain(self.root, project="demo-project")
        remaining = result["remaining"]
        self.assertEqual([i["line_no"] for i in remaining["expired_noncode"]], [3])
        self.assertEqual([i["line_no"] for i in remaining["changed_gone_code"]], [9])
        self.assertEqual([i["line_no"] for i in remaining["changed_gone_other"]], [15])
        self.assertEqual([i["line_no"] for i in remaining["unverifiable"]], [21])
        self.assertEqual(result["total_remaining"], 4)
        self.assertEqual(len(result["touched_files"]), 1)

    def test_drain_reports_lines_the_write_back_actually_changed(self):
        """Directory scan write-backs are reported from actual file differences."""
        proj = self.root / "demo-project" / "notes"
        proj.mkdir(parents=True)
        target = proj / "a.md"
        target.write_text(
            'before line\n⟦cite kind=ticket id="DRQS 1" seen=2020-01-01T00:00Z ttl=3d⟧\n',
            encoding="utf-8",
        )
        result = freshness.drain(self.root, project="demo-project")

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
        path = extra / "note.md"
        path.write_text('⟦cite kind=ticket seen=2020-01-01T00:00Z ttl=1d⟧\n', encoding="utf-8")
        result = freshness.drain(self.root, paths=[str(extra)])
        self.assertEqual(result["paths"], [str(extra)])
        self.assertEqual(result["touched_files"][0]["file"], str(path))

    def test_drain_unavailable_source_is_not_silently_clean(self):
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "note.md").write_text(
            f'⟦cite kind=code repo=local:{self.root / "missing"} path=x L=1-1⟧\n',
            encoding="utf-8",
        )
        result = freshness.drain(self.root, project="demo-project")
        self.assertTrue(result["citations_available"])
        self.assertEqual(result["total_remaining"], 1)
        self.assertEqual(result["remaining"]["unverifiable"][0]["status"], "unverifiable")

    def test_drain_surfaces_open_corrections(self):
        """Resume protocol visibility: `kctx stale --drain` must surface an
        open correction the same way `kctx stale` already does -- a session
        that only ran `--drain` shouldn't walk away unaware one is pending."""
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name='pbpsvc', id=AssetId('service-pbpsvc'))
        dossiers_mod.new(self.root, AssetId('service-pbpsvc'))
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "README.md").write_text(
            "relies on service-pbpsvc\n", encoding="utf-8"
        )
        retract_result = corrections_mod.retract(self.root, corrections_mod.parse_correction_target('service-pbpsvc'), reason='found to be wrong', kind=CorrectionKind.DISPUTE)

        result = freshness.drain(self.root, project="demo-project")

        self.assertEqual(result["open_corrections_total"], 1)
        row = result["open_corrections"][0]
        self.assertEqual(row["file"], retract_result.corrections_file)
        self.assertEqual(row["target"], "service-pbpsvc")
        self.assertEqual(row["referrer"], "demo-project/README.md")
        self.assertEqual(row["status"], "pending")


class UsesTest(KctxTestCase):
    """G1/Q43: `kctx uses` is a reverse lookup over the citation graph --
    find every tracked file that literally mentions a durable id, grouped by
    kind, with the id's own home file marked `self` rather than a referrer."""

    def test_fix_addresses_reverse_lookup_live_and_pinned_files(self):
        refs = {
            "evidence": "ev:project/fixing-pr",
            "long-evidence": "ev:project/fixing-pr-extended",
            "code": "acme/widget@abcdef1234:src/fix.py:10-20",
            "other-repo": "acme/widget-extra@abcdef1234:src/fix.py:10-20",
            "other-revision": "acme/widget@abcdef12345:src/fix.py:10-20",
            "other-path": "acme/widget@abcdef1234:src/fix.py.extra:10-20",
            "other-range": "acme/widget@abcdef1234:src/fix.py:100-200",
        }
        files = {}
        for slug, raw in refs.items():
            created = sig_mod.new(self.root, slug, fix=(parse_fix_reference(raw),))
            files[f"signatures/{slug}.md"] = created.path.read_text()
        for query, expected in (
            ("ev:project/fixing-pr", {"signatures/evidence.md"}),
            ("acme/widget@abcdef1234:src/fix.py:20", {"signatures/code.md"}),
            ("acme/widget@ABCDEF1234:src/fix.py:10", {"signatures/code.md"}),
            ("acme/widget@abcdef1:src/fix.py:10", set()),
            ("acme/widget@abcdef1234:src/fix.py:21", set()),
            ("acme/widget@abcdef1234:src/fix.py:1-9", set()),
        ):
            for result in (
                backlinks.uses(self.root, parse_use_target(query)),
                backlinks.uses_from_files(self.root, parse_use_target(query), files),
            ):
                with self.subTest(query=query):
                    self.assertEqual({row["file"] for row in result["referrers"]}, expected)

    def test_malformed_fix_disclosed_by_reverse_lookup(self):
        text = "---\nid: broken\nstatus: suspected\nfix: [acme/widget#7]\n---\n"
        result = backlinks.uses_from_files(
            self.root, parse_use_target("acme/widget@abcdef1234:src/fix.py"),
            {"signatures/broken.md": text},
        )
        self.assertEqual(result["referrers"], [])
        self.assertIn("signatures/broken.md", result["warnings"][0])

    def _make_investigation_with_evidence(self):
        inv = inv_mod.new(self.root, 'spike', trigger=InvestigationTrigger.ADHOC, created='2026-10-21')
        inv_id = inv.id.val
        ev_dir = self.root / "investigations" / inv_id / "evidence"
        ev_dir.mkdir(parents=True, exist_ok=True)
        ev_id = f"ev:{inv_id}/failure-paths"
        (ev_dir / "failure-paths.md").write_text(
            "---\nid: x\n---\n\nbody text\n\n## Corrections\n\nnone\n",
            encoding="utf-8",
        )
        found = inv_mod.load(self.root, InvestigationId(inv_id))
        fm, body = found.frontmatter, dict(found.document.sections)
        body["Findings"] = f"three failure paths -- {ev_id}."
        found.path.write_text(inv_mod.render(fm, body), encoding="utf-8")
        return inv_id, ev_id

    def test_ev_id_referrers_grouped_with_home_marked_self(self):
        inv_id, ev_id = self._make_investigation_with_evidence()

        sig_mod.new(self.root, "sig-a")
        sig_a = sig_mod.load(self.root, SignatureId('sig-a'))
        sig_a.document.update_section("Mechanism", f"traced via {ev_id}.").write(sig_a.path)

        other_inv = inv_mod.new(self.root, 'unrelated', trigger=InvestigationTrigger.ADHOC)
        found_other = inv_mod.load(self.root, other_inv.id)
        found_other.path.write_text(
            inv_mod.render(found_other.frontmatter, dict(found_other.document.sections)),
            encoding="utf-8",
        )

        result = backlinks.uses(self.root, parse_use_target(ev_id))
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

        other_rel = f"investigations/{other_inv.id.val}/README.md"
        self.assertNotIn(other_rel, files)
        self.assertEqual(set(result["by_kind"].keys()), {"investigation", "signature"})

    def test_proposal_referrer_grouped_separately_in_bare_or_prefixed_form(self):
        proposals_mod.add(self.root, kind=ProposalKind.CONFIG, origin=ProposalOrigin.USER_REQUEST, title='Widget', context='ctx', evidence='ev', change='chg', why='why', research='researched', alternatives=TWO_ALTERNATIVES, gates=GATES_TABLE)
        proposal_id = f"config/{today()}-widget"
        found = proposals_mod.load(self.root, ProposalId(proposal_id))
        found.document.update_section("Context", f"see {proposal_id} for background").write(found.path)

        result = backlinks.uses(self.root, parse_use_target(f"proposal/{proposal_id}"))
        self.assertEqual(
            [r["kind"] for r in result["referrers"]], ["proposal"] * len(result["referrers"])
        )
        self.assertTrue(result["referrers"])

    def test_no_match_still_returns_boundary_note(self):
        result = backlinks.uses(self.root, parse_use_target("sig:nothing-cites-this"))
        self.assertEqual(result["referrers"], [])
        self.assertIn("note", result)

    def test_asset_target_resolves_by_alias(self):
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name='pbpsvc', id=AssetId('service-pbpsvc'), aliases=('pbp-svc',))
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "README.md").write_text("owns pbp-svc\n", encoding="utf-8")

        result = backlinks.uses(self.root, parse_use_target("service-pbpsvc"))
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
        result = backlinks.uses(self.root, parse_use_target("tnawara/kb@abc1234:tools/kctx/runs.py:180"))
        self.assertEqual(
            [r["file"] for r in result["referrers"]], ["demo-project/notes.md"]
        )

        miss = backlinks.uses(self.root, parse_use_target("tnawara/kb@abc1234:tools/kctx/runs.py:999"))
        self.assertEqual(miss["referrers"], [])

    def test_ev_id_is_not_matched_by_a_longer_id_sharing_its_prefix(self):
        inv_id, ev_id = self._make_investigation_with_evidence()
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "notes.md").write_text(
            f"see {ev_id}-extended for background\n", encoding="utf-8"
        )

        result = backlinks.uses(self.root, parse_use_target(ev_id))
        files = {r["file"] for r in result["referrers"]}
        self.assertNotIn("demo-project/notes.md", files)

    def test_asset_id_is_not_matched_by_a_longer_id_sharing_its_prefix(self):
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name='pbp', id=AssetId('repo-pbp'))
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name='pbp-lua', id=AssetId('repo-pbp-lua'))
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "notes.md").write_text("owned by repo-pbp-lua\n", encoding="utf-8")

        result = backlinks.uses(self.root, parse_use_target("repo-pbp"))
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
        pattern = backlinks._uses_boundary_pattern("repo-pbp")
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
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name='widget', id=AssetId('repo-widget'), locator='bbgithub.dev.bloomberg.com/org/widget-repo')
        dossiers_mod.new(self.root, AssetId('repo-widget'))
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "README.md").write_text("depends on repo-widget\n", encoding="utf-8")

        result = backlinks.uses(self.root, parse_use_target("widget-repo"))
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
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name='pbpsvc', id=AssetId('service-pbpsvc'))
        dossiers_mod.new(self.root, AssetId('service-pbpsvc'))
        proj = self.root / "demo-project"
        proj.mkdir()
        (proj / "README.md").write_text("relies on service-pbpsvc\n", encoding="utf-8")

        before = {
            p: p.read_text(encoding="utf-8")
            for p in self.root.rglob("*")
            if p.is_file()
        }

        result = corrections_mod.retract(self.root, corrections_mod.parse_correction_target('service-pbpsvc'), reason='found to be wrong', kind=CorrectionKind.DISPUTE)

        self.assertEqual(result.target_kind.value, "dossier")
        corrections_path = self.root / result.corrections_file
        self.assertTrue(corrections_path.is_file())
        parsed = corrections_mod.parse(corrections_path.read_text(encoding="utf-8"))
        self.assertEqual(parsed.frontmatter.target.spelling, "service-pbpsvc")
        self.assertEqual([row.file for row in parsed.rows], ["demo-project/README.md"])
        self.assertEqual(parsed.rows[0].status.value, "pending")

        for p, text in before.items():
            if p == self.root / "inventory" / "dossiers" / "service-pbpsvc.md":
                continue  # the retraction target itself is meant to change
            self.assertEqual(
                p.read_text(encoding="utf-8"), text, f"referrer {p} was edited"
            )

        context = context_mod.context(self.root, "service-pbpsvc")
        self.assertTrue(context["dossier"]["open_corrections"])

        self.assertEqual(validate_mod.validate(self.root).problems, ())

    def test_retract_signature_appends_corrections_section(self):
        sig_mod.new(self.root, "sig-a")

        corrections_mod.retract(self.root, corrections_mod.parse_correction_target('sig:sig-a'), reason='root cause was different', kind=CorrectionKind.RETRACT)
        found = sig_mod.load(self.root, SignatureId('sig-a'))
        self.assertIn("root cause was different", dict(found.document.sections)["Corrections"])

    def test_retract_ev_target_replaces_none_placeholder_under_corrections(self):
        inv = inv_mod.new(self.root, 'spike', trigger=InvestigationTrigger.ADHOC, created='2026-10-21')
        inv_id = inv.id.val
        ev_dir = self.root / "investigations" / inv_id / "evidence"
        ev_dir.mkdir(parents=True, exist_ok=True)
        ev_path = ev_dir / "x.md"
        ev_path.write_text(
            "---\nid: x\n---\n\nbody text\n\n## Corrections\n\nnone\n",
            encoding="utf-8",
        )
        ev_id = f"ev:{inv_id}/x"

        result = corrections_mod.retract(self.root, corrections_mod.parse_correction_target(ev_id), reason='found stale', kind=CorrectionKind.DISPUTE)
        self.assertEqual(result.target_kind.value, "ev")
        text = ev_path.read_text(encoding="utf-8")
        self.assertNotIn("none", text)
        self.assertIn("found stale", text)
        self.assertEqual(text.count("## Corrections"), 1)

    def test_retract_proposal_appends_decision_log(self):
        proposals_mod.add(self.root, kind=ProposalKind.CONFIG, origin=ProposalOrigin.USER_REQUEST, title='Widget', context='ctx', evidence='ev', change='chg', why='why', research='researched', alternatives=TWO_ALTERNATIVES, gates=GATES_TABLE)
        proposal_id = f"config/{today()}-widget"

        corrections_mod.retract(self.root, corrections_mod.parse_correction_target(f'proposal/{proposal_id}'), reason='superseded by a later filing', kind=CorrectionKind.SUPERSEDE, by_replacement='config/2026-11-01-widget-v2')
        found = proposals_mod.load(self.root, ProposalId(proposal_id))
        self.assertIn("superseded by a later filing", dict(found.document.sections)["Decision log"])
        self.assertIn("config/2026-11-01-widget-v2", dict(found.document.sections)["Decision log"])

    def test_retract_inv_target_is_rejected(self):
        inv_mod.new(self.root, 'x', trigger=InvestigationTrigger.ADHOC)
        with self.assertRaises(KctxError) as ctx:
            corrections_mod.retract(self.root, corrections_mod.parse_correction_target('inv:2026/2026-01-01-x'), reason='x', kind=CorrectionKind.RETRACT)
        self.assertEqual(ctx.exception.category, "malformed")


class SnapshotUsesTest(KctxTestCase):
    def test_pinned_alias_and_canonical_homes_ignore_live_inventory(self):
        from unittest.mock import patch

        inventory.asset_add(
            self.root, kind=AssetKind.SERVICE, name="widget", id=AssetId("repo-widget"),
            aliases=("widget",), locator="acme/widget-repo",
        )
        dossiers_mod.new(self.root, AssetId("repo-widget"))
        project = self.root / "demo-project"
        project.mkdir()
        (project / "notes.md").write_text("relies on widget\n", encoding="utf-8")
        files = {
            str(path.relative_to(self.root)): path.read_text(encoding="utf-8")
            for path in self.root.rglob("*") if path.is_file()
        }
        target = parse_use_target("widget-repo")
        expected = backlinks.uses(self.root, target)
        inventory.asset_add(
            self.root, kind=AssetKind.SERVICE, name="live-only", id=AssetId("live-only"),
            aliases=("widget-repo",),
        )
        (project / "notes.md").write_text("no longer a referrer\n", encoding="utf-8")
        with patch("pathlib.Path.read_text", side_effect=AssertionError("snapshot read live text")):
            actual = backlinks.uses_from_files(self.root, target, files)
        self.assertEqual(actual, expected)
        self.assertEqual(
            {row["file"] for row in actual["referrers"] if row.get("self")},
            {"inventory/assets/repo-widget.json", "inventory/dossiers/repo-widget.md"},
        )

    def test_pinned_evidence_home_and_locator_overlap_use_shared_matching(self):
        files = {
            "investigations/2026/2026-01-01-spike/README.md": "ev:2026/2026-01-01-spike/finding",
            "investigations/2026/2026-01-01-spike/evidence/finding.md": "finding",
            "demo/notes.md": "ev:2026/2026-01-01-spike/finding. ⟦cite kind=code repo=acme/widget rev=abc1234567 path=x.py L=10-20⟧",
            "demo/not-a-match.md": "ev:2026/2026-01-01-spike/finding-more",
        }
        evidence = backlinks.uses_from_files(self.root, parse_use_target("ev:2026/2026-01-01-spike/finding"), files)
        self.assertEqual(len(evidence["referrers"]), 2)
        self.assertTrue(evidence["referrers"][0]["self"])
        locator = backlinks.uses_from_files(self.root, parse_use_target("acme/widget@abc1234:x.py:20-30"), files)
        self.assertEqual(locator["referrers"], [{"file": "demo/notes.md", "kind": "notes/log"}])
        miss = backlinks.uses_from_files(self.root, parse_use_target("acme/widget@abc1234:x.py:21-30"), files)
        self.assertEqual(miss["referrers"], [])

    def test_pinned_ambiguous_alias_keeps_candidate_diagnostics(self):
        for ident in ("first", "second"):
            inventory.asset_add(self.root, kind=AssetKind.SERVICE, name=ident, id=AssetId(ident), aliases=("shared",))
        files = {
            str(path.relative_to(self.root)): path.read_text(encoding="utf-8")
            for path in self.root.rglob("*.json")
        }
        with self.assertRaises(KctxError) as raised:
            backlinks.uses_from_files(self.root, parse_use_target("shared"), files)
        self.assertEqual(raised.exception.category, "conflict")
        self.assertIn("first", raised.exception.message)
        self.assertIn("second", raised.exception.message)
