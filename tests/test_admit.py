"""Covers the kctx-admit proposal's acceptance gates G2-G5 (G1/G6/G7 are the
drain-reuse/docs/repo-named gates already exercised by test_nav.py and the
docs themselves). Gates in each test's docstring refer to
proposals/config/2026-10-26-kctx-admit-.../proposal.md."""

from pathlib import Path
from unittest.mock import patch

from _base import KctxTestCase, set_config

import kctx.services.admit as admit
from kctx.services import admission_state, citation_refresh
from kctx.citations.code import make_code
from kctx.citations.scan import run_check
from kctx.errors import KctxError
from kctx.domain.vocabulary import InvestigationTrigger, SignatureStatus
import kctx.services.investigations as inv_mod
import kctx.services.ktlo as ktlo_mod
import kctx.services.signatures as sig_mod


class CursorSafetyTest(KctxTestCase):
    """G3: cursor safety."""

    def test_no_cursor_and_no_since_blocks(self):
        res = admit.admit_repo(self.root, "acme/widget")
        self.assertEqual(res["exit_code"], 3)
        self.assertIsNone(admission_state.load_cursor(self.root, "acme", "widget"))

    def test_cursor_unreachable_after_rewrite_blocks_and_leaves_cursor_untouched(self):
        
        with self.cache_backed_repo("acme", "widget") as remote:
            sha0 = self.commit_file(remote, "f.txt", "v0", "init")
            admission_state.save_cursor(self.root, "acme", "widget", sha0)

            self.run_git(remote, "checkout", "-q", "--orphan", "newmain")
            self.commit_file(remote, "f.txt", "different-v0", "fresh root")
            self.run_git(remote, "branch", "-D", "main")
            self.run_git(remote, "branch", "-m", "newmain", "main")

            res = admit.admit_repo(self.root, "acme/widget")
            self.assertEqual(res["exit_code"], 3)
            cursor = admission_state.load_cursor(self.root, "acme", "widget")
            self.assertEqual(cursor["sha"], sha0)

    def test_cursor_advances_only_after_a_successful_run(self):
        
        with self.cache_backed_repo("acme", "widget") as remote:
            sha0 = self.commit_file(remote, "f.txt", "v0", "init")
            admission_state.save_cursor(self.root, "acme", "widget", sha0)
            sha1 = self.commit_file(remote, "f.txt", "v1", "update")

            res = admit.admit_repo(self.root, "acme/widget")
            self.assertEqual(res["exit_code"], 0)
            cursor = admission_state.load_cursor(self.root, "acme", "widget")
            self.assertEqual(cursor["sha"], sha1)

    def test_dry_run_writes_nothing(self):
        
        with self.cache_backed_repo("acme", "widget") as remote:
            sha0 = self.commit_file(remote, "f.txt", "v0", "init")
            admission_state.save_cursor(self.root, "acme", "widget", sha0)
            self.commit_file(remote, "f.txt", "v1", "update")

            
            line = make_code("acme/widget", "f.txt", "1-1", rev=sha0).line
            note = self.root / "note.md"
            note.write_text(f"claim. {line}\n", encoding="utf-8")
            before = note.read_text(encoding="utf-8")

            res = admit.admit_repo(self.root, "acme/widget", dry_run=True)
            self.assertIn(res["exit_code"], (0, 2))
            self.assertEqual(note.read_text(encoding="utf-8"), before)
            cursor = admission_state.load_cursor(self.root, "acme", "widget")
            self.assertEqual(cursor["sha"], sha0)


