"""Q26/Q28/Q29/Q30/Q31 authored-workflow boundaries, not release authority."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
import hashlib
import time

from _base import KctxTestCase
from test_proposals import GATES_TABLE_FULL, _add, _landed

from kctx.adapters.files.mutations import FileRevision
from kctx.domain.ids import GateId, ProposalId, TargetRevision
from kctx.domain.vocabulary import GateOutcome, ProposalStatus
from kctx.errors import KctxError
from kctx.services import proposal_mutation, proposals


class AuthoredWorkflowBoundariesTest(KctxTestCase):
    def _landing(self, title="Bound workflow"):
        added = _add(self.root, title=title)
        proposals.set_status(self.root, added.id, status=ProposalStatus.ACCEPTED, by="acceptor")
        proposals.set_status(self.root, added.id, status=ProposalStatus.LANDING, by="executor")
        return added

    def _gate(self, added, identity="G1", **changes):
        kwargs = dict(outcome=GateOutcome.PASS, evidence="retained-check-result", by="checker-actor", checker="fixture-checker", expires_at=4102444800)
        kwargs.update(changes)
        return proposals.gate(self.root, added.id, GateId(identity), **kwargs)

    def test_q26_missing_malformed_duplicate_tables_never_get_legacy_exemption(self):
        for index, replacement in enumerate(("", "| claim | check |\n|---|---|\n| x | y |", GATES_TABLE_FULL + "\n### Acceptance gates\n" + GATES_TABLE_FULL)):
            added = self._landing(f"Modern table {index}")
            document = proposals.load(self.root, added.id).document.update_section("Acceptance gates", replacement)
            document.write(added.path)
            before = added.path.read_bytes()
            with self.assertRaises(KctxError):
                proposals.set_status(self.root, added.id, status=ProposalStatus.APPLIED, by="executor", landed_add=(_landed(self.root),))
            self.assertEqual(added.path.read_bytes(), before)

    def test_q26_directory_record_cannot_claim_legacy_profile(self):
        added = self._landing()
        added.path.write_text(added.path.read_text().replace("profile: modern", "profile: legacy_limited"))
        with self.assertRaises(KctxError):
            proposals.load(self.root, added.id)

    def test_q28_wrong_target_and_old_definition_do_not_authorize(self):
        added = self._landing()
        other = self.root / "other-target.txt"
        other.write_text("different retained target")
        other_revision = "other-target.txt@sha256:" + hashlib.sha256(other.read_bytes()).hexdigest()
        self._gate(added, target_revision=TargetRevision(other_revision))
        with self.assertRaises(KctxError):
            proposals.set_status(self.root, added.id, status=ProposalStatus.APPLIED, by="executor", landed_add=(_landed(self.root),))
        self._gate(added)
        added.path.write_text(added.path.read_text().replace("`true`", "`false`", 1))
        with self.assertRaises(KctxError):
            proposals.set_status(self.root, added.id, status=ProposalStatus.APPLIED, by="executor", landed_add=(_landed(self.root),))

    def test_q28_latest_failure_invalidates_previous_pass(self):
        added = self._landing()
        self._gate(added)
        self._gate(added, outcome=GateOutcome.FAIL)
        with self.assertRaises(KctxError):
            proposals.set_status(self.root, added.id, status=ProposalStatus.APPLIED, by="executor", landed_add=(_landed(self.root),))
        self.assertIs(proposals.show(self.root, added.id).gates[0].outcome, GateOutcome.FAIL)

    def test_q28_expired_receipt_does_not_authorize(self):
        added = self._landing()
        now = int(time.time())
        self._gate(added, expires_at=now + 10)
        with patch("kctx.services.proposals.time.time", return_value=now + 11), self.assertRaises(KctxError):
            proposals.set_status(self.root, added.id, status=ProposalStatus.APPLIED, by="executor", landed_add=(_landed(self.root),))

    def test_q29_same_command_landed_additions_validate_whole_candidate(self):
        added = self._landing()
        self._gate(added)
        before = added.path.read_bytes()
        with self.assertRaises(KctxError):
            proposals.set_status(self.root, added.id, status=ProposalStatus.APPLIED, by="executor")
        self.assertEqual(added.path.read_bytes(), before)
        result = proposals.set_status(self.root, added.id, status=ProposalStatus.APPLIED, by="executor", landed_add=(_landed(self.root),))
        self.assertIs(result.proposal.status, ProposalStatus.APPLIED)
        self.assertEqual(result.proposal.landed, (_landed(self.root),))

    def test_q30_one_expected_predecessor_has_only_one_landing_winner(self):
        added = _add(self.root)
        proposals.set_status(self.root, added.id, status=ProposalStatus.ACCEPTED, by="acceptor")
        expected = FileRevision(proposals.load(self.root, added.id).revision)
        barrier = Barrier(2)
        def attempt(actor):
            barrier.wait(timeout=10)
            try:
                proposals.set_status(self.root, added.id, status=ProposalStatus.LANDING, by=actor, expected_revision=expected)
                return "landed"
            except KctxError as exc:
                return exc.category
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(attempt, ("executor-a", "executor-b")))
        self.assertEqual(sorted(results), ["conflict", "landed"])
        found = proposals.load(self.root, added.id)
        self.assertEqual(found.document.sections["Decision log"].count(": landing by"), 1)

    def test_q31_acceptance_and_executor_survive_verification(self):
        added = self._landing()
        for identity in ("G1", "G2", "G3"):
            self._gate(added, identity)
        proposals.set_status(self.root, added.id, status=ProposalStatus.APPLIED, by="executor", landed_add=(_landed(self.root),))
        result = proposals.set_status(self.root, added.id, status=ProposalStatus.VERIFIED, by="executor")
        self.assertEqual((result.proposal.decided_by, result.proposal.acceptor, result.proposal.executor, result.proposal.verifier), ("acceptor", "acceptor", "executor", "executor"))
        history = proposals.load(self.root, added.id).document.sections["Decision log"]
        for event in ("accepted by acceptor", "landing by executor", "applied by executor", "verified by executor"):
            self.assertIn(event, history)

    def test_interrupted_gate_log_publication_is_recovered_before_read(self):
        added = self._landing()
        actual = proposal_mutation.compare_and_write
        def fail_document(path, content, *, expected):
            if path == added.path:
                raise OSError("interrupted after history publication")
            return actual(path, content, expected=expected)
        with patch("kctx.services.proposal_mutation.compare_and_write", side_effect=fail_document), self.assertRaises(OSError):
            self._gate(added)
        recovered = proposals.load(self.root, added.id)
        self.assertIn("gate G1 -> pass", recovered.document.sections["Decision log"])
        self.assertIs(proposals.show(self.root, added.id).gates[0].outcome, GateOutcome.PASS)
        self.assertFalse(added.path.with_name(".proposal.md.kctx-mutation.json").exists())

    def test_gate_check_prose_is_never_executed(self):
        sentinel = self.root / "must-not-exist"
        table = GATES_TABLE_FULL.replace("`true`", f"`touch {sentinel}`")
        added = _add(self.root, gates=table)
        self._gate(added)
        self.assertFalse(sentinel.exists())

    def test_original_five_column_gate_table_remains_reviewable(self):
        table = GATES_TABLE_FULL.replace(" | checker |", " |").replace("|---|---|---|---|---|---|", "|---|---|---|---|---|").replace(" | fixture-checker |", " |")
        added = _add(self.root, gates=table)
        self.assertIs(added.proposal.status, ProposalStatus.PROPOSED)
        self._gate(added)
        self.assertIs(proposals.show(self.root, added.id).gates[0].outcome, GateOutcome.PASS)

    def test_verified_without_actor_does_not_invent_attribution(self):
        added = self._landing()
        for identity in ("G1", "G2", "G3"):
            self._gate(added, identity)
        proposals.set_status(self.root, added.id, status=ProposalStatus.APPLIED, by="executor", landed_add=(_landed(self.root),))
        result = proposals.set_status(self.root, added.id, status=ProposalStatus.VERIFIED)
        self.assertIsNone(result.proposal.verifier)
        self.assertEqual(result.proposal.acceptor, "acceptor")
        self.assertEqual(result.proposal.executor, "executor")

    def test_invalid_bound_metadata_is_rejected_before_journal_publication(self):
        added = self._landing()
        document = added.path.read_bytes()
        history = (added.path.parent / "gates.json").read_bytes()
        for changes in ({"checker": " "}, {"repo_rev": " "}, {"evidence": " "}):
            with self.subTest(changes=changes), self.assertRaises(KctxError):
                self._gate(added, **changes)
            self.assertEqual(added.path.read_bytes(), document)
            self.assertEqual((added.path.parent / "gates.json").read_bytes(), history)
            self.assertFalse(added.path.with_name(".proposal.md.kctx-mutation.json").exists())

    def test_supersession_requires_resolving_acyclic_replacement(self):
        first = _add(self.root, title="First")
        second = _add(self.root, title="Second")
        for replacement in (None, first.id, ProposalId("other/missing")):
            with self.subTest(replacement=replacement), self.assertRaises(KctxError):
                proposals.set_status(self.root, first.id, status=ProposalStatus.SUPERSEDED, superseded_by=replacement)
        proposals.set_status(self.root, first.id, status=ProposalStatus.SUPERSEDED, superseded_by=second.id)
        before = second.path.read_bytes()
        with self.assertRaises(KctxError):
            proposals.set_status(self.root, second.id, status=ProposalStatus.SUPERSEDED, superseded_by=first.id)
        self.assertEqual(second.path.read_bytes(), before)
        self.assertIs(proposals.load(self.root, second.id).proposal.status, ProposalStatus.PROPOSED)

    def test_verified_regression_preserves_verification_and_contradiction(self):
        added = self._landing()
        for identity in ("G1", "G2", "G3"):
            self._gate(added, identity)
        proposals.set_status(self.root, added.id, status=ProposalStatus.APPLIED, by="executor", landed_add=(_landed(self.root),))
        verified = proposals.set_status(self.root, added.id, status=ProposalStatus.VERIFIED, by="verifier")
        with self.assertRaises(KctxError):
            proposals.set_status(self.root, added.id, status=ProposalStatus.REGRESSED)
        regressed = proposals.set_status(self.root, added.id, status=ProposalStatus.REGRESSED, note="contradiction: retained evidence ev:counterexample", by="reviewer")
        self.assertEqual(regressed.proposal.verifier, verified.proposal.verifier)
        self.assertEqual(regressed.proposal.accepted_revision, verified.proposal.accepted_revision)
        self.assertIn("contradiction: retained evidence ev:counterexample", proposals.load(self.root, added.id).document.sections["Decision log"])

    def test_context_unknown_or_mismatched_results_cannot_authorize(self):
        unknown = _add(self.root, title="Unknown context", environment=None, scope=None)
        with self.assertRaises(KctxError):
            self._gate(unknown)
        added = self._landing()
        for changes in ({"environment": "other-environment"}, {"scope": "other-target"}):
            self._gate(added, **changes)
            with self.assertRaises(KctxError):
                proposals.set_status(self.root, added.id, status=ProposalStatus.APPLIED, by="executor", landed_add=(_landed(self.root),))

    def test_material_change_invalidates_acceptance_and_gate_receipts(self):
        added = self._landing()
        accepted = proposals.load(self.root, added.id).proposal.accepted_revision
        self._gate(added)
        found = proposals.load(self.root, added.id)
        found.document.update_section("Proposed change", "a materially different change").write(found.path)
        self._gate(added)
        with self.assertRaises(KctxError):
            proposals.set_status(self.root, added.id, status=ProposalStatus.APPLIED, by="executor", landed_add=(_landed(self.root),))
        self.assertEqual(proposals.load(self.root, added.id).proposal.accepted_revision, accepted)

    def test_acceptance_binds_combined_candidate_material(self):
        added = _add(self.root)
        result = proposals.set_status(self.root, added.id, status=ProposalStatus.ACCEPTED, by="acceptor", environment="updated-fixture")
        found = proposals.load(self.root, added.id)
        self.assertEqual(result.proposal.accepted_revision, proposals.material_revision(found.document))
