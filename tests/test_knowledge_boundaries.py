"""Consumer regressions for untrusted policy, query, journal and backup inputs."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

import test_knowledge as fixtures
from kctx.adapters.files.knowledge import digest, canonical, load, save
from kctx.cli.context import CliState
from kctx.cli import knowledge as knowledge_cli
from kctx.config import Config
from kctx.domain.ids import AuthorityKeyId, DoltCommitId, OperationId, PlanId, PolicyDigest, ReleaseId, SourceId, SourceRevision
from kctx.domain.json import JsonObject, object_value, text
from kctx.errors import KctxError
from kctx.semantics.model import TTL_NO_EXPIRY
from kctx.semantics.wire import enc_context, enc_kb, enc_ref, enc_witness
from kctx.services.knowledge import KnowledgeEngine
from kctx.services.knowledge_models import AdmissionPlan, Approval, CaptureKind


class SimulatedStop(RuntimeError):
    pass


class KnowledgeBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixtures.KnowledgeAdmissionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.engine = self.fixture.engine
        self.key = AuthorityKeyId("reviewer-key")

    def plan(self, snapshot: str = "generation-1") -> tuple[AdmissionPlan, Approval]:
        candidate = self.fixture.candidate(CaptureKind.DOCUMENT)
        kb = object_value(candidate["kb"])
        kb["snapshot"] = snapshot
        candidate["kb"] = kb
        plan = self.engine.propose(candidate, "review", 5)
        return plan, self.engine.sign(plan.id, self.fixture.key_file, self.key)

    def published(self) -> tuple[AdmissionPlan, Approval, ReleaseId]:
        plan, approval = self.plan()
        reply = self.engine.admit(plan.id, approval)
        return plan, approval, ReleaseId(text(reply["release"], "release"))

    def next_plan(self, previous: AdmissionPlan, snapshot: str) -> tuple[AdmissionPlan, Approval]:
        kb = object_value(enc_kb(previous.semantic.candidate))
        kb["snapshot"] = snapshot
        context = replace(previous.context, snapshot=previous.semantic.candidate.snapshot, now=6)
        candidate: JsonObject = {"kb": kb, "capture_ids": [identity.val for identity in previous.captures], "context": object_value(enc_context(context)), "claim": object_value(enc_ref(previous.semantic.claim)), "witness": object_value(enc_witness(previous.semantic.witness)), "authority_key": self.key.val}
        plan = self.engine.propose(candidate, "review", 6)
        return plan, self.engine.sign(plan.id, self.fixture.key_file, self.key)

    def interrupt(self, plan: AdmissionPlan, approval: Approval, phase: str) -> JsonObject:
        def stop(current: str) -> None:
            if current == phase:
                raise SimulatedStop(current)
        self.engine.fault = stop
        try:
            with self.assertRaises(SimulatedStop):
                self.engine.admit(plan.id, approval)
        finally:
            self.engine.fault = None
        return load(self.engine.root / "journal" / (plan.id.val + ".json"))

    def test_boundary_strict_nested_policy_codec(self) -> None:
        original = load(self.fixture.repo / ".kctx" / "knowledge-policy.json")
        original_key = object_value(object_value(original["trusted_keys"])[self.key.val])
        variants: list[JsonObject] = [
            {**original, "schema_version": 2.0},
            {**original, "trusted_keys": {self.key.val: {**original_key, "public_key": "zz"}}},
            {**original, "trusted_keys": {self.key.val: {**original_key, "target_uses": ["review", 17]}}},
            {**original, "trusted_keys": {self.key.val: original_key, "unused": {"public_key": original_key["public_key"]}}},
            {**original, "trusted_keys": {self.key.val: original_key, "unused": {**original_key, "revoked": True}}},
        ]
        for policy in variants:
            with self.subTest(policy=policy):
                save(self.fixture.repo / ".kctx" / "knowledge-policy.json", policy)
                self.engine.bootstrap = PolicyDigest(digest(canonical(policy)))
                with self.assertRaises(KctxError):
                    self.engine.capture(CaptureKind.DOCUMENT, SourceId("doc"), SourceRevision("r1"), b"bytes", 1)

    def test_boundary_approval_and_semantic_decode_errors_are_domain_errors(self) -> None:
        plan, approval = self.plan()
        for record in ({**approval.wire(), "signature": "zz"}, {**approval.wire(), "signature": "ab" * 63}, {**approval.wire(), "accepted": True}, {**approval.wire(), "schema_version": 2.0}):
            with self.subTest(record=record), self.assertRaises(KctxError):
                Approval.decode(record)
        candidate = self.fixture.candidate(CaptureKind.DOCUMENT)
        candidate["context"] = {"unknown": True}
        path = self.fixture.root / "bad-candidate.json"
        save(path, candidate)
        config = Config(knowledge_dir=self.engine.store.path, knowledge_policy_digest=plan.policy.val)
        with patch.object(Config, "load", return_value=config), patch("kctx.cli.context.find_root", return_value=self.fixture.repo), self.assertRaises(KctxError):
            knowledge_cli.knowledge.main(
                ["propose", "--candidate", str(path), "--target-use", "review", "--now", "5"],
                obj=CliState(as_json=True), standalone_mode=False,
            )

    def test_boundary_unsigned_query_cannot_weaken_approved_context(self) -> None:
        plan, _, _ = self.published()
        context = replace(plan.context, snapshot=plan.semantic.candidate.snapshot)
        variants = (
            replace(context, intended_use="production-deploy"),
            replace(context, policy=replace(context.policy, require_fresh=False)),
            replace(context, policy=replace(context.policy, require_validation=True)),
            replace(context, policy=replace(context.policy, ttl=TTL_NO_EXPIRY)),
            replace(context, target=replace(context.target, project=type(context.target.project)("other-project"))),
            replace(context, now=context.now - 1),
            replace(context, checker=type(context.checker)("other-checker")),
        )
        for changed in variants:
            with self.subTest(context=changed), self.assertRaises(KctxError):
                self.engine.context((plan.semantic.claim,), changed)
        narrower_query = replace(context, target=replace(context.target, selector="specific-endpoint"), now=context.now + 1)
        self.assertIn(b'"support":"positive"', canonical(self.engine.context((plan.semantic.claim,), narrower_query)))

    def test_boundary_foreign_signed_journal_release_is_not_authority(self) -> None:
        first, approval = self.plan("candidate-a")
        journal = self.interrupt(first, approval, "candidate")
        foreign, foreign_approval = self.plan("candidate-b")
        foreign_journal = self.interrupt(foreign, foreign_approval, "manifest")
        journal["release"] = foreign_journal["release"]
        journal["phase"] = "manifest"
        save(self.engine.root / "journal" / (first.id.val + ".json"), journal)
        with self.assertRaises(KctxError):
            self.engine.admit(first.id, approval)
        self.assertIsNone(self.engine.git.current())

    def test_boundary_current_release_cannot_fake_other_operation_replay(self) -> None:
        first, _, release = self.published()
        second, approval = self.next_plan(first, "generation-2")
        journal = self.interrupt(second, approval, "candidate")
        journal["release"] = release.val
        journal["phase"] = "manifest"
        save(self.engine.root / "journal" / (second.id.val + ".json"), journal)
        with self.assertRaises(KctxError):
            self.engine.admit(second.id, approval)
        self.assertEqual(self.engine.git.current(), release.val)

    def test_boundary_native_admission_rows_are_validated(self) -> None:
        plan, approval = self.plan()
        journal = self.interrupt(plan, approval, "candidate")
        self.engine.store.execute("UPDATE admissions SET actor = 'foreign-signer'")
        self.engine.store.run("add", ".")
        self.engine.store.run("commit", "--author", "fixture <fixture@localhost>", "-m", "Corrupt admission metadata only")
        changed = DoltCommitId(text(self.engine.store.sql("SELECT DOLT_HASHOF('HEAD') AS h")[0]["h"], "hash"))
        journal["dolt_commit"] = changed.val
        save(self.engine.root / "journal" / (plan.id.val + ".json"), journal)
        with self.assertRaises(KctxError):
            self.engine.admit(plan.id, approval)
        self.assertIsNone(self.engine.git.current())

    def test_boundary_configured_dolt_binary_is_not_ignored(self) -> None:
        missing = self.fixture.root / "missing-configured-dolt"
        with patch.object(Config, "load", return_value=Config(dolt_bin=missing)), self.assertRaises(KctxError):
            KnowledgeEngine(self.fixture.repo, self.fixture.root / "other-store", self.engine.bootstrap)
        with patch.object(Config, "load", return_value=Config(dolt_bin=Path(self.engine.store.binary))):
            selected = KnowledgeEngine(self.fixture.repo, self.fixture.root / "configured-store", self.engine.bootstrap)
        self.assertEqual(selected.store.binary, self.engine.store.binary)

    def test_boundary_saved_selection_cannot_bypass_completed_target_requirement(self) -> None:
        first, _, release = self.published()
        pending, pending_approval = self.next_plan(first, "unpublished-view")
        journal = self.interrupt(pending, pending_approval, "manifest")
        target = ReleaseId(text(journal["release"], "release"))
        context = replace(first.context, snapshot=first.semantic.candidate.snapshot, now=7)
        with self.assertRaises(KctxError):
            self.engine.rollback(target, context, self.key)
        selection = self.engine.rollback(release, context, self.key)
        changed = replace(selection, retained=target, semantic=replace(selection.semantic, target_snapshot=pending.semantic.candidate.snapshot))
        material = changed.wire()
        del material["id"]
        semantic = object_value(material["plan"])
        del semantic["id"]
        material["plan"] = semantic
        identity = PlanId(digest(canonical(material)))
        changed = replace(changed, id=identity, semantic=replace(changed.semantic, id=OperationId(identity.val)))
        save(self.engine.root / "plans" / (identity.val + ".json"), changed.wire())
        approval = self.engine.sign(identity, self.fixture.key_file, self.key)
        with self.assertRaises(KctxError):
            self.engine.admit(identity, approval)
        self.assertEqual(self.engine.git.current(), release.val)

    def test_boundary_journal_identity_cannot_redirect_durable_writes(self) -> None:
        plan, approval = self.plan()
        journal = self.interrupt(plan, approval, "prepared")
        journal["id"] = "../outside"
        save(self.engine.root / "journal" / (plan.id.val + ".json"), journal)
        with self.assertRaises(KctxError):
            self.engine.admit(plan.id, approval)
        self.assertFalse((self.engine.root / "outside.json").exists())
        self.assertIsNone(self.engine.git.current())

    def test_boundary_corrupt_backup_cannot_select_unpublished_manifest(self) -> None:
        first, _, release = self.published()
        pending, approval = self.next_plan(first, "generation-2")
        journal = self.interrupt(pending, approval, "manifest")
        pending_release = text(journal["release"], "release")
        self.assertEqual(self.engine.git.ref_revision("refs/kctx/prepared/" + pending.id.val), pending_release)
        backup = self.fixture.root / "backup"
        self.engine.backup(backup)
        metadata = load(backup / "backup.json")
        metadata["release"] = pending_release
        save(backup / "backup.json", metadata)
        restored_repo = self.fixture.root / "restored-authored"
        restored_repo.mkdir()
        self.engine.git.run("init", "-q", str(restored_repo))
        restored = KnowledgeEngine(restored_repo, self.fixture.root / "restored-dolt", self.engine.bootstrap)
        with self.assertRaises(KctxError):
            restored.restore(backup)
        self.assertIsNone(restored.git.current())
        self.assertEqual(self.engine.git.current(), release.val)

    def test_boundary_backup_preserves_pending_manifest_for_verified_recovery(self) -> None:
        first, _, release = self.published()
        pending, approval = self.next_plan(first, "generation-2")
        journal = self.interrupt(pending, approval, "manifest")
        pending_release = text(journal["release"], "release")
        backup = self.fixture.root / "valid-backup"
        self.engine.backup(backup)
        restored_repo = self.fixture.root / "restored-valid-authored"
        restored_repo.mkdir()
        self.engine.git.run("init", "-q", str(restored_repo))
        restored = KnowledgeEngine(restored_repo, self.fixture.root / "restored-valid-dolt", self.engine.bootstrap)
        restored.restore(backup)
        self.assertEqual(restored.git.current(), release.val)
        self.assertEqual(restored.git.ref_revision("refs/kctx/prepared/" + pending.id.val), pending_release)
        results = canonical(restored.recover())
        self.assertNotIn(b'"outcome":"conflict"', results)
        self.assertEqual(restored.git.current(), pending_release)
        self.assertEqual(restored.admit(pending.id, approval)["outcome"], "already_applied")

    def test_boundary_journal_cannot_substitute_unsigned_toolchain_provenance(self) -> None:
        plan, approval = self.plan()
        journal = self.interrupt(plan, approval, "manifest")
        original = ReleaseId(text(journal["release"], "release"))
        manifest = self.engine.git.manifest(original.val)
        raw_artifacts = manifest["artifacts"]
        if not isinstance(raw_artifacts, list):
            self.fail("release artifact fixture must be an array")
        artifacts = {text(identity, "artifact"): self.engine.git.artifact(original.val, text(identity, "artifact")) for identity in raw_artifacts}
        del artifacts[text(manifest["toolchain_artifact"], "toolchain_artifact")]
        forged = canonical({"forged_toolchain": True})
        artifacts[digest(forged)] = forged
        manifest["toolchain_artifact"] = digest(forged)
        manifest["artifacts"] = [identity for identity in sorted(artifacts)]
        substituted = self.engine.git.prepare(manifest, None, artifacts)
        journal["release"] = substituted
        save(self.engine.root / "journal" / (plan.id.val + ".json"), journal)
        with self.assertRaises(KctxError):
            self.engine.admit(plan.id, approval)
        self.assertIsNone(self.engine.git.current())

    def test_boundary_missing_semantic_constructor_tags_are_domain_errors(self) -> None:
        policy = load(self.fixture.repo / ".kctx" / "knowledge-policy.json")
        config = Config(knowledge_dir=self.engine.store.path, knowledge_policy_digest=digest(canonical(policy)))
        for kind in ("witness", "formula", "dependency"):
            candidate = self.fixture.candidate(CaptureKind.DOCUMENT)
            kb = object_value(candidate["kb"])
            if kind == "witness":
                candidate["witness"] = {}
            elif kind == "formula":
                claims = kb["claims"]
                if not isinstance(claims, list):
                    self.fail("claim fixture must be an array")
                claim = object_value(claims[0])
                statement = object_value(claim["statement"])
                statement["formula"] = {}
                claim["statement"] = statement
                claims[0] = claim
            else:
                context = object_value(candidate["context"])
                context["snapshot"] = kb["snapshot"]
                kb["receipts"] = [{"id": "bad-dependency", "claim": candidate["claim"], "context": context, "witness": candidate["witness"], "dependencies": [{}], "result": "pass", "expires_at": 10}]
            candidate["kb"] = kb
            path = self.fixture.root / ("missing-tag-" + kind + ".json")
            save(path, candidate)
            with self.subTest(kind=kind), patch.object(Config, "load", return_value=config), patch("kctx.cli.context.find_root", return_value=self.fixture.repo), self.assertRaises(KctxError):
                knowledge_cli.knowledge.main(
                    ["propose", "--candidate", str(path), "--target-use", "review", "--now", "5"],
                    obj=CliState(as_json=True), standalone_mode=False,
                )
        self.assertIsNone(self.engine.git.current())

    def test_boundary_retained_signed_plan_requires_canonical_inner_identity(self) -> None:
        plan, approval = self.plan()
        journal = self.interrupt(plan, approval, "manifest")
        original = ReleaseId(text(journal["release"], "release"))
        altered = replace(plan, semantic=replace(plan.semantic, id=OperationId("caller-chosen")))
        signature = self.fixture.key.sign(b"kctx-operation-v2\x00" + canonical(altered.wire()))
        signed = Approval(plan.id, self.key, signature)
        self.engine.store.execute("UPDATE admissions SET signature = '" + signature.hex() + "'")
        self.engine.store.run("add", ".")
        self.engine.store.run("commit", "--author", "fixture <fixture@localhost>", "-m", "Retain externally signed mismatched identity")
        commit = text(self.engine.store.sql("SELECT DOLT_HASHOF('HEAD') AS h")[0]["h"], "commit")
        manifest = self.engine.git.manifest(original.val)
        raw_artifacts = manifest["artifacts"]
        if not isinstance(raw_artifacts, list):
            self.fail("release artifact fixture must be an array")
        artifacts = {text(identity, "artifact"): self.engine.git.artifact(original.val, text(identity, "artifact")) for identity in raw_artifacts}
        del artifacts[text(manifest["plan_artifact"], "plan_artifact")]
        del artifacts[text(manifest["approval_artifact"], "approval_artifact")]
        plan_bytes = canonical(altered.wire())
        approval_bytes = canonical(signed.wire())
        artifacts[digest(plan_bytes)] = plan_bytes
        artifacts[digest(approval_bytes)] = approval_bytes
        manifest["plan_artifact"] = digest(plan_bytes)
        manifest["approval_artifact"] = digest(approval_bytes)
        manifest["dolt_commit"] = commit
        manifest["artifacts"] = [identity for identity in sorted(artifacts)]
        forged = self.engine.git.prepare(manifest, None, artifacts)
        self.engine.git.publish(forged, None)
        context = replace(plan.context, snapshot=plan.semantic.candidate.snapshot)
        with self.assertRaises(KctxError):
            self.engine.context((plan.semantic.claim,), context)


if __name__ == "__main__":
    unittest.main()
