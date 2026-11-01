"""Consumer-visible design acceptance, implementation binding and explicit migration."""

from hashlib import sha256
from unittest.mock import patch

from _base import KctxTestCase
from test_proposals import GATES_TABLE_FULL, GATES_TABLE_LAND, TWO_ALTERNATIVES

from kctx.adapters.files.mutations import FileRevision
from kctx.codecs.documents import parse_document
from kctx.codecs.proposals import decode_proposal, encode_proposal
from kctx.domain.ids import GateId, ProposalId, ProposalMaterialRevision, SourceId, TargetRevision
from kctx.domain.vocabulary import GateOutcome, ProposalKind, ProposalOrigin, ProposalStatus
from kctx.errors import KctxError
from kctx.services import gates, proposals, validate


class DesignWorkflowTest(KctxTestCase):
    def _design(self, title="Design before implementation", table=GATES_TABLE_LAND, source=None):
        return proposals.add(
            self.root, kind=ProposalKind.CONFIG, origin=ProposalOrigin.USER_REQUEST,
            title=title, context="Intent", evidence="Design evidence", change="Implement design",
            why="Useful", research="Reviewed", alternatives=TWO_ALTERNATIVES, gates=table,
            target_source=source or SourceId(str(self.root / "implementation.txt")),
            environment="test", scope="implementation",
        )

    def _target(self, contents="implementation one", filename="implementation.txt"):
        path = self.root / filename
        path.write_text(contents)
        return TargetRevision(f"{path}@sha256:{sha256(path.read_bytes()).hexdigest()}")

    def _accept(self, added):
        return proposals.set_status(self.root, added.id, status=ProposalStatus.ACCEPTED, by="designer")

    def _pass(self, added, identity="G1"):
        return proposals.gate(
            self.root, added.id, GateId(identity), outcome=GateOutcome.PASS, evidence="obs:checked",
            by="checker", checker="fixture-checker", expires_at=4102444800,
        )

    def _unchanged(self, added, action):
        before = added.path.read_bytes()
        history = gates.gates_json_path(added.path).read_bytes()
        with self.assertRaises(KctxError):
            action()
        self.assertEqual(added.path.read_bytes(), before)
        self.assertEqual(gates.gates_json_path(added.path).read_bytes(), history)
        self.assertFalse(added.path.with_name(".proposal.md.kctx-mutation.json").exists())

    def test_accept_before_file_exists_then_bind_pass_land_apply(self):
        added = self._design()
        accepted = self._accept(added).proposal
        self.assertFalse((self.root / "implementation.txt").exists())
        self.assertIsNone(accepted.target_revision)
        self.assertIsNone(accepted.binding)
        self.assertEqual(accepted.workflow_version, 3)
        self.assertEqual(proposals.load(self.root, added.id).document.frontmatter["schema_version"], "1")
        self.assertTrue(validate.validate(self.root).ok)
        target = self._target()
        bound = proposals.bind(self.root, added.id, target_revision=target, by="implementer").proposal
        self.assertEqual(bound.accepted_revision, accepted.accepted_revision)
        self.assertEqual(bound.acceptor, "designer")
        self.assertEqual(bound.binding, proposals.load(self.root, added.id).proposal.binding)
        self.assertEqual(encode_proposal(bound)["binding"]["target_revision"], target.val)
        self._pass(added)
        proposals.set_status(self.root, added.id, status=ProposalStatus.LANDING, by="implementer")
        applied = proposals.set_status(
            self.root, added.id, status=ProposalStatus.APPLIED, by="implementer", landed_add=(target.val,)
        )
        self.assertIs(applied.proposal.status, ProposalStatus.APPLIED)
        self.assertTrue(validate.validate(self.root).ok)

    def test_retarget_accepted_and_landing_preserves_design_not_old_gates(self):
        for landing in (False, True):
            with self.subTest(landing=landing):
                added = self._design(title=f"Retarget {landing}")
                accepted = self._accept(added).proposal
                first = self._target()
                proposals.bind(self.root, added.id, target_revision=first, by="implementer")
                self._pass(added)
                proposals.set_status(self.root, added.id, landed_add=(first.val,))
                if landing:
                    proposals.set_status(self.root, added.id, status=ProposalStatus.LANDING, by="implementer")
                second = self._target("implementation two")
                bound = proposals.bind(self.root, added.id, target_revision=second, by="retargeter").proposal
                self.assertEqual(bound.accepted_revision, accepted.accepted_revision)
                self.assertEqual(bound.acceptor, accepted.acceptor)
                self.assertEqual(bound.landed, ())
                self.assertEqual(proposals.material_revision(proposals.load(self.root, added.id).document), accepted.accepted_revision)
                self.assertEqual(len(gates.load_results(added.path)), 1)
                self.assertIs(proposals.show(self.root, added.id).gates[0].outcome, GateOutcome.UNK)
                if not landing:
                    proposals.set_status(self.root, added.id, status=ProposalStatus.LANDING, by="implementer")
                apply = lambda: proposals.set_status(
                    self.root, added.id, status=ProposalStatus.APPLIED, by="implementer", landed_add=(second.val,)
                )
                self._unchanged(added, apply)
                self._pass(added)
                self.assertIs(apply().proposal.status, ProposalStatus.APPLIED)

    def test_wrong_source_changed_design_and_stale_revision_reject_atomically(self):
        added = self._design()
        self._accept(added)
        other = self._target(filename="other.txt")
        self._unchanged(added, lambda: proposals.bind(self.root, added.id, target_revision=other, by="implementer"))
        target = self._target()
        expected = FileRevision(proposals.load(self.root, added.id).revision)
        proposals.bind(self.root, added.id, target_revision=target, by="implementer")
        self._unchanged(added, lambda: proposals.bind(self.root, added.id, target_revision=target, by="other", expected_revision=expected))
        self._unchanged(added, lambda: proposals.reopen(self.root, added.id, by="designer", note="Renew", expected_revision=expected))
        found = proposals.load(self.root, added.id)
        found.document.update_section("Proposed change", "Different design").write(found.path)
        self._unchanged(added, lambda: proposals.bind(self.root, added.id, target_revision=target, by="implementer"))
        reopened = proposals.reopen(self.root, added.id, by="designer", note="Approve changed design explicitly")
        self.assertIs(reopened.proposal.status, ProposalStatus.PROPOSED)
        self.assertIsNone(reopened.proposal.accepted_revision)
        self._accept(added)
        self.assertIsNotNone(proposals.bind(self.root, added.id, target_revision=target, by="implementer").proposal.binding)

    def test_landing_does_not_infer_a_missing_acceptor_from_legacy_attribution(self):
        added = self._design()
        self._accept(added)
        found = proposals.load(self.root, added.id)
        found.document.update_fields({"acceptor": None}).write(found.path)
        self._unchanged(added, lambda: proposals.set_status(
            self.root, added.id, status=ProposalStatus.LANDING, by="implementer"
        ))

    def test_future_or_wrong_design_binding_cannot_authorize_application(self):
        for changes in ({"binding_observed_at": "4102444800"}, {"binding_design_revision": "wrong-design"}):
            added = self._design(title=f"Binding tamper {next(iter(changes))}")
            self._accept(added)
            target = self._target()
            proposals.bind(self.root, added.id, target_revision=target, by="implementer")
            proposals.set_status(self.root, added.id, status=ProposalStatus.LANDING, by="implementer")
            self._pass(added)
            found = proposals.load(self.root, added.id)
            found.document.update_fields(changes).write(found.path)
            with patch("kctx.services.proposals.time.time", return_value=1800000000):
                self._unchanged(added, lambda: proposals.set_status(
                    self.root, added.id, status=ProposalStatus.APPLIED, by="implementer", landed_add=(target.val,)
                ))

    def test_generic_material_and_target_edits_require_explicit_reopen_or_bind(self):
        added = self._design()
        self._accept(added)
        target = self._target()
        for fields in ({"environment": "production"}, {"scope": "other"}, {"target_source": SourceId("./other.txt")}, {"target_revision": target}, {"origin": ProposalOrigin.STEWARD}):
            self._unchanged(added, lambda fields=fields: proposals.set_status(self.root, added.id, **fields))
        proposals.bind(self.root, added.id, target_revision=target, by="implementer")
        self._pass(added)
        proposals.set_status(self.root, added.id, status=ProposalStatus.LANDING, by="implementer", landed_add=(target.val,))
        reopened = proposals.reopen(self.root, added.id, by="designer", note="Revise deployment design").proposal
        for value in (reopened.accepted_revision, reopened.acceptor, reopened.executor, reopened.verifier, reopened.decided_by, reopened.binding, reopened.target_revision):
            self.assertIsNone(value)
        self.assertEqual(reopened.landed, ())
        self.assertEqual(len(gates.load_results(added.path)), 1)
        proposals.set_status(self.root, added.id, environment="production")
        self._accept(added)
        proposals.bind(self.root, added.id, target_revision=target, by="implementer")
        self.assertIs(proposals.show(self.root, added.id).gates[0].outcome, GateOutcome.UNK)

    def test_finalized_design_cannot_rebind_reopen_or_force_overwrite(self):
        added = self._design(table=GATES_TABLE_FULL)
        self._accept(added)
        target = self._target()
        proposals.bind(self.root, added.id, target_revision=target, by="implementer")
        proposals.set_status(self.root, added.id, status=ProposalStatus.LANDING, by="implementer")
        self._pass(added)
        proposals.set_status(self.root, added.id, status=ProposalStatus.APPLIED, by="implementer", landed_add=(target.val,))
        for status in (ProposalStatus.APPLIED, ProposalStatus.VERIFIED):
            if status is ProposalStatus.VERIFIED:
                self._pass(added, "G2")
                self._pass(added, "G3")
                proposals.set_status(self.root, added.id, status=status, by="verifier")
            self._unchanged(added, lambda: proposals.bind(self.root, added.id, target_revision=target, by="other"))
            self._unchanged(added, lambda: proposals.reopen(self.root, added.id, by="designer", note="Cannot rewrite history"))
            self._unchanged(added, lambda: proposals.set_status(self.root, added.id, target_revision=target))
            self._unchanged(added, lambda: proposals.add(
                self.root, kind=ProposalKind.CONFIG, origin=ProposalOrigin.USER_REQUEST,
                title=added.proposal.title, context="Replacement", evidence="ev", change="ch", why="why",
                target_source=added.proposal.target_source, force=True,
            ))

    def test_explicit_or_safely_inferred_source_is_required(self):
        arguments = dict(kind=ProposalKind.CONFIG, origin=ProposalOrigin.USER_REQUEST, title="Source", context="c", evidence="e", change="ch", why="w")
        for source in (None, SourceId("unknown")):
            with self.assertRaises(KctxError):
                proposals.add(self.root, **arguments, target_source=source)
        self.assertEqual(proposals.all_paths(self.root), ())
        target = self._target()
        with self.assertRaises(KctxError):
            proposals.add(self.root, **arguments, target_source=SourceId("./wrong.txt"), target_revision=target)
        result = proposals.add(self.root, **arguments, target_revision=target)
        self.assertEqual(result.proposal.target_source, SourceId(str(self.root / "implementation.txt")))

    def test_partial_binding_and_unknown_workflow_are_not_admitted(self):
        added = self._design()
        document = proposals.load(self.root, added.id).document
        for changes in ({"binding_actor": "implementer"}, {"workflow_version": "4"}, {"target_source": "unknown"}):
            with self.assertRaises(KctxError):
                decode_proposal(document.update_fields(changes))

    def test_accept_repo_design_before_repository_exists_then_rebind_real_commits(self):
        source = self.root / "_fixture-design"
        added = self._design(source=SourceId(str(source)))
        accepted = self._accept(added).proposal
        self.assertFalse(source.exists())
        repo = self.make_git_repo("design")
        first = TargetRevision(f"{repo}@{self.commit_file(repo, 'tracked.txt', 'first implementation')}")
        proposals.bind(self.root, added.id, target_revision=first, by="implementer")
        self._pass(added)
        proposals.set_status(self.root, added.id, status=ProposalStatus.LANDING, by="implementer", landed_add=(first.val,))
        second = TargetRevision(f"{repo}@{self.commit_file(repo, 'tracked.txt', 'second implementation')}")
        rebound = proposals.bind(self.root, added.id, target_revision=second, by="implementer")
        self.assertEqual(rebound.proposal.accepted_revision, accepted.accepted_revision)
        self.assertEqual(rebound.proposal.landed, ())
        self._unchanged(added, lambda: proposals.set_status(
            self.root, added.id, status=ProposalStatus.APPLIED, by="implementer", landed_add=(second.val,)
        ))
        self._pass(added)
        applied = proposals.set_status(
            self.root, added.id, status=ProposalStatus.APPLIED, by="implementer", landed_add=(second.val,)
        )
        self.assertIs(applied.proposal.status, ProposalStatus.APPLIED)

    def test_forged_binding_source_label_cannot_authorize_another_actual_source(self):
        added = self._design()
        self._accept(added)
        target = self._target()
        proposals.bind(self.root, added.id, target_revision=target, by="implementer")
        proposals.set_status(self.root, added.id, status=ProposalStatus.LANDING, by="implementer")
        other = self._target(filename="another-source.txt")
        found = proposals.load(self.root, added.id)
        found.document.update_fields({
            "target_revision": other.val, "binding_target_revision": other.val,
        }).write(found.path)
        self._pass(added)
        self._unchanged(added, lambda: proposals.set_status(
            self.root, added.id, status=ProposalStatus.APPLIED, by="implementer", landed_add=(other.val,)
        ))
        self.assertFalse(validate.validate(self.root).ok)


