from __future__ import annotations

import subprocess
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from kctx.adapters.git.citations import (
    ensure_cache_clone,
    get_cache_path,
    git_file_content,
    git_rev_parse,
    repo_from_url,
    resolve_default_branch_rev,
    run_git,
)
from kctx.citations.classification import classify, classify_gate
from kctx.citations.code import make_code
from kctx.citations.models import CitationStatus
from kctx.citations.records import load_evidence_record, load_proposal_record, load_record_status
from kctx.config import Config
from kctx.domain.ids import EvidenceId, ProposalId
from kctx.domain.targets import EvidenceRef
from kctx.errors import KctxError


class CitationSourcesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "checkout"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Citation Test")
        self.git("config", "user.email", "citation@example.invalid")
        self.source = self.repo / "source.py"
        self.source.write_text("before\ndef target():\n    return 1\nafter\n", encoding="utf-8")
        self.commit()
        self.config = Config(root=self.root, cache_dir=self.root / "cache", fetch_interval_seconds=0)

    def git(self, *args: str) -> str:
        result = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def commit(self) -> str:
        self.git("add", "--all")
        self.git("commit", "-m", "fixture")
        return self.git("rev-parse", "HEAD")

    def test_make_pins_real_commit_blob_and_span(self) -> None:
        made = make_code(str(self.repo), "source.py", "2-3", sym="target", config=self.config)
        self.assertEqual(made.fields["rev"], self.git("rev-parse", "HEAD"))
        self.assertEqual(made.fields["blob"], self.git("rev-parse", "HEAD:source.py"))
        self.assertEqual(classify(made.fields, config=self.config).status, CitationStatus.FRESH)
        self.assertEqual(made.fields["url"], str(self.repo))
        self.assertEqual(git_file_content(self.repo, made.fields["rev"], "source.py"), self.source.read_text())

    def test_current_checks_move_change_and_delete_without_rewriting_history(self) -> None:
        made = make_code(str(self.repo), "source.py", "2-3", sym="target", config=self.config)
        original = self.source.read_text()
        self.source.write_text("inserted\n" + original)
        self.commit()
        moved = classify(made.fields, config=self.config)
        self.assertEqual(moved.status, CitationStatus.MOVED)
        self.assertEqual(moved.line_range, "3-4")
        self.source.write_text("inserted\nbefore\ndef target():\n    return 2\nafter\n")
        self.commit()
        changed = classify(made.fields, config=self.config)
        self.assertEqual(changed.status, CitationStatus.CHANGED)
        self.assertEqual(changed.sym_line, 3)
        self.source.unlink()
        self.commit()
        self.assertEqual(classify(made.fields, config=self.config).status, CitationStatus.GONE)
        self.assertEqual(git_file_content(self.repo, made.fields["rev"], "source.py"), original)

    def test_missing_tree_and_blob_objects_are_unverifiable(self) -> None:
        nested = self.repo / "nested"
        nested.mkdir()
        (nested / "item.txt").write_text("nested\n", encoding="utf-8")
        self.commit()
        made = make_code(str(self.repo), "nested/item.txt", "1-1", config=self.config)
        for revision in ("HEAD^{tree}", "HEAD:nested", "HEAD:nested/item.txt"):
            object_id = self.git("rev-parse", revision)
            object_path = self.repo / ".git" / "objects" / object_id[:2] / object_id[2:]
            original = object_path.read_bytes()
            object_path.unlink()
            try:
                with self.subTest(revision=revision):
                    result = classify(made.fields, config=self.config)
                    self.assertEqual(result.status, CitationStatus.UNVERIFIABLE)
                    self.assertIsNotNone(result.reason)
                    with self.assertRaises(KctxError):
                        git_file_content(self.repo, made.fields["rev"], "nested/item.txt")
            finally:
                object_path.write_bytes(original)

    def test_historical_lookup_ignores_replacement_objects_and_never_uses_head(self) -> None:
        original = self.source.read_text()
        old = self.git("rev-parse", "HEAD")
        self.source.write_text("replacement\n", encoding="utf-8")
        new = self.commit()
        self.git("replace", old, new)
        self.assertEqual(git_file_content(self.repo, old, "source.py"), original)
        with self.assertRaises(KctxError):
            git_file_content(self.repo, "missing-revision", "source.py")

    def test_source_inspection_does_not_execute_repository_diff_or_fsmonitor(self) -> None:
        marker = self.root / "helper-ran"
        helper = self.root / "helper.sh"
        helper.write_text(f'#!/bin/sh\nprintf executed > "{marker}"\n', encoding="utf-8")
        helper.chmod(0o700)
        (self.repo / ".gitattributes").write_text("*.py diff=untrusted\n", encoding="utf-8")
        self.commit()
        self.git("config", "diff.external", str(helper))
        self.git("config", "diff.untrusted.textconv", str(helper))
        self.git("config", "core.fsmonitor", str(helper))
        self.source.write_text("changed\n", encoding="utf-8")
        made = make_code(str(self.repo), "source.py", "2-3", allow_dirty=True, config=self.config)
        self.assertIn("dirty", made.fields)
        self.assertEqual(classify(made.fields, config=self.config).status, CitationStatus.FRESH)
        diff = run_git(["diff", "HEAD", "--", "source.py"], cwd=self.repo)
        self.assertEqual(diff.returncode, 0)
        self.assertIn("-before", diff.stdout)
        self.assertFalse(marker.exists())

    def test_literal_git_paths_are_not_globs(self) -> None:
        special = self.repo / "file[1].txt"
        special.write_text("literal\n", encoding="utf-8")
        (self.repo / "file1.txt").write_text("other\n", encoding="utf-8")
        self.commit()
        self.assertEqual(git_file_content(self.repo, "HEAD", special.name), "literal\n")
        self.assertIsNone(git_file_content(self.repo, "HEAD", "file*.txt"))

    def test_dirty_requires_opt_in_and_still_cites_committed_bytes(self) -> None:
        clean = make_code(str(self.repo), "source.py", "2-3", config=self.config)
        self.source.write_text("dirty\n")
        with self.assertRaises(KctxError):
            make_code(str(self.repo), "source.py", "2-3", config=self.config)
        dirty = make_code(str(self.repo), "source.py", "2-3", allow_dirty=True, config=self.config)
        self.assertEqual(dirty.fields["span"], clean.fields["span"])
        self.assertEqual(dirty.fields["blob"], clean.fields["blob"])
        self.assertRegex(dirty.fields["dirty"], r"^[0-9a-f]{12}$")

    def test_org_repo_uses_configured_local_remote_and_fetches_changes(self) -> None:
        remote = self.root / "remotes" / "team" / "project.git"
        remote.parent.mkdir(parents=True)
        subprocess.run(["git", "clone", "--bare", str(self.repo), str(remote)], capture_output=True, check=True)
        self.git("remote", "add", "origin", str(remote))
        config = replace(self.config, git_url_template=str(self.root / "remotes" / "{org}" / "{repo}.git"))
        made = make_code("team/project", "source.py", "2-3", config=config)
        cache = get_cache_path("team", "project", config=config)
        self.assertTrue((cache / ".git").is_dir())
        self.assertEqual(classify(made.fields, config=config).status, CitationStatus.FRESH)
        self.source.write_text("new\n" + self.source.read_text())
        head = self.commit()
        self.git("push", "origin", "main")
        self.assertEqual(classify(made.fields, config=config).status, CitationStatus.MOVED)
        self.assertEqual(resolve_default_branch_rev(cache), head)

    def test_gate_compares_current_head_and_accepts_abbreviated_revision(self) -> None:
        head = self.git("rev-parse", "HEAD")
        fields = {"kind": "gate", "rev": f"{self.repo}@{head[:10]}"}
        self.assertEqual(classify_gate(fields, config=self.config).status, CitationStatus.FRESH)
        self.source.write_text("changed\n")
        self.commit()
        self.assertEqual(classify_gate(fields, config=self.config).status, CitationStatus.CHANGED)

    def test_missing_and_malformed_sources_are_never_fresh(self) -> None:
        self.assertEqual(classify({"kind": "code", "repo": "unavailable"}, config=self.config).status, CitationStatus.UNVERIFIABLE)
        with self.assertRaises(KctxError):
            make_code(str(self.repo), "source.py", "1-99", config=self.config)
        with self.assertRaises(KctxError):
            make_code(str(self.repo), "source.py", "1-1", rev="missing", config=self.config)
        with self.assertRaises(KctxError):
            get_cache_path("..", "escape", config=self.config)
        self.assertIsNone(git_rev_parse(self.repo, "--help"))
        self.assertIsNone(git_file_content(self.repo, "HEAD", "missing.py"))
        with self.assertRaises(KctxError):
            git_file_content(self.repo, "HEAD", "../outside")
        self.assertEqual(classify({"kind": "unknown", "seen": "2026-01-01", "ttl": "none"}, config=self.config).status, CitationStatus.UNVERIFIABLE)

    def test_clone_failure_and_timeout_are_honest_errors(self) -> None:
        config = replace(self.config, git_url_template=str(self.root / "missing" / "{org}" / "{repo}"))
        with self.assertRaises(KctxError):
            ensure_cache_clone(get_cache_path("team", "missing", config=config), "team", "missing", config=config)
        with patch("kctx.adapters.git.citations.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 15)):
            with self.assertRaises(KctxError) as caught:
                run_git(["status"], cwd=self.repo)
        self.assertIn("exceeded", str(caught.exception))

    def test_repo_url_forms(self) -> None:
        for url in ("git@example.invalid:team/project.git", "https://example.invalid/team/project.git", "bbgithub:team/project.git"):
            self.assertEqual(repo_from_url(url), ("team", "project"))
        self.assertIsNone(repo_from_url("../escape"))

    def test_records_support_nominal_ids_both_proposal_layouts_and_crlf(self) -> None:
        evidence = self.root / "proposals" / "feature" / "2026-10-31-example" / "evidence" / "measurement.md"
        evidence.parent.mkdir(parents=True)
        evidence.write_bytes(b"---\r\nsource: instrument\r\n---\r\n\r\nmeasured result\r\n")
        reference = EvidenceRef("proposals/feature/2026-10-31-example", EvidenceId("measurement"))
        record = load_evidence_record(reference, config=self.config)
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.source, "instrument")
        self.assertEqual(record.excerpt, "measured result")
        proposal = evidence.parent.parent / "proposal.md"
        proposal.write_text("---\nstatus: proposed\n---\n")
        identity = ProposalId("feature/2026-10-31-example")
        loaded = load_proposal_record(identity, config=self.config)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.path, proposal)
        fields = {"kind": "proposal", "id": identity.val, "state": "accepted"}
        self.assertEqual(classify(fields, config=self.config).status, CitationStatus.CHANGED)
        single = proposal.parent.with_suffix(".md")
        single.write_text("---\nstatus: accepted\n---\n")
        self.assertEqual(classify(fields, config=self.config).status, CitationStatus.FRESH)

    def test_records_reject_traversal_symlink_escape_and_missing_status(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            (self.root / "escape").symlink_to(outside, target_is_directory=True)
            for path in ("../secret", "/etc/passwd", "escape/secret"):
                with self.subTest(path=path), self.assertRaises(KctxError):
                    load_record_status(path, config=self.config)
        (self.root / "record.md").write_text("---\ntitle: unfinished\n---\n")
        self.assertEqual(classify({"kind": "record", "path": "record.md"}, config=self.config).status, CitationStatus.UNVERIFIABLE)
        self.assertEqual(classify({"kind": "record", "path": "missing.md"}, config=self.config).status, CitationStatus.GONE)
        self.assertEqual(classify({"kind": "proposal", "id": "feature/absent"}, config=self.config).status, CitationStatus.GONE)
        self.assertIsNone(load_evidence_record("project/missing", config=self.config))

    def test_noncode_expiry_reports_refresh_query(self) -> None:
        fields = {"kind": "query", "seen": "2026-01-01T00:00Z", "ttl": "1d", "q": "query"}
        result = classify(fields, datetime(2026, 1, 3, tzinfo=UTC), config=self.config)
        self.assertEqual(result.status, CitationStatus.EXPIRED)
        self.assertEqual(result.query, "query")
        self.assertEqual(classify({"kind": "web"}, config=self.config).status, CitationStatus.UNVERIFIABLE)
