"""Structured logging for kctx: every invocation gets a run_id, every
notable step gets a span with start/end + duration_ms + status, and it all
lands in a JSONL file an agent can replay with `kctx logs` after something
goes wrong -- without needing the original terminal output.

Wired at kctx's entry point (kctx.py), not inside cli.py's dispatch, so every
command gets it for free without rewriting cli.py's existing handlers. Only
the graph package's own code (dolt_store, extract, sync, queries) emits
spans/events today; non-graph commands get a bare run_id-tagged
command.start/command.end pair from the entry point and nothing more, which
is enough for `kctx logs` to show "what command ran, how long, did it fail"
even for commands this change didn't otherwise touch.

File: $KCTX_LOG_DIR/kctx.jsonl, else $XDG_STATE_HOME/kctx/logs/kctx.jsonl,
else ~/.local/state/kctx/logs/kctx.jsonl. Rotated by size (5 MiB, 5 backups).
Console: nothing by default; concise human lines to stderr once verbose
(-v/--verbose, handled by kctx.py before cli.main() ever sees argv) or
KCTX_LOG=debug is set.
"""

import contextlib
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

_span_stack: ContextVar = ContextVar("kctx_span_stack", default=())
_initialized = False
_log_path: Optional[Path] = None


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


def _level_name(verbose: bool) -> str:
    if verbose:
        return "debug"
    return os.environ.get("KCTX_LOG", "info").lower()


def init_logging(verbose: bool = False) -> str:
    """Idempotent per process. Returns the run_id for this invocation (a new
    one each call, so a test that re-inits gets a fresh run)."""
    global _initialized, _log_path

    run_id = uuid.uuid4().hex[:16]
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(run_id=run_id)

    if _initialized:
        return run_id

    d = log_dir()
    d.mkdir(parents=True, exist_ok=True)
    _log_path = d / "kctx.jsonl"

    pre_chain = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    structlog.configure(
        processors=pre_chain + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
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
    root.handlers = [file_handler]

    if _level_name(verbose) == "debug":
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
                foreign_pre_chain=pre_chain,
            )
        )
        console_handler.setLevel(logging.DEBUG)
        root.addHandler(console_handler)

    _initialized = True
    return run_id


def get_logger(name: str = "kctx"):
    return structlog.get_logger(name)


@contextlib.contextmanager
def span(name: str, **attrs: Any):
    """Logs span.start/span.end around a block, with span_id/parent_span_id
    (nested spans chain through a contextvar stack) and duration_ms. On
    exception, status='error' and the exception is logged, then re-raised --
    this never swallows an error, only records it."""
    log = get_logger()
    span_id = uuid.uuid4().hex[:12]
    stack = _span_stack.get()
    parent_span_id = stack[-1] if stack else None
    token = _span_stack.set(stack + (span_id,))
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


def run_logged(
    argv: List[str],
    *,
    cwd=None,
    input: Optional[str] = None,
    check: bool = True,
    timeout=None,
    text: bool = True,
) -> subprocess.CompletedProcess:
    """subprocess.run wrapped in a span that logs argv, exit code, duration,
    and truncated stderr -- used for every git/dolt call the graph package
    makes, so a `kctx logs` replay shows exactly what shelled out and why it
    failed. `text=False` captures stdout as raw bytes (e.g. `git archive`'s
    tar stream); stderr is always decoded for logging."""
    log = get_logger()
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            input=input,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=text,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        log.debug("subprocess", argv=argv, cwd=str(cwd) if cwd else None, timeout=True, duration_ms=duration_ms)
        raise exc
    duration_ms = round((time.monotonic() - t0) * 1000, 2)
    raw_stderr = proc.stderr if isinstance(proc.stderr, str) else (proc.stderr or b"").decode("utf-8", "replace")
    stderr_tail = raw_stderr[-2000:]
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
def read_events(run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Reads the live JSONL log file (rotated backups are not consulted --
    `--last`/a recent --run id is the supported case). With no run_id, finds
    the most recent run_id present and returns only its events."""
    path = log_file_path()
    if not path.is_file():
        return []
    events: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if run_id is None:
        for e in reversed(events):
            if e.get("run_id"):
                run_id = e["run_id"]
                break
    if run_id is None:
        return []
    return [e for e in events if e.get("run_id") == run_id]


def format_event_line(e: Dict[str, Any]) -> str:
    ts = e.get("timestamp", "")
    level = (e.get("level") or "").upper()
    event = e.get("event", "")
    extras = {
        k: v
        for k, v in e.items()
        if k not in ("timestamp", "level", "event", "run_id", "logger")
    }
    extras_str = " ".join(f"{k}={v}" for k, v in extras.items())
    return f"{ts} {level:<7} {event}" + (f"  {extras_str}" if extras_str else "")


def add_logs_subparser(sub) -> None:
    logs_p = sub.add_parser(
        "logs", help="events for the last (or a given) kctx invocation, from the JSONL log"
    )
    logs_p.add_argument("--run", dest="run_id", default=None, help="a specific run_id; default is the most recent")
    logs_p.add_argument("--last", dest="last_n", type=int, default=None, metavar="N", help="only the last N events")


def logs_dispatch(args) -> "tuple[Any, int]":
    events = read_events(run_id=args.run_id)
    if args.last_n:
        events = events[-args.last_n :]
    return events, (0 if events else 2)
