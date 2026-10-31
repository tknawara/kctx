"""Fail-closed execution of user redaction expressions in a bounded worker."""

import json
import signal
import subprocess
import sys
from pathlib import Path

from kctx.citations._redaction_worker import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    MAX_SPEC_BYTES,
    MAX_TEXT_BYTES,
    WALL_SECONDS,
)
from kctx.domain.json import object_value
from kctx.domain.json import text as json_text
from kctx.errors import KctxError


def apply_redact_fields(text: str, redact_spec: str | None) -> str:
    if not redact_spec:
        return text
    if len(text) > MAX_TEXT_BYTES or len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise KctxError("malformed", "redaction input exceeds 256 KiB")
    if len(redact_spec) > MAX_SPEC_BYTES or len(redact_spec.encode("utf-8")) > MAX_SPEC_BYTES:
        raise KctxError("malformed", "redaction spec exceeds 4096 bytes")
    payload = json.dumps({"text": text, "spec": redact_spec}).encode("utf-8")
    if len(payload) > MAX_REQUEST_BYTES:
        raise KctxError("malformed", "redaction request exceeds size limit")
    worker = Path(__file__).with_name("_redaction_worker.py")
    try:
        process = subprocess.Popen(
            [sys.executable, "-I", str(worker)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise KctxError("malformed", "cannot start isolated redaction worker") from exc
    try:
        stdout, _stderr = process.communicate(payload, timeout=WALL_SECONDS)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise KctxError("timeout", "redaction exceeded 1 second wall limit") from exc
    except BaseException:
        process.kill()
        process.communicate()
        raise
    if process.returncode != 0:
        if process.returncode in (-signal.SIGKILL, -signal.SIGXCPU):
            raise KctxError("timeout", "redaction exceeded worker resource limits")
        raise KctxError("malformed", "isolated redaction worker failed")
    if len(stdout) > MAX_RESPONSE_BYTES:
        raise KctxError("malformed", "redaction response exceeds size limit")
    try:
        decoded: object = json.loads(stdout)
    except ValueError as exc:
        raise KctxError("malformed", "invalid isolated redaction response") from exc
    result = object_value(decoded, "redaction response")
    if "error" in result:
        raise KctxError(
            "malformed", "redaction refused: " + json_text(result["error"], "redaction error")
        )
    return json_text(result.get("text"), "redacted text")
