"""Fixed stdlib-only worker for bounded citation redaction; never runs source code."""

import json
import re
import resource
import sys
from typing import TypeGuard

MAX_TEXT_BYTES = 256 * 1024
MAX_SPEC_BYTES = 4096
MAX_REQUEST_BYTES = 6 * (MAX_TEXT_BYTES + MAX_SPEC_BYTES) + 1024
MAX_RESPONSE_BYTES = 6 * MAX_TEXT_BYTES + 1024
WALL_SECONDS = 1.0
CPU_SECONDS = 1
ADDRESS_SPACE_BYTES = 128 * 1024 * 1024
_REDACTED = "\u2039redacted\u203a"


def _object_dict(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _bounded_sub(pattern: re.Pattern[str], text: str, *, named_field: bool) -> str:
    parts: list[str] = []
    size = 0
    end = 0
    for match in pattern.finditer(text):
        replacement = f"{match.group(1)}{match.group(2)}{_REDACTED}" if named_field else _REDACTED
        prefix = text[end : match.start()]
        size += len(prefix.encode("utf-8")) + len(replacement.encode("utf-8"))
        if size > MAX_TEXT_BYTES:
            raise ValueError("redacted output exceeds 256 KiB")
        parts.extend((prefix, replacement))
        end = match.end()
    suffix = text[end:]
    if size + len(suffix.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError("redacted output exceeds 256 KiB")
    parts.append(suffix)
    return "".join(parts)


def _redact(text: str, spec: str) -> str:
    for item in (part.strip() for part in spec.split(",")):
        if not item:
            continue
        regex = item.startswith("regex:")
        expression = item[len("regex:") :] if regex else rf"\b({re.escape(item)})\s*([:=])\s*(\S+)"
        pattern = re.compile(expression, 0 if regex else re.IGNORECASE)
        text = _bounded_sub(pattern, text, named_field=not regex)
    return text


def main() -> int:
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
        resource.setrlimit(resource.RLIMIT_AS, (ADDRESS_SPACE_BYTES, ADDRESS_SPACE_BYTES))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("redaction request exceeds size limit")
        payload: object = json.loads(raw)
        if not _object_dict(payload):
            raise ValueError("redaction request must be an object")
        text, spec = payload.get("text"), payload.get("spec")
        if not isinstance(text, str) or not isinstance(spec, str):
            raise ValueError("redaction text and spec must be strings")
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES or len(spec.encode("utf-8")) > MAX_SPEC_BYTES:
            raise ValueError("redaction input exceeds size limit")
        response = {"text": _redact(text, spec)}
    except (ValueError, re.error, OSError, MemoryError, RecursionError) as exc:
        response = {"error": str(exc) or "redaction resource limit exceeded"}
    sys.stdout.write(json.dumps(response, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
