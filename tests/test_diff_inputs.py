from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kctx.adapters.git.diff import read_local_diff, repository_matches, resolve_local_pin
from kctx.citations.syntax import format_cite
from kctx.domain.diff import DiffHunk, LocalDiff
from kctx.domain.json import JsonObject
from kctx.errors import KctxError
from kctx.services.diff_citations import citations_for_diff


class DiffInputsTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "checkout"
        self.repo.mkdir()
        self.kb = self.root / "kb"
        self.kb.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Diff Test")
        self.git("config", "user.email", "diff@example.invalid")
        self.git("remote", "add", "origin", "https://example.invalid/acme/project.git")
        self.original = "one\ntwo\nthree\nfour\nfive\n"
        self.source = self.repo / "source.py"
        self.source.write_text(self.original, encoding="utf-8")
        self.base = self.commit()

    def git(self, *args: str, input: str | None = None) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.repo), *args],
            capture_output=True,
            text=True,
            check=True,
            input=input,
        )
        return result.stdout.strip()

    def commit(self) -> str:
        self.git("add", "--all")
        self.git("commit", "-m", "fixture")
        return self.git("rev-parse", "HEAD")

    def change(self) -> str:
        self.source.write_text(self.original.replace("three", "changed"), encoding="utf-8")
        return self.commit()

    def cite(
        self,
        revision: str,
        lines: str = "3-3",
        path: str = "source.py",
        repo: str = "acme/project",
        **extra: str,
    ) -> str:
        fields = {"kind": "code", "repo": repo, "path": path, "rev": revision, "L": lines}
        fields.update(extra)
        return format_cite(fields, tuple(fields))

    def scan(self, diff: LocalDiff, *citations: str) -> tuple[dict[str, tuple[JsonObject, ...]], tuple[str, ...]]:
        (self.kb / "notes.md").write_text("\n".join(citations), encoding="utf-8")
        return citations_for_diff(self.kb, diff)

    def test_endpoint_overlap_nonoverlap_and_unique_abbreviations(self) -> None:
        head = self.change()
        diff = read_local_diff(f"{self.base}..{head}", self.repo)
        self.assertEqual((diff.base, diff.head), (self.base, head))
        self.assertEqual(diff.files[0].hunks, (DiffHunk(3, 1, 3, 1),))
        results, warnings = self.scan(
            diff,
            self.cite(self.base),
            self.cite(head[:9]),
            self.cite(head, "1-2"),
        )
        self.assertFalse(warnings)
        entries = results["source.py"]
        self.assertEqual([item["range_status"] for item in entries], ["overlap", "overlap", "nonoverlap"])
        self.assertEqual(entries[0]["overlaps"], [{"hunk_index": 0, "side": "old"}])
        self.assertEqual(entries[1]["overlaps"], [{"hunk_index": 0, "side": "new"}])
        self.assertEqual(entries[2]["overlaps"], [])
        self.assertEqual(entries[0]["file"], "notes.md")
        self.assertEqual(entries[0]["line_no"], 1)
        self.assertEqual(entries[0]["cited_range"], "3-3")
        self.assertEqual(entries[1]["fields"], {
            "kind": "code", "repo": "acme/project", "path": "source.py", "rev": head[:9], "L": "3-3"
        })

    def test_historical_identical_blob_maps_but_shifted_and_unknown_pins_do_not(self) -> None:
        prior = self.base
        (self.repo / "other.txt").write_text("unrelated\n", encoding="utf-8")
        base = self.commit()
        head = self.change()
        self.source.write_text("shift\n" + self.original, encoding="utf-8")
        shifted = self.commit()
        diff = read_local_diff(f"{base}..{head}", self.repo)
        results, warnings = self.scan(
            diff,
            self.cite(prior[:11]),
            self.cite(shifted),
            self.cite("0" * 40),
            self.cite("HEAD"),
        )
        entries = results["source.py"]
        self.assertEqual(entries[0]["overlaps"], [{"hunk_index": 0, "side": "old"}])
        for item in entries[1:]:
            self.assertEqual(item["range_status"], "unmapped_revision")
            self.assertEqual(item["overlaps"], [])
        self.assertEqual(len(warnings), 3)
        self.assertTrue(all("notes.md:" in warning for warning in warnings))

    def test_insertions_and_deletions_do_not_turn_gaps_into_lines(self) -> None:
        self.source.write_text("one\ntwo\ninserted\nthree\nfour\nfive\n", encoding="utf-8")
        inserted = self.commit()
        forward = read_local_diff(f"{self.base}..{inserted}", self.repo)
        self.assertEqual(forward.files[0].hunks, (DiffHunk(2, 0, 3, 1),))
        results, warnings = self.scan(forward, self.cite(self.base, "2-3"), self.cite(inserted))
        self.assertFalse(warnings)
        self.assertEqual(results["source.py"][0]["range_status"], "nonoverlap")
        self.assertEqual(results["source.py"][1]["overlaps"], [{"hunk_index": 0, "side": "new"}])
        reverse = read_local_diff(f"{inserted}..{self.base}", self.repo)
        self.assertEqual(reverse.files[0].hunks, (DiffHunk(3, 1, 2, 0),))
        results, warnings = self.scan(reverse, self.cite(inserted), self.cite(self.base, "2-3"))
        self.assertFalse(warnings)
        self.assertEqual(results["source.py"][0]["overlaps"], [{"hunk_index": 0, "side": "old"}])
        self.assertEqual(results["source.py"][1]["range_status"], "nonoverlap")

    def test_rename_retains_both_paths_and_coordinate_sides(self) -> None:
        target = "new name\tmodule.py"
        self.source.rename(self.repo / target)
        (self.repo / target).write_text(self.original.replace("three", "changed"), encoding="utf-8")
        head = self.commit()
        diff = read_local_diff(f"{self.base}..{head}", self.repo)
        self.assertEqual(len(diff.files), 1)
        file = diff.files[0]
        self.assertEqual((file.old_path, file.new_path, file.status), ("source.py", target, "R"))
        results, warnings = self.scan(diff, self.cite(self.base), self.cite(head, path=target))
        self.assertFalse(warnings)
        self.assertEqual(len(results[target]), 2)
        self.assertEqual(results[target][0]["overlaps"], [{"hunk_index": 0, "side": "old"}])
        self.assertEqual(results[target][1]["overlaps"], [{"hunk_index": 0, "side": "new"}])

    def test_nul_paths_preserve_quotes_tabs_newlines_and_leading_dashes(self) -> None:
        names = (
            'quote"name.py', "tab\tname.py", "line\nname.py", "cr\rname.py", "-option.py"
        )
        for name in names:
            (self.repo / name).write_text(f"{name!r}\n", encoding="utf-8")
        head = self.commit()
        diff = read_local_diff(f"{self.base}..{head}", self.repo)
        additions = {file.new_path: file for file in diff.files}
        self.assertEqual(set(additions), set(names))
        for file in additions.values():
            self.assertEqual(file.status, "A")
            self.assertIsNone(file.old_path)
            self.assertEqual(file.hunks, (DiffHunk(0, 0, 1, 1),))
        reverse = read_local_diff(f"{head}..{self.base}", self.repo)
        self.assertEqual({file.old_path for file in reverse.files}, set(names))
        for file in reverse.files:
            self.assertEqual(file.status, "D")
            self.assertIsNone(file.new_path)
            self.assertEqual(file.hunks, (DiffHunk(1, 1, 0, 0),))

    def test_type_change_retains_one_file_with_both_patch_sides(self) -> None:
        self.source.unlink()
        self.source.symlink_to("target.py")
        head = self.commit()
        diff = read_local_diff(f"{self.base}..{head}", self.repo)
        self.assertEqual(len(diff.files), 1)
        self.assertEqual(diff.files[0].status, "T")
        self.assertEqual((diff.files[0].old_path, diff.files[0].new_path), ("source.py", "source.py"))
        self.assertEqual(diff.files[0].hunks, (DiffHunk(1, 5, 0, 0), DiffHunk(0, 0, 1, 1)))

    def test_non_utf8_paths_fail_explicitly_instead_of_breaking_json(self) -> None:
        path = self.repo / os.fsdecode(b"bad-\xff.py")
        path.write_text("text\n", encoding="utf-8")
        head = self.commit()
        with self.assertRaises(KctxError) as caught:
            read_local_diff(f"{self.base}..{head}", self.repo)
        self.assertIn("UTF-8", str(caught.exception))

    def test_binary_and_mode_only_changes_have_no_invented_hunks(self) -> None:
        binary = self.repo / "image.bin"
        binary.write_bytes(b"before\x00binary")
        base = self.commit()
        binary.write_bytes(b"after\x00binary")
        self.source.chmod(0o755)
        head = self.commit()
        diff = read_local_diff(f"{base}..{head}", self.repo)
        files = {file.new_path: file for file in diff.files}
        self.assertTrue(files["image.bin"].binary)
        self.assertEqual(files["image.bin"].hunks, ())
        self.assertFalse(files["source.py"].binary)
        self.assertEqual(files["source.py"].hunks, ())
        results, warnings = self.scan(diff, self.cite(base), self.cite(head, "1-1", "image.bin"))
        self.assertEqual(results["source.py"][0]["range_status"], "nonoverlap")
        self.assertEqual(results["image.bin"][0]["range_status"], "unmapped_binary")
        self.assertEqual(len(warnings), 1)

    def test_malformed_tokens_are_located_and_illustrative_tokens_are_excluded(self) -> None:
        head = self.change()
        diff = read_local_diff(f"{self.base}..{head}", self.repo)
        valid = self.cite(head)
        results, warnings = self.scan(
            diff,
            "⟦cite kind=code kind=web⟧",
            "⟦cite kind=code repo=acme/project",
            valid,
            valid.replace("⟦cite ", "⟦cite illus "),
            self.cite(head, "0-3"),
            "⟦cite nonsense⟧",
            self.cite(head).replace(f" rev={head}", ""),
        )
        self.assertEqual(len(results["source.py"]), 3)
        self.assertEqual(results["source.py"][0]["line_no"], 3)
        self.assertEqual(results["source.py"][1]["range_status"], "invalid_range")
        self.assertEqual(results["source.py"][2]["range_status"], "unmapped_revision")
        self.assertEqual(len(warnings), 5)
        for line in (1, 2, 5, 6, 7):
            self.assertTrue(any(f"notes.md:{line}:" in warning for warning in warnings))

    def test_exact_identity_rejects_collisions_and_accepts_local_make_form(self) -> None:
        head = self.change()
        diff = read_local_diff(f"{self.base}..{head}", self.repo)
        self.assertEqual(diff.repository, "acme/project")
        for identity in (
            "acme/project", "https://example.invalid/acme/project.git",
            "git@example.invalid:acme/project.git", str(self.repo), self.repo.as_uri(),
        ):
            self.assertTrue(repository_matches(identity, diff), identity)
        for identity in (
            "project", "checkout", "other/project", "acme/project-extra",
            "https://other.invalid/acme/project.git", str(self.root / "other" / "checkout"),
        ):
            self.assertFalse(repository_matches(identity, diff), identity)
        results, warnings = self.scan(
            diff,
            self.cite(head, repo="checkout", url="https://example.invalid/acme/project.git"),
            self.cite(head, repo="checkout", url=str(self.repo)),
            self.cite(head, repo="checkout"),
            self.cite(head, repo="other/project"),
            self.cite(head, url="https://other.invalid/acme/project.git"),
            self.cite(head, repo="other/project", url="https://example.invalid/acme/project.git"),
        )
        self.assertFalse(warnings)
        self.assertEqual(len(results["source.py"]), 2)

    def test_scheme_less_inventory_locators_retain_exact_host_identity(self) -> None:
        head = self.change()
        diff = read_local_diff(f"{self.base}..{head}", self.repo)
        self.assertTrue(repository_matches("example.invalid/acme/project", diff))
        self.assertTrue(repository_matches("example.invalid/acme/project.git", diff))
        self.assertFalse(repository_matches("other.invalid/acme/project", diff))
        self.assertFalse(repository_matches("example.invalid/acme/project-extra", diff))

    def test_nested_namespace_and_relative_origin_do_not_conflate_repositories(self) -> None:
        head = self.change()
        self.git("remote", "set-url", "origin", "https://example.invalid/group/acme/project.git")
        diff = read_local_diff(f"{self.base}..{head}", self.repo)
        self.assertFalse(repository_matches("acme/project", diff))
        self.assertTrue(repository_matches("example.invalid/group/acme/project", diff))
        self.git("remote", "set-url", "origin", "../project")
        diff = read_local_diff(f"{self.base}..{head}", self.repo)
        self.assertFalse(repository_matches("project", diff))
        self.assertTrue(repository_matches(str(self.root / "project"), diff))

    def test_no_origin_uses_exact_checkout_identity_not_basename(self) -> None:
        self.git("remote", "remove", "origin")
        head = self.change()
        diff = read_local_diff(f"{self.base}..{head}", self.repo)
        self.assertEqual(diff.repository, str(self.repo))
        results, warnings = self.scan(
            diff,
            self.cite(head, repo=self.repo.name, url=str(self.repo)),
            self.cite(head, repo=self.repo.name),
        )
        self.assertFalse(warnings)
        self.assertEqual(len(results["source.py"]), 1)

    def test_invalid_ranges_and_missing_endpoints_do_not_default_to_head(self) -> None:
        self.change()
        for value in ("", "HEAD", "..HEAD", "HEAD..", "HEAD...HEAD", "HEAD..HEAD..HEAD"):
            with self.subTest(value=value), self.assertRaises(KctxError):
                read_local_diff(value, self.repo)
        for value in ("missing..HEAD", "HEAD..missing", "--output=bad..HEAD"):
            with self.subTest(value=value), self.assertRaises(KctxError):
                read_local_diff(value, self.repo)
        self.assertEqual(read_local_diff("HEAD..HEAD", self.repo).files, ())

    def test_committed_bytes_ignore_worktree_and_repository_helpers(self) -> None:
        head = self.change()
        marker = self.root / "executed"
        script = self.root / "helper.sh"
        script.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n", encoding="utf-8")
        script.chmod(0o755)
        self.git("config", "diff.external", str(script))
        self.git("config", "diff.danger.textconv", str(script))
        self.git("config", "core.fsmonitor", str(script))
        (self.repo / ".gitattributes").write_text("*.py diff=danger\n", encoding="utf-8")
        self.source.write_text("uncommitted\n", encoding="utf-8")
        diff = read_local_diff(f"{self.base}..{head}", self.repo)
        self.assertEqual(diff.files[0].hunks, (DiffHunk(3, 1, 3, 1),))
        self.assertFalse(marker.exists())

    def test_explicit_repo_ignores_inherited_git_directory_overrides(self) -> None:
        head = self.change()
        wrong = self.root / "wrong"
        wrong.mkdir()
        environment = {
            "GIT_DIR": str(wrong),
            "GIT_WORK_TREE": str(wrong),
            "GIT_INDEX_FILE": str(wrong / "index"),
            "GIT_COMMON_DIR": str(wrong),
            "GIT_DIFF_OPTS": "--unified=20",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.worktree",
            "GIT_CONFIG_VALUE_0": str(wrong),
        }
        with patch.dict(os.environ, environment):
            diff = read_local_diff(f"{self.base}..{head}", self.repo)
        self.assertEqual(diff.repo_path, self.repo)
        self.assertEqual(diff.repository, "acme/project")
        self.assertEqual(diff.files[0].hunks, (DiffHunk(3, 1, 3, 1),))
        nested = self.repo / "nested"
        nested.mkdir()
        self.assertEqual(read_local_diff(f"{self.base}..{head}", nested).repo_path, self.repo)
        with patch("pathlib.Path.cwd", return_value=nested):
            self.assertEqual(read_local_diff(f"{self.base}..{head}").repo_path, self.repo)

    def test_ambiguous_abbreviations_are_not_matched_by_prefix(self) -> None:
        head = self.change()
        tree = self.git("rev-parse", f"{self.base}^{{tree}}")
        seen: dict[str, str] = {}
        pair: tuple[str, str] | None = None
        prefix = ""
        for index in range(65537):
            content = (
                f"tree {tree}\nauthor Diff <diff@example.invalid> 1 +0000\n"
                f"committer Diff <diff@example.invalid> 1 +0000\n\ncollision {index}\n"
            )
            encoded = content.encode()
            identity = hashlib.sha1(b"commit " + str(len(encoded)).encode() + b"\x00" + encoded).hexdigest()
            prefix = identity[:4]
            if prefix in seen:
                pair = seen[prefix], content
                break
            seen[prefix] = content
        self.assertIsNotNone(pair)
        if pair is None:
            self.fail("pigeonhole construction must produce an abbreviated SHA collision")
        for content in pair:
            self.git("hash-object", "-t", "commit", "-w", "--stdin", input=content)
        self.assertIsNone(resolve_local_pin(self.repo, prefix))
        diff = read_local_diff(f"{self.base}..{head}", self.repo)
        results, warnings = self.scan(diff, self.cite(prefix))
        self.assertEqual(results["source.py"][0]["range_status"], "unmapped_revision")
        self.assertEqual(len(warnings), 1)

    def test_missing_promisor_blob_is_unmapped_without_lazy_fetch(self) -> None:
        head = self.change()
        diff = read_local_diff(f"{self.base}..{head}", self.repo)
        blob = self.git("rev-parse", f"{self.base}:source.py")
        object_path = self.repo / ".git" / "objects" / blob[:2] / blob[2:]
        object_path.unlink()
        marker = self.root / "network-attempt"
        self.git("config", "remote.origin.url", f"ext::touch {marker}")
        self.git("config", "protocol.ext.allow", "always")
        self.git("config", "remote.origin.promisor", "true")
        self.git("config", "extensions.partialclone", "origin")
        results, warnings = self.scan(diff, self.cite(self.base))
        self.assertEqual(results["source.py"][0]["range_status"], "unmapped_revision")
        self.assertEqual(len(warnings), 1)
        with self.assertRaises(KctxError):
            read_local_diff(f"{self.base}..{head}", self.repo)
        self.assertFalse(marker.exists())

    def test_unreadable_authored_sources_are_disclosed(self) -> None:
        head = self.change()
        diff = read_local_diff(f"{self.base}..{head}", self.repo)
        (self.kb / "invalid.md").write_bytes(b"\xff")
        (self.kb / os.fsdecode(b"bad-\xff.md")).write_text(self.cite(head), encoding="utf-8")
        results, warnings = self.scan(diff, self.cite(head))
        self.assertEqual(len(results["source.py"]), 1)
        self.assertTrue(any("invalid.md" in warning for warning in warnings))
        self.assertTrue(any("filename is not UTF-8" in warning for warning in warnings))
        for warning in warnings:
            warning.encode("utf-8")
        (self.kb / "linked.md").symlink_to(self.kb / "notes.md")
        _, warnings = citations_for_diff(self.kb, diff)
        self.assertTrue(any("scan incomplete" in warning for warning in warnings))
