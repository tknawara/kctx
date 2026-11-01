"""Use-target boundary fixtures (M2 slice 7): the six spellings parse once
into a closed sum; per-variant search-widening matches the baseline rules."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kctx.domain.targets import (  # noqa: E402
    AssetRef,
    CodeLocator,
    EvidenceRef,
    InvRef,
    ProposalRef,
    SigRef,
    fix_reference_spelling,
    parse_fix_reference,
    parse_use_target,
    search_strings,
)
from kctx.domain.ids import EvidenceId, ProposalId, SignatureId, InvestigationId
from kctx.errors import KctxError


class ParseUseTargetTests(unittest.TestCase):
    def test_evidence(self):
        t = parse_use_target("ev:2026/inv-1/ev-3")
        self.assertIsInstance(t, EvidenceRef)
        self.assertEqual((t.home, t.stem), ("2026/inv-1", EvidenceId("ev-3")))
        self.assertEqual(search_strings(t), ("ev:2026/inv-1/ev-3",))

    def test_sig_and_inv_widen_to_bare(self):
        for cls, prefix in ((SigRef, "sig:"), (InvRef, "inv:")):
            t = parse_use_target(prefix + "known-err")
            self.assertIsInstance(t, cls)
            self.assertEqual(search_strings(t), (prefix + "known-err", "known-err"))

    def test_proposal_widens_to_dateslug(self):
        t = parse_use_target("proposal/config/2026-01-02-thing")
        self.assertIsInstance(t, ProposalRef)
        self.assertEqual(
            search_strings(t),
            ("proposal/config/2026-01-02-thing", "config/2026-01-02-thing"),
        )

    def test_locator(self):
        t = parse_use_target("acme/w@abcd1234:src/x.py:12-40")
        self.assertIsInstance(t, CodeLocator)
        self.assertEqual((t.repo, t.sha, t.path), ("acme/w", "abcd1234", "src/x.py"))
        self.assertEqual(t.line, (12, 40))
        t2 = parse_use_target("acme/w@ABCD1234567890abcd1234567890abcd12345678:README")
        self.assertIsInstance(t2, CodeLocator)
        self.assertIsNone(t2.line)

    def test_bare_falls_through_to_asset(self):
        t = parse_use_target("pay-svc")
        self.assertIsInstance(t, AssetRef)
        self.assertEqual(search_strings(t), ("pay-svc",))

    def test_sum_is_closed_over_variants(self):
        # every parse result is one of the six variants; nothing else leaks
        for raw in ["ev:a/b", "sig:x", "inv:x", "proposal/config/2026-01-02-thing", "r@s:p:1", "bare"]:
            t = parse_use_target(raw)
            self.assertIsInstance(
                t, (EvidenceRef, SigRef, InvRef, ProposalRef, AssetRef, CodeLocator)
            )

    def test_reference_id_namespaces_are_nominal(self):
        self.assertEqual(parse_use_target("sig:x").id, SignatureId("x"))
        self.assertEqual(parse_use_target("inv:x").id, InvestigationId("x"))
        self.assertNotEqual(SignatureId("x"), InvestigationId("x"))
        self.assertNotEqual(SignatureId("x"), "x")

    def test_malformed_evidence_rejected_at_boundary(self):
        with self.assertRaises(KctxError):
            parse_use_target("ev:missing-home")


class ParseFixReferenceTests(unittest.TestCase):
    def test_closed_fix_variants_round_trip(self):
        for raw, kind in (
            ("config/2026-01-02-thing", ProposalId),
            ("simple-proposal", ProposalId),
            ("ev:project/fixing-pr", EvidenceRef),
            ("acme/widget@abcdef1234:src/fix.py:10-20", CodeLocator),
        ):
            with self.subTest(raw=raw):
                reference = parse_fix_reference(raw)
                self.assertIsInstance(reference, kind)
                self.assertEqual(fix_reference_spelling(reference), raw)
                self.assertEqual(parse_fix_reference(fix_reference_spelling(reference)), reference)

    def test_malformed_fix_references_are_rejected(self):
        for raw in (
            "acme/widget#7", "TICKET 1234", "ev:missing-home", "ev:project/",
            "acme/widget@main:src/fix.py", "acme/widget@abcdef1:src/fix.py:0",
            "acme/widget@abcdef1:src/fix.py:20-10",
        ):
            with self.subTest(raw=raw), self.assertRaises(KctxError):
                parse_fix_reference(raw)


if __name__ == "__main__":
    unittest.main()
