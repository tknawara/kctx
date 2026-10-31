"""Actual source-object checks for the authored landed-resolution boundary."""

import hashlib
import subprocess

from _base import KctxTestCase

from kctx.domain.ids import TargetRevision
from kctx.domain.vocabulary import AssetKind
from kctx.errors import KctxError
from kctx.services import inventory
from kctx.services.proposal_targets import resolve_landed


class ProposalTargetResolutionTest(KctxTestCase):
    def _repo(self):
        repo = self.root / "target-repo"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "source.txt").write_text("retained source\n")
        subprocess.run(["git", "-C", str(repo), "add", "source.txt"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "retained source"], check=True)
        commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        return repo, commit

    def test_exact_commit_and_unique_abbreviation_resolve_to_full_identity(self):
        repo, commit = self._repo()
        references = (f"target-repo@{commit}", f"target-repo@{commit[:12]}")
        records = resolve_landed(self.root, references)
        self.assertEqual(tuple(record.reference for record in records), references)
        self.assertEqual(tuple(record.target_revision for record in records), (TargetRevision(f"{repo.resolve()}@{commit}"),) * 2)

    def test_tree_blob_and_missing_objects_never_fall_back_to_head(self):
        repo, _ = self._repo()
        tree = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], text=True).strip()
        blob = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD:source.txt"], text=True).strip()
        for revision in (tree, blob, "0" * 40, "HEAD"):
            with self.subTest(revision=revision), self.assertRaises(KctxError):
                resolve_landed(self.root, (f"target-repo@{revision}",))

    def test_inventory_alias_resolves_exact_repository_object(self):
        repo, commit = self._repo()
        inventory.asset_add(self.root, kind=AssetKind.REPO, name="Resolved target", locator=str(repo), aliases=("target-alias",))
        result = resolve_landed(self.root, (f"target-alias@{commit}",))[0]
        self.assertEqual(result.target_revision, TargetRevision(f"{repo.resolve()}@{commit}"))

    def test_retained_file_digest_mismatch_and_missing_file_are_rejected(self):
        path = self.root / "retained.txt"
        path.write_bytes(b"retained material")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        reference = f"retained.txt@sha256:{digest}"
        self.assertEqual(resolve_landed(self.root, (reference,))[0].target_revision, TargetRevision(f"{path.resolve()}@sha256:{digest}"))
        path.write_bytes(b"changed material")
        with self.assertRaises(KctxError):
            resolve_landed(self.root, (reference,))
        path.unlink()
        with self.assertRaises(KctxError):
            resolve_landed(self.root, (reference,))
