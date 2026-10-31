from unittest import mock

from _base import KctxTestCase

import kctx.services.ktlo as ktlo
from kctx.domain.ids import AssetId, TicketId
from kctx.domain.time import today
from kctx.domain.vocabulary import KtloStatus
from kctx.errors import KctxError


class TicketNormalizationTest(KctxTestCase):
    def test_normalizes_every_accepted_form_to_the_same_id(self):
        for raw in ("DRQS 123", "{DRQS 123}", "drqs-123", "{drqs 123}"):
            with self.subTest(raw=raw):
                self.assertEqual(ktlo.normalize_ticket(raw), TicketId("DRQS-123"))

    def test_jira_style_ticket(self):
        self.assertEqual(ktlo.normalize_ticket("RDTSPBP-123"), TicketId("RDTSPBP-123"))

    def test_unrecognized_ticket_is_malformed(self):
        with self.assertRaises(KctxError) as ctx:
            ktlo.normalize_ticket("not a ticket")
        self.assertEqual(ctx.exception.category, "malformed")


class NewRecordTest(KctxTestCase):
    def test_new_scaffolds_record_with_normalized_path_and_frontmatter(self):
        result = ktlo.new(self.root, ticket=ktlo.normalize_ticket("{DRQS 123}"),
                          title="fix the thing", assets=(AssetId("service-pbpsvc"),))
        self.assertEqual(result.ticket, TicketId("DRQS-123"))
        expected_path = self.root / "ktlo" / today()[:4] / "drqs-123-fix-the-thing.md"
        self.assertEqual(result.path, expected_path)
        self.assertTrue(expected_path.exists())
        parsed = ktlo.parse(expected_path.read_text(encoding="utf-8"))
        self.assertEqual(parsed.frontmatter.ticket, TicketId("DRQS-123"))
        self.assertEqual(parsed.frontmatter.assets, (AssetId("service-pbpsvc"),))
        self.assertIs(parsed.frontmatter.status, KtloStatus.TODO)
        self.assertIsNone(parsed.frontmatter.promoted_to)
        for section in ktlo.SECTION_ORDER:
            self.assertIn(section, parsed.body)
        self.assertEqual(ktlo.result_to_wire(result)["ticket"], "DRQS-123")

    def test_new_without_assets_defaults_to_empty_tuple(self):
        result = ktlo.new(self.root, ticket=TicketId("DRQS-1"), title="no assets yet")
        self.assertEqual(result.frontmatter.assets, ())

    def test_duplicate_ticket_same_title_is_conflict(self):
        ktlo.new(self.root, ticket=ktlo.normalize_ticket("DRQS 5"), title="dup")
        with self.assertRaises(KctxError) as ctx:
            ktlo.new(self.root, ticket=ktlo.normalize_ticket("drqs-5"), title="dup")
        self.assertEqual(ctx.exception.category, "conflict")


class LoadByTicketTest(KctxTestCase):
    def test_load_by_ticket_resolves_any_accepted_form(self):
        ktlo.new(self.root, ticket=TicketId("DRQS-42"), title="findable")
        for raw in ("DRQS 42", "{DRQS 42}", "drqs-42"):
            with self.subTest(raw=raw):
                found = ktlo.load_by_ticket(self.root, ktlo.normalize_ticket(raw))
                self.assertEqual(found.frontmatter.ticket, TicketId("DRQS-42"))

    def test_unknown_ticket_is_not_found(self):
        with self.assertRaises(KctxError) as ctx:
            ktlo.load_by_ticket(self.root, TicketId("DRQS-999"))
        self.assertEqual(ctx.exception.category, "not-found")


