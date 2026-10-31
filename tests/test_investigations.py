from dataclasses import replace
from unittest import mock

from _base import KctxTestCase

import kctx.services.investigations as inv_mod
from kctx.domain.ids import AssetId, InvestigationId, TicketId
from kctx.domain.incidents import FollowUp, FollowUpStatus, Hypothesis
from kctx.domain.time import today
from kctx.domain.vocabulary import HypothesisStatus, InvestigationStatus, InvestigationTrigger
from kctx.errors import KctxError


class NewRecordTest(KctxTestCase):
    def test_new_scaffolds_record_with_id_path_and_frontmatter(self):
        created = today()
        result = inv_mod.new(self.root, "pbp-batch-error-spikes", trigger=InvestigationTrigger.DRQS,
                             title="PBP batch error spikes", tickets=(TicketId("DRQS-1"),),
                             alerts=(AssetId("alert-b1"),), windows=("2026-09-24T16:32Z/2026-09-24T17:02Z",))
        expected = f"{created[:4]}/{created}-pbp-batch-error-spikes"
        self.assertEqual(result.id, InvestigationId(expected))
        path = self.root / "investigations" / expected / "README.md"
        self.assertTrue(path.exists())
        self.assertTrue((path.parent / "evidence").is_dir())
        self.assertTrue((path.parent / "queries").is_dir())
        parsed = inv_mod.parse(path.read_text(encoding="utf-8"))
        fm = parsed.frontmatter
        self.assertIs(fm.trigger, InvestigationTrigger.DRQS)
        self.assertEqual(fm.tickets, (TicketId("DRQS-1"),))
        self.assertEqual(fm.alerts, (AssetId("alert-b1"),))
        self.assertIs(fm.status, InvestigationStatus.OPEN)
        self.assertEqual(fm.signatures, ())
        self.assertIsNone(fm.promoted_to)
        for section in inv_mod.SECTION_ORDER:
            self.assertIn(section, parsed.body)
        self.assertEqual(inv_mod.result_to_wire(result)["id"], expected)

    def test_bad_trigger_rejected(self):
        with self.assertRaises(KctxError):
            inv_mod.parse("---\nid: x\ntrigger: not-a-trigger\nstatus: open\n---\n")

    def test_duplicate_slug_same_day_is_conflict(self):
        inv_mod.new(self.root, "dup", trigger=InvestigationTrigger.ADHOC)
        with self.assertRaises(KctxError) as ctx:
            inv_mod.new(self.root, "dup", trigger=InvestigationTrigger.ADHOC)
        self.assertEqual(ctx.exception.category, "conflict")

    def test_title_defaults_from_slug_when_omitted(self):
        self.assertEqual(inv_mod.new(self.root, "no-title-given", trigger=InvestigationTrigger.ADHOC).frontmatter.title, "no title given")


class FollowUpRoundTripTest(KctxTestCase):
    def test_follow_ups_round_trip_with_and_without_ticket(self):
        result = inv_mod.new(self.root, "x", trigger=InvestigationTrigger.ADHOC)
        found = inv_mod.load(self.root, result.id)
        follow_ups = (FollowUp("group-1135", FollowUpStatus("open")), FollowUp("group-1789", FollowUpStatus("open"), TicketId("DRQS-9")))
        fm = replace(found.frontmatter, follow_ups=follow_ups)
        found.path.write_text(inv_mod.render(fm, found.body), encoding="utf-8")
        self.assertEqual(inv_mod.parse(found.path.read_text(encoding="utf-8")).frontmatter.follow_ups, follow_ups)


class ParseHypothesesTest(KctxTestCase):
    def test_parses_ledger_bullets(self):
        text = "- H1: supported — the request type was rejected (ev:x)\n  continuation line, ignored\n- H2: refuted — not a timeout\n- H3: unk — client cancellation reason\n"
        self.assertEqual(inv_mod.parse_hypotheses(text), (
            Hypothesis("H1", HypothesisStatus.SUPPORTED, "- H1: supported — the request type was rejected (ev:x)"),
            Hypothesis("H2", HypothesisStatus.REFUTED, "- H2: refuted — not a timeout"),
            Hypothesis("H3", HypothesisStatus.UNK, "- H3: unk — client cancellation reason"),
        ))

    def test_empty_section_has_no_hypotheses(self):
        self.assertEqual(inv_mod.parse_hypotheses(""), ())

    def test_prose_without_bullets_is_ignored(self):
        self.assertEqual(inv_mod.parse_hypotheses("No hypotheses were needed here."), ())


