"""Durable-event ordering and lossless correction target mutation contracts."""
import io
import json
from contextlib import redirect_stdout
from unittest import mock

from _base import KctxTestCase

from kctx.cli import app
from kctx.domain.corrections import CorrectionTargetKind, UnchangedReview
from kctx.domain.ids import AssetId, EvidenceId, OperationId, SignatureId
from kctx.domain.targets import DossierRef, EvidenceRef, SigRef
from kctx.domain.vocabulary import CorrectionKind, CorrectionRowStatus
from kctx.errors import KctxError
from kctx.services import corrections, signatures


class RetractOrderingTest(KctxTestCase):
    def _dossier(self):
        (self.root / "inventory" / "assets").mkdir(parents=True)
        (self.root / "inventory" / "assets" / "a1.json").write_text(
            '{"id":"a1","kind":"service","name":"Asset One","locator":"x",'
            '"owner":"o","owner_source":"s","schema_version":1}', encoding="utf-8")
        path = self.root / "inventory" / "dossiers" / "a1.md"
        path.parent.mkdir(parents=True)
        path.write_text("---\nasset: a1\nupdated: 2026-01-01\n---\n\n## Purpose\n\nDoes things.\n", encoding="utf-8")
        return path

    def test_correction_event_survives_target_append_failure(self):
        self._dossier()
        original_write = corrections.compare_and_write

        def flaky(path, data, *, expected):
            if path.name == "a1.md":
                raise OSError("disk simulated failure during target update")
            return original_write(path, data, expected=expected)

        with mock.patch.object(corrections, "compare_and_write", flaky):
            with self.assertRaises(OSError):
                corrections.retract(self.root, DossierRef(AssetId("a1")), reason="no longer true", kind=CorrectionKind.DISPUTE)
        records = corrections.all_paths(self.root)
        self.assertEqual(len(records), 1)
        parsed = corrections.parse(records[0].read_text(encoding="utf-8"))
        self.assertEqual(parsed.frontmatter.target, DossierRef(AssetId("a1")))
        self.assertIs(parsed.frontmatter.kind, CorrectionKind.DISPUTE)
        if parsed.rows:
            self.assertIs(parsed.rows[0].status, CorrectionRowStatus.PENDING)
        else:
            self.assertIn("no known referrers", records[0].read_text(encoding="utf-8"))

    def test_retract_writes_event_before_mutating_target(self):
        dossier = self._dossier()
        order = []
        event_write, projection_write = corrections.atomic_write_bytes, corrections.compare_and_write

        def record_event(path, data, *, exclusive=False):
            order.append("event")
            return event_write(path, data, exclusive=exclusive)

        def record_projection(path, data, *, expected):
            order.append("target" if path.name == "a1.md" else "tasks")
            return projection_write(path, data, expected=expected)

        with mock.patch.object(corrections, "atomic_write_bytes", record_event), mock.patch.object(corrections, "compare_and_write", record_projection):
            result = corrections.retract(self.root, DossierRef(AssetId("a1")), reason="superseded by b", kind=CorrectionKind.SUPERSEDE)
        self.assertEqual(order, ["event", "tasks", "target"])
        self.assertIs(result.target_kind, CorrectionTargetKind.DOSSIER)
        self.assertEqual(corrections.result_to_wire(result)["target_kind"], "dossier")
        self.assertIn("## Corrections", dossier.read_text(encoding="utf-8"))

    def test_referrers_are_snapshotted_before_target_update(self):
        dossier = self._dossier()
        before = dossier.read_bytes()

        def uses(root, target):
            self.assertEqual(dossier.read_bytes(), before)
            return {"target": target.spelling, "referrers": [{"file": "project/README.md", "kind": "project"}, {"file": "inventory/dossiers/a1.md", "kind": "dossier", "self": True}], "by_kind": {}, "note": ""}

        with mock.patch("kctx.services.corrections.backlinks.uses", uses):
            result = corrections.retract(self.root, DossierRef(AssetId("a1")), reason="changed", kind=CorrectionKind.DISPUTE)
        self.assertEqual(len(result.referrers), 1)
        event = corrections.parse((self.root / result.corrections_file).read_text())
        self.assertIs(event.rows[0].status, CorrectionRowStatus.PENDING)

    def test_unsupported_target_and_empty_reason_refuse_before_event(self):
        with self.assertRaises(KctxError):
            corrections.parse_correction_target("inv:2026/2026-01-01-x")
        with self.assertRaises(KctxError):
            corrections.retract(self.root, DossierRef(AssetId("a1")), reason=" ", kind=CorrectionKind.RETRACT)
        self.assertEqual(corrections.all_paths(self.root), ())

    def test_signature_correction_preserves_crlf_unknown_and_fenced_headings(self):
        created = signatures.new(self.root, "failure")
        original = (created.path.read_text() + "\n## Custom\n\n```md\n## Corrections\n```\nopaque\n").replace("\n", "\r\n")
        created.path.write_bytes(original.encode())
        corrections.retract(self.root, SigRef(SignatureId("failure")), reason="incorrect", kind=CorrectionKind.RETRACT)
        actual = created.path.read_bytes().decode()
        self.assertTrue(actual.startswith(original))
        self.assertIn("## Corrections\r\n\r\n- ", actual[len(original):])
        self.assertNotIn("\n", actual.replace("\r\n", ""))

    def test_evidence_placeholder_update_preserves_following_section(self):
        path = self.root / "project" / "evidence" / "sample.md"
        path.parent.mkdir(parents=True)
        path.write_text("---\nsummary: sample\n---\n\n## Corrections\n\nnone\n\n## Custom\n\nkeep me\n")
        corrections.retract(self.root, EvidenceRef("project", EvidenceId("sample")), reason="incorrect", kind=CorrectionKind.RETRACT)
        text = path.read_text()
        self.assertIn("## Custom\n\nkeep me\n", text)
        self.assertNotIn("\nnone\n", text)
        self.assertLess(text.index("retract — incorrect"), text.index("## Custom"))

    def test_proposal_correction_appends_only_decision_log_and_update(self):
        path = self.root / "proposals" / "config" / "2026-01-01-change" / "proposal.md"
        path.parent.mkdir(parents=True)
        original = "---\nid: config/2026-01-01-change\nkind: config\ntitle: change\nstatus: draft\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\n\n## Decision log\n\nold decision\n\n## Custom\n\nopaque\n"
        path.write_text(original)
        target = corrections.parse_correction_target("proposal/config/2026-01-01-change")
        corrections.retract(self.root, target, reason="wrong", kind=CorrectionKind.DISPUTE)
        actual = path.read_text()
        self.assertIn("old decision\n- ", actual)
        self.assertIn("dispute — wrong\n\n## Custom\n\nopaque\n", actual)
        self.assertEqual(actual.split("## Decision log")[0].split("updated:")[0],
                         original.split("## Decision log")[0].split("updated:")[0])

    def test_unchanged_review_is_distinct_and_fenced_rows_ignored(self):
        text = "---\ntarget: a1\ntarget_kind: dossier\nkind: dispute\n---\n\n```md\n| file | kind | status | owner |\n| hidden | note | invalid | x |\n```\n\n| file | kind | status | owner |\n|---|---|---|---|\n| p.md | note | unchanged:ev:x/y | me |\n"
        parsed = corrections.parse(text)
        self.assertEqual(len(parsed.rows), 1)
        self.assertEqual(parsed.rows[0].status, UnchangedReview("ev:x/y"))

    def test_same_input_retry_reuses_event_and_repairs_interrupted_target(self):
        dossier = self._dossier()
        original = corrections.compare_and_write

        def fail_target(path, content, *, expected):
            if path == dossier:
                raise OSError("target interrupted")
            return original(path, content, expected=expected)

        with mock.patch.object(corrections, "compare_and_write", fail_target):
            with self.assertRaises(OSError):
                corrections.retract(self.root, DossierRef(AssetId("a1")), reason="wrong", kind=CorrectionKind.DISPUTE)
        events = tuple((self.root / "corrections" / ".events").glob("*.json"))
        self.assertEqual(len(events), 1)
        retained = events[0].read_bytes()
        with mock.patch.object(corrections.backlinks, "uses", side_effect=AssertionError("must not rediscover")):
            result = corrections.retract(self.root, DossierRef(AssetId("a1")), reason="wrong", kind=CorrectionKind.DISPUTE)
            corrections.recover(self.root)
        self.assertEqual(events[0].read_bytes(), retained)
        self.assertEqual(len(corrections.all_paths(self.root)), 1)
        self.assertEqual(dossier.read_text().count("dispute — wrong"), 1)
        self.assertEqual(result.corrections_file, str(corrections.all_paths(self.root)[0].relative_to(self.root)))

    def test_recovery_after_event_before_task_projection(self):
        dossier = self._dossier()
        with mock.patch.object(corrections, "_project_tasks", side_effect=OSError("tasks interrupted")):
            with self.assertRaises(OSError):
                corrections.retract(self.root, DossierRef(AssetId("a1")), reason="wrong", kind=CorrectionKind.RETRACT)
        self.assertEqual(corrections.all_paths(self.root), ())
        self.assertNotIn("retract — wrong", dossier.read_text())
        self.assertEqual(len(corrections.recover(self.root)), 1)
        self.assertEqual(len(corrections.all_paths(self.root)), 1)
        self.assertEqual(dossier.read_text().count("retract — wrong"), 1)

    def test_recovery_repairs_deleted_tasks_without_resetting_authored_reviews(self):
        dossier = self._dossier()
        refs = {"target": "a1", "referrers": [
            {"file": "one.md", "kind": "note"}, {"file": "two.md", "kind": "note"}
        ], "by_kind": {}, "note": ""}
        with mock.patch.object(corrections.backlinks, "uses", return_value=refs):
            result = corrections.retract(self.root, DossierRef(AssetId("a1")), reason="wrong", kind=CorrectionKind.RETRACT)
        path = self.root / result.corrections_file
        edited = path.read_text().replace("| one.md | note | pending | |", "| one.md | note | corrected | alice |")
        edited = edited.replace("| two.md | note | pending | |\n", "") + "\n## Authored\n\nopaque citation history\n"
        path.write_bytes(edited.replace("\n", "\r\n").encode())
        target_before = dossier.read_bytes()
        corrections.recover(self.root)
        repaired = path.read_bytes().decode()
        self.assertIn("| one.md | note | corrected | alice |\r\n", repaired)
        self.assertIn("| two.md | note | pending | |\r\n", repaired)
        self.assertIn("## Authored\r\n\r\nopaque citation history\r\n", repaired)
        self.assertEqual(dossier.read_bytes(), target_before)
        corrections.recover(self.root)
        self.assertEqual(path.read_bytes().decode(), repaired)

    def test_explicit_operation_rejects_changed_input(self):
        self._dossier()
        identity = OperationId("correction-one")
        corrections.retract(self.root, DossierRef(AssetId("a1")), reason="wrong", kind=CorrectionKind.DISPUTE, operation_id=identity)
        with self.assertRaises(KctxError) as failure:
            corrections.retract(self.root, DossierRef(AssetId("a1")), reason="different", kind=CorrectionKind.DISPUTE, operation_id=identity)
        self.assertEqual(failure.exception.category, "conflict")
        self.assertEqual(len(corrections.all_paths(self.root)), 1)

    def test_distinct_interrupted_operations_reserve_distinct_task_paths(self):
        self._dossier()
        with mock.patch.object(corrections, "_project_tasks", side_effect=OSError("tasks interrupted")):
            for reason in ("first", "second"):
                with self.assertRaises(OSError):
                    corrections.retract(self.root, DossierRef(AssetId("a1")), reason=reason, kind=CorrectionKind.DISPUTE)
        results = corrections.recover(self.root)
        self.assertEqual(len({result.corrections_file for result in results}), 2)

    def test_cli_explicit_identity_and_recovery_use_configured_root(self):
        self._dossier()
        output = io.StringIO()
        with redirect_stdout(output):
            code = app.main(["--json", "retract", "a1", "--kind", "dispute",
                             "--reason", "wrong", "--operation-id", "cli-correction"])
        self.assertEqual(code, 0)
        first = json.loads(output.getvalue())
        projection = self.root / first["corrections_file"]
        projection.unlink()
        output = io.StringIO()
        with redirect_stdout(output):
            code = app.main(["--json", "correction", "recover"])
        self.assertEqual(code, 0)
        recovered = json.loads(output.getvalue())
        self.assertEqual(recovered["operations"][0]["corrections_file"], first["corrections_file"])
        self.assertTrue(projection.exists())
