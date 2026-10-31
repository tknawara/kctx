import json

from _base import KctxTestCase

from kctx.services import runs
from kctx.errors import KctxError
from kctx.domain.ids import ObservationId
from kctx.domain.records import CoverageCount
from kctx.domain.vocabulary import CoverageOutcome, ObservationRole, ObservationStatus, ObservationSystem, Readiness, RunMode
from kctx.codecs.records import encode_observation


def _new_run(root):
    return runs.new_run(root, project="demo", mode=RunMode("advice"), task="test task").run_id


class CoverRefusalTest(KctxTestCase):
    """Q12: a required dashboard or deployment source times out or denies
    access -- the affected conclusion is never implicitly supported."""

    def test_q12_supported_refused_for_timeout_and_denied(self):
        run_id = _new_run(self.root)
        for bad_status in ("timeout", "denied"):
            with self.subTest(status=bad_status):
                obs = runs.add_observation(self.root,
                run_id, system=ObservationSystem("grafana"), locator="dash://x", role=ObservationRole("runtime"), status=ObservationStatus(bad_status), )
                with self.assertRaises(KctxError) as ctx:
                    runs.cover(self.root,
                    run_id,
                    item=f"item-{bad_status}", outcome=CoverageOutcome("supported"), evidence=tuple([obs.id]), )
                self.assertEqual(ctx.exception.category, "incomplete")

    def test_cover_supported_requires_evidence(self):
        run_id = _new_run(self.root)
        with self.assertRaises(KctxError) as ctx:
            runs.cover(self.root, run_id, item="no-evidence", outcome=CoverageOutcome.SUPPORTED)
        self.assertEqual(ctx.exception.category, "incomplete")

    def test_cover_non_supported_requires_reason(self):
        run_id = _new_run(self.root)
        with self.assertRaises(KctxError):
            runs.cover(self.root, run_id, item="x", outcome=CoverageOutcome.INCONCLUSIVE)


class NoDataPartialTruncatedTest(KctxTestCase):
    """Q13: a runtime query returns no data, warnings, truncation, or partial
    data -- the result retains these conditions and never establishes a
    supported outcome by default."""

    def test_q13_no_data_partial_truncated_cannot_back_supported(self):
        run_id = _new_run(self.root)
        for status in ("no-data", "partial", "truncated"):
            with self.subTest(status=status):
                obs = runs.add_observation(self.root,
                run_id, system=ObservationSystem("metrics"), locator="metric://x", role=ObservationRole("runtime"), status=ObservationStatus(status), )
                with self.assertRaises(KctxError) as ctx:
                    runs.cover(self.root,
                    run_id,
                    item=f"q13-{status}", outcome=CoverageOutcome("supported"), evidence=tuple([obs.id]), )
                self.assertEqual(ctx.exception.category, "incomplete")
                # The unsupported condition is still visible as a regular,
                # non-supported coverage entry with the required reason.
                entry = runs.cover(self.root,
                run_id,
                item=f"q13-{status}-recorded", outcome=CoverageOutcome("inconclusive"), evidence=tuple([obs.id]), reason=f"observation status={status}",)
                self.assertEqual(entry.outcome.value, "inconclusive")


class DirtyWorktreeTest(KctxTestCase):
    """Q17: a test runs on a dirty workspace -- its evidence identifies the
    actual tested inputs (dirty flag + diff digest), and is never attributed
    solely to the clean commit."""

    def test_q17_dirty_observation_distinct_from_clean(self):
        repo = self.make_git_repo("dirty-check")
        run_id = _new_run(self.root)

        clean = runs.add_observation(self.root, run_id, system=ObservationSystem("git"), locator=str(repo), role=ObservationRole.CODE)
        self.assertFalse(bool(clean.dirty))
        self.assertIsNone(clean.dirty_diff_sha256)
        clean_revision = clean.source.revision
        self.assertTrue(clean_revision)

        (repo / "tracked.txt").write_text(
            "synthetic fixture content, modified\n", encoding="utf-8"
        )
        dirty = runs.add_observation(self.root, run_id, system=ObservationSystem("git"), locator=str(repo), role=ObservationRole.CODE)

        self.assertTrue(dirty.dirty)
        self.assertIsNone(dirty.dirty_diff_sha256)
        # New captures retain a complete declared input identity; the old
        # git-diff digest field is never relabeled as complete evidence.
        assert clean.input_identity is not None
        assert dirty.input_identity is not None
        self.assertEqual(dirty.source.revision, clean_revision)
        self.assertNotEqual(dirty.input_identity.digest, clean.input_identity.digest)
        self.assertNotEqual(
            json.dumps(encode_observation(dirty), sort_keys=True), json.dumps(encode_observation(clean), sort_keys=True)
        )


