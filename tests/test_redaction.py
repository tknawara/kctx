"""Credential markers must not cross rendering, errors, or logging boundaries."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kctx.citations.rendering import render_one
from kctx.config import Config
from kctx.errors import KctxError
from kctx.redaction import REDACTED, mask_secrets, scrub, scrub_argv

MARKER = "DUMMY_CREDENTIAL_927_MARKER"


class RedactionTests(unittest.TestCase):
    def test_labeled_text_json_headers_flags_and_urls(self) -> None:
        samples = (
            f'{{"password": "{MARKER}", "name": "useful"}}',
            f"{{'api_key': '{MARKER}', 'status': 'failed'}}",
            f"password={MARKER} status=failed",
            f"Authorization: Bearer {MARKER}",
            f'{{"Authorization": "Basic {MARKER}"}}',
            f"--token {MARKER} --branch main",
            f"['fetch', '--password', '{MARKER}']",
            f"https://user:{MARKER}@example.test/path?branch=main",
            f"https://example.test/path?access_token={MARKER}&branch=main",
            f"https://example.test/path?access%5Ftoken={MARKER}&branch=main",
            f"-----BEGIN RSA PRIVATE KEY-----\n{MARKER}\n-----END RSA PRIVATE KEY-----",
        )
        for sample in samples:
            with self.subTest(sample=sample):
                rendered = mask_secrets(sample)
                self.assertNotIn(MARKER, rendered)
                self.assertIn(REDACTED, rendered)
                self.assertEqual(mask_secrets(rendered), rendered)
        self.assertIn('"name": "useful"', mask_secrets(samples[0]))
        self.assertIn("branch=main", mask_secrets(samples[-2]))
        self.assertEqual(mask_secrets("normal source=https://example.test/a?rev=abc"), "normal source=https://example.test/a?rev=abc")

    def test_nested_values_and_argv_are_detached_not_source_mutations(self) -> None:
        source = {"request": {"password": MARKER, "headers": {"Authorization": "Bearer " + MARKER}}, "argv": ["fetch", "--token", MARKER, "--branch", "main"], "status": "failed"}
        redacted = scrub(source)
        self.assertNotIn(MARKER, json.dumps(redacted))
        self.assertIn(MARKER, json.dumps(source))
        self.assertEqual(scrub_argv(["fetch", "--token", MARKER, "main"]), ["fetch", "--token", REDACTED, "main"])
        self.assertEqual(scrub_argv(["fetch", f"--password={MARKER}", "main"]), ["fetch", f"--password={REDACTED}", "main"])

    def test_render_and_cli_error_message_share_redaction(self) -> None:
        quote = json.dumps({"password": MARKER, "context": "failed request"})
        fields = {"kind": "usr", "quote": quote}
        for fmt in ("plain", "md", "html"):
            rendered = render_one(fields, fmt=fmt, config=Config())
            self.assertNotIn(MARKER, rendered)
            self.assertIn("failed request", rendered)
        self.assertIn(MARKER, fields["quote"])
        error = KctxError("malformed", f"request failed: {quote}")
        self.assertNotIn(MARKER, str(error))
        self.assertNotIn(MARKER, json.dumps({"category": error.category, "message": error.message}))
        self.assertIn("request failed", error.message)

    def test_real_logs_console_spans_stderr_and_raw_provenance(self) -> None:
        script = '''
import json, logging, sys
from pathlib import Path
from unittest.mock import patch
from kctx import observability
marker = sys.argv[2]
root = Path(sys.argv[1])
with patch("kctx.observability.log_dir", return_value=root):
    observability.init_logging(verbose=True)
    observability.get_logger().info("request", nested={"password": marker}, argv=["fetch", "--token", marker])
    logging.getLogger("foreign").warning("request password=%s", marker)
    try:
        with observability.span("fetch", remote="https://example.test/a?token=" + marker):
            raise RuntimeError(json.dumps({"password": marker, "context": "span failure"}))
    except RuntimeError:
        pass
    proc = observability.run_logged([sys.executable, "-c", "import sys; sys.stderr.write('token=' + sys.argv[-1]); sys.exit(3)", "--token", marker], check=False)
    pem = "-----BEGIN PRIVATE KEY-----\\n" + marker + "x" * 2500 + "\\n-----END PRIVATE KEY-----"
    observability.get_logger().error("pem", payload=pem)
    events = observability.read_events()
    print(json.dumps({"raw_stderr_retained": marker in proc.stderr, "events": events}))
'''
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run([sys.executable, "-c", script, directory, MARKER], capture_output=True, text=True, check=True)
            log_bytes = (Path(directory) / "kctx.jsonl").read_text(encoding="utf-8")
            self.assertNotIn(MARKER, log_bytes)
            self.assertNotIn(MARKER, process.stderr)
            self.assertNotIn(MARKER, process.stdout)
            result = json.loads(process.stdout)
            self.assertTrue(result["raw_stderr_retained"])
            self.assertTrue(any(event["event"] == "subprocess" and event["returncode"] == 3 for event in result["events"]))
            self.assertTrue(any(event["event"] == "span.end" and event["status"] == "error" for event in result["events"]))
            self.assertIn("span failure", log_bytes)
