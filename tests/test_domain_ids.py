"""Q01/Q02 fixtures: nominal ids at the legacy boundary — same spelling,
different namespaces; malformed ids rejected once, at parse time."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from errors import KctxError  # noqa: E402
from kctx.domain.ids import (  # noqa: E402
    AssetId,
    EvidenceId,
    RelationshipId,
    parse_asset_id,
    parse_evidence_id,
)


class NominalIdTests(unittest.TestCase):
    def test_same_spelling_different_namespace_not_equal(self):
        a = parse_asset_id("widget")
        e = parse_evidence_id("widget")
        self.assertEqual(a.val, e.val)
        self.assertNotEqual(a, e)

    def test_malformed_rejected_at_parse(self):
        for bad in ["", "Widget", "has space", "x_y", "-leading", "trail-"]:
            with self.assertRaises(KctxError) as ctx:
                parse_asset_id(bad)
            self.assertEqual(ctx.exception.category, "malformed")

    def test_valid_slug_alphabet_accepted(self):
        self.assertEqual(parse_asset_id("a").val, "a")
        self.assertEqual(parse_asset_id("pay-svc-2").val, "pay-svc-2")

    def test_interops_with_string_keys_and_dicts(self):
        a = parse_asset_id("widget")
        d = {a: 1, "other": 2}
        self.assertEqual(d[a], 1)
        self.assertEqual(d["widget"], 1)

    def test_frozen(self):
        a = parse_asset_id("widget")
        with self.assertRaises(Exception):
            a.val = "changed"  # type: ignore[misc]

    def test_evidence_and_relationship_namespaces(self):
        r = RelationshipId("rel-1")
        e = parse_evidence_id("ev-1")
        self.assertNotEqual(r, AssetId("rel-1"))
        self.assertNotEqual(e, AssetId("ev-1"))

    def test_relationship_ids_allow_double_underscore_join(self):
        # the corpus convention: type__from__to
        self.assertEqual(
            RelationshipId("depends-on__svc-a__svc-b").val,
            "depends-on__svc-a__svc-b",
        )
        # but each segment still must be a slug
        for bad in ["_x__y", "x___y", "x__y_", "x__Y", "x__y z"]:
            with self.assertRaises(KctxError):
                RelationshipId(bad)


if __name__ == "__main__":
    unittest.main()
