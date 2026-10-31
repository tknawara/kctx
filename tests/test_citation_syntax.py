"""Literal compatibility fixtures for the authored citation language."""

import unittest
from datetime import UTC, datetime, timedelta

from kctx.citations.models import CitationKind, CitationStatus, Classification, MadeCitation
from kctx.citations.syntax import (
    find_cite_lines,
    format_cite,
    is_illustrative,
    normalize_span,
    parse_cite_body,
    parse_range,
    remove_field,
    replace_field,
)
from kctx.citations.time import due_for_touch, is_expired, parse_seen, parse_ttl_seconds
from kctx.errors import KctxError


class CitationSyntaxTests(unittest.TestCase):
    def test_literal_quoted_unicode_extensions_and_multiple_tokens(self) -> None:
        text = (
            'before ⟦cite kind=query sys=humio q="service=foo | count()" '
            'result="三 rows" seen=2026-10-31T12:00Z ttl=none x_extension=✓⟧ '
            'after ⟦cite kind=usr date=2026-10-31 where="review call" who=Zoë⟧'
        )
        citations = list(find_cite_lines(text))
        self.assertEqual(len(citations), 2)
        self.assertEqual(citations[0][1], {
            "kind": "query", "sys": "humio", "q": "service=foo | count()",
            "result": "三 rows", "seen": "2026-10-31T12:00Z", "ttl": "none",
            "x_extension": "✓",
        })
        self.assertEqual(citations[1][1]["who"], "Zoë")
        self.assertEqual(text[citations[0][0].start():citations[0][0].end()], citations[0][0].group(0))

    def test_illustrative_marker_only_at_start(self) -> None:
        self.assertTrue(is_illustrative(' illus kind=code path="example.py"'))
        self.assertTrue(is_illustrative("\nillus kind=web"))
        self.assertFalse(is_illustrative(' kind=usr quote="illus"'))
        self.assertFalse(is_illustrative(" illustration kind=web"))

    def test_duplicate_fields_are_diagnosed(self) -> None:
        with self.assertRaisesRegex(KctxError, "duplicate citation field 'kind'"):
            parse_cite_body(" kind=web kind=code")
        self.assertEqual(parse_cite_body('q="kind=web kind=code"')["q"], "kind=web kind=code")

    def test_replacement_preserves_final_closing_delimiter(self) -> None:
        raw = '⟦cite kind=code note="quoted seen=old" seen=2026-01-01T00:00Z⟧'
        expected = '⟦cite kind=code note="quoted seen=old" seen=2026-10-31T12:00Z⟧'
        self.assertEqual(replace_field(raw, "seen", "2026-10-31T12:00Z"), expected)
        self.assertEqual(remove_field(raw, "seen"), '⟦cite kind=code note="quoted seen=old"⟧')
        self.assertEqual(remove_field('⟦cite kind=code stale=changed@2026-01-01⟧', "stale"), '⟦cite kind=code⟧')

    def test_replacement_preserves_other_bytes_and_unknown_fields(self) -> None:
        raw = '⟦cite  kind=web\nurl="https://example.test/a" x=µ q="curl -I url"⟧'
        self.assertEqual(replace_field(raw, "x", "two words"), raw.replace("x=µ", 'x="two words"'))
        self.assertEqual(remove_field(raw, "missing"), raw)
        self.assertEqual(replace_field(raw, "ttl", "none"), raw[:-1] + " ttl=none⟧")

    def test_format_order_and_unrepresentable_values(self) -> None:
        self.assertEqual(
            format_cite({"x": "µ", "kind": "web", "q": "curl -I", "empty": ""}, ("kind", "q", "kind")),
            '⟦cite kind=web q="curl -I" x=µ⟧',
        )
        for value in ('embedded " quote', "closing⟧delimiter"):
            with self.assertRaises(KctxError):
                format_cite({"q": value}, ("q",))

    def test_ranges_and_normalized_spans(self) -> None:
        self.assertEqual(parse_range("4-4"), (4, 4))
        for bad in ("0-1", "4-3", "1", "1-2\n"):
            with self.assertRaises(KctxError):
                parse_range(bad)
        self.assertEqual(normalize_span(["  x", "", " y  "]), normalize_span(["x", "y"]))
        self.assertNotEqual(normalize_span(["x y"]), normalize_span(["x", "y"]))

    def test_immutable_fields_and_explicit_wire_names(self) -> None:
        fields = {"kind": "web"}
        made = MadeCitation("⟦cite kind=web⟧", fields)
        fields["kind"] = "code"
        self.assertEqual(made.fields["kind"], "web")
        self.assertEqual(made.to_wire(), {"line": "⟦cite kind=web⟧", "fields": {"kind": "web"}})
        self.assertEqual(
            Classification(CitationStatus.MOVED, line_range="2-4", sym_line=2, query="cmd").to_wire(),
            {"status": "moved", "L": "2-4", "sym_line": 2, "q": "cmd"},
        )

    def test_vocabulary_is_nominal_not_string_equal(self) -> None:
        self.assertNotEqual(CitationKind.CODE, "code")
        self.assertNotEqual(CitationStatus.FRESH, "fresh")
        self.assertEqual(CitationKind("code"), CitationKind.CODE)
        self.assertEqual(CitationStatus("fresh"), CitationStatus.FRESH)


class CitationTimeTests(unittest.TestCase):
    def test_timestamp_and_ttl_grammar(self) -> None:
        self.assertEqual(parse_seen("2026-10-31T12:00Z"), datetime(2026, 10, 31, 12, tzinfo=UTC))
        self.assertEqual(parse_seen("2026-10-31T12:00:01Z").second, 1)
        for bad in ("2026-10-31", "2026-10-31T12:00+00:00", "not-a-date"):
            with self.assertRaises(KctxError):
                parse_seen(bad)
        for value, expected in ((None, None), ("", None), ("none", None), ("3d", 259200), ("2h", 7200), ("0h", 0)):
            self.assertEqual(parse_ttl_seconds(value), expected)
        with self.assertRaises(KctxError):
            parse_ttl_seconds("1w")

    def test_strict_expiry_and_half_ttl_touch_boundaries(self) -> None:
        seen = "2026-10-31T12:00Z"
        at = parse_seen(seen)
        self.assertFalse(is_expired(seen, "1h", at + timedelta(hours=1)))
        self.assertTrue(is_expired(seen, "1h", at + timedelta(hours=1, microseconds=1)))
        self.assertFalse(is_expired("invalid-but-unbounded", "none", at))
        self.assertFalse(due_for_touch({"seen": seen, "ttl": "1h"}, at + timedelta(minutes=30)))
        self.assertTrue(due_for_touch({"seen": seen, "ttl": "1h"}, at + timedelta(minutes=31)))
        self.assertFalse(due_for_touch({"seen": seen, "ttl": "none"}, at + timedelta(days=100)))
        self.assertFalse(due_for_touch({"seen": "invalid", "ttl": "1h"}, at))
