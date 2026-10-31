"""Untrusted regular expressions are isolated, bounded, and fail closed."""

import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from kctx.citations._redaction_worker import MAX_SPEC_BYTES, MAX_TEXT_BYTES
from kctx.citations.redaction import apply_redact_fields
from kctx.citations.rendering import render_one
from kctx.config import Config
from kctx.errors import KctxError
from kctx.redaction import REDACTED


class BoundedCitationRedactionTests(unittest.TestCase):
    def test_valid_regex_matches_original_substitution_semantics(self) -> None:
        for pattern, text in (
            (r"[0-9]+", "private 123 and 456"),
            (r"(?i)secret", "SECRET and Secret"),
            (r"(?<=account=)[a-z]+", "account=alice"),
            (r"x*", "abxd"),
            (r"(ab|cd)+", "abab xy cd"),
        ):
            with self.subTest(pattern=pattern):
                self.assertEqual(apply_redact_fields(text, "regex:" + pattern), re.sub(pattern, REDACTED, text))
        self.assertEqual(apply_redact_fields("account=alice number 123", "account,regex:[0-9]+"), f"account={REDACTED} number {REDACTED}")

    def test_catastrophic_pattern_refuses_rendering_with_external_deadline(self) -> None:
        script = '''
from kctx.citations.rendering import render_one
from kctx.config import Config
from kctx.errors import KctxError
try:
    render_one({"kind": "usr", "quote": "a" * 30 + "!", "redact": "regex:(a+)+$"}, config=Config())
except KctxError as exc:
    print(exc.category)
else:
    raise SystemExit("unsafe rendering fallback")
'''
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=5, check=True)
        self.assertEqual(result.stdout.strip(), "timeout")
        self.assertNotIn("a" * 30, result.stdout + result.stderr)

    def test_bad_patterns_and_input_output_limits_refuse(self) -> None:
        for text, spec in (
            ("secret", "regex:["),
            ("x" * (MAX_TEXT_BYTES + 1), "regex:x"),
            ("secret", "regex:" + "x" * MAX_SPEC_BYTES),
            ("x" * 30_000, "regex:"),
        ):
            with self.subTest(spec=spec[:30]), self.assertRaises(KctxError):
                apply_redact_fields(text, spec)
        with self.assertRaises(KctxError):
            render_one({"kind": "usr", "quote": "PRIVATE_MARKER", "redact": "regex:["}, config=Config())

    def test_keyboard_cancellation_kills_and_reaps_real_worker(self) -> None:
        original_popen = subprocess.Popen
        children: list[subprocess.Popen[bytes]] = []

        def start(argv: list[str], *, stdin: int, stdout: int, stderr: int) -> subprocess.Popen[bytes]:
            self.assertEqual(argv[:2], [sys.executable, "-I"])
            self.assertEqual(Path(argv[2]).name, "_redaction_worker.py")
            self.assertEqual(len(argv), 3)
            child = original_popen(argv, stdin=stdin, stdout=stdout, stderr=stderr)
            children.append(child)
            communicate = child.communicate
            interrupted = False

            def interrupt_once(input: bytes | None = None, timeout: float | None = None) -> tuple[bytes, bytes]:
                nonlocal interrupted
                if not interrupted:
                    interrupted = True
                    raise KeyboardInterrupt
                return communicate(input, timeout=timeout)

            replacement = patch.object(child, "communicate", side_effect=interrupt_once)
            replacement.start()
            self.addCleanup(replacement.stop)
            return child

        with patch("kctx.citations.redaction.subprocess.Popen", side_effect=start), self.assertRaises(KeyboardInterrupt):
            apply_redact_fields("private 123", "regex:[0-9]+")
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].returncode)
