from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import time

from _base import KctxTestCase

import kctx.services.corrections as corrections_mod
import kctx.services.inventory as inventory
import kctx.services.investigations as inv_mod
import kctx.services.ktlo as ktlo
import kctx.services.proposals as proposals
import kctx.services.signatures as sig_mod
import kctx.services.validate as validate
import kctx.services.gates as gates_mod
from kctx.adapters.files.storage import atomic_write_json
from kctx.codecs.gates import encode_gate_result
from kctx.codecs.documents import read_document, render_document
from kctx.domain.ids import (
    AssetId, GateId, InvestigationId, ProposalMaterialRevision, SignatureId,
    TargetRevision, TicketId,
)
from kctx.domain.proposals import ProposalAdded
from kctx.domain.vocabulary import (
    AssetKind, CorrectionKind, GateOutcome, InvestigationStatus,
    InvestigationTrigger, ProposalKind, ProposalOrigin, ProposalStatus,
    RelationshipType, SignatureStatus,
)


GATES_TABLE = (
    "| id | claim | check | when | by | checker |\n"
    "|---|---|---|---|---|---|\n"
    "| G1 | it works | `true` | land | agent | checker-v2 |\n"
)

ARTIFACT_CONTENTS = b"validated release artifact\n"


def _landed_reference(root: Path) -> str:
    return f"{root / 'landed-artifact.txt'}@sha256:{sha256(ARTIFACT_CONTENTS).hexdigest()}"


def _add_reviewable(root: Path, *, title: str = "Some idea") -> ProposalAdded:
    artifact = root / "landed-artifact.txt"
    artifact.write_bytes(ARTIFACT_CONTENTS)
    reference = _landed_reference(root)
    return proposals.add(
        root,
        kind=ProposalKind.STEWARD,
        origin=ProposalOrigin.USER_REQUEST,
        title=title,
        context="c",
        evidence="e",
        change="ch",
        why="w",
        research="researched",
        alternatives="- A. do nothing\n- B. do it",
        gates=GATES_TABLE,
        target_revision=TargetRevision(reference),
        environment="test",
        scope="service-a",
    )


class ProposalDecisionValidationTest(KctxTestCase):
    """Authored decisions need explicit provenance, not implicit acceptance.

    A lifecycle decision is distinct from signed factual knowledge admission.
    """

    def test_q07_new_proposal_is_proposed_not_accepted(self):
        result = _add_reviewable(self.root)
        fm = proposals.load(self.root, result.id).proposal
        self.assertEqual(fm.status, ProposalStatus.PROPOSED)

        listed_proposed = proposals.list_proposals(self.root, status=ProposalStatus.PROPOSED)
        listed_accepted = proposals.list_proposals(self.root, status=ProposalStatus.ACCEPTED)
        self.assertEqual(len(listed_proposed), 1)
        self.assertEqual(listed_accepted, ())

        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)

    def test_q07_validate_flags_accepted_without_decided_by(self):
        result = _add_reviewable(self.root, title="Needs a decision")
        # Simulate a record that reached "accepted" without going through
        # set_status (e.g. a hand edit or a bug) -- decided_by is empty.
        path = proposals.load(self.root, result.id).path
        text = path.read_text(encoding="utf-8").replace(
            "status: proposed", "status: accepted", 1
        )
        path.write_text(text, encoding="utf-8")

        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        messages = [p.message for p in report.problems]
        self.assertTrue(any("decided_by" in m for m in messages))

    def test_set_status_accepted_requires_by(self):
        from kctx.errors import KctxError

        result = _add_reviewable(self.root, title="Needs by")
        with self.assertRaises(KctxError) as ctx:
            proposals.set_status(self.root, result.id, status=ProposalStatus.ACCEPTED)
        self.assertEqual(ctx.exception.category, "incomplete")

        fm = proposals.set_status(
            self.root, result.id, status=ProposalStatus.ACCEPTED, by="user 2026-10-23"
        )
        self.assertEqual(fm.proposal.decided_by, "user 2026-10-23")

        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)