LEGACY_DESIGN = """---
schema_version: 1
id: config/legacy
kind: config
title: Legacy design
status: proposed
created: 2026-01-01
profile: modern
environment: test
scope: implementation
---
## Research
Known design
## Alternatives considered
- A
- B
## Acceptance gates
| id | claim | check | when | by | checker |
|---|---|---|---|---|---|
| G1 | it works | `true` | land | agent | fixture-checker |
## Decision log
- Initial
"""
LEGACY_DIGEST = ProposalMaterialRevision("1947884be0e451a4959e78aef25b81ebf36cb09e4138b7d937166f8181d5e453")


class LegacyDesignMigrationTest(KctxTestCase):
    def _legacy(self, status=ProposalStatus.PROPOSED):
        path = self.root / "proposals/config/legacy/proposal.md"
        path.parent.mkdir(parents=True)
        document = parse_document(LEGACY_DESIGN)
        if status is not ProposalStatus.PROPOSED:
            document = document.update_fields({"status": status.value, "accepted_revision": LEGACY_DIGEST.val, "acceptor": "original", "decided_by": "original", "last_actor": "original"})
        document.write(path)
        return proposals.load(self.root, ProposalId("config/legacy"))

    def test_historical_digest_is_exact_until_explicit_adoption(self):
        found = self._legacy()
        original = found.path.read_bytes()
        self.assertEqual(found.proposal.workflow_version, 2)
        self.assertEqual(proposals.material_revision(found.document), LEGACY_DIGEST)
        proposals.show(self.root, found.proposal.id)
        proposals.list_proposals(self.root)
        validate.validate(self.root)
        self.assertEqual(found.path.read_bytes(), original)
        with self.assertRaises(KctxError):
            proposals.set_status(self.root, found.proposal.id, status=ProposalStatus.ACCEPTED, by="designer")
        self.assertEqual(found.path.read_bytes(), original)
        result = proposals.adopt(self.root, found.proposal.id, by="designer", note="Explicit new design review", target_source=SourceId("./future.txt"))
        self.assertEqual(result.proposal.workflow_version, 3)
        self.assertIsNone(result.proposal.accepted_revision)
        migrated = proposals.load(self.root, found.proposal.id)
        self.assertNotEqual(proposals.material_revision(migrated.document), LEGACY_DIGEST)
        accepted = proposals.set_status(self.root, found.proposal.id, status=ProposalStatus.ACCEPTED, by="new-designer")
        self.assertNotEqual(accepted.proposal.accepted_revision, LEGACY_DIGEST)

    def test_workflow2_custom_metadata_never_becomes_binding_authority(self):
        found = self._legacy()
        document = found.document.update_fields({
            "target_source": "historical custom source metadata",
            "binding_actor": "historical custom actor metadata",
            "binding_observed_at": "not an execution timestamp",
        })
        document.write(found.path)
        original = found.path.read_bytes()
        historical_revision = proposals.material_revision(document)
        self.assertNotEqual(historical_revision, LEGACY_DIGEST)
        shown = proposals.show(self.root, found.proposal.id)
        self.assertEqual(shown.proposal.workflow_version, 2)
        self.assertIsNone(shown.proposal.target_source)
        self.assertIsNone(shown.proposal.binding)
        self.assertEqual(found.path.read_bytes(), original)
        self.assertEqual(
            proposals.material_revision(proposals.load(self.root, found.proposal.id).document),
            historical_revision,
        )

    def test_v2_material_hash_cannot_authorize_workflow3_design_semantics(self):
        found = self._legacy()
        # Frozen output of the v2 hasher: these were then unknown material fields.
        old_revision = ProposalMaterialRevision(
            "64ac3c312822e38a0737a897434cdba9493a421f7dff49001744f3e1aad29a4a"
        )
        found.document.update_fields({
            "workflow_version": "3", "target_source": "example/repo",
            "status": "accepted", "accepted_revision": old_revision.val,
            "acceptor": "original", "decided_by": "original", "last_actor": "original",
        }).write(found.path)
        self.assertFalse(validate.validate(self.root).ok)
        self.assertEqual(proposals.load(self.root, found.proposal.id).proposal.accepted_revision, old_revision)
        proposals.reopen(self.root, found.proposal.id, by="new-designer", note="Authorize workflow3 explicitly")
        accepted = proposals.set_status(
            self.root, found.proposal.id, status=ProposalStatus.ACCEPTED, by="new-designer"
        )
        self.assertNotEqual(accepted.proposal.accepted_revision, old_revision)
        self.assertTrue(validate.validate(self.root).ok)

    def test_legacy_accepted_reopen_discards_approval_without_relabeling(self):
        found = self._legacy(ProposalStatus.ACCEPTED)
        self.assertEqual(proposals.material_revision(found.document), LEGACY_DIGEST)
        result = proposals.reopen(self.root, found.proposal.id, by="new-designer", note="Renew approval", target_source=SourceId("./future.txt"))
        self.assertIs(result.proposal.status, ProposalStatus.PROPOSED)
        self.assertEqual(result.proposal.workflow_version, 3)
        self.assertIsNone(result.proposal.accepted_revision)
        self.assertIsNone(result.proposal.acceptor)
        self.assertIn("new-designer", proposals.load(self.root, found.proposal.id).document.sections["Decision log"])

    def test_terminal_legacy_history_remains_readable_and_cannot_migrate(self):
        found = self._legacy(ProposalStatus.APPLIED)
        original = found.path.read_bytes()
        self.assertEqual(proposals.show(self.root, found.proposal.id).proposal.workflow_version, 2)
        for action in (proposals.adopt, proposals.reopen):
            with self.assertRaises(KctxError):
                action(self.root, found.proposal.id, by="designer", note="No rewriting", target_source=SourceId("./future.txt"))
        self.assertEqual(found.path.read_bytes(), original)
        self.assertEqual(proposals.material_revision(proposals.load(self.root, found.proposal.id).document), LEGACY_DIGEST)

    def test_valid_workflow2_applied_history_keeps_exact_gate_and_design_interpretation(self):
        from kctx.adapters.files.storage import atomic_write_json
        from kctx.codecs.gates import encode_gate_result
        from kctx.domain.proposals import GateResult

        found = self._legacy(ProposalStatus.APPLIED)
        artifact = self.root / "retained.txt"
        artifact.write_text("historical retained implementation")
        target = TargetRevision(f"{artifact}@sha256:{sha256(artifact.read_bytes()).hexdigest()}")
        document = found.document.update_fields({
            "target_revision": target.val, "landed": f"[{target.val}]", "executor": "original",
        })
        digest = proposals.material_revision(document)
        document = document.update_fields({"accepted_revision": digest.val})
        document.write(found.path)
        definition = gates.parse_gates_table(document.sections)[0]
        result = GateResult(
            GateId("G1"), GateOutcome.PASS, "historical observation", "2026-01-01T00:00:00Z",
            by="original", rev=gates.gates_rev(document.sections), target_revision=target,
            checker="fixture-checker", observed_at=1, expires_at=4102444800, definition=definition,
            proposal_revision=digest, environment="test", scope="implementation",
        )
        atomic_write_json(gates.gates_json_path(found.path), [encode_gate_result(result)])
        original, history = found.path.read_bytes(), gates.gates_json_path(found.path).read_bytes()
        self.assertTrue(validate.validate(self.root).ok)
        self.assertIs(proposals.show(self.root, found.proposal.id).gates[0].outcome, GateOutcome.PASS)
        self.assertEqual(found.path.read_bytes(), original)
        self.assertEqual(gates.gates_json_path(found.path).read_bytes(), history)
        replacement = proposals.add(
            self.root, kind=ProposalKind.CONFIG, origin=ProposalOrigin.USER_REQUEST,
            title="Replacement design", context="c", evidence="e", change="ch", why="w",
            target_source=SourceId(str(artifact)),
        )
        superseded = proposals.set_status(
            self.root, found.proposal.id, status=ProposalStatus.SUPERSEDED,
            superseded_by=replacement.id, by="reviewer",
        )
        self.assertEqual(superseded.proposal.workflow_version, 2)
        self.assertEqual(proposals.material_revision(proposals.load(self.root, found.proposal.id).document), digest)
        self.assertEqual(gates.gates_json_path(found.path).read_bytes(), history)
