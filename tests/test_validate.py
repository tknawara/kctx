from _base import KctxTestCase

import corrections as corrections_mod
import inventory
import investigations as inv_mod
import ktlo
import proposals
import signatures as sig_mod
import validate


GATES_TABLE = (
    "| id | claim | check | when | by |\n"
    "|---|---|---|---|---|\n"
    "| G1 | it works | `true` | land | agent |\n"
)


def _add_reviewable(root, **overrides):
    kwargs = dict(
        kind="steward",
        origin="user-request",
        title="Some idea",
        context="c",
        evidence="e",
        change="ch",
        why="w",
        research="researched",
        alternatives="- A. do nothing\n- B. do it",
        gates=GATES_TABLE,
    )
    kwargs.update(overrides)
    return proposals.add(root, **kwargs)


class ProposalDecisionValidationTest(KctxTestCase):
    """Q07/Q25: an unmerged/unaccepted proposal must never read as an
    accepted decision. A freshly added proposal stays status=proposed (never
    accepted), and validate flags any accepted/applied proposal that lacks
    decided_by — the only way a proposal becomes team policy."""

    def test_q07_new_proposal_is_proposed_not_accepted(self):
        result = _add_reviewable(self.root)
        fm = proposals.load(self.root, result["id"])["frontmatter"]
        self.assertEqual(fm["status"], "proposed")

        listed_proposed = proposals.list_proposals(self.root, status="proposed")
        listed_accepted = proposals.list_proposals(self.root, status="accepted")
        self.assertEqual(len(listed_proposed), 1)
        self.assertEqual(listed_accepted, [])

        report = validate.validate(self.root)
        self.assertTrue(report["ok"], report["problems"])

    def test_q07_validate_flags_accepted_without_decided_by(self):
        result = _add_reviewable(self.root, title="Needs a decision")
        # Simulate a record that reached "accepted" without going through
        # set_status (e.g. a hand edit or a bug) -- decided_by is empty.
        path = proposals.load(self.root, result["id"])["path"]
        text = path.read_text(encoding="utf-8").replace(
            "status: proposed", "status: accepted", 1
        )
        path.write_text(text, encoding="utf-8")

        report = validate.validate(self.root)
        self.assertFalse(report["ok"])
        messages = [p["message"] for p in report["problems"]]
        self.assertTrue(any("decided_by" in m for m in messages))

    def test_set_status_accepted_requires_by(self):
        from errors import KctxError

        result = _add_reviewable(self.root, title="Needs by")
        with self.assertRaises(KctxError) as ctx:
            proposals.set_status(self.root, result["id"], status="accepted")
        self.assertEqual(ctx.exception.category, "incomplete")

        fm = proposals.set_status(
            self.root, result["id"], status="accepted", by="user 2026-10-23"
        )
        self.assertEqual(fm["decided_by"], "user 2026-10-23")

        report = validate.validate(self.root)
        self.assertTrue(report["ok"], report["problems"])


class ProposalLandedValidationTest(KctxTestCase):
    """An applied/verified proposal must point at what actually landed --
    either `landed` or a repo@sha token in the Decision log -- so applied
    can't mean 'nobody wrote down what shipped'."""

    def _to_applied(self, root, title="Lands somewhere", note=None):
        added = _add_reviewable(root, title=title)
        pid = added["id"]
        proposals.set_status(root, pid, status="accepted", by="user")
        proposals.set_status(root, pid, status="landing", by="agent")
        proposals.gate(root, pid, "G1", outcome="pass", evidence="obs:1")
        return proposals.set_status(root, pid, status="applied", by="agent", note=note)

    def test_applied_with_landed_field_is_ok(self):
        added = _add_reviewable(self.root, title="Lands with field")
        pid = added["id"]
        proposals.set_status(self.root, pid, status="accepted", by="user")
        proposals.set_status(self.root, pid, status="landing", by="agent")
        proposals.gate(self.root, pid, "G1", outcome="pass", evidence="obs:1")
        proposals.set_status(self.root, pid, status="applied", by="agent")
        proposals.set_status(self.root, pid, landed_add=["dotfiles@abc1234"])

        report = validate.validate(self.root)
        self.assertTrue(report["ok"], report["problems"])

    def test_applied_with_note_token_is_ok(self):
        self._to_applied(
            self.root, title="Lands via note", note="shipped — dotfiles@abc1234"
        )
        report = validate.validate(self.root)
        self.assertTrue(report["ok"], report["problems"])

    def test_applied_without_landed_or_note_is_a_problem(self):
        found_id = self._to_applied(self.root, title="Lands nowhere written down")["id"]
        # The happy-path set_status call never writes a repo@sha itself --
        # applied only needs --by, not a note -- so this should already be a
        # problem; assert it explicitly in case that changes.
        report = validate.validate(self.root)
        self.assertFalse(report["ok"])
        messages = [p["message"] for p in report["problems"]]
        self.assertTrue(any("landed" in m for m in messages))


