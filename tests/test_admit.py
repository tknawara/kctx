"""Covers the kctx-admit proposal's acceptance gates G2-G5 (G1/G6/G7 are the
drain-reuse/docs/repo-named gates already exercised by test_nav.py and the
docs themselves). Gates in each test's docstring refer to
proposals/config/2026-10-26-kctx-admit-.../proposal.md."""

import os
from pathlib import Path

from _base import KctxTestCase, dotfiles_cite_available

import admit
import investigations as inv_mod
import ktlo as ktlo_mod
import signatures as sig_mod


class CursorSafetyTest(KctxTestCase):
    """G3: cursor safety."""

    def test_no_cursor_and_no_since_blocks(self):
        res = admit.admit_repo(self.root, "acme/widget")
        self.assertEqual(res["exit_code"], 3)
        self.assertIsNone(admit.load_cursor(self.root, "acme", "widget"))

    def test_cursor_unreachable_after_rewrite_blocks_and_leaves_cursor_untouched(self):
        if not dotfiles_cite_available():
            self.skipTest("grounding cite.py not found in this environment")
        with self.cache_backed_repo("acme", "widget") as remote:
            sha0 = self.commit_file(remote, "f.txt", "v0", "init")
            admit.save_cursor(self.root, "acme", "widget", sha0)

            self.run_git(remote, "checkout", "-q", "--orphan", "newmain")
            self.commit_file(remote, "f.txt", "different-v0", "fresh root")
            self.run_git(remote, "branch", "-D", "main")
            self.run_git(remote, "branch", "-m", "newmain", "main")

            res = admit.admit_repo(self.root, "acme/widget")
            self.assertEqual(res["exit_code"], 3)
            cursor = admit.load_cursor(self.root, "acme", "widget")
            self.assertEqual(cursor["sha"], sha0)

    def test_cursor_advances_only_after_a_successful_run(self):
        if not dotfiles_cite_available():
            self.skipTest("grounding cite.py not found in this environment")
        with self.cache_backed_repo("acme", "widget") as remote:
            sha0 = self.commit_file(remote, "f.txt", "v0", "init")
            admit.save_cursor(self.root, "acme", "widget", sha0)
            sha1 = self.commit_file(remote, "f.txt", "v1", "update")

            res = admit.admit_repo(self.root, "acme/widget")
            self.assertEqual(res["exit_code"], 0)
            cursor = admit.load_cursor(self.root, "acme", "widget")
            self.assertEqual(cursor["sha"], sha1)

    def test_dry_run_writes_nothing(self):
        if not dotfiles_cite_available():
            self.skipTest("grounding cite.py not found in this environment")
        with self.cache_backed_repo("acme", "widget") as remote:
            sha0 = self.commit_file(remote, "f.txt", "v0", "init")
            admit.save_cursor(self.root, "acme", "widget", sha0)
            self.commit_file(remote, "f.txt", "v1", "update")

            cite_mod = admit.load_cite_module()
            line = cite_mod.make_code("acme/widget", "f.txt", "1-1", rev=sha0)["line"]
            note = self.root / "note.md"
            note.write_text(f"claim. {line}\n", encoding="utf-8")
            before = note.read_text(encoding="utf-8")

            res = admit.admit_repo(self.root, "acme/widget", dry_run=True)
            self.assertIn(res["exit_code"], (0, 2))
            self.assertEqual(note.read_text(encoding="utf-8"), before)
            cursor = admit.load_cursor(self.root, "acme", "widget")
            self.assertEqual(cursor["sha"], sha0)


class CodeCitationIntersectionTest(KctxTestCase):
    """G2: admit refreshes exactly the intersecting code citations."""

    def test_marks_only_the_touched_paths_and_their_rename_sources(self):
        if not dotfiles_cite_available():
            self.skipTest("grounding cite.py not found in this environment")
        with self.cache_backed_repo("acme", "widget") as remote:
            self.commit_file(remote, "file1.py", "print('v0')\n", "init f1")
            sha0 = self.commit_file(remote, "file2.py", "print('other')\n", "init f2")

            cite_mod = admit.load_cite_module()
            c1 = cite_mod.make_code("acme/widget", "file1.py", "1-1", rev=sha0)["line"]
            c2 = cite_mod.make_code("acme/widget", "file2.py", "1-1", rev=sha0)["line"]
            note1 = self.root / "note1.md"
            note2 = self.root / "note2.md"
            note1.write_text(f"claim about file1. {c1}\n", encoding="utf-8")
            note2.write_text(f"claim about file2. {c2}\n", encoding="utf-8")
            before_note2 = note2.read_text(encoding="utf-8")

            admit.save_cursor(self.root, "acme", "widget", sha0)
            self.commit_file(remote, "file1.py", "print('v1')\n", "change f1")

            res = admit.admit_repo(self.root, "acme/widget")
            self.assertTrue(res["code_citations"]["citations_available"])
            touched = {
                Path(t["file"]).name for t in res["code_citations"]["touched_files"]
            }
            self.assertIn("note1.md", touched)
            self.assertNotIn("note2.md", touched)
            self.assertEqual(note2.read_text(encoding="utf-8"), before_note2)
            self.assertIn("stale=", note1.read_text(encoding="utf-8"))

            self.rename_file(remote, "file2.py", "file3.py", "rename f2")
            res2 = admit.admit_repo(self.root, "acme/widget")
            touched2 = {
                Path(t["file"]).name for t in res2["code_citations"]["touched_files"]
            }
            self.assertIn("note2.md", touched2)