class ProposalLandedValidationTest(KctxTestCase):
    """Applied claims require the same scoped evidence as authored transitions."""

    def _to_landing(self, title: str = "Lands somewhere") -> ProposalAdded:
        added = _add_reviewable(self.root, title=title)
        proposals.set_status(self.root, added.id, status=ProposalStatus.ACCEPTED, by="user")
        proposals.set_status(self.root, added.id, status=ProposalStatus.LANDING, by="agent")
        proposals.gate(
            self.root, added.id, GateId("G1"), outcome=GateOutcome.PASS,
            evidence="obs:1", by="agent", checker="checker-v2",
            expires_at=int(time.time()) + 3600,
        )
        return added

    def test_landed_reference_requires_unchanged_actual_artifact(self):
        added = self._to_applied()
        (self.root / "landed-artifact.txt").write_bytes(b"different artifact\n")
        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(any(problem.where in (str(added.path), added.id.val) for problem in report.problems))

    def test_landed_reference_requires_existing_artifact(self):
        added = self._to_applied()
        (self.root / "landed-artifact.txt").unlink()
        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(any(problem.where in (str(added.path), added.id.val) for problem in report.problems))

    def _to_applied(self, title: str = "Lands somewhere") -> ProposalAdded:
        added = self._to_landing(title)
        proposals.set_status(
            self.root, added.id, status=ProposalStatus.APPLIED, by="agent",
            landed_add=(_landed_reference(self.root),),
        )
        return added

    def test_applied_with_landed_field_is_ok(self):
        self._to_applied()
        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)

    def test_note_token_does_not_replace_explicit_landed_references(self):
        added = self._to_landing("Lands via note")
        document = read_document(added.path)
        document.update_fields({"status": "applied"}).append_section(
            "Decision log", "- shipped — dotfiles@abc1234"
        ).write(added.path)
        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(any("landed" in problem.message for problem in report.problems))

    def test_applied_without_landed_is_a_problem(self):
        added = self._to_applied()
        read_document(added.path).update_fields({"landed": "[]"}).write(added.path)
        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(any("landed" in problem.message for problem in report.problems))

    def test_expired_gate_is_not_reused_by_validation(self):
        added = self._to_applied()
        results = gates_mod.load_results(added.path)
        expired = replace(results[0], observed_at=1, expires_at=2)
        atomic_write_json(gates_mod.gates_json_path(added.path), [encode_gate_result(expired)])
        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(any("gate" in problem.message for problem in report.problems))

    def test_changed_gate_binding_is_not_reused_by_validation(self):
        added = self._to_applied()
        result = gates_mod.load_results(added.path)[0]
        assert result.definition is not None
        for changed in (
            replace(result, target_revision=TargetRevision("different-target")),
            replace(result, checker="different-checker"),
            replace(result, rev="different-definitions"),
            replace(result, definition=replace(result.definition, claim="Different gate claim")),
            replace(result, proposal_revision=ProposalMaterialRevision("0" * 64)),
            replace(result, environment="different-environment"),
            replace(result, scope="different-scope"),
            replace(result, evidence=""),
            replace(result, by=""),
            replace(result, observed_at=int(time.time()) + 1800),
        ):
            with self.subTest(result=changed):
                atomic_write_json(gates_mod.gates_json_path(added.path), [encode_gate_result(changed)])
                report = validate.validate(self.root)
                self.assertFalse(report.ok)

    def test_unbound_historical_gate_does_not_authorize_applied_status(self):
        added = self._to_applied()
        result = gates_mod.load_results(added.path)[0]
        historical = {
            "gate": result.gate.val,
            "outcome": result.outcome.value,
            "evidence": result.evidence,
            "at": result.at,
            "by": result.by,
            "rev": result.rev,
        }
        atomic_write_json(gates_mod.gates_json_path(added.path), [historical])
        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(any(problem.category == "incomplete" for problem in report.problems))

    def test_material_edit_invalidates_recorded_acceptance(self):
        added = self._to_applied()
        read_document(added.path).update_section("Proposed change", "Different intent").write(added.path)
        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(any("revision" in problem.message for problem in report.problems))

    def test_malformed_gate_file_does_not_hide_other_proposals(self):
        added = self._to_applied()
        gates_mod.gates_json_path(added.path).write_text("{", encoding="utf-8")
        other = _add_reviewable(self.root, title="Another proposal")
        read_document(other.path).update_fields({"status": "accepted"}).write(other.path)
        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(any(problem.category == "malformed" for problem in report.problems))
        self.assertTrue(any(problem.where == other.id.val for problem in report.problems))
        self.assertEqual(report.counts.proposals, 2)

    def test_land_gate_alone_does_not_authorize_verified_status(self):
        added = self._to_applied()
        read_document(added.path).update_fields(
            {"status": "verified", "verifier": "reviewer", "last_actor": "reviewer"}
        ).write(added.path)
        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(any("gate" in problem.message for problem in report.problems))