class ConcludeTest(KctxTestCase):
    def _fill(self, inv_id, *, checked_against="", scope="", hypotheses=""):
        found = inv_mod.load(self.root, inv_id)
        found.document.update_section("Checked against", checked_against).update_section("Scope and limits", scope).update_section("Hypotheses", hypotheses).write(found.path)

    def test_conclusion_uses_actual_typed_summary_predicate(self):
        result = inv_mod.new(self.root, "summary", trigger=InvestigationTrigger.ADHOC)
        self._fill(result.id, checked_against="usr checked", scope="sample only", hypotheses="- H1: unk — not established")
        predicate = inv_mod.semantic_workflow.conclude
        with mock.patch.object(inv_mod.semantic_workflow, "conclude", wraps=predicate) as conclude:
            inv_mod.conclude(self.root, result.id)
        summary = conclude.call_args.args[0]
        self.assertEqual(summary.checked_against, "usr checked")
        self.assertEqual(summary.scope_and_limits, "sample only")
        self.assertEqual(summary.hypotheses[0].text, "- H1: unk — not established")
        self.assertIs(summary.hypotheses[0].status, inv_mod.semantic_model.HypothesisStatus.UNKNOWN)

    def test_conclude_refuses_without_checked_against(self):
        result = inv_mod.new(self.root, "x", trigger=InvestigationTrigger.ADHOC)
        self._fill(result.id, scope="18 sampled runs")
        with self.assertRaises(KctxError) as ctx:
            inv_mod.conclude(self.root, result.id)
        self.assertEqual(ctx.exception.category, "incomplete")
        self.assertIn("Checked against", ctx.exception.message)

    def test_conclude_refuses_without_scope_and_limits(self):
        result = inv_mod.new(self.root, "x", trigger=InvestigationTrigger.ADHOC)
        self._fill(result.id, checked_against="usr@2026-10-25 confirmed")
        with self.assertRaises(KctxError) as ctx:
            inv_mod.conclude(self.root, result.id)
        self.assertIn("Scope and limits", ctx.exception.message)

    def test_conclude_refuses_with_open_hypothesis(self):
        result = inv_mod.new(self.root, "x", trigger=InvestigationTrigger.ADHOC)
        self._fill(result.id, checked_against="usr@2026-10-25 confirmed", scope="18 sampled runs", hypotheses="- H1: open — still unresolved")
        with self.assertRaises(KctxError) as ctx:
            inv_mod.conclude(self.root, result.id)
        self.assertIn("H1", ctx.exception.message)

    def test_conclude_allows_unk_hypothesis(self):
        result = inv_mod.new(self.root, "x", trigger=InvestigationTrigger.ADHOC)
        self._fill(result.id, checked_against="usr@2026-10-25 confirmed", scope="18 sampled runs", hypotheses="- H1: unk — never confirmed")
        self.assertIs(inv_mod.conclude(self.root, result.id).status, InvestigationStatus.CONCLUDED)

    def test_conclude_succeeds_with_no_hypotheses_at_all(self):
        result = inv_mod.new(self.root, "x", trigger=InvestigationTrigger.ADHOC)
        self._fill(result.id, checked_against="usr@2026-10-25 confirmed", scope="n/a")
        self.assertIs(inv_mod.conclude(self.root, result.id).status, InvestigationStatus.CONCLUDED)

    def test_malformed_hypotheses_refuse_conclusion_without_writing(self):
        for index, bullet in enumerate(("- H1: definitely-safe", "- H2 missing-colon", "* H3:")):
            with self.subTest(bullet=bullet):
                created = inv_mod.new(self.root, f"malformed-{index}", trigger=InvestigationTrigger.ADHOC)
                self._fill(created.id, checked_against="source", scope="demo", hypotheses=bullet)
                before = created.path.read_bytes()
                with self.assertRaises(KctxError) as error:
                    inv_mod.conclude(self.root, created.id)
                self.assertEqual(error.exception.category, "malformed")
                self.assertEqual(created.path.read_bytes(), before)
                self.assertIs(inv_mod.load(self.root, created.id).frontmatter.status, InvestigationStatus.OPEN)

    def test_fenced_hypothesis_examples_are_not_live_requirements(self):
        created = inv_mod.new(self.root, "fenced", trigger=InvestigationTrigger.ADHOC)
        self._fill(created.id, checked_against="source", scope="demo",
                   hypotheses="```text\n- H1: invalid-example\n```\n- H2: supported — source")
        self.assertIs(inv_mod.conclude(self.root, created.id).status, InvestigationStatus.CONCLUDED)

    def test_conclude_preserves_unknown_sections_fences_and_crlf(self):
        result = inv_mod.new(self.root, "x", trigger=InvestigationTrigger.ADHOC)
        self._fill(result.id, checked_against="x", scope="x")
        original = (result.path.read_text(encoding="utf-8") + "\n## Custom\n\n```md\n## Findings\n```\nopaque\n").replace("\n", "\r\n")
        result.path.write_bytes(original.encode())
        inv_mod.conclude(self.root, result.id)
        self.assertEqual(result.path.read_bytes().decode(), original.replace("status: open\r\n", "status: concluded\r\n"))