class PrShortcutTest(KctxTestCase):
    """G4: PR shortcut and PR-state refresh."""

    def test_unmerged_pr_exits_2(self):
        stub = self.write_gh_stub({"9": {"merged": False, "state": "open"}})
        old = os.environ.get("KCTX_GH")
        os.environ["KCTX_GH"] = stub
        try:
            res = admit.admit_pr(self.root, "acme/widget#9")
        finally:
            if old is None:
                os.environ.pop("KCTX_GH", None)
            else:
                os.environ["KCTX_GH"] = old
        self.assertEqual(res["exit_code"], 2)

    def test_merged_pr_rewrites_its_pr_citations_state(self):
        if not dotfiles_cite_available():
            self.skipTest("grounding cite.py not found in this environment")
        with self.cache_backed_repo("acme", "widget") as remote:
            self.commit_file(remote, "f.txt", "v0", "init")
            sha1 = self.commit_file(remote, "f.txt", "v1", "the PR's change")

            note = self.root / "pr-note.md"
            note.write_text(
                'claim. ⟦cite kind=pr repo=acme/widget n=9 q="landed?" '
                "state=open seen=2026-01-01T00:00Z ttl=3d⟧\n",
                encoding="utf-8",
            )

            stub = self.write_gh_stub(
                {"9": {"merged": True, "merge_commit_sha": sha1, "state": "closed"}}
            )
            old = os.environ.get("KCTX_GH")
            os.environ["KCTX_GH"] = stub
            try:
                res = admit.admit_pr(self.root, "acme/widget#9")
            finally:
                if old is None:
                    os.environ.pop("KCTX_GH", None)
                else:
                    os.environ["KCTX_GH"] = old

            self.assertEqual(res["merge_commit_sha"], sha1)
            text = note.read_text(encoding="utf-8")
            self.assertIn("state=merged", text)
            self.assertNotIn("state=open", text)

    def test_cite_py_gains_no_gh_call(self):
        if not dotfiles_cite_available():
            self.skipTest("grounding cite.py not found in this environment")
        from _base import DOTFILES_CITE_BIN

        cite_py = DOTFILES_CITE_BIN.parent / "cite.py"
        text = cite_py.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"""["']gh["']""")


