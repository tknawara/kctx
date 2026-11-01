"""Real Git/Dolt source-admission regressions; run in the verify Compose image."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kctx.adapters.files.knowledge import canonical, digest, load, save
from kctx.domain.ids import AssetId, AuthorityKeyId, PlanId, PolicyDigest, ReceiptId, ReleaseId, SourceId, SourceRevision
from kctx.domain.json import JsonObject, object_value
from kctx.errors import KctxError
from kctx.semantics.wire import dec_context, dec_kb, dec_ref, dec_witness, enc_context, enc_kb, enc_receipt
from kctx.semantics.checker import accepted
from kctx.semantics.model import Receipt, ReceiptResult, SourceSelection
from kctx.services.knowledge import KnowledgeEngine
from kctx.services.knowledge_models import CaptureKind


class KnowledgeAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.repo = self.root / "authored"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.key = Ed25519PrivateKey.generate()
        self.key_file = self.root / "operator.pem"
        self.key_file.write_bytes(self.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        policy: JsonObject = {"schema_version": 2, "kb_id": "test-kb", "policy_version": "review-policy", "trusted_keys": {"reviewer-key": {"public_key": self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex(), "target_uses": ["review"]}}}
        save(self.repo / ".kctx" / "knowledge-policy.json", policy)
        self.engine = KnowledgeEngine(self.repo, self.root / "dolt", PolicyDigest(digest(canonical(policy))))

    def candidate(self, kind: CaptureKind) -> JsonObject:
        capture = self.engine.capture(kind, SourceId("https://example.test/pull/42" if kind is CaptureKind.PR else "docs/design.md"), SourceRevision("immutable-revision-17"), b"Reviewed exact source bytes\n", 1)
        scope: JsonObject = {"project": "test-kb", "selector": ""}
        statement: JsonObject = {"formula": {"tag": "atom", "atom": {"subject": "service", "predicate": "reviewed", "args": []}}, "scope": scope, "polarity": "positive"}
        ref: JsonObject = {"id": "reviewed", "revision": "r1"}
        witness: JsonObject = {"tag": "attest", "attestation": "attestation-1"}
        context: JsonObject = {"snapshot": "bootstrap:test-kb", "semantic_version": "2.0.0", "ruleset": "core-2", "checker": "kctx-2", "policy": {"id": "review-policy", "require_fresh": True, "require_validation": False, "require_uncontested": True, "ttl": 100, "authorized_actors": ["reviewer-key"]}, "now": 5, "target": scope, "intended_use": "review"}
        context["sources"] = [{"source": capture.source.val, "revision": capture.revision.val, "content": capture.content.val}]
        kb: JsonObject = {"snapshot": "generation-1", "observations": [{"id": "observation-1", "source": capture.source.val, "revision": capture.revision.val, "content": capture.content.val, "observed_at": 1, "outcome": "ok"}], "claims": [{"id": "reviewed", "revision": "r1", "statement": statement}], "attestations": [{"id": "attestation-1", "claim": ref, "observation": "observation-1", "statement": statement, "authority": "reviewer-key"}], "enumerations": [], "derivations": [{"id": "derivation-1", "claim": ref, "witness": witness}], "corrections": [], "receipts": []}
        return {"kb": kb, "capture_ids": [capture.id.val], "context": context, "claim": ref, "witness": witness, "authority_key": "reviewer-key"}

    def test_document_requires_signature_then_retrieves_pinned_support(self) -> None:
        candidate = self.candidate(CaptureKind.DOCUMENT)
        plan = self.engine.propose(candidate, "review", 5)
        self.assertIsNone(self.engine.git.current())
        approval = self.engine.sign(plan.id, self.key_file, AuthorityKeyId("reviewer-key"))
        with self.assertRaises(KctxError):
            self.engine.admit(plan.id, replace(approval, signature=b"x" * 64))
        result = self.engine.admit(plan.id, approval)
        self.assertEqual(result["outcome"], "applied")
        self.assertEqual(self.engine.admit(plan.id, approval)["outcome"], "already_applied")
        context = replace(dec_context(candidate["context"]), snapshot=plan.semantic.candidate.snapshot)
        response = self.engine.context((dec_ref(candidate["claim"]),), context, release=ReleaseId(str(result["release"])))
        self.assertIn(b'"support":"positive"', canonical(response))
        self.assertIn(b'"usable":true', canonical(response))
        self.assertTrue(response["complete"])

    def test_pr_capture_never_proves_arbitrary_prose_claim(self) -> None:
        candidate = self.candidate(CaptureKind.PR)
        kb = candidate["kb"]
        self.assertIsInstance(kb, dict)
        if isinstance(kb, dict):
            kb["attestations"] = []
            kb["derivations"] = []
        with self.assertRaises((KctxError, ValueError)):
            self.engine.propose(candidate, "review", 5)
        self.assertIsNone(self.engine.git.current())

    def test_pr_approved_capture_publishes(self) -> None:
        candidate = self.candidate(CaptureKind.PR)
        plan = self.engine.propose(candidate, "review", 5)
        approval = self.engine.sign(plan.id, self.key_file, AuthorityKeyId("reviewer-key"))
        self.assertEqual(self.engine.admit(plan.id, approval)["outcome"], "applied")

    def test_authorized_selection_preserves_later_retraction_and_rolls_forward(self) -> None:
        candidate = self.candidate(CaptureKind.DOCUMENT)
        first = self.engine.propose(candidate, "review", 5)
        first_release = ReleaseId(str(self.engine.admit(first.id, self.engine.sign(first.id, self.key_file, AuthorityKeyId("reviewer-key")))["release"]))
        kb = object_value(enc_kb(first.semantic.candidate))
        original = object_value(candidate["claim"])
        statement = object_value(object_value(kb["claims"][0])["statement"]) if isinstance(kb["claims"], list) else {}
        statement["formula"] = {"tag": "atom", "atom": {"subject": "service", "predicate": "secondary", "args": []}}
        second_ref: JsonObject = {"id": "secondary", "revision": "r1"}
        witness: JsonObject = {"tag": "attest", "attestation": "attestation-2"}
        for collection, record in (
            ("claims", {"id": "secondary", "revision": "r1", "statement": statement}),
            ("attestations", {"id": "attestation-2", "claim": second_ref, "observation": "observation-1", "statement": statement, "authority": "reviewer-key"}),
            ("derivations", {"id": "derivation-2", "claim": second_ref, "witness": witness}),
            ("corrections", {"id": "correction-1", "kind": "retract", "target": original, "replacement": None, "recorded_at": 6}),
        ):
            entries = kb[collection]
            if isinstance(entries, list):
                entries.append(object_value(record))
        kb["snapshot"] = "generation-2"
        second_context = replace(first.context, snapshot=first.semantic.candidate.snapshot, now=6)
        second_input: JsonObject = {"kb": kb, "capture_ids": candidate["capture_ids"], "context": object_value(enc_context(second_context)), "claim": second_ref, "witness": witness, "authority_key": "reviewer-key"}
        second = self.engine.propose(second_input, "review", 6)
        second_release = ReleaseId(str(self.engine.admit(second.id, self.engine.sign(second.id, self.key_file, AuthorityKeyId("reviewer-key")))["release"]))
        selection_context = replace(second_context, snapshot=second.semantic.candidate.snapshot, now=7)
        rollback = self.engine.rollback(first_release, selection_context, AuthorityKeyId("reviewer-key"))
        self.assertEqual(self.engine.git.current(), second_release.val)
        selected_release = ReleaseId(str(self.engine.admit(rollback.id, self.engine.sign(rollback.id, self.key_file, AuthorityKeyId("reviewer-key")))["release"]))
        selected_context = replace(selection_context, snapshot=rollback.semantic.new_snapshot)
        response = self.engine.context((), selected_context)
        self.assertEqual(response["selection_omitted"], 1)
        self.assertIn(b'"support":"none"', canonical(response))
        self.assertIn(b'"correction-1"', canonical(response))
        asset_context = self.engine.context_for_assets((AssetId("service"),))
        self.assertEqual(asset_context["release"], selected_release.val)
        self.assertEqual(
            [row["claim"]["id"] for row in asset_context["records"]], ["reviewed"]
        )
        self.assertEqual(asset_context["records"][0]["assessment"]["support"], "none")
        self.assertEqual(asset_context["selection_omitted"], 1)
        historical = self.engine.context((dec_ref(original),), replace(first.context, snapshot=first.semantic.candidate.snapshot), release=first_release)
        self.assertIn(b'"support":"positive"', canonical(historical))
        forward = self.engine.rollback(second_release, replace(selected_context, now=8), AuthorityKeyId("reviewer-key"))
        self.engine.admit(forward.id, self.engine.sign(forward.id, self.key_file, AuthorityKeyId("reviewer-key")))
        forward_response = self.engine.context((), replace(selected_context, now=8, snapshot=forward.semantic.new_snapshot))
        self.assertEqual(forward_response["selection_omitted"], 0)
        self.assertIn(b'"correction-1"', canonical(forward_response))
        self.assertNotEqual(self.engine.git.current(), selected_release.val)
        with self.assertRaises(KctxError):
            self.engine.rollback(ReleaseId("f" * 40), replace(selected_context, snapshot=forward.semantic.new_snapshot), AuthorityKeyId("reviewer-key"))

    def test_legacy_import_accounts_restores_and_does_not_admit_prose(self) -> None:
        legacy = self.root / "legacy"
        legacy.mkdir()
        save(legacy / "database.json", {"id": "db", "kind": "store", "name": "Database", "aliases": ["primary"]})
        doc = "\r\n".join(("---", "id: legacy-doc", "custom: untouched", "---", "## Notes", "Prose is not proof. ⟦cite kind=record id=primary⟧", "")).encode()
        (legacy / "notes.md").write_bytes(doc)
        (legacy / "bad.json").write_bytes(b'{"id":"x","id":"y"}')
        dry = self.engine.migrate(legacy)
        self.assertEqual(dry["state"], "dry_run")
        counts = object_value(dry["counts"])
        self.assertGreater(counts["exact"], 0)
        self.assertEqual(counts["uniquely_resolvable"], 1)
        self.assertEqual(counts["malformed"], 1)
        receipt = self.engine.migrate(legacy, apply=True)
        self.assertEqual(self.engine.migrate(legacy, apply=True), receipt)
        self.assertIsNone(self.engine.git.current())
        identity = PlanId(str(receipt["migration"]))
        staged = load(self.engine.root / "migration-candidates" / (identity.val + ".json"))
        self.assertEqual(staged["claims"], [])
        restored = self.root / "restored-legacy"
        self.engine.restore_migration(identity, restored)
        for path in legacy.iterdir():
            self.assertEqual((restored / path.name).read_bytes(), path.read_bytes())
        self.engine.migrate(legacy, rollback=identity)
        self.assertFalse((self.engine.root / "migration-candidates" / (identity.val + ".json")).exists())

    def test_signed_context_cannot_weaken_policy_under_same_identity(self) -> None:
        plan = self.engine.propose(self.candidate(CaptureKind.DOCUMENT), "review", 5)
        approval = self.engine.sign(plan.id, self.key_file, AuthorityKeyId("reviewer-key"))
        changed = plan.wire()
        context = object_value(changed["context"])
        policy = object_value(context["policy"])
        policy["require_fresh"] = False
        context["policy"] = policy
        changed["context"] = context
        save(self.engine.root / "plans" / (plan.id.val + ".json"), changed)
        with self.assertRaises(KctxError):
            self.engine.admit(plan.id, approval)
        self.assertIsNone(self.engine.git.current())

    def test_named_receipt_checker_rejects_forged_result_and_dependencies(self) -> None:
        candidate = self.candidate(CaptureKind.DOCUMENT)
        context = dec_context(candidate["context"])
        context = replace(context, policy=replace(context.policy, require_validation=True))
        candidate["context"] = object_value(enc_context(context))
        kb = dec_kb(candidate["kb"])
        execution = replace(context, snapshot=kb.snapshot)
        ref = dec_ref(candidate["claim"])
        witness = dec_witness(candidate["witness"])
        checked = accepted(kb, execution, ref)[0][1]
        receipt = Receipt(ReceiptId("actual-check"), ref, execution, witness, checked.dependencies, ReceiptResult.PASS, 10)
        raw_kb = object_value(candidate["kb"])
        raw_kb["receipts"] = [object_value(enc_receipt(receipt))]
        candidate["kb"] = raw_kb
        self.engine.propose(candidate, "review", 5)
        for forged in (replace(receipt, dependencies=()), replace(receipt, result=ReceiptResult.FAIL)):
            raw_kb["receipts"] = [object_value(enc_receipt(forged))]
            with self.assertRaises(KctxError):
                self.engine.propose(candidate, "review", 5)

    def test_source_revision_selection_does_not_reuse_old_current_support(self) -> None:
        candidate = self.candidate(CaptureKind.DOCUMENT)
        first = self.engine.propose(candidate, "review", 5)
        old_release = ReleaseId(str(self.engine.admit(first.id, self.engine.sign(first.id, self.key_file, AuthorityKeyId("reviewer-key")))["release"]))
        capture = self.engine.capture(CaptureKind.DOCUMENT, SourceId("docs/design.md"), SourceRevision("immutable-revision-18"), b"Changed exact source bytes", 6)
        kb = object_value(enc_kb(first.semantic.candidate))
        statement: JsonObject = {"formula": {"tag": "atom", "atom": {"subject": "service", "predicate": "new-review", "args": []}}, "scope": object_value(candidate["context"])["target"], "polarity": "positive"}
        ref: JsonObject = {"id": "new-review", "revision": "r2"}
        witness: JsonObject = {"tag": "attest", "attestation": "attestation-2"}
        for collection, row in (
            ("observations", {"id": "observation-2", "source": capture.source.val, "revision": capture.revision.val, "content": capture.content.val, "observed_at": 6, "outcome": "ok"}),
            ("claims", {"id": "new-review", "revision": "r2", "statement": statement}),
            ("attestations", {"id": "attestation-2", "claim": ref, "observation": "observation-2", "statement": statement, "authority": "reviewer-key"}),
            ("derivations", {"id": "derivation-2", "claim": ref, "witness": witness}),
        ):
            values = kb[collection]
            if isinstance(values, list):
                values.append(object_value(row))
        kb["snapshot"] = "generation-2"
        context = replace(first.context, snapshot=first.semantic.candidate.snapshot, now=7, sources=(SourceSelection(capture.source, capture.revision, capture.content_identity),))
        capture_ids = candidate["capture_ids"]
        if not isinstance(capture_ids, list):
            self.fail("capture fixture must be an array")
        changed: JsonObject = {"kb": kb, "capture_ids": [*capture_ids, capture.id.val], "context": object_value(enc_context(context)), "claim": ref, "witness": witness, "authority_key": "reviewer-key"}
        plan = self.engine.propose(changed, "review", 7)
        self.engine.admit(plan.id, self.engine.sign(plan.id, self.key_file, AuthorityKeyId("reviewer-key")))
        current = replace(context, snapshot=plan.semantic.candidate.snapshot)
        old_ref = dec_ref(candidate["claim"])
        self.assertIn(b'"support":"none"', canonical(self.engine.context((old_ref,), current)))
        with self.assertRaises(KctxError):
            self.engine.context((old_ref,), replace(current, sources=first.context.sources))
        historical = self.engine.context((old_ref,), replace(first.context, snapshot=first.semantic.candidate.snapshot), release=old_release)
        self.assertIn(b'"support":"positive"', canonical(historical))
        kb["snapshot"] = first.semantic.candidate.snapshot.val
        changed["context"] = object_value(enc_context(current))
        with self.assertRaises(KctxError):
            self.engine.propose(changed, "review", 7)

    def test_asset_context_filters_exact_identities_and_pins_continuation(self) -> None:
        candidate = self.candidate(CaptureKind.DOCUMENT)
        kb = object_value(candidate["kb"])
        claims = kb["claims"]
        assert isinstance(claims, list)
        attestations, derivations = kb["attestations"], kb["derivations"]
        assert isinstance(attestations, list) and isinstance(derivations, list)
        for identity, subject, args in (
            ("mentioned", "consumer", ["service"]),
            ("not-this-asset", "service-extra", []),
        ):
            statement = {
                "formula": {"tag": "atom", "atom": {
                    "subject": subject, "predicate": "reviewed", "args": args,
                }},
                "scope": {"project": "test-kb", "selector": ""},
                "polarity": "positive",
            }
            ref = {"id": identity, "revision": "r1"}
            claims.append({**ref, "statement": statement})
            attestations.append({
                "id": f"attest-{identity}", "claim": ref,
                "observation": "observation-1", "statement": statement,
                "authority": "reviewer-key",
            })
            derivations.append({
                "id": f"derive-{identity}", "claim": ref,
                "witness": {"tag": "attest", "attestation": f"attest-{identity}"},
            })
        candidate["kb"] = kb
        plan = self.engine.propose(candidate, "review", 5)
        release = self.engine.admit(
            plan.id, self.engine.sign(plan.id, self.key_file, AuthorityKeyId("reviewer-key"))
        )["release"]
        first = self.engine.context_for_assets((AssetId("service"),), limit=1)
        self.assertEqual(first["release"], release)
        self.assertEqual(first["context"]["now"], 5)
        self.assertEqual(first["records"][0]["claim"]["id"], "reviewed")
        self.assertEqual(first["records"][0]["assessment"]["support"], "positive")
        self.assertEqual(first["records"][0]["matched_assets"], ["service"])
        self.assertEqual(first["omitted"], 1)
        second = self.engine.context_for_assets(
            (AssetId("service"),), continuation=first["continuation"]
        )
        self.assertEqual(second["release"], release)
        self.assertEqual([row["claim"]["id"] for row in second["records"]], ["mentioned"])
        self.assertEqual(second["records"][0]["assessment"]["support"], "positive")
        self.assertIsNone(second["continuation"])
        with self.assertRaises(KctxError):
            self.engine.context_for_assets(
                (AssetId("service-extra"),), continuation=first["continuation"]
            )

    def test_policy_edit_does_not_replace_bootstrap_trust(self) -> None:
        (self.repo / ".kctx" / "knowledge-policy.json").write_bytes(b"{}")
        with self.assertRaises(KctxError):
            self.engine.capture(CaptureKind.DOCUMENT, SourceId("doc"), SourceRevision("r1"), b"bytes", 1)


if __name__ == "__main__":
    unittest.main()