class ConcurrentObservationTest(KctxTestCase):
    """Q19: two agents concurrently reconcile different or conflicting
    knowledge -- unrelated updates survive, and a duplicate id is refused
    rather than silently overwriting the earlier observation."""

    def test_q19_concurrent_observations_survive_duplicate_refused(self):
        run_id = _new_run(self.root)
        first = runs.add_observation(self.root, run_id, system=ObservationSystem("other"), locator="a", obs_id=ObservationId("obs-concurrent-a"))
        second = runs.add_observation(self.root, run_id, system=ObservationSystem("other"), locator="b", obs_id=ObservationId("obs-concurrent-b"))

        all_obs = {o.id for o in runs.load_observations(self.root, run_id)}
        self.assertEqual(all_obs, {first.id, second.id})

        with self.assertRaises(KctxError) as ctx:
            runs.add_observation(self.root,
            run_id, system=ObservationSystem("other"), locator="clobber-attempt", obs_id=ObservationId("obs-concurrent-a"), )
        self.assertEqual(ctx.exception.category, "conflict")

        # The original observation must be untouched by the refused write.
        reloaded = runs.get_observation(self.root, run_id, ObservationId("obs-concurrent-a"))
        self.assertEqual(reloaded.source.locator, "a")


class CrashRecoveryTest(KctxTestCase):
    """Q20: a run crashes during evidence or summary persistence -- recovery
    preserves durable evidence and unfinished state without inventing
    completion."""

    def test_q20_stray_temp_file_does_not_corrupt_run_and_resume_works(self):
        run_id = _new_run(self.root)
        runs.add_observation(self.root, run_id, system=ObservationSystem("other"), locator="a", obs_id=ObservationId("obs-1"))
        runs.cover(self.root, run_id, item="q1", outcome=CoverageOutcome("not-examined"), reason="not yet")

        run_dir = runs.run_dir(self.root, run_id)
        stray = run_dir / ".tmp-abcd1234"
        stray.write_text('{"broken json truncated mid-writ', encoding="utf-8")

        result = runs.resume(self.root, run_id)
        self.assertEqual(result.coverage_summary, (CoverageCount(CoverageOutcome.NOT_EXAMINED, 1),))
        self.assertEqual(result.manifest.run_id, run_id)
        # The stray temp file is still there (we don't clean it up implicitly)
        # but is not mistaken for a real record.
        self.assertTrue(stray.exists())


