"""Structured logging for kctx: every invocation gets a run_id, every
notable step gets a span with start/end + duration_ms + status, and it all
lands in a JSONL file an agent can replay with `kctx logs` after something
goes wrong -- without needing the original terminal output.

Native Click leaf commands initialize logging once per invocation. Detailed
subprocess and service spans retain run/parent identity in the JSONL file.

File: config log_dir/kctx.jsonl, else $XDG_STATE_HOME/kctx/logs/kctx.jsonl,
else ~/.local/state/kctx/logs/kctx.jsonl. Rotated by size (5 MiB, 5 backups).
Console: verbose human events use Rich on stderr; machine invocations retain
file logs without emitting human diagnostics into their streams.
"""

from __future__ import annotations

import contextlib
import json
import logging
import logging.handlers
import os
import subprocess
import time
import uuid
from collections.abc import Iterator, MutableMapping
from contextvars import ContextVar
from pathlib import Path
from typing import Literal, cast, overload

import structlog
from rich.logging import RichHandler
from structlog.typing import Processor

from kctx.domain.json import JsonObject, JsonValue, object_value
from kctx.errors import KctxError
from kctx.presentation import console, terminal_text
from kctx.redaction import REDACTED, is_secret_key, mask_secrets, scrub

_span_stack: ContextVar[tuple[str, ...]] = ContextVar("kctx_span_stack", default=())
_log_path: Path | None = None


def log_dir() -> Path:
    from kctx.config import Config

    cfg = Config.load()
    if cfg.log_dir is not None:
        return cfg.log_dir
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "kctx" / "logs"
    return Path.home() / ".local" / "state" / "kctx" / "logs"


def log_file_path() -> Path:
    return log_dir() / "kctx.jsonl"


def _redact_event(
    _logger: object,
    _method_name: str,
    event: MutableMapping[str, object],
) -> MutableMapping[str, object]:
    for key, value in event.items():
        if key not in {"_record", "_from_structlog"}:
            event[key] = REDACTED if is_secret_key(key) else scrub(value)
    return event


def _human_event(
    _logger: object,
    _method_name: str,
    event: MutableMapping[str, object],
) -> str:
    summary = terminal_text(event.get("event", ""))
    fields = " ".join(
        f"{terminal_text(key)}={terminal_text(value)}"
        for key, value in event.items()
        if key not in {"event", "timestamp", "level", "_record", "_from_structlog"}
    )
    return f"{summary} {fields}" if fields else summary


def init_logging(
    verbose: bool = False,
    *,
    machine: bool = False,
    color: bool | None = None,
) -> str:
    """Initialize the invocation's file and optional human-only console sink."""
    global _log_path

    run_id = uuid.uuid4().hex[:16]
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(run_id=run_id)

    d = log_dir()
    d.mkdir(parents=True, exist_ok=True)
    _log_path = d / "kctx.jsonl"

    pre_chain: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _redact_event,
    ]

    structlog.configure(
        processors=[*pre_chain, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    file_handler = logging.handlers.RotatingFileHandler(
        str(_log_path), maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(), foreign_pre_chain=pre_chain
        )
    )
    file_handler.setLevel(logging.DEBUG)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for handler in root.handlers:
        handler.close()
    root.handlers = [file_handler]

    if verbose and not machine:
        console_handler = RichHandler(
            console=console(stderr=True, color=color),
            show_path=False,
            markup=False,
            rich_tracebacks=False,
        )
        console_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=_human_event,
                foreign_pre_chain=pre_chain,
            )
        )
        console_handler.setLevel(logging.DEBUG)
        root.addHandler(console_handler)

    return run_id


def get_logger(name: str = "kctx") -> structlog.stdlib.BoundLogger:
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


