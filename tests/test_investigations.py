from _base import KctxTestCase

import investigations as inv_mod
from errors import KctxError
from storage import today


class NewRecordTest(KctxTestCase):
    def test_new_scaffolds_record_with_id_path_and_frontmatter(self):
        created = today()
        year = created[:4]
        result = inv_mod.new(
            self.root,
            "pbp-batch-error-spikes",
            trigger="drqs",
            title="PBP batch error spikes",
            tickets=["DRQS-1"],
            alerts=["alert-b1"],
            windows=["2026-09-24T16:32Z/2026-09-24T17:02Z"],
        )
        expected_id = f"{year}/{created}-pbp-batch-error-spikes"
        self.assertEqual(result["id"], expected_id)
        path = self.root / "investigations" / expected_id / "README.md"
        self.assertTrue(path.exists())
        self.assertTrue((path.parent / "evidence").is_dir())
        self.assertTrue((path.parent / "queries").is_dir())

        parsed = inv_mod.parse(path.read_text(encoding="utf-8"))
        fm = parsed["frontmatter"]
        self.assertEqual(fm["trigger"], "drqs")
        self.assertEqual(fm["tickets"], ["DRQS-1"])
        self.assertEqual(fm["alerts"], ["alert-b1"])
        self.assertEqual(fm["status"], "open")
        self.assertEqual(fm["signatures"], [])
        self.assertIsNone(fm["promoted_to"])
        for section in inv_mod.SECTION_ORDER:
            self.assertIn(section, parsed["body"])

    def test_bad_trigger_rejected(self):
        with self.assertRaises(KctxError):
            inv_mod.new(self.root, "x", trigger="not-a-trigger")

    def test_duplicate_slug_same_day_is_conflict(self):
        inv_mod.new(self.root, "dup", trigger="adhoc")
        with self.assertRaises(KctxError) as ctx:
            inv_mod.new(self.root, "dup", trigger="adhoc")
        self.assertEqual(ctx.exception.category, "conflict")

    def test_title_defaults_from_slug_when_omitted(self):
        result = inv_mod.new(self.root, "no-title-given", trigger="adhoc")
        self.assertEqual(result["frontmatter"]["title"], "no title given")


class FollowUpRoundTripTest(KctxTestCase):
    def test_follow_ups_round_trip_with_and_without_ticket(self):
        result = inv_mod.new(self.root, "x", trigger="adhoc")
        found = inv_mod.load(self.root, result["id"])
        fm = found["frontmatter"]
        fm["follow_ups"] = [
            {"owner": "group-1135", "status": "open", "ticket": ""},
            {"owner": "group-1789", "status": "open", "ticket": "DRQS-9"},
        ]
        found["path"].write_text(inv_mod.render(fm, found["body"]), encoding="utf-8")
        reparsed = inv_mod.parse(found["path"].read_text(encoding="utf-8"))
        self.assertEqual(
            reparsed["frontmatter"]["follow_ups"],
            [
                {"owner": "group-1135", "status": "open", "ticket": ""},
                {"owner": "group-1789", "status": "open", "ticket": "DRQS-9"},
            ],
        )


class ParseHypothesesTest(KctxTestCase):
    def test_parses_ledger_bullets(self):
        text = (
            "- H1: supported — the request type was rejected (ev:x)\n"
            "  continuation line, ignored\n"
            "- H2: refuted — not a timeout\n"
            "- H3: unk — client cancellation reason\n"
        )
        parsed = inv_mod.parse_hypotheses(text)
        self.assertEqual(
            parsed,
            [
                {"id": "H1", "status": "supported"},
                {"id": "H2", "status": "refuted"},
                {"id": "H3", "status": "unk"},
            ],
        )

    def test_empty_section_has_no_hypotheses(self):
        self.assertEqual(inv_mod.parse_hypotheses(""), [])

    def test_prose_without_bullets_is_ignored(self):
        self.assertEqual(
            inv_mod.parse_hypotheses("No hypotheses were needed here."), []
        )


