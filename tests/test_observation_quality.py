"""Real Git, provenance and publication regressions for Q32–Q35/Q45."""

import hashlib
import io
from contextlib import redirect_stdout
import base64
import json
import multiprocessing
import os
import shutil
import subprocess
from unittest.mock import patch

from _base import KctxTestCase
from kctx.adapters.files.storage import exclusive_write_json, read_json
from kctx.cli import app as cli
from kctx.adapters.git.inspection import capture_worktree
from kctx.codecs.records import decode_observation, decode_run_receipt, encode_observation, encode_run_receipt
from kctx.domain.capture import CaptureStatus, CoveragePolicy, ObservationAssessment
from kctx.domain.ids import ContentDigest, GitRevision, ObservationId, SourceRevision
from kctx.domain.vocabulary import CoverageOutcome, ObservationRole, ObservationStatus, ObservationSystem, Readiness, RunMode
from kctx.errors import KctxError
from kctx.services import runs


def _interrupted_observe(root, run_id, ready, release):
    def pause_link(*args, **kwargs):
        ready.set()
        release.wait(30)
        raise AssertionError("parent must terminate before publication")

    with patch("kctx.adapters.files.storage.os.link", side_effect=pause_link):
        runs.add_observation(root, run_id, system=ObservationSystem.DOC, locator="notes://interrupted", obs_id=ObservationId("obs-interrupted"))