class ListAndShowTest(KctxTestCase):
    def test_list_filters_open_only(self):
        a = inv_mod.new(self.root, "open-one", trigger=InvestigationTrigger.ADHOC)
        b = inv_mod.new(self.root, "concluded-one", trigger=InvestigationTrigger.ADHOC)
        found = inv_mod.load(self.root, b.id)
        found.document.update_section("Checked against", "x").update_section("Scope and limits", "x").write(found.path)
        inv_mod.conclude(self.root, b.id)
        self.assertEqual([fm.id for fm in inv_mod.list_investigations(self.root, open_only=True)], [a.id])

    def test_list_filters_by_asset_or_alert(self):
        inv_mod.new(self.root, "x", trigger=InvestigationTrigger.ADHOC, assets=(AssetId("service-pbpsvc"),))
        inv_mod.new(self.root, "y", trigger=InvestigationTrigger.ADHOC, alerts=(AssetId("alert-b1"),))
        inv_mod.new(self.root, "z", trigger=InvestigationTrigger.ADHOC)
        self.assertEqual(len(inv_mod.list_investigations(self.root, asset=AssetId("service-pbpsvc"))), 1)
        self.assertEqual(len(inv_mod.list_investigations(self.root, asset=AssetId("alert-b1"))), 1)

    def test_show_lists_evidence_and_queries(self):
        result = inv_mod.new(self.root, "x", trigger=InvestigationTrigger.ADHOC)
        home = result.path.parent
        (home / "evidence" / "q1.md").write_text("excerpt", encoding="utf-8")
        (home / "queries" / "q1.logscale").write_text("query", encoding="utf-8")
        shown = inv_mod.show(self.root, result.id)
        self.assertEqual(shown.evidence, ("q1.md",))
        self.assertEqual(shown.queries, ("q1.logscale",))


class PromoteTest(KctxTestCase):
    def test_promote_sets_promoted_to_and_appends_log_pointer(self):
        result = inv_mod.new(self.root, "x", trigger=InvestigationTrigger.ADHOC)
        self.assertFalse(inv_mod.promote(self.root, result.id, "demo-project").already_promoted)
        self.assertEqual(inv_mod.load(self.root, result.id).frontmatter.promoted_to, "demo-project")
        log_path = self.root / "demo-project" / "log" / f"{today()}.md"
        self.assertTrue(log_path.exists())
        self.assertIn(result.id.val, log_path.read_text(encoding="utf-8"))

    def test_promote_is_idempotent(self):
        result = inv_mod.new(self.root, "x", trigger=InvestigationTrigger.ADHOC)
        inv_mod.promote(self.root, result.id, "demo-project")
        log_path = self.root / "demo-project" / "log" / f"{today()}.md"
        first = log_path.read_text(encoding="utf-8")
        self.assertTrue(inv_mod.promote(self.root, result.id, "demo-project").already_promoted)
        self.assertEqual(log_path.read_text(encoding="utf-8"), first)

    def test_next_day_retry_does_not_duplicate_project_pointer(self):
        result = inv_mod.new(self.root, "retry", trigger=InvestigationTrigger.ADHOC)
        with mock.patch.object(inv_mod, "today", return_value="2026-01-01"):
            inv_mod.promote(self.root, result.id, "project")
        first = (self.root / "project" / "log" / "2026-01-01.md").read_bytes()
        with mock.patch.object(inv_mod, "today", return_value="2026-01-02"):
            self.assertTrue(inv_mod.promote(self.root, result.id, "project").already_promoted)
        self.assertEqual((self.root / "project" / "log" / "2026-01-01.md").read_bytes(), first)
        self.assertFalse((self.root / "project" / "log" / "2026-01-02.md").exists())

    def test_retry_repairs_pointer_after_record_update_succeeded(self):
        result = inv_mod.new(self.root, "repair", trigger=InvestigationTrigger.ADHOC)
        with mock.patch.object(inv_mod, "append_log_pointer", side_effect=OSError("interrupted projection")):
            with self.assertRaises(OSError):
                inv_mod.promote(self.root, result.id, "project")
        self.assertEqual(inv_mod.load(self.root, result.id).frontmatter.promoted_to, "project")
        before = result.path.read_bytes()
        self.assertTrue(inv_mod.promote(self.root, result.id, "project").already_promoted)
        self.assertEqual(result.path.read_bytes(), before)
        log = self.root / "project" / "log" / f"{today()}.md"
        self.assertEqual(log.read_text().count("investigation promote:"), 1)

    def test_fenced_pointer_is_not_a_completed_projection(self):
        result = inv_mod.new(self.root, "fenced", trigger=InvestigationTrigger.ADHOC)
        pointer = f"investigation promote: {result.id} -> project (investigations/{result.id}/README.md)"
        log = self.root / "project" / "log" / f"{today()}.md"
        log.parent.mkdir(parents=True)
        log.write_text("---\nsummary:\n---\n\n## Done\n\n```md\n- " + pointer + "\n```\n")
        inv_mod.promote(self.root, result.id, "project")
        self.assertEqual(sum(line.strip() == "- " + pointer for line in inv_mod.read_document(log).unfenced_lines()), 1)