class ConcludeTest(KctxTestCase):
    def _fill(self, inv_id, *, checked_against="", scope="", hypotheses=""):
        found = inv_mod.load(self.root, inv_id)
        fm, body, path = found["frontmatter"], found["body"], found["path"]
        body["Checked against"] = checked_against
        body["Scope and limits"] = scope
        body["Hypotheses"] = hypotheses
        path.write_text(inv_mod.render(fm, body), encoding="utf-8")

    def test_conclude_refuses_without_checked_against(self):
        result = inv_mod.new(self.root, "x", trigger="adhoc")
        self._fill(result["id"], scope="18 sampled runs")
        with self.assertRaises(KctxError) as ctx:
            inv_mod.conclude(self.root, result["id"])
        self.assertEqual(ctx.exception.category, "incomplete")
        self.assertIn("Checked against", ctx.exception.message)

    def test_conclude_refuses_without_scope_and_limits(self):
        result = inv_mod.new(self.root, "x", trigger="adhoc")
        self._fill(result["id"], checked_against="usr@2026-10-25 confirmed")
        with self.assertRaises(KctxError) as ctx:
            inv_mod.conclude(self.root, result["id"])
        self.assertIn("Scope and limits", ctx.exception.message)

    def test_conclude_refuses_with_open_hypothesis(self):
        result = inv_mod.new(self.root, "x", trigger="adhoc")
        self._fill(
            result["id"],
            checked_against="usr@2026-10-25 confirmed",
            scope="18 sampled runs",
            hypotheses="- H1: open — still unresolved",
        )
        with self.assertRaises(KctxError) as ctx:
            inv_mod.conclude(self.root, result["id"])
        self.assertIn("H1", ctx.exception.message)

    def test_conclude_allows_unk_hypothesis(self):
        result = inv_mod.new(self.root, "x", trigger="adhoc")
        self._fill(
            result["id"],
            checked_against="usr@2026-10-25 confirmed",
            scope="18 sampled runs",
            hypotheses="- H1: unk — never confirmed",
        )
        res = inv_mod.conclude(self.root, result["id"])
        self.assertEqual(res["status"], "concluded")

    def test_conclude_succeeds_with_no_hypotheses_at_all(self):
        result = inv_mod.new(self.root, "x", trigger="adhoc")
        self._fill(
            result["id"], checked_against="usr@2026-10-25 confirmed", scope="n/a"
        )
        res = inv_mod.conclude(self.root, result["id"])
        self.assertEqual(res["status"], "concluded")


class ListAndShowTest(KctxTestCase):
    def test_list_filters_open_only(self):
        a = inv_mod.new(self.root, "open-one", trigger="adhoc")
        b = inv_mod.new(self.root, "concluded-one", trigger="adhoc")
        found = inv_mod.load(self.root, b["id"])
        found["body"]["Checked against"] = "x"
        found["body"]["Scope and limits"] = "x"
        found["path"].write_text(
            inv_mod.render(found["frontmatter"], found["body"]), encoding="utf-8"
        )
        inv_mod.conclude(self.root, b["id"])

        open_only = inv_mod.list_investigations(self.root, open_only=True)
        self.assertEqual([fm["id"] for fm in open_only], [a["id"]])

    def test_list_filters_by_asset_or_alert(self):
        inv_mod.new(self.root, "x", trigger="adhoc", assets=["service-pbpsvc"])
        inv_mod.new(self.root, "y", trigger="adhoc", alerts=["alert-b1"])
        inv_mod.new(self.root, "z", trigger="adhoc")

        by_asset = inv_mod.list_investigations(self.root, asset="service-pbpsvc")
        self.assertEqual(len(by_asset), 1)
        by_alert = inv_mod.list_investigations(self.root, asset="alert-b1")
        self.assertEqual(len(by_alert), 1)

    def test_show_lists_evidence_and_queries(self):
        result = inv_mod.new(self.root, "x", trigger="adhoc")
        home = self.root / "investigations" / result["id"]
        (home / "evidence" / "q1.md").write_text("excerpt", encoding="utf-8")
        (home / "queries" / "q1.logscale").write_text("query", encoding="utf-8")
        shown = inv_mod.show(self.root, result["id"])
        self.assertEqual(shown["evidence"], ["q1.md"])
        self.assertEqual(shown["queries"], ["q1.logscale"])


class PromoteTest(KctxTestCase):
    def test_promote_sets_promoted_to_and_appends_log_pointer(self):
        result = inv_mod.new(self.root, "x", trigger="adhoc")
        promoted = inv_mod.promote(self.root, result["id"], "demo-project")
        self.assertFalse(promoted["already_promoted"])

        found = inv_mod.load(self.root, result["id"])
        self.assertEqual(found["frontmatter"]["promoted_to"], "demo-project")

        log_path = self.root / "demo-project" / "log" / f"{today()}.md"
        self.assertTrue(log_path.exists())
        self.assertIn(result["id"], log_path.read_text(encoding="utf-8"))

    def test_promote_is_idempotent(self):
        result = inv_mod.new(self.root, "x", trigger="adhoc")
        inv_mod.promote(self.root, result["id"], "demo-project")
        log_path = self.root / "demo-project" / "log" / f"{today()}.md"
        first = log_path.read_text(encoding="utf-8")

        second = inv_mod.promote(self.root, result["id"], "demo-project")
        self.assertTrue(second["already_promoted"])
        self.assertEqual(log_path.read_text(encoding="utf-8"), first)