class CodeCitationIntersectionTest(KctxTestCase):
    """G2: admit refreshes exactly the intersecting code citations."""

    def test_marks_only_the_touched_paths_and_their_rename_sources(self):
        
        with self.cache_backed_repo("acme", "widget") as remote:
            self.commit_file(remote, "file1.py", "print('v0')\n", "init f1")
            sha0 = self.commit_file(remote, "file2.py", "print('other')\n", "init f2")

            
            c1 = make_code("acme/widget", "file1.py", "1-1", rev=sha0).line
            c2 = make_code("acme/widget", "file2.py", "1-1", rev=sha0).line
            note1 = self.root / "note1.md"
            note2 = self.root / "note2.md"
            note1.write_text(f"claim about file1. {c1}\n", encoding="utf-8")
            note2.write_text(f"claim about file2. {c2}\n", encoding="utf-8")
            before_note2 = note2.read_text(encoding="utf-8")

            admission_state.save_cursor(self.root, "acme", "widget", sha0)
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
        set_config(gh_bin=stub)
        res = admit.admit_pr(self.root, "acme/widget#9")
        self.assertEqual(res["exit_code"], 2)

    def test_merged_pr_records_advisory_without_rewriting_observation(self):
        
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
            set_config(gh_bin=stub)
            res = admit.admit_pr(self.root, "acme/widget#9")

            self.assertEqual(res["merge_commit_sha"], sha1)
            text = note.read_text(encoding="utf-8")
            self.assertIn("current_state=merged", text)
            self.assertIn("state=open seen=2026-01-01T00:00Z", text)
            self.assertIn("checked_at=", text)
            self.assertEqual(run_check([str(note)])["results"][0]["status"], "expired")

    def test_pr_classification_does_not_query_live_github(self):
        result = run_check(inline_line='⟦cite kind=pr repo=acme/widget n=9 q="landed?" state=open seen=2020-01-01T00:00Z ttl=3d⟧')
        self.assertEqual(result["results"][0]["status"], "expired")


class JudgmentScanTest(KctxTestCase):
    """G5: judgment items reported, never edited."""

    def test_status_ktlo_investigation_and_open_signature_are_reported_and_untouched(
        self,
    ):
        
        with self.cache_backed_repo("acme", "widget") as remote:
            sha0 = self.commit_file(remote, "f.txt", "v0", "init")
            admission_state.save_cursor(self.root, "acme", "widget", sha0)

            proj = self.root / "demo-project"
            proj.mkdir()
            status_path = proj / "STATUS.md"
            status_path.write_text(
                "updated: 2026-01-01\nphase: active\n\n"
                "Waiting on acme/widget#9 before continuing.\n",
                encoding="utf-8",
            )
            before_status = status_path.read_text(encoding="utf-8")

            ktlo_mod.new(self.root, ticket=ktlo_mod.normalize_ticket('DRQS 1'), title='widget fix', assets=())
            ktlo_path = ktlo_mod.all_paths(self.root)[0]
            parsed = ktlo_mod.parse(ktlo_path.read_text(encoding="utf-8"))
            parsed.document.update_section("Symptom", "Blocked on #9 landing.").write(ktlo_path)
            before_ktlo = ktlo_path.read_text(encoding="utf-8")

            inv_mod.new(self.root, 'widget-wait', trigger=InvestigationTrigger.ADHOC)
            inv_path = inv_mod.all_paths(self.root)[0]
            inv_parsed = inv_mod.parse(inv_path.read_text(encoding="utf-8"))
            inv_parsed.document.update_section("Follow-ups", "Check once #9 merges.").write(inv_path)
            before_inv = inv_path.read_text(encoding="utf-8")

            sig_mod.new(self.root, 'widget-flake', status=SignatureStatus.SUSPECTED)
            sig_path = sig_mod.all_paths(self.root)[0]
            sig_parsed = sig_mod.parse(sig_path.read_text(encoding="utf-8"))
            sig_parsed.document.update_section("Mechanism", "Suspect acme/widget#9 reintroduced this.").write(sig_path)
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
            set_config(gh_bin=stub)
            res = admit.admit_repo(self.root, "acme/widget")

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
        self.assertEqual(admission_state.merge_pending([a], [dup, b]), [a, b])
        self.assertEqual(admission_state.merge_pending(None, []), [])
        self.assertEqual(admission_state.merge_pending([a], []), [a])

    def test_cursor_round_trips_pending(self):
        item = {"file": "p/STATUS.md", "line_no": 3, "reason": "project reference",
                "excerpt": "acme/widget#7"}
        admission_state.save_cursor(self.root, "acme", "widget", "deadbeef", pending=[item])
        cursor = admission_state.load_cursor(self.root, "acme", "widget")
        self.assertEqual(cursor["sha"], "deadbeef")
        self.assertEqual(cursor["pending"], [item])

    def test_pending_survives_rewrite_block_and_no_change_replay(self):
        # A rewrite-blocked run must not lose prior pending work either.
        item = {"file": "p/STATUS.md", "line_no": 3, "reason": "project reference",
                "excerpt": "acme/widget#7"}
        admission_state.save_cursor(self.root, "acme", "widget", "aaa", pending=[item])
        cursor = admission_state.load_cursor(self.root, "acme", "widget")
        self.assertEqual(cursor["pending"], [item])

    def test_legacy_cursor_without_pending_reads_cleanly(self):
        from kctx.adapters.files.storage import atomic_write_json
        atomic_write_json(
            admission_state.cursor_path(self.root, "acme", "widget"),
            {"repo": "acme/widget", "sha": "bb", "admitted_at": "x", "by": "old"},
        )
        cursor = admission_state.load_cursor(self.root, "acme", "widget")
        self.assertEqual(admission_state.merge_pending((cursor or {}).get("pending"), []), [])


