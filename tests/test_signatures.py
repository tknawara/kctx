from _base import KctxTestCase

import signatures as sig_mod
from errors import KctxError


class NewRecordTest(KctxTestCase):
    def test_new_scaffolds_record_with_id_path_and_frontmatter(self):
        result = sig_mod.new(
            self.root,
            "pedl001-duplicate-element-customer-sql",
            title="PEDL001 duplicate element",
            match=["PEDL001", "duplicate element:"],
            match_where="humio #repo=pbp",
            owner_group="group-2423",
            status="known-error",
        )
        self.assertEqual(result["id"], "pedl001-duplicate-element-customer-sql")
        path = self.root / "signatures" / "pedl001-duplicate-element-customer-sql.md"
        self.assertTrue(path.exists())

        parsed = sig_mod.parse(path.read_text(encoding="utf-8"))
        fm = parsed["frontmatter"]
        self.assertEqual(fm["match"], ["PEDL001", "duplicate element:"])
        self.assertEqual(fm["owner_group"], "group-2423")
        self.assertEqual(fm["status"], "known-error")
        for section in sig_mod.SECTION_ORDER:
            self.assertIn(section, parsed["body"])

    def test_default_status_is_suspected(self):
        result = sig_mod.new(self.root, "x")
        self.assertEqual(result["frontmatter"]["status"], "suspected")

    def test_bad_status_rejected(self):
        with self.assertRaises(KctxError):
            sig_mod.new(self.root, "x", status="not-a-status")

    def test_duplicate_slug_is_conflict(self):
        sig_mod.new(self.root, "dup")
        with self.assertRaises(KctxError) as ctx:
            sig_mod.new(self.root, "dup")
        self.assertEqual(ctx.exception.category, "conflict")


class ListShowTest(KctxTestCase):
    def test_list_and_show(self):
        sig_mod.new(self.root, "a", title="first")
        sig_mod.new(self.root, "b", title="second")
        self.assertEqual(
            sorted(fm["id"] for fm in sig_mod.list_signatures(self.root)), ["a", "b"]
        )
        shown = sig_mod.show(self.root, "a")
        self.assertEqual(shown["frontmatter"]["title"], "first")

    def test_show_unknown_is_not_found(self):
        with self.assertRaises(KctxError) as ctx:
            sig_mod.show(self.root, "nope")
        self.assertEqual(ctx.exception.category, "not-found")


class MatchSignaturesTest(KctxTestCase):
    def test_literal_match_is_case_insensitive_and_ranked_by_pattern_count(self):
        sig_mod.new(
            self.root,
            "pedl001-duplicate-element-customer-sql",
            match=["PEDL001", "duplicate element:"],
            owner_group="group-2423",
        )
        sig_mod.new(
            self.root,
            "prep-invalid-reqtype-5007",
            match=["Not a valid reqType: 5007"],
            owner_group="group-1135",
        )
        hits = sig_mod.match_signatures(
            self.root, "pedl001 DUPLICATE ELEMENT: 110002187"
        )
        self.assertEqual(hits[0]["id"], "pedl001-duplicate-element-customer-sql")
        self.assertEqual(hits[0]["owner_group"], "group-2423")
        self.assertEqual(len(hits[0]["matched_patterns"]), 2)

    def test_regex_prefixed_pattern(self):
        sig_mod.new(self.root, "x", match=["re:duplicate element: \\d+"])
        hits = sig_mod.match_signatures(self.root, "saw duplicate element: 9999 today")
        self.assertEqual(len(hits), 1)

    def test_no_hit_returns_empty_list(self):
        sig_mod.new(self.root, "x", match=["PEDL001"])
        self.assertEqual(sig_mod.match_signatures(self.root, "unrelated text"), [])