class ProposalOriginValidationTest(KctxTestCase):
    def test_new_format_proposal_missing_origin_is_a_warning_not_a_problem(self):
        added = _add_reviewable(self.root, title="No origin on disk")
        path = proposals.load(self.root, added["id"])["path"]
        text = path.read_text(encoding="utf-8").replace("origin: user-request\n", "", 1)
        path.write_text(text, encoding="utf-8")

        report = validate.validate(self.root)
        self.assertTrue(report["ok"], report["problems"])
        self.assertTrue(
            any("missing origin" in w["message"] for w in report["warnings"])
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
        path.write_text(proposals.render(fm, body), encoding="utf-8")

        report = validate.validate(self.root)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["warnings"], [])


class RelationshipEndpointValidationTest(KctxTestCase):
    def test_dangling_endpoint_is_flagged_not_crashed(self):
        inventory.asset_add(
            self.root, kind="service", name="only-one", id="svc-only-one"
        )
        inventory.rel_add(
            self.root, type="consumes", from_="svc-only-one", to="svc-missing"
        )

        report = validate.validate(self.root)
        self.assertFalse(report["ok"])
        self.assertTrue(any("svc-missing" in p["message"] for p in report["problems"]))


class KtloValidationTest(KctxTestCase):
    def test_ktlo_record_with_known_asset_is_ok(self):
        inventory.asset_add(self.root, kind="service", name="svc", id="service-svc")
        ktlo.new(self.root, ticket="DRQS 1", title="fine", assets=["service-svc"])

        report = validate.validate(self.root)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["counts"]["ktlo"], 1)
        self.assertEqual(report["warnings"], [])

    def test_ktlo_record_with_unknown_asset_is_a_problem_not_a_warning(self):
        ktlo.new(
            self.root, ticket="DRQS 2", title="dangling", assets=["service-missing"]
        )

        report = validate.validate(self.root)
        self.assertFalse(report["ok"])
        self.assertTrue(
            any("service-missing" in p["message"] for p in report["problems"])
        )

    def test_ktlo_record_with_empty_assets_is_only_a_warning(self):
        ktlo.new(self.root, ticket="DRQS 3", title="no assets yet")

        report = validate.validate(self.root)
        self.assertTrue(report["ok"], report["problems"])
        self.assertTrue(
            any("assets list is empty" in w["message"] for w in report["warnings"])
        )

    def test_duplicate_ticket_id_is_a_conflict(self):
        ktlo.new(self.root, ticket="DRQS 4", title="first")
        # Simulate a hand-authored second record reusing the same ticket id
        # under a different slug, rather than going through ktlo.new (which
        # already refuses an exact path collision).
        dup_path = ktlo.ktlo_root(self.root) / "2026" / "drqs-4-second.md"
        dup_path.parent.mkdir(parents=True, exist_ok=True)
        dup_path.write_text(
            ktlo.render(
                {
                    "ticket": "DRQS-4",
                    "title": "second",
                    "assets": [],
                    "status": "todo",
                    "prs": [],
                    "summary": "",
                    "created": "2026-01-01",
                    "updated": "2026-01-01",
                    "promoted_to": None,
                },
                {s: "" for s in ktlo.SECTION_ORDER},
            ),
            encoding="utf-8",
        )

        report = validate.validate(self.root)
        self.assertFalse(report["ok"])
        self.assertTrue(
            any("duplicate ticket" in p["message"] for p in report["problems"])
        )


