from _base import KctxTestCase

import ktlo
from errors import KctxError
from storage import today


class TicketNormalizationTest(KctxTestCase):
    """Accepts the four forms the author-change skill's phase 0 hands it and
    normalizes them to one canonical id, so the same ticket is never filed
    twice under different spellings."""

    def test_normalizes_every_accepted_form_to_the_same_id(self):
        for raw in ("DRQS 123", "{DRQS 123}", "drqs-123", "{drqs 123}"):
            with self.subTest(raw=raw):
                self.assertEqual(ktlo.normalize_ticket(raw)["id"], "DRQS-123")
                self.assertEqual(ktlo.normalize_ticket(raw)["slug"], "drqs-123")

    def test_jira_style_ticket(self):
        norm = ktlo.normalize_ticket("RDTSPBP-123")
        self.assertEqual(norm["id"], "RDTSPBP-123")
        self.assertEqual(norm["slug"], "rdtspbp-123")

    def test_unrecognized_ticket_is_malformed(self):
        with self.assertRaises(KctxError) as ctx:
            ktlo.normalize_ticket("not a ticket")
        self.assertEqual(ctx.exception.category, "malformed")


class NewRecordTest(KctxTestCase):
    def test_new_scaffolds_record_with_normalized_path_and_frontmatter(self):
        year = today()[:4]
        result = ktlo.new(
            self.root,
            ticket="{DRQS 123}",
            title="fix the thing",
            assets=["service-pbpsvc"],
        )
        self.assertEqual(result["ticket"], "DRQS-123")
        expected_path = self.root / "ktlo" / year / "drqs-123-fix-the-thing.md"
        self.assertEqual(result["path"], str(expected_path))
        self.assertTrue(expected_path.exists())

        parsed = ktlo.parse(expected_path.read_text(encoding="utf-8"))
        fm = parsed["frontmatter"]
        self.assertEqual(fm["ticket"], "DRQS-123")
        self.assertEqual(fm["assets"], ["service-pbpsvc"])
        self.assertEqual(fm["status"], "todo")
        self.assertIsNone(fm["promoted_to"])
        for section in ktlo.SECTION_ORDER:
            self.assertIn(section, parsed["body"])

    def test_new_without_assets_defaults_to_empty_list(self):
        result = ktlo.new(self.root, ticket="DRQS 1", title="no assets yet")
        self.assertEqual(result["frontmatter"]["assets"], [])

    def test_duplicate_ticket_same_title_is_conflict(self):
        ktlo.new(self.root, ticket="DRQS 5", title="dup")
        with self.assertRaises(KctxError) as ctx:
            ktlo.new(self.root, ticket="drqs-5", title="dup")
        self.assertEqual(ctx.exception.category, "conflict")


class LoadByTicketTest(KctxTestCase):
    def test_load_by_ticket_resolves_any_accepted_form(self):
        ktlo.new(self.root, ticket="DRQS 42", title="findable")
        for raw in ("DRQS 42", "{DRQS 42}", "drqs-42"):
            with self.subTest(raw=raw):
                found = ktlo.load_by_ticket(self.root, raw)
                self.assertEqual(found["frontmatter"]["ticket"], "DRQS-42")

    def test_unknown_ticket_is_not_found(self):
        with self.assertRaises(KctxError) as ctx:
            ktlo.load_by_ticket(self.root, "DRQS 999")
        self.assertEqual(ctx.exception.category, "not-found")


class PromoteTest(KctxTestCase):
    """Promoting a ktlo record must be safe to repeat: the second run is a
    no-op on the record and must not duplicate the log pointer line."""

    def test_promote_sets_promoted_to_and_appends_log_pointer(self):
        ktlo.new(self.root, ticket="DRQS 7", title="grows into a project")

        result = ktlo.promote(self.root, "DRQS 7", "demo-project")
        self.assertFalse(result["already_promoted"])

        found = ktlo.load_by_ticket(self.root, "DRQS 7")
        self.assertEqual(found["frontmatter"]["promoted_to"], "demo-project")

        log_path = self.root / "demo-project" / "log" / f"{today()}.md"
        self.assertTrue(log_path.exists())
        text = log_path.read_text(encoding="utf-8")
        self.assertIn("DRQS-7", text)
        self.assertIn("demo-project", text)
        self.assertEqual(text.count("ktlo promote: DRQS-7"), 1)

    def test_promote_is_idempotent(self):
        ktlo.new(self.root, ticket="DRQS 8", title="grows again")
        ktlo.promote(self.root, "DRQS 8", "demo-project")

        log_path = self.root / "demo-project" / "log" / f"{today()}.md"
        text_after_first = log_path.read_text(encoding="utf-8")

        second = ktlo.promote(self.root, "DRQS 8", "demo-project")
        self.assertTrue(second["already_promoted"])

        text_after_second = log_path.read_text(encoding="utf-8")
        self.assertEqual(text_after_first, text_after_second)
        self.assertEqual(text_after_second.count("ktlo promote: DRQS-8"), 1)

    def test_promote_unknown_ticket_is_not_found(self):
        with self.assertRaises(KctxError) as ctx:
            ktlo.promote(self.root, "DRQS 404", "demo-project")
        self.assertEqual(ctx.exception.category, "not-found")

    def test_promote_creates_log_from_template_when_missing(self):
        ktlo.new(self.root, ticket="DRQS 9", title="first promote of the day")
        ktlo.promote(self.root, "DRQS 9", "fresh-project")

        log_path = self.root / "fresh-project" / "log" / f"{today()}.md"
        text = log_path.read_text(encoding="utf-8")
        self.assertIn("## Done", text)
        self.assertIn("## Findings", text)
        self.assertIn("## Next", text)
