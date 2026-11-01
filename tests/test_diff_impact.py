"""Behavioral boundaries of local diff review composition."""

import unittest

from _base import KctxTestCase
from kctx.domain.ids import AssetId, RelationshipId
from kctx.domain.vocabulary import AssetKind, RelationshipType
from kctx.services import inventory, signatures
from kctx.services.diff_impact import impact_diff


class DiffImpactTests(KctxTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.make_git_repo("source")
        self.run_git(self.repo, "remote", "add", "origin", "https://example.invalid/acme/widget.git")
        self.base = self.commit_file(self.repo, "src/main.py", "one\ntwo\nthree\n")
        self.head = self.commit_file(self.repo, "src/main.py", "one\nchanged\nthree\n")
        (self.root / "notes.md").write_text(
            f"⟦cite kind=code repo=acme/widget rev={self.base} path=src/main.py L=2-2⟧\n"
        )

    def test_bidirectional_inventory_signatures_and_no_release_are_distinct(self):
        for ident, locator in (
            ("service", "acme/widget"), ("consumer", "acme/consumer"),
            ("database", "acme/data"), ("further", "acme/further"),
            ("wrong-repository", "other/widget"),
        ):
            inventory.asset_add(
                self.root, id=AssetId(ident), name=ident, kind=AssetKind.SERVICE, locator=locator
            )
        for ident, from_, to in (
            ("inbound", "consumer", "service"),
            ("outbound", "service", "database"),
            ("beyond-depth", "further", "consumer"),
        ):
            inventory.rel_add(
                self.root, id=RelationshipId(ident), type=RelationshipType.DEPENDS_ON,
                from_=AssetId(from_), to=AssetId(to),
            )
        signatures.new(self.root, "attached", assets=(AssetId("service"),))
        signatures.new(self.root, "not-attached", assets=(AssetId("database"),))
        result = impact_diff(self.root, f"{self.base}..{self.head}", repo=self.repo, depth=1)
        self.assertEqual((result["base"], result["head"]), (self.base, self.head))
        file = result["files"][0]
        self.assertEqual(file["path"], "src/main.py")
        self.assertEqual(file["citations"][0]["range_status"], "overlap")
        self.assertEqual([row["asset"]["id"] for row in file["assets"]], ["service"])
        asset = file["assets"][0]
        self.assertEqual([row["id"] for row in asset["inbound"]], ["inbound"])
        self.assertEqual([row["id"] for row in asset["outbound"]], ["outbound"])
        self.assertEqual({row["id"] for row in asset["related_assets"]}, {"consumer", "database"})
        self.assertEqual(asset["impact"]["unexplored_edges"][0]["to"], "further")
        self.assertEqual([row["id"] for row in file["signatures"]], ["attached"])
        self.assertEqual(file["claims"], [])
        self.assertEqual(result["knowledge"]["status"], "no_release")
        self.assertFalse(result["complete"])

    def test_malformed_authored_records_limit_only_their_coverage(self):
        inventory.asset_add(
            self.root, id=AssetId("service"), name="Service", kind=AssetKind.SERVICE,
            locator="acme/widget",
        )
        (self.root / "inventory" / "assets" / "broken.json").write_text("{")
        signatures.new(self.root, "good", assets=(AssetId("service"),))
        (self.root / "signatures" / "bad.md").write_text("---\nid: bad\nstatus: invalid\n---\n")
        result = impact_diff(self.root, f"{self.base}..{self.head}", repo=self.repo)
        self.assertEqual(result["files"][0]["assets"][0]["asset"]["id"], "service")
        self.assertEqual([row["id"] for row in result["files"][0]["signatures"]], ["good"])
        self.assertTrue(any("broken.json" in warning for warning in result["warnings"]))
        self.assertTrue(any("bad.md" in warning for warning in result["warnings"]))
        self.assertFalse(result["complete"])


if __name__ == "__main__":
    unittest.main()