class ChangeBriefValidationTest(KctxTestCase):
    def _write_brief(self, assets_line: str = "") -> None:
        changes_dir = self.root / "demo-project" / "changes"
        changes_dir.mkdir(parents=True)
        text = "---\n" + (f"{assets_line}\n" if assets_line else "") + "---\nbody\n"
        (changes_dir / "my-change.md").write_text(text, encoding="utf-8")

    def test_change_brief_with_known_asset_is_ok(self):
        inventory.asset_add(self.root, kind="service", name="svc", id="service-svc")
        self._write_brief("assets: [service-svc]")

        report = validate.validate(self.root)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["counts"]["changes"], 1)

    def test_change_brief_with_unknown_asset_is_a_problem(self):
        self._write_brief("assets: [service-missing]")

        report = validate.validate(self.root)
        self.assertFalse(report["ok"])
        self.assertTrue(
            any("service-missing" in p["message"] for p in report["problems"])
        )

    def test_change_brief_with_empty_assets_is_only_a_warning(self):
        self._write_brief("assets: []")

        report = validate.validate(self.root)
        self.assertTrue(report["ok"], report["problems"])
        self.assertTrue(
            any("assets list is empty" in w["message"] for w in report["warnings"])
        )

    def test_change_brief_without_frontmatter_is_skipped_not_flagged(self):
        changes_dir = self.root / "demo-project" / "changes"
        changes_dir.mkdir(parents=True)
        (changes_dir / "freeform.md").write_text(
            "just prose, no frontmatter\n", encoding="utf-8"
        )

        report = validate.validate(self.root)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["warnings"], [])


class InvestigationValidationTest(KctxTestCase):
    def test_well_formed_investigation_is_ok(self):
        inventory.asset_add(self.root, kind="alert", name="b1", id="alert-b1")
        sig_mod.new(self.root, "sig-x")
        result = inv_mod.new(self.root, "x", trigger="drqs", alerts=["alert-b1"])
        found = inv_mod.load(self.root, result["id"])
        fm = found["frontmatter"]
        fm["signatures"] = ["sig-x"]
        found["path"].write_text(inv_mod.render(fm, found["body"]), encoding="utf-8")

        report = validate.validate(self.root)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["counts"]["investigations"], 1)
        self.assertEqual(report["counts"]["signatures"], 1)

    def test_unknown_alert_is_a_problem(self):
        inv_mod.new(self.root, "x", trigger="drqs", alerts=["alert-no-such"])
        report = validate.validate(self.root)
        self.assertFalse(report["ok"])
        self.assertTrue(
            any("alert-no-such" in p["message"] for p in report["problems"])
        )

    def test_unknown_signature_is_a_problem(self):
        result = inv_mod.new(self.root, "x", trigger="adhoc")
        found = inv_mod.load(self.root, result["id"])
        fm = found["frontmatter"]
        fm["signatures"] = ["no-such-signature"]
        found["path"].write_text(inv_mod.render(fm, found["body"]), encoding="utf-8")
        report = validate.validate(self.root)
        self.assertFalse(report["ok"])
        self.assertTrue(
            any("no-such-signature" in p["message"] for p in report["problems"])
        )

    def test_concluded_without_checked_against_is_a_problem(self):
        result = inv_mod.new(self.root, "x", trigger="adhoc")
        found = inv_mod.load(self.root, result["id"])
        fm, body = found["frontmatter"], found["body"]
        fm["status"] = "concluded"
        body["Scope and limits"] = "n/a"
        found["path"].write_text(inv_mod.render(fm, body), encoding="utf-8")

        report = validate.validate(self.root)
        self.assertFalse(report["ok"])
        self.assertTrue(
            any("Checked against" in p["message"] for p in report["problems"])
        )

    def test_concluded_with_open_hypothesis_is_a_problem(self):
        result = inv_mod.new(self.root, "x", trigger="adhoc")
        found = inv_mod.load(self.root, result["id"])
        fm, body = found["frontmatter"], found["body"]
        fm["status"] = "concluded"
        body["Checked against"] = "usr@2026-10-25 confirmed"
        body["Scope and limits"] = "n/a"
        body["Hypotheses"] = "- H1: open — still unresolved"
        found["path"].write_text(inv_mod.render(fm, body), encoding="utf-8")

        report = validate.validate(self.root)
        self.assertFalse(report["ok"])
        self.assertTrue(any("H1" in p["message"] for p in report["problems"]))

    def test_properly_concluded_investigation_is_ok(self):
        result = inv_mod.new(self.root, "x", trigger="adhoc")
        found = inv_mod.load(self.root, result["id"])
        fm, body = found["frontmatter"], found["body"]
        body["Checked against"] = "usr@2026-10-25 confirmed"
        body["Scope and limits"] = "n/a"
        found["path"].write_text(inv_mod.render(fm, body), encoding="utf-8")
        inv_mod.conclude(self.root, result["id"])

        report = validate.validate(self.root)
        self.assertTrue(report["ok"], report["problems"])