class ObservationQualityTests(KctxTestCase):
    def new_run(self):
        return runs.new_run(self.root, project="demo", mode=RunMode.REVIEW, task="quality").run_id

    def git_observation(self, repo, run_id):
        return runs.add_observation(self.root, run_id, system=ObservationSystem.GIT, locator=str(repo), role=ObservationRole.CODE)

    def test_untracked_content_changes_input_identity(self):
        repo = self.make_git_repo("untracked-input")
        untracked = repo / "input.txt"
        untracked.write_bytes(b"first")
        before = capture_worktree(str(repo))
        untracked.write_bytes(b"second")
        after = capture_worktree(str(repo))
        self.assertNotEqual(before.digest, after.digest)
        self.assertTrue(before.dirty)
        self.assertTrue(after.dirty)

    def test_source_movement_during_capture_is_detected(self):
        repo = self.make_git_repo("moving-source")
        original_run = subprocess.run
        moved = False

        def moving_run(command, *args, **kwargs):
            nonlocal moved
            result = original_run(command, *args, **kwargs)
            if command[-3:] == ["ls-files", "--stage", "-z"] and not moved:
                moved = True
                (repo / "tracked.txt").write_bytes(b"moved while capturing")
                original_run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
                original_run(["git", "-C", str(repo), "commit", "-qm", "move"], check=True)
            return result

        with patch("kctx.adapters.git.inspection.subprocess.run", side_effect=moving_run):
            with self.assertRaises(KctxError) as caught:
                capture_worktree(str(repo))
        self.assertEqual(caught.exception.category, "conflict")

    def test_staged_content_changes_even_when_worktree_restored(self):
        repo = self.make_git_repo("staged-input")
        tracked = repo / "tracked.txt"
        original = tracked.read_bytes()
        tracked.write_bytes(b"index-first")
        subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
        tracked.write_bytes(original)
        before = capture_worktree(str(repo))
        tracked.write_bytes(b"index-second")
        subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
        tracked.write_bytes(original)
        after = capture_worktree(str(repo))
        self.assertNotEqual(before.digest, after.digest)

    def test_binary_modes_symlinks_and_deletion_change_identity(self):
        repo = self.make_git_repo("all-inputs")
        binary = repo / "binary.dat"
        binary.write_bytes(b"\x00\xfffirst")
        subprocess.run(["git", "-C", str(repo), "add", "binary.dat"], check=True)
        before = capture_worktree(str(repo)).digest
        binary.write_bytes(b"\x00\xffsecond")
        after_binary = capture_worktree(str(repo)).digest
        self.assertNotEqual(before, after_binary)
        binary.chmod(0o755)
        after_mode = capture_worktree(str(repo)).digest
        self.assertNotEqual(after_binary, after_mode)
        link = repo / "link"
        link.symlink_to("binary.dat")
        after_link = capture_worktree(str(repo)).digest
        self.assertNotEqual(after_mode, after_link)
        link.unlink()
        link.symlink_to("tracked.txt")
        self.assertNotEqual(after_link, capture_worktree(str(repo)).digest)
        before_deleted = capture_worktree(str(repo)).digest
        binary.unlink()
        self.assertNotEqual(before_deleted, capture_worktree(str(repo)).digest)

    def test_submodule_untracked_bytes_are_part_of_identity(self):
        child = self.make_git_repo("child")
        parent = self.make_git_repo("parent")
        subprocess.run(["git", "-c", "protocol.file.allow=always", "-C", str(parent), "submodule", "add", "-q", str(child), "module"], check=True)
        subprocess.run(["git", "-C", str(parent), "commit", "-qm", "submodule"], check=True)
        before = capture_worktree(str(parent)).digest
        (parent / "module" / "untracked.bin").write_bytes(b"\x00nested")
        after = capture_worktree(str(parent)).digest
        self.assertNotEqual(before, after)
        (parent / "module" / "untracked.bin").write_bytes(b"\x00nested-modified")
        self.assertNotEqual(after, capture_worktree(str(parent)).digest)

    def test_profile_excludes_ignored_files_and_normalizes_subdirectory(self):
        repo = self.make_git_repo("profile-boundary")
        (repo / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        nested = repo / "nested"
        nested.mkdir()
        (nested / "input.txt").write_text("included", encoding="utf-8")
        before = capture_worktree(str(repo)).digest
        (repo / "ignored.txt").write_text("outside declared profile", encoding="utf-8")
        self.assertEqual(before, capture_worktree(str(repo)).digest)
        self.assertEqual(before, capture_worktree(str(nested)).digest)

    def test_violated_required_is_examined_but_not_eligible(self):
        run_id = self.new_run()
        runs.cover(self.root, run_id, item="safety", outcome=CoverageOutcome.VIOLATED, reason="counterexample")
        receipt = runs.check(self.root, run_id, require=("safety",))
        self.assertEqual(receipt.readiness, Readiness.BLOCKED)
        self.assertTrue(receipt.coverage_complete)
        self.assertFalse(receipt.eligible_to_proceed)
        self.assertEqual(receipt.missing_required, ())
        self.assertEqual(receipt.blocked_required, ("safety",))

    def test_missing_git_source_is_not_unchanged(self):
        repo = self.make_git_repo("missing-source")
        run_id = self.new_run()
        observation = self.git_observation(repo, run_id)
        runs.cover(self.root, run_id, item="safety", outcome=CoverageOutcome.SUPPORTED, evidence=(observation.id,))
        shutil.rmtree(repo)
        receipt = runs.check(self.root, run_id, require=("safety",))
        self.assertFalse(receipt.eligible_to_proceed)
        self.assertIn(observation.id, receipt.unknown_observations)
        self.assertEqual(receipt.observations[0].assessment, ObservationAssessment.UNAVAILABLE)
        self.assertIsNone(receipt.observations[0].changed)
        self.assertEqual(runs.load_coverage(self.root, run_id).entries[0].outcome, CoverageOutcome.NEEDS_RECHECK)

    def test_unavailable_capture_cannot_back_support(self):
        run_id = self.new_run()
        observation = self.git_observation(self.root / "missing", run_id)
        self.assertEqual(observation.capture_status, CaptureStatus.UNAVAILABLE)
        self.assertNotEqual(observation.status, ObservationStatus.OK)
        with self.assertRaises(KctxError):
            runs.cover(self.root, run_id, item="safety", outcome=CoverageOutcome.SUPPORTED, evidence=(observation.id,))

    def test_capture_retains_actual_input_bytes_and_rechecks_untracked_change(self):
        repo = self.make_git_repo("retained")
        (repo / "untracked.bin").write_bytes(b"\x00original")
        run_id = self.new_run()
        observation = self.git_observation(repo, run_id)
        assert observation.input_identity is not None
        identity = observation.input_identity
        retained = read_json(runs.run_dir(self.root, run_id) / identity.retained_path)
        payload = base64.b64decode(retained["payload_base64"])
        snapshot = json.loads(payload)
        captured = {base64.b64decode(item["path_base64"]): item for item in snapshot["worktree"]}
        self.assertEqual(base64.b64decode(captured[b"untracked.bin"]["content_base64"]), b"\x00original")
        self.assertEqual(ContentDigest(hashlib.sha256(payload).hexdigest()), identity.digest)
        runs.cover(self.root, run_id, item="safety", outcome=CoverageOutcome.SUPPORTED, evidence=(observation.id,))
        first = runs.check(self.root, run_id, require=("safety",))
        self.assertTrue(first.eligible_to_proceed)
        (repo / "untracked.bin").write_bytes(b"\x00changed")
        second = runs.check(self.root, run_id, require=("safety",))
        self.assertFalse(second.eligible_to_proceed)
        self.assertIn(observation.id, second.stale_observations)
        self.assertEqual(second.observations[0].assessment, ObservationAssessment.CHANGED)
        self.assertEqual(read_json(runs.run_dir(self.root, run_id) / identity.retained_path), retained)

    def test_missing_retained_payload_is_unknown_not_fresh(self):
        repo = self.make_git_repo("retained-missing")
        run_id = self.new_run()
        observation = self.git_observation(repo, run_id)
        assert observation.input_identity is not None
        (runs.run_dir(self.root, run_id) / observation.input_identity.retained_path).unlink()
        receipt = runs.check(self.root, run_id)
        self.assertEqual(receipt.observations[0].assessment, ObservationAssessment.RETAINED_MISSING)
        self.assertFalse(receipt.eligible_to_proceed)

    def test_legacy_git_digest_stays_readable_but_cannot_certify_inputs(self):
        repo = self.make_git_repo("legacy")
        run_id = self.new_run()
        observation = self.git_observation(repo, run_id)
        raw = encode_observation(observation)
        raw.update({"id": "obs-legacy", "schema_version": 1, "dirty_diff_sha256": "f" * 64})
        for field in ("input_identity", "capture_status", "derived_from"):
            del raw[field]
        legacy = decode_observation(raw)
        self.assertEqual(legacy.capture_status, CaptureStatus.LEGACY)
        self.assertIsNone(legacy.input_identity)
        exclusive_write_json(runs.observations_dir(self.root, run_id) / "obs-legacy.json", raw)
        receipt = runs.check(self.root, run_id)
        legacy_snapshot = next(item for item in receipt.observations if item.id == legacy.id)
        self.assertEqual(legacy_snapshot.assessment, ObservationAssessment.LEGACY_INSUFFICIENT)
        self.assertIn(legacy.id, receipt.unknown_observations)

    def test_copied_evidence_is_not_independent(self):
        run_id = self.new_run()
        first = self.root / "first.txt"
        second = self.root / "second.txt"
        first.write_text("one original result", encoding="utf-8")
        shutil.copyfile(first, second)
        observations = tuple(runs.add_observation(self.root, run_id, system=ObservationSystem.DOC, locator=f"notes://{path.stem}", evidence=str(path)) for path in (first, second))
        with self.assertRaises(KctxError):
            runs.cover(self.root, run_id, item="safety", outcome=CoverageOutcome.SUPPORTED, evidence=tuple(item.id for item in observations))

    def test_declared_copy_chain_and_named_policy(self):
        run_id = self.new_run()
        root = runs.add_observation(self.root, run_id, system=ObservationSystem.DOC, locator="notes://original")
        copy = runs.add_observation(self.root, run_id, system=ObservationSystem.DOC, locator="notes://copy", derived_from=(root.id,))
        copied_again = runs.add_observation(self.root, run_id, system=ObservationSystem.DOC, locator="notes://copy-again", derived_from=(copy.id,))
        with self.assertRaises(KctxError):
            runs.cover(self.root, run_id, item="safety", outcome=CoverageOutcome.SUPPORTED, evidence=(root.id, copied_again.id))
        with self.assertRaises(KctxError):
            runs.cover(self.root, run_id, item="safety", outcome=CoverageOutcome.SUPPORTED, evidence=(root.id,), policy=CoveragePolicy.INDEPENDENT_ORIGINS)
        other = runs.add_observation(self.root, run_id, system=ObservationSystem.DOC, locator="notes://independent")
        entry = runs.cover(self.root, run_id, item="safety", outcome=CoverageOutcome.SUPPORTED, evidence=(root.id, other.id), policy=CoveragePolicy.INDEPENDENT_ORIGINS)
        self.assertEqual(entry.policy, CoveragePolicy.INDEPENDENT_ORIGINS)
        self.assertEqual(runs.load_coverage(self.root, run_id).entries[0], entry)

    def test_legacy_receipt_never_gains_authorization_on_decode(self):
        receipt = runs.check(self.root, self.new_run())
        raw = encode_run_receipt(receipt)
        raw["schema_version"] = 1
        for field in ("coverage_complete", "eligible_to_proceed", "blocked_required", "unknown_observations"):
            del raw[field]
        legacy = decode_run_receipt(raw)
        self.assertFalse(legacy.eligible_to_proceed)
        self.assertIsNone(legacy.coverage_complete)

    def test_digest_revision_namespaces_and_v2_shape_are_strict(self):
        digest = ContentDigest("a" * 64)
        revision = SourceRevision("a" * 64)
        self.assertNotEqual(digest, revision)
        with self.assertRaises(KctxError):
            ContentDigest(revision)
        for invalid in ("", "abc", "A" * 64, "0" * 63):
            with self.assertRaises(KctxError):
                ContentDigest(invalid)
        with self.assertRaises(KctxError):
            GitRevision("main")
        observation = runs.add_observation(self.root, self.new_run(), system=ObservationSystem.DOC, locator="notes://shape")
        raw = encode_observation(observation)
        del raw["capture_status"]
        with self.assertRaises(KctxError):
            decode_observation(raw)

    def test_interrupted_observation_never_publishes_partial_json(self):
        run_id = self.new_run()
        context = multiprocessing.get_context("fork")
        ready = context.Event()
        release = context.Event()
        worker = context.Process(target=_interrupted_observe, args=(self.root, run_id, ready, release))
        worker.start()
        try:
            self.assertTrue(ready.wait(10), "writer never reached the publication boundary")
            self.assertFalse((runs.observations_dir(self.root, run_id) / "obs-interrupted.json").exists())
            self.assertEqual(runs.load_observations(self.root, run_id), ())
        finally:
            worker.terminate()
            worker.join(10)
        self.assertEqual(runs.load_observations(self.root, run_id), ())
        self.assertEqual(runs.resume(self.root, run_id).manifest.run_id, run_id)

    def test_cli_provenance_policy_and_eligibility_outputs(self):
        def invoke(*arguments):
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli.main(["--json", *arguments])
            return code, json.loads(output.getvalue())

        run_id = self.new_run()
        code, original = invoke("observe", run_id.val, "--system", "doc", "--locator", "notes://original")
        self.assertEqual(code, 0)
        code, copied = invoke("observe", run_id.val, "--system", "doc", "--locator", "notes://copy",
                              "--derived-from", original["id"])
        self.assertEqual(code, 0)
        self.assertEqual(copied["derived_from"], [original["id"]])
        code, refused = invoke("cover", run_id.val, "--item", "safety", "--outcome", "supported",
                               "--evidence", original["id"], "--evidence", copied["id"],
                               "--policy", "independent-origins")
        self.assertEqual(code, 1)
        self.assertEqual(refused["error"], "incomplete")
        code, _ = invoke("cover", run_id.val, "--item", "safety", "--outcome", "violated", "--reason", "failed")
        self.assertEqual(code, 0)
        code, receipt = invoke("check", run_id.val, "--require", "safety")
        self.assertEqual(code, 3)
        self.assertTrue(receipt["coverage_complete"])
        self.assertFalse(receipt["eligible_to_proceed"])
        self.assertEqual(receipt["missing_required"], [])
        self.assertEqual(receipt["blocked_required"], ["safety"])

    def test_requested_revision_mismatch_is_not_captured_as_success(self):
        repo = self.make_git_repo("revision-mismatch")
        run_id = self.new_run()
        observation = runs.add_observation(
            self.root, run_id, system=ObservationSystem.GIT, locator=str(repo),
            revision=SourceRevision("0" * 40),
        )
        self.assertEqual(observation.capture_status, CaptureStatus.MOVED)
        self.assertEqual(observation.status, ObservationStatus.PARTIAL)
        self.assertIsNone(observation.input_identity)
        with self.assertRaises(KctxError):
            runs.cover(self.root, run_id, item="safety", outcome=CoverageOutcome.SUPPORTED, evidence=(observation.id,))

    def test_receipt_cannot_claim_eligibility_with_blockers(self):
        run_id = self.new_run()
        runs.cover(self.root, run_id, item="safety", outcome=CoverageOutcome.VIOLATED, reason="failed")
        receipt = runs.check(self.root, run_id, require=("safety",))
        raw = encode_run_receipt(receipt)
        raw["eligible_to_proceed"] = True
        with self.assertRaises(KctxError):
            decode_run_receipt(raw)

    def test_tracked_parent_symlink_cannot_retain_external_bytes(self):
        repo = self.make_git_repo("parent-link")
        tracked = repo / "dir"
        tracked.mkdir()
        (tracked / "item").write_bytes(b"inside")
        subprocess.run(["git", "-C", str(repo), "add", "dir/item"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "tracked directory"], check=True)
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "item").write_bytes(b"OUTSIDE-MARKER")
        shutil.rmtree(tracked)
        tracked.symlink_to(outside, target_is_directory=True)
        try:
            capture = capture_worktree(str(repo))
        except KctxError:
            return
        self.assertNotIn(base64.b64encode(b"OUTSIDE-MARKER"), capture.payload)

    def test_inspection_never_executes_repo_fsmonitor(self):
        repo = self.make_git_repo("fsmonitor")
        marker = self.root / "helper-executed"
        helper = self.root / "fsmonitor-helper"
        helper.write_text(f"#!/bin/sh\nprintf executed > '{marker}'\nprintf '\\\\0'\n", encoding="utf-8")
        helper.chmod(0o755)
        subprocess.run(["git", "-C", str(repo), "config", "core.fsmonitor", str(helper)], check=True)
        capture_worktree(str(repo))
        self.assertFalse(marker.exists(), "capture executed source-controlled fsmonitor helper")

    def test_parent_swap_during_capture_cannot_redirect_open_leaf(self):
        repo = self.make_git_repo("parent-swap")
        tracked = repo / "dir"
        tracked.mkdir()
        (tracked / "item").write_bytes(b"inside")
        subprocess.run(["git", "-C", str(repo), "add", "dir/item"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "tracked directory"], check=True)
        outside = self.root / "outside-race"
        outside.mkdir()
        (outside / "item").write_bytes(b"OUTSIDE-RACE")
        original_open = os.open
        swapped = False

        def swapping_open(path, flags, *args, **kwargs):
            nonlocal swapped
            descriptor = original_open(path, flags, *args, **kwargs)
            if path == b"dir" and not swapped:
                swapped = True
                tracked.rename(repo / "held-dir")
                tracked.symlink_to(outside, target_is_directory=True)
            return descriptor

        with patch("kctx.adapters.git.inspection.os.open", side_effect=swapping_open):
            with self.assertRaises(KctxError):
                capture_worktree(str(repo))
        self.assertTrue(swapped)

    def test_leaf_swap_to_symlink_is_refused(self):
        repo = self.make_git_repo("leaf-swap")
        outside = self.root / "outside-leaf"
        outside.write_bytes(b"OUTSIDE-LEAF")
        original_open = os.open
        swapped = False

        def swapping_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if path == b"tracked.txt" and not swapped:
                swapped = True
                (repo / "tracked.txt").unlink()
                (repo / "tracked.txt").symlink_to(outside)
            return original_open(path, flags, *args, **kwargs)

        with patch("kctx.adapters.git.inspection.os.open", side_effect=swapping_open):
            with self.assertRaises(KctxError):
                capture_worktree(str(repo))
        self.assertTrue(swapped)

    def test_leaf_symlink_retains_target_not_external_contents(self):
        repo = self.make_git_repo("leaf-link")
        outside = self.root / "outside-target"
        outside.write_bytes(b"OUTSIDE-LEAF-CONTENT")
        (repo / "link").symlink_to(outside)
        capture = capture_worktree(str(repo))
        snapshot = json.loads(capture.payload)
        link = next(item for item in snapshot["worktree"] if base64.b64decode(item["path_base64"]) == b"link")
        self.assertEqual(link["kind"], "symlink")
        self.assertEqual(base64.b64decode(link["content_base64"]), os.fsencode(outside))
        self.assertNotIn(base64.b64encode(b"OUTSIDE-LEAF-CONTENT"), capture.payload)

    def test_source_configured_filters_and_diff_helpers_never_execute(self):
        repo = self.make_git_repo("git-helpers")
        marker = self.root / "transform-executed"
        helper = self.root / "transform-helper"
        helper.write_text(f"#!/bin/sh\nprintf executed > '{marker}'\ncat\n", encoding="utf-8")
        helper.chmod(0o755)
        (repo / ".gitattributes").write_text("tracked.txt filter=evil diff=evil\n", encoding="utf-8")
        for key in ("filter.evil.clean", "filter.evil.smudge", "diff.evil.textconv", "diff.external"):
            subprocess.run(["git", "-C", str(repo), "config", key, str(helper)], check=True)
        (repo / "tracked.txt").write_bytes(b"changed raw input")
        capture = capture_worktree(str(repo))
        self.assertTrue(capture.dirty)
        self.assertFalse(marker.exists(), "capture executed source-controlled transform helper")