@contextlib.contextmanager
def span(name: str, **attrs: JsonValue) -> Iterator[str]:
    """Logs span.start/span.end around a block, with span_id/parent_span_id
    (nested spans chain through a contextvar stack) and duration_ms. On
    exception, status='error' and the exception is logged, then re-raised --
    this never swallows an error, only records it."""
    log = get_logger()
    span_id = uuid.uuid4().hex[:12]
    stack = _span_stack.get()
    parent_span_id = stack[-1] if stack else None
    token = _span_stack.set((*stack, span_id))
    t0 = time.monotonic()
    log.debug("span.start", span=name, span_id=span_id, parent_span_id=parent_span_id, **attrs)
    status = "ok"
    try:
        yield span_id
    except BaseException as exc:
        status = "error"
        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        log.debug(
            "span.end",
            span=name,
            span_id=span_id,
            parent_span_id=parent_span_id,
            duration_ms=duration_ms,
            status=status,
            exception=repr(exc),
        )
        raise
    else:
        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        log.debug(
            "span.end",
            span=name,
            span_id=span_id,
            parent_span_id=parent_span_id,
            duration_ms=duration_ms,
            status=status,
        )
    finally:
        _span_stack.reset(token)


@overload
def run_logged(
    argv: list[str],
    *,
    cwd: Path | str | None = None,
    input: str | None = None,
    check: bool = True,
    timeout: float | None = None,
    text: Literal[True] = True,
) -> subprocess.CompletedProcess[str]: ...


@overload
def run_logged(
    argv: list[str],
    *,
    cwd: Path | str | None = None,
    input: bytes | None = None,
    check: bool = True,
    timeout: float | None = None,
    text: Literal[False],
) -> subprocess.CompletedProcess[bytes]: ...


def run_logged(
    argv: list[str],
    *,
    cwd: Path | str | None = None,
    input: str | bytes | None = None,
    check: bool = True,
    timeout: float | None = None,
    text: bool = True,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    """subprocess.run wrapped in a span that logs argv, exit code, duration,
    and truncated stderr -- used for every git/dolt call the graph package
    makes, so a `kctx logs` replay shows exactly what shelled out and why it
    failed. `text=False` captures stdout as raw bytes (e.g. `git archive`'s
    tar stream); stderr is always decoded for logging."""
    log = get_logger()
    t0 = time.monotonic()
    try:
        proc: subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]
        if text:
            if input is not None and not isinstance(input, str):
                raise TypeError("text subprocess input must be a string")
            proc = subprocess.run(
                argv,
                cwd=cwd,
                input=input,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        else:
            if input is not None and not isinstance(input, bytes):
                raise TypeError("binary subprocess input must be bytes")
            proc = subprocess.run(
                argv,
                cwd=cwd,
                input=input,
                capture_output=True,
                text=False,
                timeout=timeout,
            )
    except subprocess.TimeoutExpired as exc:
        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        log.debug(
            "subprocess",
            argv=argv,
            cwd=str(cwd) if cwd else None,
            timeout=True,
            duration_ms=duration_ms,
        )
        raise exc
    duration_ms = round((time.monotonic() - t0) * 1000, 2)
    raw_stderr = (
        proc.stderr
        if isinstance(proc.stderr, str)
        else (proc.stderr or b"").decode("utf-8", "replace")
    )
    stderr_tail = mask_secrets(raw_stderr)[-2000:]
    log.debug(
        "subprocess",
        argv=argv,
        cwd=str(cwd) if cwd else None,
        returncode=proc.returncode,
        duration_ms=duration_ms,
        stderr_tail=stderr_tail if proc.returncode != 0 else (stderr_tail[-200:] or None),
    )
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, argv, output=proc.stdout, stderr=proc.stderr
        )
    return proc


# --------------------------------------------------------------------------
# `kctx logs` read side
# --------------------------------------------------------------------------
def read_events(run_id: str | None = None) -> list[JsonObject]:
    """Reads the live JSONL log file (rotated backups are not consulted --
    `--last`/a recent --run id is the supported case). With no run_id, finds
    the most recent run_id present and returns only its events."""
    path = log_file_path()
    if not path.is_file():
        return []
    events: list[JsonObject] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(object_value(scrub(json.loads(line)), "log event"))
        except (json.JSONDecodeError, KctxError):
            continue
    if run_id is None:
        for e in reversed(events):
            candidate = e.get("run_id")
            if isinstance(candidate, str) and candidate:
                run_id = candidate
                break
    if run_id is None:
        return []
    return [e for e in events if e.get("run_id") == run_id]