class ProposalCandidateValidationTest(KctxTestCase):
    def test_hand_authored_proposed_record_requires_review_readiness(self):
        added = _add_reviewable(self.root)
        read_document(added.path).update_section("Research", "").write(added.path)
        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(any("readiness" in problem.message for problem in report.problems))

    def test_directory_home_cannot_claim_legacy_profile(self):
        added = _add_reviewable(self.root)
        read_document(added.path).update_fields({"profile": "legacy_limited"}).write(added.path)
        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(any(problem.category == "malformed" and "legacy" in problem.message for problem in report.problems))

    def test_supersession_uses_complete_resolving_acyclic_graph(self):
        first = _add_reviewable(self.root, title="First")
        second = _add_reviewable(self.root, title="Second")
        read_document(first.path).update_fields(
            {"status": "superseded", "superseded_by": second.id.val}
        ).write(first.path)
        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)
        read_document(second.path).update_fields(
            {"status": "superseded", "superseded_by": first.id.val}
        ).write(second.path)
        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(any("supersession" in problem.message for problem in report.problems))


class ProposalOriginValidationTest(KctxTestCase):
    def test_new_format_proposal_missing_origin_is_a_warning_not_a_problem(self):
        added = _add_reviewable(self.root, title="No origin on disk")
        path = proposals.load(self.root, added.id).path
        text = path.read_text(encoding="utf-8").replace("origin: user-request\n", "", 1)
        path.write_text(text, encoding="utf-8")

        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)
        self.assertTrue(
            any("missing origin" in w.message for w in report.warnings)
        )

    def test_legacy_proposal_without_origin_is_not_flagged(self):
        kind_dir = proposals.proposals_root(self.root) / "skill"
        kind_dir.mkdir(parents=True)
        path = kind_dir / "2026-10-01-legacy.md"
        fm = {
            "id": "skill/2026-10-01-legacy",
            "kind": "skill",
            "title": "Legacy",
            "status": "proposed",
            "created": "2026-10-01",
            "target": [],
            "references": [],
        }
        body = {
            "Context": "c",
            "Evidence": "e",
            "Proposed change": "ch",
            "Why general / justification": "w",
            "Decision log": "- 2026-10-01: proposed",
        }
        path.write_text(render_document({key: str(value) if value else "" for key, value in fm.items()}, body).text, encoding="utf-8")

        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(report.warnings, ())


class RelationshipEndpointValidationTest(KctxTestCase):
    def test_dangling_endpoint_is_flagged_not_crashed(self):
        inventory.asset_add(
            self.root, kind=AssetKind.SERVICE, name="only-one", id=AssetId("svc-only-one")
        )
        inventory.rel_add(
            self.root, type=RelationshipType.CONSUMES, from_=AssetId("svc-only-one"), to=AssetId("svc-missing")
        )

        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(any("svc-missing" in p.message for p in report.problems))


