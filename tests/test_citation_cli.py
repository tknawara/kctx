"""Citation behavior is available exclusively through the root kctx CLI."""

import io
import json
from contextlib import redirect_stdout

from _base import KctxTestCase
from kctx.cli.app import main


class CitationCommandTest(KctxTestCase):
    def invoke(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--json", "cite", *args])
        return code, json.loads(output.getvalue())

    def test_check_reports_structured_error(self):
        code, payload = self.invoke("check", "--line", "missing token")
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "malformed")

    def test_make_preserves_equals_in_field_values(self):
        code, payload = self.invoke("make", "web", "url=https://example.com/?a=b", "q=claim")
        self.assertEqual(code, 0)
        self.assertEqual(payload["fields"]["url"], "https://example.com/?a=b")
        self.assertIn("⟦cite", payload["line"])

    def test_duplicate_field_is_rejected_without_last_wins(self):
        code, payload = self.invoke("make", "ticket", "id=one", "id=two", "q=claim")
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "malformed")

    def test_native_code_command_constructs_pinned_binding(self):
        with self.cache_backed_repo("acme", "widget") as remote:
            sha = self.commit_file(remote, "f.py", "target()\n", "initial")
            code, payload = self.invoke("make", "code", "acme/widget", "f.py", "1-1", "--rev", sha)
        self.assertEqual(code, 0)
        self.assertEqual(payload["fields"]["rev"], sha)
        self.assertEqual(payload["fields"]["L"], "1-1")

    def test_stale_preserves_partial_exit_and_entries(self):
        path = self.root / "stale.md"
        path.write_text("⟦cite kind=ticket id=one seen=2020-01-01T00:00Z ttl=1d⟧\n", encoding="utf-8")
        code, payload = self.invoke("stale", str(path), "--offline")
        self.assertEqual(code, 2)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["entries"][0]["reason"], "due")

    def test_render_returns_rendered_strings(self):
        code, payload = self.invoke("render", "⟦cite kind=web url=https://example.com q=claim⟧")
        self.assertEqual(code, 0)
        self.assertEqual(len(payload["rendered"]), 1)
        self.assertIn("https://example.com", payload["rendered"][0])
