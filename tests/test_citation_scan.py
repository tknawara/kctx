"""Built-in scanner compatibility using authored tokens and real local Git."""
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from _base import KctxTestCase

from kctx.adapters.git.citations import git_file_content
from kctx.citations.code import make_code
from kctx.citations.scan import check_to_wire, run_check, run_stale
from kctx.citations.syntax import find_cite_lines, replace_field
from kctx.citations.time import iso_now_minute
from kctx.citations.rendering import render_one
from kctx.errors import KctxError


class CitationScanTest(KctxTestCase):
    def test_mark_preserves_crlf_surrounding_bytes_and_unknown_fields(self):
        path = self.root / "note.md"
        token = '⟦cite kind=ticket id="DRQS 1" seen=2020-01-01T00:00Z ttl=1d custom="keep me"⟧'
        original = f"# Café\r\n\r\nprefix {token} suffix\r\nend".encode()
        path.write_bytes(original)
        result = run_check([str(path)], mark=True)
        changed = path.read_bytes()
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(result["results"][0]["line_no"], 3)
        self.assertEqual(changed.count(b"\r\n"), 3)
        self.assertTrue(changed.startswith("# Café\r\n\r\nprefix ".encode()))
        self.assertTrue(changed.endswith(b" suffix\r\nend"))
        self.assertIn(b'custom="keep me"', changed)
        self.assertIn(b"stale=expired@", changed)
        self.assertNotIn("touched_line", result["results"][0])
        self.assertNotIn("available", check_to_wire(result))

    def test_illustrative_skips_and_structured_unpinned_warnings(self):
        path = self.root / "note.md"
        path.write_text('⟦cite illus kind=code repo=missing⟧\nacme/widget@main:f.py\n⟦cite kind=ticket seen=2020-01-01T00:00Z ttl=none⟧\n', encoding="utf-8")
        result = run_check([str(path)])
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["skipped"], [{"file": str(path), "line_no": 1}])
        self.assertEqual(result["warnings"], [{"file": str(path), "line_no": 2, "text": "@main:"}])
        self.assertEqual(len(result["results"]), 1)
        inline = run_check(inline_line="example ⟦cite illus kind=code⟧")
        self.assertEqual(inline["skipped"], [{"file": None, "line_no": None}])

    def test_touch_cadence_and_touch_all(self):
        token = f'⟦cite kind=ticket seen={iso_now_minute()} ttl=1d⟧'
        recent = run_check(inline_line=token, touch=True)
        self.assertNotIn("touched_line", recent["results"][0])
        forced = run_check(inline_line=token, touch_all=True)
        self.assertIn("touched_line", forced["results"][0])
        never = run_check(inline_line='⟦cite kind=ticket seen=2020-01-01T00:00Z ttl=none⟧', touch=True)
        self.assertNotIn("touched_line", never["results"][0])

    def test_moved_span_touch_preserves_historical_binding_and_records_current_locator(self):
        with self.cache_backed_repo("acme", "widget") as remote:
            sha = self.commit_file(remote, "f.py", "target()\n", "initial")
            token = make_code("acme/widget", "f.py", "1-1", rev=sha).line
            token = replace_field(token, "seen", "2020-01-01T00:00Z")
            original = next(find_cite_lines(token))[1]
            moved_sha = self.commit_file(remote, "f.py", "# heading\ntarget()\n", "move")
            moved = run_check(inline_line=token, touch_all=True, mark=True)
            self.assertEqual(moved["exit_code"], 2)
            self.assertEqual(moved["results"][0]["status"], "moved")
            self.assertEqual(moved["results"][0]["L"], "2-2")
            touched = moved["results"][0]["touched_line"]
            fields = next(find_cite_lines(touched))[1]
            for key in ("rev", "blob", "span", "L", "seen"):
                self.assertEqual(fields[key], original[key], key)
            self.assertEqual(fields["L"], "1-1")
            self.assertEqual(fields["current_L"], "2-2")
            self.assertEqual(fields["current_rev"], moved_sha)
            self.assertEqual(fields["check_status"], "moved")
            self.assertIn("checked_at", fields)
            self.assertEqual(git_file_content(remote, fields["rev"], "f.py"), "target()\n")
            rendered = render_one(fields)
            self.assertIn(f"/blob/{sha}/f.py#L1", rendered)
            self.assertNotIn("#L2", rendered)
            # A recent receipt controls check cadence, never the cited seen age.
            repeated = run_check(inline_line=touched, touch=True)
            self.assertNotIn("touched_line", repeated["results"][0])
            self.commit_file(remote, "f.py", "different()\n", "change")
            changed = run_check(inline_line=touched, mark=True)
            self.assertEqual(changed["results"][0]["status"], "changed")
            self.assertIn("stale=changed@", changed["results"][0]["touched_line"])
            self.assertIn("head=", changed["results"][0]["touched_line"])
            changed_fields = next(find_cite_lines(changed["results"][0]["touched_line"]))[1]
            self.assertNotIn("current_L", changed_fields)
            for key in ("rev", "blob", "span", "L", "seen"):
                self.assertEqual(changed_fields[key], original[key], key)
            self.run_git(remote, "rm", "f.py")
            self.run_git(remote, "commit", "-qm", "remove")
            gone = run_check(inline_line=token, mark=True)
            self.assertEqual(gone["results"][0]["status"], "gone")
            self.assertIn("stale=gone@", gone["results"][0]["touched_line"])
            gone_fields = next(find_cite_lines(gone["results"][0]["touched_line"]))[1]
            for key in ("rev", "blob", "span", "L", "seen"):
                self.assertEqual(gone_fields[key], original[key], key)

    def test_noncode_touch_receipt_does_not_renew_observation_age(self):
        now = datetime.now(UTC)
        seen = (now - timedelta(hours=18)).strftime("%Y-%m-%dT%H:%MZ")
        token = f'⟦cite kind=ticket id="DRQS 1" seen={seen} ttl=1d⟧'
        result = run_check(inline_line=token, touch=True)
        touched = result["results"][0]["touched_line"]
        fields = next(find_cite_lines(touched))[1]
        self.assertEqual(fields["seen"], seen)
        self.assertNotEqual(fields["checked_at"], seen)
        path = self.root / "note.md"
        path.write_text(touched, encoding="utf-8")
        stale = run_stale([str(path)], offline=True, now=now + timedelta(hours=7))
        self.assertEqual(stale["entries"][0]["reason"], "due")
        self.assertGreater(stale["entries"][0]["age_days"], 1.0)

    def test_unverifiable_takes_precedence_over_expired(self):
        path = self.root / "note.md"
        path.write_text('⟦cite kind=ticket seen=2020-01-01T00:00Z ttl=1d⟧\n⟦cite kind=ticket⟧\n', encoding="utf-8")
        result = run_check([str(path)], mark=True)
        self.assertEqual(result["exit_code"], 3)
        self.assertEqual([row["status"] for row in result["results"]], ["expired", "unverifiable"])
        self.assertEqual(path.read_text(encoding="utf-8").count("stale="), 1)

    def test_offline_stale_groups_and_invalid_timestamps(self):
        project = self.root / "project"
        project.mkdir()
        path = project / "note.md"
        path.write_text('⟦cite kind=code seen=2020-01-01T00:00Z ttl=1d⟧\n⟦cite kind=ticket seen=bad stale=expired@2020-01-01⟧\n⟦cite kind=ticket seen=bad ttl=1d⟧\n⟦cite illus seen=2020-01-01T00:00Z ttl=1d⟧\n', encoding="utf-8")
        with patch("kctx.citations.scan.classify", side_effect=AssertionError("offline must not classify")):
            result = run_stale([str(self.root)], offline=True, now=datetime(2020, 1, 3, tzinfo=UTC))
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["oldest_age_days"], 2.0)
        self.assertEqual(result["groups"], {"project": {"count": 2, "oldest_age_days": 2.0}})
        self.assertEqual([entry["reason"] for entry in result["entries"]], ["due", "marked"])
        self.assertIsNone(result["entries"][1]["age_days"])

    def test_missing_paths_and_missing_inline_token_are_errors(self):
        for action in (
            lambda: run_check([str(self.root / "missing")]),
            lambda: run_stale([str(self.root / "missing")]),
            lambda: run_check(inline_line="not a citation"),
        ):
            with self.subTest(action=action), self.assertRaises(KctxError):
                action()

