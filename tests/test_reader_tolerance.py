"""One malformed record limits its own reporting, never cross-cutting readers.

`impact`, `match` and `stale` aggregate over whole collections; a single
undecodable relationship, signature, investigation or correction file must be
skipped and disclosed (partial, exit 2), not abort the command for every other
record. `validate` remains the surface that reports each bad record strictly.
"""

import json

from _base import KctxTestCase

from kctx.adapters.files.storage import atomic_write_json
from kctx.domain.ids import AssetId, SignatureId
from kctx.domain.targets import parse_use_target
from kctx.domain.vocabulary import AssetKind, RelationshipType, SignatureStatus
from kctx.services import backlinks, discovery, freshness, inventory
from kctx.services import signatures as sig_mod


def _break_json(path):
    path.write_text("{ not json", encoding="utf-8")


class ImpactToleranceTest(KctxTestCase):
    def test_broken_relationship_disclosed_not_fatal(self):
        inventory.asset_add(self.root, kind=AssetKind.STORE, name="s1", id=AssetId("store-s1"))
        inventory.asset_add(self.root, kind=AssetKind.REPO, name="r1", id=AssetId("repo-r1"))
        inventory.rel_add(
            self.root,
            type=RelationshipType.CONSUMES,
            from_=AssetId("repo-r1"),
            to=AssetId("store-s1"),
        )
        _break_json(
            self.root / "inventory" / "relationships" / "consumes__repo-x__store-x.json"
        )
        result = inventory.impact(self.root, "store-s1")
        self.assertEqual([item.asset.val for item in result.reached], ["repo-r1"])
        self.assertTrue(result.warnings)
        self.assertIn("consumes__repo-x__store-x.json", result.warnings[0])

    def test_v1_locator_evidence_decodes_and_impact_traverses(self):
        inventory.asset_add(self.root, kind=AssetKind.STORE, name="s1", id=AssetId("store-s1"))
        inventory.asset_add(self.root, kind=AssetKind.REPO, name="r1", id=AssetId("repo-r1"))
        # A v1-written relationship with code-locator evidence stays readable.
        atomic_write_json(
            self.root / "inventory" / "relationships" / "consumes__repo-r1__store-s1.json",
            {
                "schema_version": 1,
                "id": "consumes__repo-r1__store-s1",
                "type": "consumes",
                "from": "repo-r1",
                "to": "store-s1",
                "status": "explicit",
                "evidence": ["example-org/r1@" + "0" * 40 + ":src/a.py:11"],
                "applicability": "",
            },
        )
        result = inventory.impact(self.root, "store-s1")
        self.assertEqual([item.asset.val for item in result.reached], ["repo-r1"])
        self.assertEqual(result.warnings, ())

    def test_uses_finds_relationship_citing_evidence_address(self):
        inventory.asset_add(self.root, kind=AssetKind.STORE, name="s1", id=AssetId("store-s1"))
        inventory.asset_add(self.root, kind=AssetKind.REPO, name="r1", id=AssetId("repo-r1"))
        atomic_write_json(
            self.root / "inventory" / "relationships" / "consumes__repo-r1__store-s1.json",
            {
                "schema_version": 1,
                "id": "consumes__repo-r1__store-s1",
                "type": "consumes",
                "from": "repo-r1",
                "to": "store-s1",
                "status": "explicit",
                "evidence": ["ev:inventory/some-record"],
                "applicability": "",
            },
        )
        result = backlinks.uses(self.root, parse_use_target("ev:inventory/some-record"))
        files = [referrer["file"] for referrer in result["referrers"]]
        self.assertTrue(
            any("consumes__repo-r1__store-s1.json" in name for name in files), files
        )


class MatchToleranceTest(KctxTestCase):
    def test_broken_signature_is_skipped_and_disclosed(self):
        sig_mod.new(
            self.root,
            "sig-good",
            title="Good signature",
            match=("database on fire",),
            status=SignatureStatus.SUSPECTED,
        )
        (self.root / "signatures").mkdir(parents=True, exist_ok=True)
        (self.root / "signatures" / "sig-b.md").write_text(
            "---\nid: sig-b\nfix: [example-org/example-repo#7]\n---\n\n# bad\n",
            encoding="utf-8",
        )
        result = discovery.match(self.root, "database on fire")
        self.assertEqual([hit["id"] for hit in result["signatures"]], ["sig-good"])
        self.assertTrue(any("sig-b" in warning for warning in result["warnings"]))

    def test_stale_survives_broken_signature(self):
        sig_mod.new(
            self.root,
            "sig-good",
            title="Good signature",
            match=("database on fire",),
            status=SignatureStatus.SUSPECTED,
        )
        (self.root / "signatures").mkdir(parents=True, exist_ok=True)
        (self.root / "signatures" / "sig-b.md").write_text(
            "---\nid: sig-b\nfix: [example-org/example-repo#7]\n---\n\n# bad\n",
            encoding="utf-8",
        )
        report = freshness.stale(self.root, offline=True)
        self.assertTrue(
            any("sig-b" in warning for warning in report["warnings"]), report["warnings"]
        )