class SignatureValidationTest(KctxTestCase):
    def test_bad_status_is_a_problem(self):
        sig_mod.new(self.root, "x")
        path = self.root / "signatures" / "x.md"
        text = path.read_text(encoding="utf-8").replace(
            "status: suspected", "status: not-a-real-status"
        )
        path.write_text(text, encoding="utf-8")

        report = validate.validate(self.root)
        self.assertFalse(report["ok"])

    def test_unknown_asset_is_a_problem(self):
        sig_mod.new(self.root, "x", assets=["asset-no-such"])
        report = validate.validate(self.root)
        self.assertFalse(report["ok"])
        self.assertTrue(
            any("asset-no-such" in p["message"] for p in report["problems"])
        )


class RunbookValidationTest(KctxTestCase):
    def test_bad_layer_is_a_problem(self):
        runbook_dir = self.root / "runbooks" / "workflow"
        runbook_dir.mkdir(parents=True)
        (runbook_dir / "x.md").write_text(
            "---\nlayer: not-a-layer\n---\n\n# x\n", encoding="utf-8"
        )
        report = validate.validate(self.root)
        self.assertFalse(report["ok"])

    def test_known_asset_reference_is_ok(self):
        inventory.asset_add(self.root, kind="alert", name="b1", id="alert-b1")
        runbook_dir = self.root / "runbooks" / "workflow"
        runbook_dir.mkdir(parents=True)
        (runbook_dir / "x.md").write_text(
            "---\nlayer: workflow\nalerts: [alert-b1]\n---\n\n# x\n",
            encoding="utf-8",
        )
        report = validate.validate(self.root)
        self.assertTrue(report["ok"], report["problems"])

    def test_frontmatter_free_runbook_is_skipped_not_flagged(self):
        runbook_dir = self.root / "runbooks" / "workflow"
        runbook_dir.mkdir(parents=True)
        (runbook_dir / "x.md").write_text(
            "just prose, no frontmatter\n", encoding="utf-8"
        )
        report = validate.validate(self.root)
        self.assertTrue(report["ok"], report["problems"])


class RegressionFlagValidationTest(KctxTestCase):
    def test_regression_is_a_warning_not_a_problem(self):
        sig_mod.new(self.root, "fixed-sig", status="fixed", fixed_at="2026-01-01")
        inv_mod.new(self.root, "after-fix", trigger="adhoc", created="2026-06-01")
        found = inv_mod.load(self.root, "2026/2026-06-01-after-fix")
        fm = found["frontmatter"]
        fm["signatures"] = ["fixed-sig"]
        found["path"].write_text(inv_mod.render(fm, found["body"]), encoding="utf-8")

        report = validate.validate(self.root)
        self.assertTrue(report["ok"], report["problems"])
        self.assertTrue(
            any("possible regression" in w["message"] for w in report["warnings"])
        )


class CorrectionsValidationTest(KctxTestCase):
    def test_well_formed_corrections_record_is_ok(self):
        sig_mod.new(self.root, "x")
        corrections_mod.retract(self.root, "sig:x", reason="wrong", kind="retract")
        report = validate.validate(self.root)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["counts"]["corrections"], 1)

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
        self.assertFalse(report["ok"])
        self.assertTrue(
            any("does not resolve" in p["message"] for p in report["problems"])
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
        self.assertFalse(report["ok"])
        self.assertTrue(
            any("bad row status" in p["message"] for p in report["problems"])
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
        self.assertTrue(report["ok"], report["problems"])