class KtloValidationTest(KctxTestCase):
    def test_ktlo_record_with_known_asset_is_ok(self):
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name="svc", id=AssetId("service-svc"))
        ktlo.new(self.root, ticket=TicketId("DRQS-1"), title="fine", assets=(AssetId("service-svc"),))

        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(report.counts.ktlo, 1)
        self.assertEqual(report.warnings, ())

    def test_ktlo_record_with_unknown_asset_is_a_problem_not_a_warning(self):
        ktlo.new(
            self.root, ticket=TicketId("DRQS-2"), title="dangling", assets=(AssetId("service-missing"),)
        )

        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(
            any("service-missing" in p.message for p in report.problems)
        )

    def test_ktlo_record_with_empty_assets_is_only_a_warning(self):
        ktlo.new(self.root, ticket=TicketId("DRQS-3"), title="no assets yet")

        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)
        self.assertTrue(
            any("assets list is empty" in w.message for w in report.warnings)
        )

    def test_duplicate_ticket_id_is_a_conflict(self):
        ktlo.new(self.root, ticket=TicketId("DRQS-4"), title="first")
        # Simulate a hand-authored second record reusing the same ticket id
        # under a different slug, rather than going through ktlo.new (which
        # already refuses an exact path collision).
        dup_path = ktlo.ktlo_root(self.root) / "2026" / "drqs-4-second.md"
        dup_path.parent.mkdir(parents=True, exist_ok=True)
        dup_path.write_text(
            render_document(
                {
                    "ticket": "DRQS-4",
                    "title": "second",
                    "assets": "[]",
                    "status": "todo",
                    "prs": "[]",
                    "summary": "",
                    "created": "2026-01-01",
                    "updated": "2026-01-01",
                    "promoted_to": None,
                },
                {s: "" for s in ktlo.SECTION_ORDER},
            ).text,
            encoding="utf-8",
        )

        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(
            any("duplicate ticket" in p.message for p in report.problems)
        )


class ChangeBriefValidationTest(KctxTestCase):
    def _write_brief(self, assets_line: str = "") -> None:
        changes_dir = self.root / "demo-project" / "changes"
        changes_dir.mkdir(parents=True)
        text = "---\n" + (f"{assets_line}\n" if assets_line else "") + "---\nbody\n"
        (changes_dir / "my-change.md").write_text(text, encoding="utf-8")

    def test_change_brief_with_known_asset_is_ok(self):
        inventory.asset_add(self.root, kind=AssetKind.SERVICE, name="svc", id=AssetId("service-svc"))
        self._write_brief("assets: [service-svc]")

        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(report.counts.changes, 1)

    def test_change_brief_with_unknown_asset_is_a_problem(self):
        self._write_brief("assets: [service-missing]")

        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(
            any("service-missing" in p.message for p in report.problems)
        )

    def test_change_brief_with_empty_assets_is_only_a_warning(self):
        self._write_brief("assets: []")

        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)
        self.assertTrue(
            any("assets list is empty" in w.message for w in report.warnings)
        )

    def test_change_brief_without_frontmatter_is_skipped_not_flagged(self):
        changes_dir = self.root / "demo-project" / "changes"
        changes_dir.mkdir(parents=True)
        (changes_dir / "freeform.md").write_text(
            "just prose, no frontmatter\n", encoding="utf-8"
        )

        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(report.warnings, ())