class PromoteTest(KctxTestCase):
    def test_promote_sets_promoted_to_and_appends_log_pointer(self):
        ktlo.new(self.root, ticket=TicketId("DRQS-7"), title="grows into a project")
        result = ktlo.promote(self.root, TicketId("DRQS-7"), "demo-project")
        self.assertFalse(result.already_promoted)
        self.assertEqual(ktlo.load_by_ticket(self.root, TicketId("DRQS-7")).frontmatter.promoted_to, "demo-project")
        log_path = self.root / "demo-project" / "log" / f"{today()}.md"
        self.assertTrue(log_path.exists())
        text = log_path.read_text(encoding="utf-8")
        self.assertIn("DRQS-7", text)
        self.assertIn("demo-project", text)
        self.assertEqual(text.count("ktlo promote: DRQS-7"), 1)

    def test_promote_is_idempotent(self):
        ktlo.new(self.root, ticket=TicketId("DRQS-8"), title="grows again")
        ktlo.promote(self.root, TicketId("DRQS-8"), "demo-project")
        log_path = self.root / "demo-project" / "log" / f"{today()}.md"
        first = log_path.read_text(encoding="utf-8")
        second = ktlo.promote(self.root, TicketId("DRQS-8"), "demo-project")
        self.assertTrue(second.already_promoted)
        self.assertEqual(log_path.read_text(encoding="utf-8"), first)
        self.assertEqual(first.count("ktlo promote: DRQS-8"), 1)

    def test_promote_unknown_ticket_is_not_found(self):
        with self.assertRaises(KctxError) as ctx:
            ktlo.promote(self.root, TicketId("DRQS-404"), "demo-project")
        self.assertEqual(ctx.exception.category, "not-found")

    def test_promote_creates_log_from_template_when_missing(self):
        ktlo.new(self.root, ticket=TicketId("DRQS-9"), title="first promote of the day")
        ktlo.promote(self.root, TicketId("DRQS-9"), "fresh-project")
        text = (self.root / "fresh-project" / "log" / f"{today()}.md").read_text(encoding="utf-8")
        for heading in ("Done", "Findings", "Next"):
            self.assertIn(f"## {heading}", text)

    def test_promote_preserves_authored_bytes_outside_changed_fields(self):
        created = ktlo.new(self.root, ticket=TicketId("DRQS-10"), title="authored")
        text = created.path.read_text(encoding="utf-8") + "\n## Custom\n\n```md\n## Outcome\n```\nopaque\n"
        original = text.replace("\n", "\r\n")
        created.path.write_bytes(original.encode())
        ktlo.promote(self.root, created.ticket, "demo")
        actual = created.path.read_bytes().decode()
        expected = original.replace("promoted_to: \r\n", "promoted_to: demo\r\n")
        self.assertEqual(actual, expected)

    def test_retry_repairs_project_pointer_without_rewriting_ticket(self):
        created = ktlo.new(self.root, ticket=TicketId("DRQS-11"), title="repair")
        with mock.patch.object(ktlo, "append_log_pointer", side_effect=OSError("pointer interrupted")):
            with self.assertRaises(OSError):
                ktlo.promote(self.root, created.ticket, "demo")
        before = created.path.read_bytes()
        result = ktlo.promote(self.root, created.ticket, "demo")
        self.assertTrue(result.already_promoted)
        self.assertEqual(created.path.read_bytes(), before)
        log = self.root / "demo" / "log" / f"{today()}.md"
        self.assertEqual(log.read_text().count("ktlo promote: DRQS-11"), 1)

    def test_next_day_retry_keeps_one_project_pointer(self):
        created = ktlo.new(self.root, ticket=TicketId("DRQS-12"), title="retry")
        with mock.patch("kctx.services.investigations.today", return_value="2026-01-01"):
            ktlo.promote(self.root, created.ticket, "demo")
        with mock.patch("kctx.services.investigations.today", return_value="2026-01-02"):
            ktlo.promote(self.root, created.ticket, "demo")
        self.assertEqual(sum(path.read_text().count("ktlo promote: DRQS-12")
                             for path in (self.root / "demo" / "log").glob("*.md")), 1)
