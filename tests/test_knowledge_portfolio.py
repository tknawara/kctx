"""Signed portfolio boundaries exercised through real native publication."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import unittest

import test_knowledge as fixtures
from kctx.adapters.files.knowledge import canonical, digest, load, save
from kctx.domain.ids import (
    ActorId, AssetId, AuthorityKeyId, ContentDigest, ContextId, DoltCommitId, OperationId,
    PlanId, PolicyDigest, ReceiptId, ReleaseId, SnapshotId, SourceCaptureId, SourceId, SourceRevision,
)
from kctx.errors import KctxError
from kctx.semantics.checker import accepted
from kctx.semantics.model import Authority, Plan, Receipt, ReceiptResult
from kctx.semantics.wire import dec_context, dec_kb, dec_ref, dec_witness, enc_kb, enc_receipt, enc_ref, enc_source_selection
from kctx.semantics.workflow_wire import enc_named_context
from kctx.services.knowledge import LEGACY_TOOLCHAIN
from kctx.services.knowledge_models import Approval, CaptureKind, LegacyAdmissionPlan


class KnowledgePortfolioTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.KnowledgeAdmissionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.engine = self.fixture.engine
        self.key = AuthorityKeyId("reviewer-key")

    def publish(self, candidate, now=5, target_use="review"):
        plan = self.engine.propose(candidate, target_use, now)
        approval = self.engine.sign(plan.id, self.fixture.key_file, self.key)
        release = ReleaseId(self.engine.admit(plan.id, approval)["release"])
        return plan, release

    def successor(self, plan, snapshot, now):
        kb = enc_kb(plan.semantic.candidate)
        kb["snapshot"] = snapshot
        contexts = [enc_named_context(replace(named, context=replace(named.context, snapshot=SnapshotId(snapshot), now=now))) for named in plan.semantic.contexts]
        return {"schema_version": 3, "expected_snapshot": plan.semantic.candidate.snapshot.val,
                "kb": kb, "capture_ids": [item.val for item in plan.captures],
                "contexts": contexts, "assignments": [], "retired_contexts": [],
                "authority_key": self.key.val}

    def add_scoped_claim(self, candidate, identity, project, selector):
        kb = candidate["kb"]
        context = deepcopy(candidate["contexts"][0]["context"])
        context["target"] = {"project": project, "selector": selector}
        candidate["contexts"].append({"id": identity, "context": context})
        ref = {"id": identity, "revision": "r1"}
        statement = {"formula": {"tag": "atom", "atom": {"subject": "service", "predicate": identity, "args": []}}, "scope": context["target"], "polarity": "positive"}
        witness = {"tag": "attest", "attestation": "attest-" + identity}
        kb["claims"].append({**ref, "statement": statement})
        kb["attestations"].append({"id": "attest-" + identity, "claim": ref, "observation": "observation-1", "statement": statement, "authority": self.key.val})
        kb["derivations"].append({"id": "derive-" + identity, "claim": ref, "witness": witness})
        candidate["assignments"].append({"claim": ref, "context": identity, "witness": witness})

    def test_scopes_projects_inherited_context_and_explicit_retirement(self):
        initial = self.fixture.candidate(CaptureKind.DOCUMENT)
        first, first_release = self.publish(initial)
        candidate = self.successor(first, "portfolio-two", 6)
        self.add_scoped_claim(candidate, "endpoint", "test-kb", "endpoint")
        self.add_scoped_claim(candidate, "other-project", "other-project", "endpoint")
        second, second_release = self.publish(candidate, 6)
        discovered = self.engine.contexts()
        self.assertEqual(discovered["release"], second_release.val)
        self.assertEqual([entry["id"] for entry in discovered["contexts"]], ["review", "endpoint", "other-project"])
        expected_claims = {
            "review": ["reviewed"],
            "endpoint": ["reviewed", "endpoint"],
            "other-project": ["other-project"],
        }
        for named in second.semantic.contexts:
            response = self.engine.context((), named.context, context_id=named.id)
            self.assertEqual(
                [(row["context_id"], row["claim"]["id"]) for row in response["records"]],
                [(named.id.val, identity) for identity in expected_claims[named.id.val]],
            )
        inherited = self.engine.context((first.semantic.assignments[0].claim,), second.semantic.contexts[0].context, context_id=ContextId("review"))
        self.assertTrue(inherited["records"][0]["assessment"]["usable"])
        with self.assertRaises(KctxError):
            self.engine.context((), second.semantic.contexts[2].context, context_id=ContextId("review"))
        retired = self.successor(second, "retired-context", 7)
        retired["contexts"] = retired["contexts"][:2]
        with self.assertRaises(KctxError):
            self.engine.propose(retired, "review", 7)
        retired["retired_contexts"] = ["other-project"]
        self.publish(retired, 7)
        with self.assertRaises(KctxError):
            self.engine.context((), second.semantic.contexts[2].context, context_id=ContextId("other-project"))
        self.assertEqual(self.engine.contexts(first_release)["contexts"][0]["id"], "review")

    def test_unsupported_second_assignment_and_borrowed_context_are_rejected(self):
        candidate = self.fixture.candidate(CaptureKind.DOCUMENT)
        self.add_scoped_claim(candidate, "second", "another-project", "endpoint")
        unsupported = deepcopy(candidate)
        unsupported["kb"]["attestations"] = unsupported["kb"]["attestations"][:1]
        unsupported["kb"]["derivations"] = unsupported["kb"]["derivations"][:1]
        unsupported["assignments"][1]["witness"] = deepcopy(unsupported["assignments"][0]["witness"])
        with self.assertRaises(KctxError):
            self.engine.propose(unsupported, "review", 5)
        borrowed = deepcopy(candidate)
        borrowed["assignments"][1]["context"] = "review"
        with self.assertRaises(KctxError):
            self.engine.propose(borrowed, "review", 5)
        borrowed_policy = deepcopy(candidate)
        borrowed_policy["contexts"][1]["context"]["policy"]["authorized_actors"] = ["foreign"]
        with self.assertRaises(KctxError):
            self.engine.propose(borrowed_policy, "review", 5)
        self.assertIsNone(self.engine.git.current())

    def test_asset_pairs_do_not_pool_sources_and_continuation_survives_head_change(self):
        candidate = self.fixture.candidate(CaptureKind.DOCUMENT)
        capture = self.engine.capture(CaptureKind.DOCUMENT, SourceId("docs/design.md"), SourceRevision("different-revision"), b"other exact bytes", 2)
        candidate["capture_ids"].append(capture.id.val)
        alternate = deepcopy(candidate["contexts"][0]["context"])
        alternate["sources"] = [{"source": capture.source.val, "revision": capture.revision.val, "content": capture.content.val}]
        candidate["contexts"].append({"id": "other-source", "context": alternate})
        first, release = self.publish(candidate)
        page = self.engine.context_for_assets((AssetId("service"),), limit=1)
        self.assertEqual(page["records"][0]["context_id"], "review")
        self.assertEqual(page["records"][0]["assessment"]["support"], "positive")
        later = self.successor(first, "later-pair-view", 6)
        self.publish(later, 6)
        next_page = self.engine.context_for_assets((AssetId("service"),), limit=1, continuation=page["continuation"])
        self.assertEqual(next_page["release"], release.val)
        self.assertEqual(next_page["records"][0]["context_id"], "other-source")
        self.assertEqual(next_page["records"][0]["assessment"]["support"], "none")
        self.assertIsNone(next_page["continuation"])
        with self.assertRaises(KctxError):
            self.engine.context((), first.semantic.contexts[1].context, context_id=ContextId("other-source"), continuation=page["continuation"])

    def test_receipt_cannot_be_borrowed_across_changed_full_context(self):
        candidate = self.fixture.candidate(CaptureKind.DOCUMENT)
        raw = candidate["contexts"][0]["context"]
        raw["policy"]["require_validation"] = True
        context = dec_context(raw)
        kb = dec_kb(candidate["kb"])
        assignment = candidate["assignments"][0]
        ref, witness = dec_ref(assignment["claim"]), dec_witness(assignment["witness"])
        checked = accepted(kb, context, ref)[0][1]
        receipt = Receipt(ReceiptId("exact-context"), ref, context, witness, checked.dependencies, ReceiptResult.PASS, 20)
        candidate["kb"]["receipts"] = [enc_receipt(receipt)]
        self.engine.propose(candidate, "review", 5)
        changed = deepcopy(candidate)
        changed["contexts"][0]["context"]["target"]["selector"] = "narrower"
        with self.assertRaises(KctxError):
            self.engine.propose(changed, "review", 5)
        changed["contexts"].append({"id": "original", "context": raw})
        with self.assertRaises(KctxError):
            self.engine.propose(changed, "review", 5)

    def test_different_uses_require_each_permission_not_identical_uses(self):
        policy = load(self.fixture.repo / ".kctx" / "knowledge-policy.json")
        policy["trusted_keys"][self.key.val]["target_uses"].append("audit")
        save(self.fixture.repo / ".kctx" / "knowledge-policy.json", policy)
        self.engine.bootstrap = PolicyDigest(digest(canonical(policy)))
        candidate = self.fixture.candidate(CaptureKind.DOCUMENT)
        alternate = deepcopy(candidate["contexts"][0]["context"])
        alternate["intended_use"] = "audit"
        candidate["contexts"].append({"id": "audit", "context": alternate})
        plan, _ = self.publish(candidate)
        self.assertTrue(self.engine.context(
            (), plan.semantic.contexts[1].context, context_id=ContextId("audit")
        )["records"][0]["assessment"]["usable"])
        denied = self.successor(plan, "forbidden-use", 6)
        denied["contexts"][1]["context"]["intended_use"] = "deploy"
        with self.assertRaises(KctxError):
            self.engine.propose(denied, "review", 6)

    def test_rollback_of_selection_uses_retained_active_refs_not_stored_claims(self):
        first, first_release = self.publish(self.fixture.candidate(CaptureKind.DOCUMENT))
        candidate = self.successor(first, "with-second-claim", 6)
        self.add_scoped_claim(candidate, "second", "test-kb", "")
        second, second_release = self.publish(candidate, 6)
        selection = self.engine.rollback(first_release, tuple(replace(named, context=replace(named.context, now=7)) for named in second.semantic.contexts), self.key, target_use="review")
        selected_release = ReleaseId(self.engine.admit(selection.id, self.engine.sign(selection.id, self.fixture.key_file, self.key))["release"])
        forward = self.engine.rollback(second_release, tuple(replace(named, context=replace(named.context, now=8)) for named in selection.semantic.contexts), self.key, target_use="review")
        self.engine.admit(forward.id, self.engine.sign(forward.id, self.fixture.key_file, self.key))
        exact = self.engine.rollback(selected_release, tuple(replace(named, context=replace(named.context, now=9)) for named in forward.semantic.contexts), self.key, target_use="review")
        self.assertEqual(exact.semantic.selected, (first.semantic.assignments[0].claim,))
        self.engine.admit(exact.id, self.engine.sign(exact.id, self.fixture.key_file, self.key))
        self.assertEqual([row["claim"]["id"] for row in self.engine.context((), exact.semantic.contexts[0].context, context_id=ContextId("review"))["records"]], ["reviewed"])

    def legacy_release(self, predecessor=None):
        """Construct actual original signed bytes and native rows, not a promoted v3 plan."""
        candidate = self.fixture.candidate(CaptureKind.DOCUMENT)
        kb = dec_kb(candidate["kb"])
        base_release = None if predecessor is None else predecessor[1]
        if predecessor is not None:
            kb = replace(kb, snapshot=SnapshotId("legacy-downgrade"))
        context = replace(
            dec_context(candidate["contexts"][0]["context"]),
            snapshot=SnapshotId("bootstrap:test-kb") if predecessor is None else predecessor[0].semantic.candidate.snapshot,
        )
        assignment = candidate["assignments"][0]
        ref = dec_ref(assignment["claim"])
        authority = Authority(actor=ActorId(self.key.val), target=ref, intended_use="review", policy=context.policy.id,
                              statement=kb.claims[0].statement, approved=kb, approvals=kb.claims if predecessor is None else (), context=context)
        semantic = Plan(OperationId("pending"), context.snapshot, kb, authority, ref, dec_witness(assignment["witness"]))
        capture = self.engine._capture(SourceCaptureId(candidate["capture_ids"][0]), None)
        policy_id, policy = self.engine._policy(None)
        toolchain = self.engine._retain(canonical({"historical_toolchain": "original-v2"}))
        plan = LegacyAdmissionPlan(PlanId("0" * 64), base_release, policy_id, (capture.id,), context, semantic, toolchain)
        identity = self.engine._identity(plan)
        plan = replace(plan, id=identity, semantic=replace(semantic, id=OperationId(identity.val)))
        approval = Approval(identity, self.key, self.fixture.key.sign(b"kctx-operation-v2\x00" + canonical(plan.wire())), schema_version=2)
        base_commit = None if base_release is None else DoltCommitId(self.engine.git.manifest(base_release.val)["dolt_commit"])
        commit = self.engine.store.commit_candidate(identity, base_commit, enc_kb(kb), [capture.wire()], self.engine._admission_row(plan, approval), "test-kb")
        plan_bytes, approval_bytes = canonical(plan.wire()), canonical(approval.wire())
        artifacts = {capture.content.val: self.engine._artifact(capture.content), policy_id.val: self.engine._artifact(ContentDigest(policy_id.val)), toolchain.val: self.engine._artifact(toolchain), digest(plan_bytes): plan_bytes, digest(approval_bytes): approval_bytes}
        manifest = {"schema_version": 2, "semantic_version": "2.0.0", "snapshot": kb.snapshot.val, "kb_id": policy["kb_id"], "operation": identity.val, "predecessor": base_release.val if base_release else None, "dolt_commit": commit.val, "policy": policy_id.val, "toolchain": LEGACY_TOOLCHAIN, "artifacts": sorted(artifacts), "plan_artifact": digest(plan_bytes), "approval_artifact": digest(approval_bytes), "toolchain_artifact": toolchain.val, "selected": [enc_ref(ref)], "sources": [enc_source_selection(source) for source in context.sources], "operation_kind": "admission"}
        release = ReleaseId(self.engine.git.prepare(manifest, base_release.val if base_release else None, artifacts))
        self.engine.git.publish(release.val, base_release.val if base_release else None)
        save(self.engine.root / "plans" / (identity.val + ".json"), plan.wire())
        save(self.engine.root / "journal" / (identity.val + ".json"), {"schema_version": 2, "id": identity.val, "approval": approval.wire(), "phase": "published", "dolt_commit": commit.val, "release": release.val})
        return plan, approval, release, candidate

    def test_actual_signed_v2_history_and_first_v3_transition(self):
        legacy, approval, release, candidate = self.legacy_release()
        discovered = self.engine.contexts()
        self.assertEqual([entry["id"] for entry in discovered["contexts"]], ["legacy"])
        query = dec_context(discovered["contexts"][0]["context"])
        self.assertTrue(self.engine.context((), query, context_id=ContextId("legacy"))["records"][0]["assessment"]["usable"])
        with self.assertRaises(KctxError):
            self.engine.sign(legacy.id, self.fixture.key_file, self.key)
        with self.assertRaises(KctxError):
            self.engine.admit(legacy.id, approval)
        candidate["expected_snapshot"] = legacy.semantic.candidate.snapshot.val
        candidate["kb"]["snapshot"] = "first-portfolio"
        candidate["assignments"] = []
        candidate["contexts"][0]["context"]["snapshot"] = "first-portfolio"
        candidate["contexts"][0]["context"]["now"] = 6
        with self.assertRaises(KctxError):
            self.engine.propose(candidate, "review", 6)
        candidate["contexts"][0]["id"] = "legacy"
        current = self.engine.propose(candidate, "review", 6)
        with self.assertRaises(KctxError):
            self.engine.admit(current.id, replace(approval, plan=current.id))
        self.engine.admit(current.id, self.engine.sign(current.id, self.fixture.key_file, self.key))
        self.assertEqual(self.engine.contexts(release), discovered)
        self.assertTrue(self.engine.context((), current.semantic.contexts[0].context, context_id=ContextId("legacy"))["records"][0]["assessment"]["usable"])
        self.assertEqual(
            sorted((item["plan"], item["outcome"]) for item in self.engine.recover()["operations"]),
            sorted(((legacy.id.val, "already_applied"), (current.id.val, "already_applied"))),
        )

    def test_unsigned_manifest_context_addition_is_not_discovery_authority(self):
        _, release = self.publish(self.fixture.candidate(CaptureKind.DOCUMENT))
        manifest = self.engine.git.manifest(release.val)
        artifacts = {identity: self.engine.git.artifact(release.val, identity) for identity in manifest["artifacts"]}
        invented = deepcopy(manifest["contexts"][0])
        invented["id"] = "unsigned"
        manifest["contexts"].append(invented)
        forged = self.engine.git.prepare(manifest, None, artifacts)
        self.engine.git.publish(forged, release.val)
        with self.assertRaises(KctxError):
            self.engine.contexts()
        with self.assertRaises(KctxError):
            self.engine.context_for_assets((AssetId("service"),))

    def test_signature_domain_version_and_pending_legacy_recovery_are_strict(self):
        candidate = self.fixture.candidate(CaptureKind.DOCUMENT)
        plan = self.engine.propose(candidate, "review", 5)
        wrong_domain = Approval(plan.id, self.key, self.fixture.key.sign(b"kctx-operation-v2\x00" + canonical(plan.wire())))
        with self.assertRaises(KctxError):
            self.engine.admit(plan.id, wrong_domain)
        approval = self.engine.sign(plan.id, self.fixture.key_file, self.key)
        with self.assertRaises(KctxError):
            self.engine.admit(plan.id, replace(approval, schema_version=2))
        self.assertIsNone(self.engine.git.current())
        legacy, legacy_approval, release, _ = self.legacy_release()
        save(self.engine.root / "journal" / (legacy.id.val + ".json"), {"schema_version": 2, "id": legacy.id.val, "approval": legacy_approval.wire(), "phase": "prepared"})
        self.assertEqual(
            [(item["plan"], item["outcome"]) for item in self.engine.recover()["operations"]],
            [(legacy.id.val, "conflict")],
        )
        self.assertEqual(self.engine.git.current(), release.val)

    def test_signed_v2_cannot_downgrade_a_portfolio_history(self):
        first = self.publish(self.fixture.candidate(CaptureKind.DOCUMENT))
        self.legacy_release(first)
        with self.assertRaises(KctxError):
            self.engine.contexts()