class InvestigationValidationTest(KctxTestCase):
    def test_well_formed_investigation_is_ok(self):
        inventory.asset_add(self.root, kind=AssetKind.ALERT, name="b1", id=AssetId("alert-b1"))
        sig_mod.new(self.root, "sig-x")
        result = inv_mod.new(self.root, "x", trigger=InvestigationTrigger.DRQS, alerts=(AssetId("alert-b1"),))
        found = inv_mod.load(self.root, result.id)
        fm = found.frontmatter
        fm = replace(fm, signatures=(SignatureId("sig-x"),))
        found.path.write_text(inv_mod.render(fm, dict(found.body)), encoding="utf-8")

        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(report.counts.investigations, 1)
        self.assertEqual(report.counts.signatures, 1)

    def test_unknown_alert_is_a_problem(self):
        inv_mod.new(self.root, "x", trigger=InvestigationTrigger.DRQS, alerts=(AssetId("alert-no-such"),))
        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(
            any("alert-no-such" in p.message for p in report.problems)
        )

    def test_unknown_signature_is_a_problem(self):
        result = inv_mod.new(self.root, "x", trigger=InvestigationTrigger.ADHOC)
        found = inv_mod.load(self.root, result.id)
        fm = found.frontmatter
        fm = replace(fm, signatures=(SignatureId("no-such-signature"),))
        found.path.write_text(inv_mod.render(fm, dict(found.body)), encoding="utf-8")
        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(
            any("no-such-signature" in p.message for p in report.problems)
        )

    def test_concluded_without_checked_against_is_a_problem(self):
        result = inv_mod.new(self.root, "x", trigger=InvestigationTrigger.ADHOC)
        found = inv_mod.load(self.root, result.id)
        fm, body = found.frontmatter, dict(found.body)
        fm = replace(fm, status=InvestigationStatus.CONCLUDED)
        body["Scope and limits"] = "n/a"
        found.path.write_text(inv_mod.render(fm, body), encoding="utf-8")

        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(
            any("Checked against" in p.message for p in report.problems)
        )

    def test_concluded_with_open_hypothesis_is_a_problem(self):
        result = inv_mod.new(self.root, "x", trigger=InvestigationTrigger.ADHOC)
        found = inv_mod.load(self.root, result.id)
        fm, body = found.frontmatter, dict(found.body)
        fm = replace(fm, status=InvestigationStatus.CONCLUDED)
        body["Checked against"] = "usr@2026-10-25 confirmed"
        body["Scope and limits"] = "n/a"
        body["Hypotheses"] = "- H1: open — still unresolved"
        found.path.write_text(inv_mod.render(fm, body), encoding="utf-8")

        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(any("H1" in p.message for p in report.problems))

    def test_properly_concluded_investigation_is_ok(self):
        result = inv_mod.new(self.root, "x", trigger=InvestigationTrigger.ADHOC)
        found = inv_mod.load(self.root, result.id)
        fm, body = found.frontmatter, dict(found.body)
        body["Checked against"] = "usr@2026-10-25 confirmed"
        body["Scope and limits"] = "n/a"
        found.path.write_text(inv_mod.render(fm, body), encoding="utf-8")
        inv_mod.conclude(self.root, result.id)

        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)

    def test_conclusion_uses_actual_hypothesis_text_and_allows_unknown(self):
        added = inv_mod.new(self.root, "unknown", trigger=InvestigationTrigger.ADHOC)
        document = read_document(added.path)
        document = document.update_section("Checked against", "Reviewed by operator")
        document = document.update_section("Scope and limits", "Only the sampled window")
        document = document.update_section(
            "Hypotheses",
            "- H1: unk — missing runtime evidence\n\n```text\n- H2: open — fenced example\n```",
        )
        document.write(added.path)
        hypotheses = inv_mod.parse_hypotheses(document.sections["Hypotheses"])
        self.assertEqual(len(hypotheses), 1)
        self.assertIn("missing runtime evidence", hypotheses[0].text)
        inv_mod.conclude(self.root, added.id)
        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)

    def test_malformed_hypothesis_does_not_hide_later_investigation(self):
        broken = inv_mod.new(self.root, "broken-hypothesis", trigger=InvestigationTrigger.ADHOC)
        read_document(broken.path).update_section("Hypotheses", "- H1: made-up — invalid").write(broken.path)
        inv_mod.new(
            self.root, "later-investigation", trigger=InvestigationTrigger.ADHOC,
            assets=(AssetId("service-missing"),),
        )
        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(any(problem.category == "malformed" and "hypothesis" in problem.message for problem in report.problems))
        self.assertTrue(any("service-missing" in problem.message for problem in report.problems))
        self.assertEqual(report.counts.investigations, 2)


class SignatureValidationTest(KctxTestCase):
    def test_bad_status_is_a_problem(self):
        sig_mod.new(self.root, "x")
        path = self.root / "signatures" / "x.md"
        text = path.read_text(encoding="utf-8").replace(
            "status: suspected", "status: not-a-real-status"
        )
        path.write_text(text, encoding="utf-8")

        report = validate.validate(self.root)
        self.assertFalse(report.ok)

    def test_unknown_asset_is_a_problem(self):
        sig_mod.new(self.root, "x", assets=(AssetId("asset-no-such"),))
        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(
            any("asset-no-such" in p.message for p in report.problems)
        )


