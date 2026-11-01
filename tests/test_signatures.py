from _base import KctxTestCase

import kctx.services.signatures as sig_mod
from kctx.domain.ids import SignatureId
from kctx.domain.targets import parse_fix_reference
from kctx.domain.vocabulary import SignatureStatus
from kctx.errors import KctxError
from kctx.services.validation_common import Diagnostics
from kctx.services.validation_incidents import validate_incidents


class NewRecordTest(KctxTestCase):
    def test_new_scaffolds_record_with_id_path_and_frontmatter(self):
        result = sig_mod.new(self.root, "pedl001-duplicate-element-customer-sql",
                             title="PEDL001 duplicate element", match=("PEDL001", "duplicate element:"),
                             match_where="humio #repo=pbp", owner_group="group-2423",
                             status=SignatureStatus.KNOWN_ERROR)
        self.assertEqual(result.id, SignatureId("pedl001-duplicate-element-customer-sql"))
        path = self.root / "signatures" / "pedl001-duplicate-element-customer-sql.md"
        self.assertTrue(path.exists())
        parsed = sig_mod.parse(path.read_text(encoding="utf-8"))
        self.assertEqual(parsed.frontmatter.match, ("PEDL001", "duplicate element:"))
        self.assertEqual(parsed.frontmatter.owner_group, "group-2423")
        self.assertIs(parsed.frontmatter.status, SignatureStatus.KNOWN_ERROR)
        for section in sig_mod.SECTION_ORDER:
            self.assertIn(section, parsed.body)
        self.assertEqual(sig_mod.result_to_wire(result)["id"], "pedl001-duplicate-element-customer-sql")

    def test_all_fix_kinds_round_trip_without_inferred_resolution(self):
        spellings = (
            "config/2026-01-02-repair",
            "ev:project/fixing-pr",
            "acme/widget@abcdef1234:src/fix.py:10-20",
        )
        fixes = tuple(parse_fix_reference(raw) for raw in spellings)
        created = sig_mod.new(self.root, "tracked-fixes", fix=fixes)
        loaded = sig_mod.load(self.root, created.id).frontmatter
        self.assertEqual(loaded.fix, fixes)
        self.assertIs(loaded.status, SignatureStatus.SUSPECTED)
        self.assertIsNone(loaded.fixed_at)
        self.assertIsNone(loaded.verified_at)
        self.assertEqual(sig_mod.frontmatter_to_wire(loaded)["fix"], list(spellings))
        self.assertEqual(sig_mod.parse(sig_mod.render(loaded, {})).frontmatter, loaded)
        diagnostics = Diagnostics()
        validate_incidents(self.root, set(), diagnostics)
        self.assertEqual(diagnostics.problems, [])

    def test_bad_fix_is_rejected_and_aggregate_reader_discloses_it(self):
        created = sig_mod.new(self.root, "bad-fix")
        for raw in ("acme/widget#7", "TICKET 1234", "ev:missing-home"):
            with self.subTest(raw=raw):
                text = created.path.read_text().replace("fix: []", f"fix: [{raw}]")
                with self.assertRaises(KctxError):
                    sig_mod.parse(text)
        created.path.write_text(text, encoding="utf-8")
        skipped = []
        self.assertEqual(sig_mod.list_signatures(self.root, skipped=skipped), ())
        self.assertEqual(len(skipped), 1)
        self.assertIn("signatures/bad-fix.md", skipped[0])
        diagnostics = Diagnostics()
        validate_incidents(self.root, set(), diagnostics)
        self.assertEqual(len(diagnostics.problems), 1)
        self.assertEqual(diagnostics.problems[0].category, "malformed")
        self.assertIn("bad-fix.md", diagnostics.problems[0].where)

    def test_default_status_is_suspected(self):
        self.assertIs(sig_mod.new(self.root, "x").frontmatter.status, SignatureStatus.SUSPECTED)

    def test_bad_status_rejected(self):
        with self.assertRaises(KctxError):
            sig_mod.parse("---\nid: x\nstatus: not-a-status\n---\n")

    def test_duplicate_slug_is_conflict(self):
        sig_mod.new(self.root, "dup")
        with self.assertRaises(KctxError) as ctx:
            sig_mod.new(self.root, "dup")
        self.assertEqual(ctx.exception.category, "conflict")

    def test_incomplete_authored_draft_is_not_admitted(self):
        self.assertEqual(sig_mod.parse_draft("---\ntitle: drafting\n---\n").frontmatter["title"], "drafting")
        with self.assertRaises(KctxError):
            sig_mod.parse("---\ntitle: drafting\n---\n")


class ListShowTest(KctxTestCase):
    def test_list_and_show(self):
        sig_mod.new(self.root, "a", title="first")
        sig_mod.new(self.root, "b", title="second")
        self.assertEqual(sorted(fm.id.val for fm in sig_mod.list_signatures(self.root)), ["a", "b"])
        self.assertEqual(sig_mod.show(self.root, SignatureId("a")).frontmatter.title, "first")

    def test_show_unknown_is_not_found(self):
        with self.assertRaises(KctxError) as ctx:
            sig_mod.show(self.root, SignatureId("nope"))
        self.assertEqual(ctx.exception.category, "not-found")


class MatchSignaturesTest(KctxTestCase):
    def test_literal_match_is_case_insensitive_and_ranked_by_pattern_count(self):
        sig_mod.new(self.root, "pedl001-duplicate-element-customer-sql",
                    match=("PEDL001", "duplicate element:"), owner_group="group-2423")
        sig_mod.new(self.root, "prep-invalid-reqtype-5007",
                    match=("Not a valid reqType: 5007",), owner_group="group-1135")
        hits = sig_mod.match_signatures(self.root, "pedl001 DUPLICATE ELEMENT: 110002187")
        self.assertEqual(hits[0].id, SignatureId("pedl001-duplicate-element-customer-sql"))
        self.assertEqual(hits[0].owner_group, "group-2423")
        self.assertEqual(len(hits[0].matched_patterns), 2)

    def test_regex_prefixed_pattern(self):
        sig_mod.new(self.root, "x", match=(r"re:duplicate element: \d+",))
        self.assertEqual(len(sig_mod.match_signatures(self.root, "saw duplicate element: 9999 today")), 1)

    def test_no_hit_returns_empty_tuple(self):
        sig_mod.new(self.root, "x", match=("PEDL001",))
        self.assertEqual(sig_mod.match_signatures(self.root, "unrelated text"), ())
