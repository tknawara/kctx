"""Persisted JSON rejects malformed records before service mutation."""

import unittest
from dataclasses import FrozenInstanceError

from _base import KctxTestCase
from kctx.adapters.files.storage import read_json
from kctx.codecs.records import (
    decode_asset, decode_relationship, decode_observation, decode_coverage,
    decode_run_manifest, decode_run_receipt, encode_asset, encode_relationship,
    encode_observation, encode_coverage, encode_run_manifest, encode_run_receipt,
)
from kctx.domain.ids import AssetId, EvidenceId, ObservationId, RelationshipId, RunId
from kctx.domain.ids import ContentDigest
from kctx.domain.targets import CodeLocator, EvidenceRef
from kctx.domain.records import Asset, Coverage, CoverageEntry, Observation, ObservationEvidence, ObservationSource, Relationship
from kctx.domain.vocabulary import AssetKind, CoverageOutcome, ObservationSystem, RelationshipType, RunMode
from kctx.errors import KctxError
from kctx.services import inventory, runs


class RecordCodecTests(unittest.TestCase):
    def test_asset_round_trip_and_legacy_defaults(self):
        asset = decode_asset({"id": "svc-example", "kind": "service", "name": "Example"})
        self.assertEqual(asset.id, AssetId("svc-example"))
        self.assertEqual(asset.kind, AssetKind.SERVICE)
        self.assertEqual(asset.aliases, ())
        encoded = encode_asset(asset)
        self.assertEqual(encoded["schema_version"], 1)
        self.assertEqual(encoded["id"], "svc-example")
        self.assertEqual(encoded["aliases"], [])
        self.assertEqual(decode_asset(encoded), asset)
        with self.assertRaises(FrozenInstanceError):
            setattr(asset, "aliases", ("changed",))

    def test_asset_rejects_missing_unknown_version_enum_and_types(self):
        valid: dict[str, object] = {"id": "svc-example", "kind": "service", "name": "Example"}
        invalid = [
            {}, {**valid, "id": "../escape"}, {**valid, "kind": "imaginary"},
            {**valid, "lifecycle": "imaginary"}, {**valid, "schema_version": 2},
            {**valid, "schema_version": True}, {**valid, "schema_version": "1"},
            {**valid, "future": "not silently dropped"}, {**valid, "aliases": "alias"},
            {**valid, "projects": [1]}, {**valid, "name": 7}, {**valid, "owner": None},
            {**valid, "ttl": False}, {**valid, "id": AssetId("svc-example")},
        ]
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(KctxError) as caught:
                decode_asset(raw)
            self.assertEqual(caught.exception.category, "malformed")

    def test_relationship_round_trip_keeps_wire_from(self):
        relationship = Relationship(
            RelationshipId("consumes__svc-a__svc-b"),
            RelationshipType.CONSUMES,
            AssetId("svc-a"),
            AssetId("svc-b"),
            evidence=(
                EvidenceRef("inventory", EvidenceId("ev-1")),
                CodeLocator("example/repo", "0" * 40, "src/a.py", (11, 11)),
            ),
        )
        encoded = encode_relationship(relationship)
        self.assertEqual(encoded["from"], "svc-a")
        self.assertNotIn("from_", encoded)
        self.assertEqual(
            encoded["evidence"], ["ev:inventory/ev-1", f"example/repo@{'0' * 40}:src/a.py:11"]
        )
        self.assertEqual(decode_relationship(encoded), relationship)
        with self.assertRaises(KctxError):
            decode_relationship({**encoded, "from_": "svc-other"})
        with self.assertRaises(KctxError):
            decode_relationship({**encoded, "evidence": [1]})
        # A bare slug addresses neither an evidence record nor a code position.
        for raw in ("ev-1", "ev:ev-1", "example/repo@main:src/a.py", "see the runbook"):
            with self.subTest(raw=raw), self.assertRaises(KctxError):
                decode_relationship({**encoded, "evidence": [raw]})

    def test_observation_nested_validation_and_immutable_evidence(self):
        observation = Observation(ObservationId("obs-1"), RunId("run-20261031T123456Z-abc123"),
                                  ObservationSource(ObservationSystem.DOC, "notes://one"), "2026-10-31T12:34:56Z",
                                  evidence=ObservationEvidence("evidence/file.txt", ContentDigest("a" * 64)))
        encoded = encode_observation(observation)
        self.assertEqual(decode_observation(encoded), observation)
        for changed in (
            {"source": {}}, {"source": {"system": "doc", "locator": 1}},
            {"source": {"system": "unknown", "locator": "x"}},
            {"source": {"system": "doc", "locator": "x", "extra": True}},
            {"evidence": []}, {"evidence": {"locator": "x", "sha256": 1}},
            {"evidence": {"locator": "x", "sha256": "abc"}},
            {"evidence": {"locator": "x", "opaque": object()}},
            {"dirty": "false"}, {"status": "unknown"}, {"schema_version": 99},
        ):
            with self.subTest(changed=changed), self.assertRaises(KctxError):
                decode_observation({**encoded, **changed})
        with self.assertRaises(FrozenInstanceError):
            setattr(observation.evidence, "locator", "different")

    def test_coverage_rejects_mismatched_keys_and_invalid_nested_records(self):
        coverage = Coverage((CoverageEntry("q1", CoverageOutcome.SUPPORTED, (ObservationId("obs-1"),)),))
        encoded = encode_coverage(coverage)
        self.assertEqual(decode_coverage(encoded), coverage)
        for raw in (
            {"entries": []}, {"schema_version": 2, "entries": {}},
            {"entries": {"q1": {"item": "q2", "outcome": "supported"}}},
            {"entries": {"q1": {"item": "q1", "outcome": "unknown"}}},
            {"entries": {"q1": {"item": "q1", "outcome": "supported", "evidence": [False]}}},
        ):
            with self.subTest(raw=raw), self.assertRaises(KctxError):
                decode_coverage(raw)
        with self.assertRaises(KctxError):
            encode_coverage(Coverage(coverage.entries + coverage.entries))


class PersistedRecordIntegrationTests(KctxTestCase):
    def test_inventory_services_persist_explicit_wire_shapes(self):
        asset = inventory.asset_add(self.root, kind=AssetKind.SERVICE, name="Example", aliases=("old",))
        self.assertIsInstance(asset, Asset)
        raw = read_json(inventory.assets_dir(self.root) / f"{asset.id.val}.json")
        self.assertEqual(raw, encode_asset(asset))
        self.assertEqual(inventory.asset_show(self.root, "old"), asset)

    def test_run_round_trip_receipt_and_manifest(self):
        manifest = runs.new_run(self.root, project="demo", mode=RunMode.ADVICE, task="codec")
        self.assertEqual(decode_run_manifest(encode_run_manifest(manifest)), manifest)
        observation = runs.add_observation(self.root, manifest.run_id, system=ObservationSystem.DOC, locator="notes://one")
        runs.cover(self.root, manifest.run_id, item="q1", outcome=CoverageOutcome.SUPPORTED, evidence=(observation.id,))
        receipt = runs.check(self.root, manifest.run_id)
        self.assertEqual(decode_run_receipt(encode_run_receipt(receipt)), receipt)
        self.assertEqual(runs.resume(self.root, manifest.run_id).last_receipt, receipt)
        for decoder, valid in ((decode_run_manifest, encode_run_manifest(manifest)), (decode_run_receipt, encode_run_receipt(receipt))):
            for patch in ({"schema_version": 99}, {"unknown": "value"}):
                with self.assertRaises(KctxError):
                    decoder({**valid, **patch})