class RunbookValidationTest(KctxTestCase):
    def test_bad_layer_is_a_problem(self):
        runbook_dir = self.root / "runbooks" / "workflow"
        runbook_dir.mkdir(parents=True)
        (runbook_dir / "x.md").write_text(
            "---\nlayer: not-a-layer\n---\n\n# x\n", encoding="utf-8"
        )
        report = validate.validate(self.root)
        self.assertFalse(report.ok)

    def test_known_asset_reference_is_ok(self):
        inventory.asset_add(self.root, kind=AssetKind.ALERT, name="b1", id=AssetId("alert-b1"))
        runbook_dir = self.root / "runbooks" / "workflow"
        runbook_dir.mkdir(parents=True)
        (runbook_dir / "x.md").write_text(
            "---\nlayer: workflow\nalerts: [alert-b1]\n---\n\n# x\n",
            encoding="utf-8",
        )
        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)

    def test_frontmatter_free_runbook_is_skipped_not_flagged(self):
        runbook_dir = self.root / "runbooks" / "workflow"
        runbook_dir.mkdir(parents=True)
        (runbook_dir / "x.md").write_text(
            "just prose, no frontmatter\n", encoding="utf-8"
        )
        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)


class RegressionFlagValidationTest(KctxTestCase):
    def test_regression_is_a_warning_not_a_problem(self):
        sig_mod.new(self.root, "fixed-sig", status=SignatureStatus.FIXED, fixed_at="2026-01-01")
        inv_mod.new(self.root, "after-fix", trigger=InvestigationTrigger.ADHOC, created="2026-06-01")
        found = inv_mod.load(self.root, InvestigationId("2026/2026-06-01-after-fix"))
        fm = found.frontmatter
        fm = replace(fm, signatures=(SignatureId("fixed-sig"),))
        found.path.write_text(inv_mod.render(fm, dict(found.body)), encoding="utf-8")

        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)
        self.assertTrue(
            any("possible regression" in w.message for w in report.warnings)
        )


class CorrectionsValidationTest(KctxTestCase):
    def test_well_formed_corrections_record_is_ok(self):
        sig_mod.new(self.root, "x")
        corrections_mod.retract(self.root, corrections_mod.parse_correction_target("sig:x"), reason="wrong", kind=CorrectionKind.RETRACT)
        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(report.counts.corrections, 1)

    def test_unresolved_target_is_a_problem(self):
        corrections_dir = self.root / "corrections"
        corrections_dir.mkdir()
        (corrections_dir / "2026-01-01-nothing.md").write_text(
            "---\n"
            "target: sig:no-such-signature\n"
            "target_kind: signature\n"
            "kind: retract\n"
            "reason: x\n"
            "by_replacement: \n"
            "created: 2026-01-01\n"
            "---\n\n"
            "(no known referrers at time of retraction)\n",
            encoding="utf-8",
        )
        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(
            any("does not resolve" in p.message for p in report.problems)
        )

    def test_bad_row_status_is_a_problem(self):
        sig_mod.new(self.root, "x")
        corrections_dir = self.root / "corrections"
        corrections_dir.mkdir()
        (corrections_dir / "2026-01-01-x.md").write_text(
            "---\n"
            "target: sig:x\n"
            "target_kind: signature\n"
            "kind: retract\n"
            "reason: x\n"
            "by_replacement: \n"
            "created: 2026-01-01\n"
            "---\n\n"
            "| file | kind | status | owner |\n"
            "|---|---|---|---|\n"
            "| signatures/x.md | signature | made-up-status | |\n",
            encoding="utf-8",
        )
        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertTrue(
            any("bad row status" in p.message for p in report.problems)
        )

    def test_unchanged_with_evidence_suffix_is_a_valid_status(self):
        sig_mod.new(self.root, "x")
        corrections_dir = self.root / "corrections"
        corrections_dir.mkdir()
        (corrections_dir / "2026-01-01-x.md").write_text(
            "---\n"
            "target: sig:x\n"
            "target_kind: signature\n"
            "kind: retract\n"
            "reason: x\n"
            "by_replacement: \n"
            "created: 2026-01-01\n"
            "---\n\n"
            "| file | kind | status | owner |\n"
            "|---|---|---|---|\n"
            "| signatures/x.md | signature | unchanged:re-verified 2026-01-02 | |\n",
            encoding="utf-8",
        )
        report = validate.validate(self.root)
        self.assertTrue(report.ok, report.problems)


