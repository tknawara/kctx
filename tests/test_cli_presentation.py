"""CLI stream contracts for untrusted text and parse failures."""

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from _base import KctxTestCase
from kctx.cli.app import main


class PresentationBoundaryTests(KctxTestCase):
    def invoke(self, *arguments: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_explicit_help_color_is_applied_before_eager_help(self):
        with patch.dict("os.environ", {"NO_COLOR": "1"}):
            for choice in ("always", "never", "auto"):
                with self.subTest(color=choice):
                    code, stdout, stderr = self.invoke("--color", choice, "--help")
                    self.assertEqual(code, 0)
                    self.assertEqual("\x1b[" in stdout, choice == "always")
                    self.assertEqual(stderr, "")

    def test_machine_parse_errors_are_json_and_nonzero(self):
        for arguments in (("--json", "missing-command"), ("--json", "--missing-option"),
                          ("--json", "asset", "add", "--kind", "service")):
            with self.subTest(arguments=arguments):
                code, stdout, stderr = self.invoke(*arguments)
                self.assertEqual(code, 1)
                error = json.loads(stdout)
                self.assertEqual(error["error"], "malformed")
                self.assertEqual(error["diagnostics"][0]["code"], "E102")
                self.assertNotIn("\x1b", stdout + stderr)
                self.assertEqual(stderr, "")

    def test_human_data_cannot_execute_ansi_or_markup(self):
        name = "[bold]source[/bold]\x1b[2J\u202erecord"
        code, _, _ = self.invoke("--json", "asset", "add", "--id", "unsafe-text", "--kind", "service", "--name", name)
        self.assertEqual(code, 0)
        code, stdout, stderr = self.invoke("--color", "never", "asset", "show", "unsafe-text")
        self.assertEqual(code, 0)
        self.assertNotIn("\x1b", stdout)
        self.assertNotIn("\u202e", stdout)
        self.assertIn("[bold]source[/bold]", stdout)
        self.assertIn("\\x1b[2J", stdout)
        self.assertIn("\\u202e", stdout)
        self.assertEqual(stderr, "")
        code, machine, _ = self.invoke("--json", "--color", "always", "asset", "show", "unsafe-text")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(machine)["name"], name)
        self.assertNotIn("\x1b", machine)

    def test_json_option_spelling_as_value_does_not_change_mode(self):
        code, stdout, stderr = self.invoke("--color", "never", "asset", "add", "--id", "literal-value", "--kind", "service", "--name", "--json")
        self.assertEqual(code, 0)
        self.assertIn("name: --json", stdout)
        self.assertEqual(stderr, "")
        with self.assertRaises(json.JSONDecodeError):
            json.loads(stdout)

    def test_no_color_auto_keeps_expected_error_on_stderr(self):
        with patch.dict("os.environ", {"NO_COLOR": "1"}):
            code, stdout, stderr = self.invoke("asset", "show", "absent-asset")
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("error[E101]", stderr)
        self.assertNotIn("\x1b", stderr)