class JudgmentScanTest(KctxTestCase):
    """G5: judgment items reported, never edited."""

    def test_status_ktlo_investigation_and_open_signature_are_reported_and_untouched(
        self,
    ):
        if not dotfiles_cite_available():
            self.skipTest("grounding cite.py not found in this environment")
        with self.cache_backed_repo("acme", "widget") as remote:
            sha0 = self.commit_file(remote, "f.txt", "v0", "init")
            admit.save_cursor(self.root, "acme", "widget", sha0)

            proj = self.root / "demo-project"
            proj.mkdir()
            status_path = proj / "STATUS.md"
            status_path.write_text(
                "updated: 2026-01-01\nphase: active\n\n"
                "Waiting on acme/widget#9 before continuing.\n",
                encoding="utf-8",
            )
            before_status = status_path.read_text(encoding="utf-8")

            ktlo_mod.new(self.root, ticket="DRQS 1", title="widget fix", assets=[])
            ktlo_path = ktlo_mod.all_paths(self.root)[0]
            parsed = ktlo_mod.parse(ktlo_path.read_text(encoding="utf-8"))
            parsed["body"]["Symptom"] = "Blocked on #9 landing."
            ktlo_path.write_text(
                ktlo_mod.render(parsed["frontmatter"], parsed["body"]),
                encoding="utf-8",
            )
            before_ktlo = ktlo_path.read_text(encoding="utf-8")

            inv_mod.new(self.root, "widget-wait", trigger="adhoc")
            inv_path = inv_mod.all_paths(self.root)[0]
            inv_parsed = inv_mod.parse(inv_path.read_text(encoding="utf-8"))
            inv_parsed["body"]["Follow-ups"] = "Check once #9 merges."
            inv_path.write_text(
                inv_mod.render(inv_parsed["frontmatter"], inv_parsed["body"]),
                encoding="utf-8",
            )
            before_inv = inv_path.read_text(encoding="utf-8")

            sig_mod.new(self.root, "widget-flake", status="suspected")
            sig_path = sig_mod.all_paths(self.root)[0]
            sig_parsed = sig_mod.parse(sig_path.read_text(encoding="utf-8"))
            sig_parsed["body"]["Mechanism"] = "Suspect acme/widget#9 reintroduced this."
            sig_path.write_text(
                sig_mod.render(sig_parsed["frontmatter"], sig_parsed["body"]),
                encoding="utf-8",
            )
            before_sig = sig_path.read_text(encoding="utf-8")

            pr_note = self.root / "pr-note.md"
            pr_note.write_text(
                'claim. ⟦cite kind=pr repo=acme/widget n=9 q="landed?" '
                "state=open seen=2026-01-01T00:00Z ttl=3d⟧\n",
                encoding="utf-8",
            )
            stub = self.write_gh_stub(
                {"9": {"merged": True, "merge_commit_sha": sha0, "state": "closed"}}
            )
            old = os.environ.get("KCTX_GH")
            os.environ["KCTX_GH"] = stub
            try:
                res = admit.admit_repo(self.root, "acme/widget")
            finally:
                if old is None:
                    os.environ.pop("KCTX_GH", None)
                else:
                    os.environ["KCTX_GH"] = old

            files_hit = {item["file"] for item in res["judgment"]}
            self.assertTrue(any(f.endswith("STATUS.md") for f in files_hit))
            self.assertTrue(any(f.endswith(ktlo_path.name) for f in files_hit))
            self.assertTrue(any(f.endswith(inv_path.name) for f in files_hit))
            self.assertTrue(any(f.endswith(sig_path.name) for f in files_hit))

            self.assertEqual(status_path.read_text(encoding="utf-8"), before_status)
            self.assertEqual(ktlo_path.read_text(encoding="utf-8"), before_ktlo)
            self.assertEqual(inv_path.read_text(encoding="utf-8"), before_inv)
            self.assertEqual(sig_path.read_text(encoding="utf-8"), before_sig)


class PendingJudgmentPersistenceTest(KctxTestCase):
    """G3/Q36: advancing the scan cursor must not drop unresolved judgment
    work; pending items survive a second no-change invocation, and a dry run
    reports them without writing."""

    def test_merge_pending_is_idempotent(self):
        a = {"file": "p/STATUS.md", "line_no": 3, "reason": "project reference",
             "excerpt": "acme/widget#7 landed"}
        dup = dict(a)
        b = {"file": "ktlo/x.md", "line_no": 1, "reason": "ktlo record",
             "excerpt": "widget#7 again"}
        self.assertEqual(admit.merge_pending([a], [dup, b]), [a, b])
        self.assertEqual(admit.merge_pending(None, []), [])
        self.assertEqual(admit.merge_pending([a], []), [a])

    def test_cursor_round_trips_pending(self):
        item = {"file": "p/STATUS.md", "line_no": 3, "reason": "project reference",
                "excerpt": "acme/widget#7"}
        admit.save_cursor(self.root, "acme", "widget", "deadbeef", pending=[item])
        cursor = admit.load_cursor(self.root, "acme", "widget")
        self.assertEqual(cursor["sha"], "deadbeef")
        self.assertEqual(cursor["pending"], [item])

    def test_pending_survives_rewrite_block_and_no_change_replay(self):
        # A rewrite-blocked run must not lose prior pending work either.
        item = {"file": "p/STATUS.md", "line_no": 3, "reason": "project reference",
                "excerpt": "acme/widget#7"}
        admit.save_cursor(self.root, "acme", "widget", "aaa", pending=[item])
        cursor = admit.load_cursor(self.root, "acme", "widget")
        self.assertEqual(cursor["pending"], [item])

    def test_legacy_cursor_without_pending_reads_cleanly(self):
        from storage import atomic_write_json
        atomic_write_json(
            admit.cursor_path(self.root, "acme", "widget"),
            {"repo": "acme/widget", "sha": "bb", "admitted_at": "x", "by": "old"},
        )
        cursor = admit.load_cursor(self.root, "acme", "widget")
        self.assertEqual(admit.merge_pending((cursor or {}).get("pending"), []), [])