class TypedRefreshBoundaryTest(KctxTestCase):
    def test_malformed_pending_cursor_is_rejected_without_rewrite(self):
        from kctx.adapters.files.storage import atomic_write_json
        path = admission_state.cursor_path(self.root, "acme", "widget")
        atomic_write_json(path, {"repo": "acme/widget", "sha": "abc", "admitted_at": "x", "by": "old", "pending": [{"file": "x", "line_no": "one"}]})
        before = path.read_bytes()
        with self.assertRaises(KctxError):
            admission_state.load_cursor(self.root, "acme", "widget")
        self.assertEqual(path.read_bytes(), before)

    def test_unavailable_source_is_unverifiable(self):
        result = run_check(inline_line=f'⟦cite kind=code repo=local:{self.root / "missing"} path=f.py rev=abcdef0 blob=abcdef0 L=1-1⟧')
        self.assertTrue(result["available"])
        self.assertEqual(result["exit_code"], 3)
        self.assertEqual(result["results"][0]["status"], "unverifiable")
        self.assertTrue(result["results"][0]["reason"])

    def test_pr_refresh_preserves_crlf_and_unrelated_bytes(self):
        path = self.root / "notes.md"
        original = b'# Unknown heading\r\n\r\nclaim \xe2\x9f\xa6cite kind=pr repo=acme/widget n=9 state=open seen=2020-01-01T00:00Z ttl=3d\xe2\x9f\xa7\r\n'
        path.write_bytes(original)
        with patch("kctx.services.citation_refresh.fetch_pr", return_value={"merged": True, "state": "closed", "merge_commit_sha": "abc"}):
            result = citation_refresh.refresh_pr_citations(self.root, "acme/widget")
        self.assertEqual(result["merged_numbers"], [9])
        self.assertTrue(path.read_bytes().startswith(b"# Unknown heading\r\n\r\n"))
        self.assertEqual(path.read_bytes().count(b"\r\n"), 3)
        self.assertIn(b"state=open seen=2020-01-01T00:00Z", path.read_bytes())
        self.assertIn(b"current_state=merged", path.read_bytes())
        self.assertEqual(run_check([str(path)])["results"][0]["status"], "expired")

    def test_refresh_uses_shared_quoted_grammar_and_skips_illustrations(self):
        path = self.root / "notes.md"
        illustrative = '⟦cite illus kind=pr repo=acme/widget n=8 state=open⟧'
        path.write_text(
            illustrative + '\n⟦cite kind="pr" repo="acme/widget" n=9 state=open⟧\n',
            encoding="utf-8",
        )
        with patch("kctx.services.citation_refresh.fetch_pr", return_value={"merged": True, "state": "closed", "merge_commit_sha": "abc"}) as fetched:
            result = citation_refresh.refresh_pr_citations(self.root, "acme/widget")
        fetched.assert_called_once_with("acme", "widget", 9)
        self.assertEqual(result["merged_numbers"], [9])
        self.assertIn(illustrative, path.read_text(encoding="utf-8"))