class MalformedRecordAggregationTest(KctxTestCase):
    def test_malformed_records_do_not_hide_later_records_or_families(self):
        asset = inventory.asset_add(
            self.root, kind=AssetKind.SERVICE, name="valid", id=AssetId("service-valid")
        )
        asset_dir = self.root / "inventory" / "assets"
        (asset_dir / "00-malformed.json").write_text("{", encoding="utf-8")
        (asset_dir / "01-invalid-enum.json").write_text(
            '{"id":"service-invalid","name":"bad","kind":"not-a-kind"}',
            encoding="utf-8",
        )
        inventory.rel_add(
            self.root, type=RelationshipType.CONSUMES,
            from_=asset.id, to=AssetId("service-missing"),
        )
        relationships = self.root / "inventory" / "relationships"
        (relationships / "00-malformed.json").write_text("[]", encoding="utf-8")

        proposal = _add_reviewable(self.root)
        proposal.path.write_text("---\nid: invalid\n", encoding="utf-8")
        signature = sig_mod.new(self.root, "broken")
        signature.path.write_text("---\nid: broken\nstatus: impossible\n---\n", encoding="utf-8")
        sig_mod.new(self.root, "valid", assets=(AssetId("service-missing"),))
        investigation = inv_mod.new(self.root, "broken", trigger=InvestigationTrigger.ADHOC)
        investigation.path.write_text("---\nid: broken\n", encoding="utf-8")
        inv_mod.new(self.root, "valid", trigger=InvestigationTrigger.ADHOC, assets=(AssetId("service-missing"),))
        ticket = ktlo.new(self.root, ticket=TicketId("DRQS-9"), title="broken")
        ticket.path.write_text("---\nticket:\n---\n", encoding="utf-8")
        ktlo.new(self.root, ticket=TicketId("DRQS-10"), title="valid")

        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        malformed = [problem for problem in report.problems if problem.category == "malformed"]
        self.assertGreaterEqual(len(malformed), 7)
        self.assertGreaterEqual(
            sum("service-missing" in problem.message for problem in report.problems), 3
        )
        self.assertTrue(any("assets list is empty" in warning.message for warning in report.warnings))
        self.assertEqual(report.counts.assets, 3)
        self.assertEqual(report.counts.relationships, 2)
        self.assertEqual(report.counts.proposals, 1)
        self.assertEqual(report.counts.signatures, 2)
        self.assertEqual(report.counts.investigations, 2)
        self.assertEqual(report.counts.ktlo, 2)

    def test_malformed_documents_do_not_abort_other_document_checks(self):
        for relative in (
            "runbooks/workflow/00-broken.md",
            "demo-project/changes/00-broken.md",
            "inventory/dossiers/00-broken.md",
            "corrections/00-broken.md",
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("---\nid: broken\n", encoding="utf-8")
        runbook = self.root / "runbooks/workflow/01-valid.md"
        runbook.write_text("---\nassets: [service-missing]\n---\n", encoding="utf-8")
        change = self.root / "demo-project/changes/01-valid.md"
        change.write_text("---\nassets: []\n---\n", encoding="utf-8")

        report = validate.validate(self.root)
        self.assertFalse(report.ok)
        self.assertGreaterEqual(
            sum(problem.category == "malformed" for problem in report.problems), 4
        )
        self.assertTrue(any("service-missing" in problem.message for problem in report.problems))
        self.assertTrue(any("assets list is empty" in warning.message for warning in report.warnings))
        self.assertEqual(report.counts.changes, 2)
        self.assertEqual(report.counts.corrections, 1)

    def test_wire_report_preserves_cli_shape(self):
        report = validate.validate(self.root)
        wire = validate.result_to_wire(report)
        self.assertEqual(wire["ok"], report.ok)
        self.assertEqual(wire["problems"], [])
        self.assertEqual(wire["warnings"], [])
        self.assertEqual(
            wire["counts"],
            {
                "assets": 0, "relationships": 0, "proposals": 0, "ktlo": 0,
                "changes": 0, "investigations": 0, "signatures": 0,
                "dossiers": 0, "corrections": 0,
            },
        )