class ReceiptRevisionBindingTest(KctxTestCase):
    """Q10: PR head changes during review -- results depending on the changed
    head are reassessed, and the old receipt cannot certify the new head."""

    def test_q10_new_commit_makes_check_report_stale_and_needs_recheck(self):
        repo = self.make_git_repo("revision-binding")
        run_id = _new_run(self.root)

        obs = runs.add_observation(self.root, run_id, system=ObservationSystem("git"), locator=str(repo), role=ObservationRole.CODE)
        first_revision = obs.source.revision
        runs.cover(self.root, run_id, item="q1", outcome=CoverageOutcome("supported"), evidence=(obs.id,))

        receipt1 = runs.check(self.root, run_id)
        self.assertEqual(receipt1.readiness, Readiness.READY)
        self.assertEqual(receipt1.stale_observations, ())
        self.assertEqual(receipt1.observations[0].revision, first_revision)

        # Move the repo forward -- the reviewed head changed.
        (repo / "tracked.txt").write_text(
            "a new committed revision\n", encoding="utf-8"
        )
        import subprocess

        subprocess.run(
            ["git", "-C", str(repo), "add", "tracked.txt"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "second commit"],
            check=True,
            capture_output=True,
        )

        receipt2 = runs.check(self.root, run_id)
        self.assertIn(obs.id, receipt2.stale_observations)
        self.assertEqual(receipt2.readiness, Readiness.PARTIAL)

        coverage = runs.load_coverage(self.root, run_id)
        self.assertEqual(coverage.entries[0].outcome, CoverageOutcome.NEEDS_RECHECK)
        self.assertEqual(coverage.entries[0].prior_outcome, CoverageOutcome.SUPPORTED)

        # The first receipt is immutable: it still certifies only the old revision.
        receipts_dir = runs.receipts_dir(self.root, run_id)
        reloaded_receipt1 = json.loads(
            (receipts_dir / "1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            reloaded_receipt1["observations"][0]["revision"], first_revision.val
        )
        self.assertEqual(reloaded_receipt1["readiness"], "ready")
        self.assertNotEqual(receipt2.receipt, receipt1.receipt)


class SharedEvidenceOriginTest(KctxTestCase):
    """Q21: several summaries repeat the same unsupported assertion -- all
    references trace back to the same single observation, so repetition
    cannot be mistaken for two independent pieces of evidence."""

    def test_q21_check_counts_distinct_observations_not_citations(self):
        run_id = _new_run(self.root)
        obs = runs.add_observation(self.root,
        run_id, system=ObservationSystem("doc"), locator="notes://shared", role=ObservationRole("note"), status=ObservationStatus("ok"), )

        runs.cover(self.root,
        run_id,
        item="claim-a", outcome=CoverageOutcome("inconclusive"), evidence=tuple([obs.id]), reason="only a note, unverified",)
        runs.cover(self.root,
        run_id,
        item="claim-b", outcome=CoverageOutcome("inconclusive"), evidence=tuple([obs.id]), reason="same unverified note cited again",)

        receipt = runs.check(self.root, run_id)
        origins = receipt.evidence_origins
        self.assertEqual(origins.total_citations, 2)
        self.assertEqual(origins.distinct_observations, 1)
        self.assertEqual(origins.shared_evidence[0].observation, obs.id)
        self.assertEqual(set(origins.shared_evidence[0].items), {"claim-a", "claim-b"})


class SameOriginCorroborationTest(KctxTestCase):
    """Q44: two different observation ids, each individually status=ok,
    cited together for one outcome=supported, but both trace to the same
    (source.system, source.locator) origin -- shared lineage, not
    independent corroboration."""

    def test_q44_cover_supported_refuses_same_origin_evidence(self):
        run_id = _new_run(self.root)
        obs_a = runs.add_observation(self.root, run_id, system=ObservationSystem("doc"), locator="notes://shared", status=ObservationStatus.OK)
        obs_b = runs.add_observation(self.root, run_id, system=ObservationSystem("doc"), locator="notes://shared", status=ObservationStatus.OK)
        with self.assertRaises(KctxError) as ctx:
            runs.cover(self.root,
            run_id,
            item="claim-a", outcome=CoverageOutcome("supported"), evidence=tuple([obs_a.id, obs_b.id]), )
        self.assertEqual(ctx.exception.category, "incomplete")

    def test_q44_cover_supported_allows_distinct_origin_evidence(self):
        run_id = _new_run(self.root)
        obs_a = runs.add_observation(self.root, run_id, system=ObservationSystem("doc"), locator="notes://one", status=ObservationStatus.OK)
        obs_b = runs.add_observation(self.root, run_id, system=ObservationSystem("doc"), locator="notes://two", status=ObservationStatus.OK)
        entry = runs.cover(self.root,
        run_id,
        item="claim-a", outcome=CoverageOutcome("supported"), evidence=tuple([obs_a.id, obs_b.id]), )
        self.assertEqual(entry.outcome.value, "supported")

    def test_q44_cover_supported_refuses_three_evidence_all_same_origin(self):
        run_id = _new_run(self.root)
        obs_ids = [
            runs.add_observation(self.root, run_id, system=ObservationSystem("doc"), locator="notes://shared", status=ObservationStatus.OK).id
            for _ in range(3)
        ]
        with self.assertRaises(KctxError) as ctx:
            runs.cover(self.root,
            run_id,
            item="claim-a", outcome=CoverageOutcome("supported"), evidence=tuple(obs_ids), )
        self.assertEqual(ctx.exception.category, "incomplete")

    def test_q44_cover_supported_allows_two_shared_plus_one_distinct_origin(self):
        """Partial overlap isn't the same as no corroboration at all: two
        observations sharing an origin alongside a third from a distinct
        origin still provides independent corroboration, so this must be
        allowed."""
        run_id = _new_run(self.root)
        obs_a = runs.add_observation(self.root, run_id, system=ObservationSystem("doc"), locator="notes://shared", status=ObservationStatus.OK)
        obs_b = runs.add_observation(self.root, run_id, system=ObservationSystem("doc"), locator="notes://shared", status=ObservationStatus.OK)
        obs_c = runs.add_observation(self.root, run_id, system=ObservationSystem("doc"), locator="notes://distinct", status=ObservationStatus.OK)
        entry = runs.cover(self.root,
        run_id,
        item="claim-a", outcome=CoverageOutcome("supported"), evidence=tuple([obs_a.id, obs_b.id, obs_c.id]), )
        self.assertEqual(entry.outcome.value, "supported")
