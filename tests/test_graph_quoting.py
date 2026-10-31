"""graph.quoting has no third-party deps, so these run unconditionally under
plain `python3 -m unittest` -- no skip guard needed."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


import unittest

from errors import KctxError
from kctx.graph.quoting import sql_quote, validate_id


class SqlQuoteTest(unittest.TestCase):
    def test_none_is_null(self):
        self.assertEqual(sql_quote(None), "NULL")

    def test_plain_string(self):
        self.assertEqual(sql_quote("abc"), "'abc'")

    def test_escapes_single_quote(self):
        self.assertEqual(sql_quote("it's"), "'it''s'")

    def test_escapes_backslash(self):
        self.assertEqual(sql_quote("a\\b"), "'a\\\\b'")

    def test_int_coerced_to_string(self):
        self.assertEqual(sql_quote(5), "'5'")


class ValidateIdTest(unittest.TestCase):
    def test_accepts_normal_id(self):
        self.assertEqual(validate_id("proposal:decision/2026-10-30-foo"), "proposal:decision/2026-10-30-foo")

    def test_rejects_empty(self):
        with self.assertRaises(KctxError):
            validate_id("")

    def test_rejects_quote(self):
        with self.assertRaises(KctxError):
            validate_id("abc' OR '1'='1")

    def test_rejects_backslash(self):
        with self.assertRaises(KctxError):
            validate_id("abc\\def")

    def test_rejects_newline(self):
        with self.assertRaises(KctxError):
            validate_id("abc\ndef")


if __name__ == "__main__":
    unittest.main()
