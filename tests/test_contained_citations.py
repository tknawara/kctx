"""Citation source boundaries use real links and retained file descriptors."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from _base import KctxTestCase

from kctx.adapters.files.contained import ContainedFile, contained_markdown, open_directory
from kctx.citations.classification import classify
from kctx.citations.rendering import extract_cite_items
from kctx.citations.scan import run_check, run_stale
from kctx.citations.syntax import find_cite_lines
from kctx.errors import KctxError
from kctx.services.citation_refresh import find_citing_files, refresh_pr_citations
from kctx.services.freshness import drain

EXPIRED = '⟦cite kind=query seen=2000-01-01T00:00Z ttl=1d q="original observation"⟧'
PR = '⟦cite kind=pr repo=acme/widget n=9 state=open seen=2000-01-01T00:00Z ttl=1d⟧'


class ContainedCitationTest(KctxTestCase):
    def setUp(self):
        super().setUp()
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        self.outside = Path(outside.name)
        self.marker = self.outside / "outside.md"
        self.original = ("OUTSIDE MARKER\r\n" + EXPIRED + "\r\n" + PR + "\r\n").encode()
        self.marker.write_bytes(self.original)

    def test_recursive_leaf_link_refuses_all_consumers_without_outside_mutation(self):
        link = self.root / "link.md"
        link.symlink_to(self.marker)
        actions = (
            lambda: run_check([str(self.root)], mark=True),
            lambda: run_check([str(self.root)]),
            lambda: run_stale([str(self.root)], offline=True),
            lambda: run_stale([str(self.root)]),
            lambda: refresh_pr_citations(self.root, "acme/widget"),
            lambda: refresh_pr_citations(self.root, "acme/widget", dry_run=True),
            lambda: find_citing_files(self.root, "acme/widget", {"f.py"}),
            lambda: extract_cite_items(str(link)),
            lambda: drain(self.root, paths=[str(self.root)]),
        )
        with patch("kctx.services.citation_refresh.fetch_pr") as provider:
            for action in actions:
                with self.subTest(action=action):
                    with self.assertRaises(KctxError) as error:
                        action()
                    self.assertIn("source unavailable", error.exception.message)
                    self.assertEqual(self.marker.read_bytes(), self.original)
            provider.assert_not_called()

    def test_walk_skips_non_markdown_links_but_refuses_selected_ones(self):
        alias = self.root / "linked-directory"
        alias.symlink_to(self.outside, target_is_directory=True)
        # A non-Markdown link inside a walk is skipped unread, never followed:
        # a git-ignored .venv link must not make the tree unscannable.
        result = run_check([str(self.root)], mark=True)
        self.assertNotIn("outside.md", {entry["file"] for entry in result["results"]})
        for target in (alias, alias / "outside.md"):
            with self.subTest(target=target), self.assertRaises(KctxError):
                run_check([str(target)], mark=True)
        with self.assertRaises(OSError):
            descriptor = open_directory(alias)
            os.close(descriptor)
        self.assertEqual(self.marker.read_bytes(), self.original)

    def test_dangling_link_is_not_reported_as_a_clean_drain(self):
        link = self.root / "dangling.md"
        link.symlink_to(self.outside / "missing")
        with self.assertRaises(KctxError):
            drain(self.root, paths=[str(link)])

    def test_later_unsafe_root_prevents_earlier_root_writeback(self):
        safe = self.root / "safe.md"
        before = (EXPIRED + "\r\n").encode()
        safe.write_bytes(before)
        unsafe = self.root / "unsafe"
        unsafe.mkdir()
        (unsafe / "link.md").symlink_to(self.marker)
        with self.assertRaises(KctxError):
            run_check([str(safe), str(unsafe)], mark=True)
        self.assertEqual(safe.read_bytes(), before)
        self.assertEqual(self.marker.read_bytes(), self.original)

    def test_explicit_legitimate_roots_and_overlapping_paths_preserve_observation(self):
        first = self.root / "one.md"
        second = self.outside / "explicit.md"
        before = ("prefix\r\n" + EXPIRED + "\r\nsuffix").encode()
        first.write_bytes(before)
        second.write_bytes(before)
        result = run_check([str(first), str(first), str(second)], mark=True)
        self.assertEqual(len(result["results"]), 2)
        original_fields = next(find_cite_lines(EXPIRED))[1]
        for path in (first, second):
            after = path.read_bytes()
            self.assertTrue(after.startswith(b"prefix\r\n"))
            self.assertTrue(after.endswith(b"\r\nsuffix"))
            self.assertEqual(after.count(b"\r\n"), 2)
            fields = next(find_cite_lines(after.decode()))[1]
            for key, value in original_fields.items():
                self.assertEqual(fields[key], value)
            self.assertIn("stale", fields)
        self.assertEqual(self.marker.read_bytes(), self.original)

    def test_leaf_swap_after_acquisition_cannot_redirect_writeback(self):
        note = self.root / "note.md"
        original = (EXPIRED + "\n").encode()
        note.write_bytes(original)
        retained = self.root / "retained.md"
        def swap(fields, now=None, *, config=None):
            note.rename(retained)
            note.symlink_to(self.marker)
            return classify(fields, now=now, config=config)
        with patch("kctx.citations.scan.classify", side_effect=swap), self.assertRaises(KctxError):
            run_check([str(note)], mark=True)
        self.assertEqual(self.marker.read_bytes(), self.original)
        self.assertEqual(retained.read_bytes(), original)

    def test_directory_swap_keeps_reads_and_writes_on_acquired_descriptors(self):
        directory = self.root / "nested"
        directory.mkdir()
        note = directory / "outside.md"
        note.write_text(EXPIRED, encoding="utf-8")
        held = self.root / "held"
        with contained_markdown([str(directory)], writable=True) as sources:
            directory.rename(held)
            directory.symlink_to(self.outside, target_is_directory=True)
            self.assertEqual(sources[0].text(), EXPIRED)
            ContainedFile.write_updates([(sources[0], EXPIRED + "\nADVISORY")])
        self.assertEqual(self.marker.read_bytes(), self.original)
        self.assertEqual((held / "outside.md").read_text(), EXPIRED + "\nADVISORY")

    def test_batch_preflight_does_not_overwrite_concurrent_edits(self):
        first = self.root / "a.md"
        second = self.root / "b.md"
        first.write_text("first", encoding="utf-8")
        second.write_text("second", encoding="utf-8")
        with contained_markdown([str(first), str(second)], writable=True) as sources:
            second.write_text("concurrent edit", encoding="utf-8")
            with self.assertRaises(KctxError):
                ContainedFile.write_updates([(sources[0], "changed first"), (sources[1], "changed second")])
        self.assertEqual(first.read_text(), "first")
        self.assertEqual(second.read_text(), "concurrent edit")

    def test_pr_refresh_preserves_all_files_when_one_source_is_unsafe(self):
        first = self.root / "a.md"
        first.write_bytes((PR + "\r\n").encode())
        before = first.read_bytes()
        (self.root / "z.md").symlink_to(self.marker)
        with patch("kctx.services.citation_refresh.fetch_pr") as provider:
            with self.assertRaises(KctxError):
                refresh_pr_citations(self.root, "acme/widget")
            provider.assert_not_called()
        self.assertEqual(first.read_bytes(), before)
        self.assertEqual(self.marker.read_bytes(), self.original)

    def test_hardlinked_write_target_is_refused(self):
        note = self.root / "linked.md"
        os.link(self.marker, note)
        with self.assertRaises(KctxError):
            run_check([str(note)], mark=True)
        self.assertEqual(self.marker.read_bytes(), self.original)

    def test_leaf_swap_between_enumeration_and_open_is_refused(self):
        note = self.root / "note.md"
        note.write_text(EXPIRED, encoding="utf-8")
        original_open = os.open
        def swap_before_open(path, flags, mode=0o777, *, dir_fd=None):
            if path == "note.md" and dir_fd is not None:
                note.unlink()
                note.symlink_to(self.marker)
            return original_open(path, flags, mode, dir_fd=dir_fd)
        with patch("kctx.adapters.files.contained.os.open", side_effect=swap_before_open):
            with self.assertRaises(KctxError):
                run_check([str(self.root)], mark=True)
        self.assertEqual(self.marker.read_bytes(), self.original)

    def test_ancestor_swap_between_enumeration_and_open_is_refused(self):
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "note.md").write_text(EXPIRED, encoding="utf-8")
        held = self.root / "held"
        original_open = os.open
        def swap_before_open(path, flags, mode=0o777, *, dir_fd=None):
            if path == "nested" and dir_fd is not None:
                nested.rename(held)
                nested.symlink_to(self.outside, target_is_directory=True)
            return original_open(path, flags, mode, dir_fd=dir_fd)
        with patch("kctx.adapters.files.contained.os.open", side_effect=swap_before_open):
            with self.assertRaises(KctxError):
                run_check([str(self.root)], mark=True)
        self.assertEqual(self.marker.read_bytes(), self.original)
        self.assertEqual((held / "note.md").read_text(), EXPIRED)

    def test_pr_provider_time_swap_cannot_redirect_writeback(self):
        note = self.root / "note.md"
        note.write_text(PR, encoding="utf-8")
        held = self.root / "held.md"
        def swap(*args):
            note.rename(held)
            note.symlink_to(self.marker)
            return {"merged": True, "state": "closed", "merge_commit_sha": "abcdef0"}
        with patch("kctx.services.citation_refresh.fetch_pr", side_effect=swap):
            with self.assertRaises(KctxError):
                refresh_pr_citations(self.root, "acme/widget")
        self.assertEqual(self.marker.read_bytes(), self.original)
        self.assertEqual(held.read_text(), PR)


class ReadOnlyDescriptorTest(KctxTestCase):
    def test_read_only_scans_do_not_hold_one_descriptor_per_file(self):
        notes = self.root / "notes"
        notes.mkdir()
        for index in range(200):
            (notes / f"n{index}.md").write_text("plain text\n", encoding="utf-8")

        def open_fds() -> int:
            return len(os.listdir("/proc/self/fd"))

        baseline = open_fds()
        with contained_markdown([str(notes)]) as sources:
            self.assertEqual(len(sources), 200)
            inside = open_fds()
        self.assertLess(inside, baseline + 100, "read-only scan must not retain a descriptor per file")
        with contained_markdown([str(notes)], writable=True) as writable:
            self.assertEqual(len(writable), 200)
            self.assertGreater(open_fds(), baseline + 190, "write-back runs retain their descriptors")
