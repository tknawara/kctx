"""Nominal identity namespaces reject mixing and malformed boundary values."""

import unittest
from dataclasses import FrozenInstanceError

from kctx.errors import KctxError
from kctx.domain.ids import (
    AssetId, RelationshipId, EvidenceId, ObservationId, ProposalId, InvestigationId,
    SignatureId, ClaimId, ClaimRevision, CitationId, RuleVersion, OperationId,
    SnapshotId, DerivationId, RunId, GateId, TicketId, parse_asset_id, parse_evidence_id,
)


class NominalIdTests(unittest.TestCase):
    def test_all_namespaces_are_distinct(self):
        namespaces = (AssetId, RelationshipId, EvidenceId, ObservationId, ProposalId,
                      InvestigationId, SignatureId, ClaimId, ClaimRevision, CitationId,
                      RuleVersion, OperationId, SnapshotId, DerivationId, RunId, GateId, TicketId)
        values = [namespace("widget") for namespace in namespaces]
        self.assertEqual(len(set(values)), len(namespaces))
        for value in values:
            self.assertNotEqual(value, "widget")
            self.assertEqual(value.val, "widget")
            self.assertFalse(hasattr(value, "__dict__"))
            for namespace in namespaces:
                with self.subTest(source=type(value).__name__, destination=namespace.__name__):
                    with self.assertRaises(KctxError):
                        namespace(value)

    def test_malformed_rejected_at_parse(self):
        for bad in ("", "Widget", "has space", "x_y", "-leading", "trail-"):
            with self.assertRaises(KctxError) as ctx:
                parse_asset_id(bad)
            self.assertEqual(ctx.exception.category, "malformed")

    def test_valid_slug_alphabet_accepted(self):
        self.assertEqual(parse_asset_id("a").val, "a")
        self.assertEqual(parse_asset_id("pay-svc-2").val, "pay-svc-2")
        self.assertNotEqual(parse_evidence_id("a"), parse_asset_id("a"))

    def test_string_keys_do_not_alias_identity_keys(self):
        identity = AssetId("widget")
        values = {identity: 1, "widget": 2, EvidenceId("widget"): 3}
        self.assertEqual(len(values), 3)
        self.assertEqual(values[identity], 1)
        self.assertEqual(values["widget"], 2)
        self.assertEqual(values[EvidenceId("widget")], 3)

    def test_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            setattr(AssetId("widget"), "val", "changed")

    def test_relationship_namespace(self):
        self.assertEqual(RelationshipId("depends-on__svc-a__svc-b").val, "depends-on__svc-a__svc-b")
        for bad in ("_x__y", "x___y", "x__y_", "x__Y", "x__y z"):
            with self.assertRaises(KctxError):
                RelationshipId(bad)

    def test_persisted_namespace_spellings(self):
        self.assertEqual(ProposalId("config/2026-10-31-typed-model").val, "config/2026-10-31-typed-model")
        self.assertEqual(ProposalId("other/id").val, "other/id")
        self.assertEqual(InvestigationId("2026/2026-10-31-latency").val, "2026/2026-10-31-latency")
        self.assertEqual(RunId("run-20261031T142233Z-a1b2c3").val, "run-20261031T142233Z-a1b2c3")
        self.assertEqual(ObservationId("obs-20261031T142233Z-a1b2c3d4").val, "obs-20261031T142233Z-a1b2c3d4")
        self.assertEqual(TicketId("DRQS-123").val, "DRQS-123")
        self.assertEqual(GateId("G01").val, "G01")
        self.assertEqual(RuleVersion("1.0.0").val, "1.0.0")
        for namespace in (ProposalId, InvestigationId, RunId, ObservationId):
            for bad in ("", "../escape", "/absolute", "has space", "foo/bar/baz"):
                with self.assertRaises(KctxError):
                    namespace(bad)
