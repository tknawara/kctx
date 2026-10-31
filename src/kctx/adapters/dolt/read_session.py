"""Private, authenticated native Dolt readers for immutable published snapshots.

The server owns a native backup/restore, never the published repository's lock.
Dolt 2.6.1 initializes DOLT_ROOT_PASSWORD before accepting connections. Its TCP
listener is loopback-only and authenticated; the client uses a socket beneath a
0700 directory. Credentials never occur in argv, configuration, or application logs.
"""

from __future__ import annotations

import datetime
import json
import math
import os
import secrets
import socket
import subprocess
import tempfile
import threading
import time
from decimal import Decimal
from pathlib import Path
from types import TracebackType
from typing import Protocol, TypeGuard

import pymysql
from pymysql.constants import FIELD_TYPE
from pymysql.cursors import SSCursor

from kctx.domain.json import JsonObject, JsonValue, json_value
from kctx.errors import KctxError


class _UnbufferedResult(Protocol):
    unbuffered_active: bool
    connection: object | None


class _ReadCursor(SSCursor):
    # PyMySQL 1.1.2 has no public unbuffered cancel operation. Closing an
    # interrupted SSCursor otherwise drains the entire response and its destructor
    # reads an already-closed connection. The owning session terminates the server.
    _result: _UnbufferedResult | None

    def abort(self) -> None:
        if self._result is not None:
            self._result.unbuffered_active = False
            self._result.connection = None
            self._result = None


def _tuple(value: object) -> TypeGuard[tuple[object, ...]]:
    return isinstance(value, tuple)


def _columns(value: object) -> list[tuple[str, int]]:
    # Validate PEP 249 metadata at the boundary: the pinned upstream stubs type
    # description as tuple[str, ...], unlike the actual seven-field columns.
    if not _tuple(value) or not value:
        raise KctxError("malformed", "Dolt SELECT returned no column description")
    columns: list[tuple[str, int]] = []
    for column in value:
        if (
            not _tuple(column)
            or len(column) != 7
            or not isinstance(column[0], str)
            or not isinstance(column[1], int)
        ):
            raise KctxError("malformed", "Dolt returned invalid column metadata")
        columns.append((column[0], column[1]))
    return columns


def _value(value: object, type_code: int) -> JsonValue:
    """Match native CLI values where MySQL retains their type information.

    MySQL exposes boolean expressions as TINYINT, indistinguishable from integer
    columns. Preserve those integers rather than guessing from display width.
    Typed product queries select stored numeric flags, not boolean expressions.
    """
    if type_code == FIELD_TYPE.JSON and isinstance(value, str):
        try:
            parsed: object = json.loads(value)
        except (ValueError, RecursionError) as exc:
            raise KctxError("malformed", "Dolt returned an invalid JSON column") from exc
        return json_value(parsed, "Dolt JSON column")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime.datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return (value.days * 86400 + value.seconds) * 1000000 + value.microseconds
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return json_value(value, "Dolt column")


class DoltReadSession:
    """Single-owner reusable read connection; enter/close are explicit and bounded.

    SQL is an internal adapter API, not an agent-facing command. Only SELECT is
    admitted; multi-statements and local infile are disabled. Server read-only
    mode is the independent authority, including for functions invoked by SELECT.
    Any failed/interrupted query closes the session rather than reusing uncertain
    protocol state. A closed session cannot be reopened.
    """

    def __init__(
        self,
        db_dir: Path,
        dolt_bin: str,
        *,
        startup_timeout: float = 30.0,
        query_timeout: float = 10.0,
        max_rows: int = 1000000,
        max_response_bytes: int = 67108864,
        max_query_bytes: int = 1048576,
    ) -> None:
        if (
            not math.isfinite(startup_timeout)
            or startup_timeout <= 0
            or not math.isfinite(query_timeout)
            or query_timeout <= 0
            or min(max_rows, max_response_bytes, max_query_bytes) <= 0
        ):
            raise ValueError("Dolt read-session limits must be finite and positive")
        self.db_dir = db_dir.resolve()
        self.dolt_bin = dolt_bin
        self.startup_timeout = startup_timeout
        self.query_timeout = query_timeout
        self.max_rows = max_rows
        self.max_response_bytes = max_response_bytes
        self.max_query_bytes = max_query_bytes
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._connection: pymysql.Connection[_ReadCursor] | None = None
        self._closed = False
        self._owner: int | None = None
        self.socket_path: Path | None = None
        self.port: int | None = None
        self.startup_seconds: float | None = None

    def resource_identity(self) -> JsonObject:
        """Identify owned native resources for external, out-of-band measurement.

        Paths and PID are absent after close; startup time includes native backup,
        restore, server launch, and authenticated connection establishment.
        """
        process = self._process
        private = Path(self._temporary.name) if self._temporary is not None else None
        return {
            "native_server_pid": process.pid
            if process is not None and process.poll() is None
            else None,
            "private_directory": str(private) if private is not None else None,
            "snapshot_directory": str(private / "snapshot") if private is not None else None,
            "backup_directory": str(private / "backup") if private is not None else None,
            "startup_seconds": self.startup_seconds,
        }

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise KctxError("timeout", "Dolt read-session startup deadline exceeded")
        return remaining

    def _native(
        self, args: list[str], cwd: Path, environment: dict[str, str], deadline: float
    ) -> None:
        # No output/SQL/credentials are logged. communicate's context cleanup also
        # waits for a killed child when cancellation arrives during native backup.
        with subprocess.Popen(
            [self.dolt_bin, *args],
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ) as process:
            try:
                process.wait(timeout=self._remaining(deadline))
            except BaseException:
                process.kill()
                process.wait()
                raise
            if process.returncode:
                raise KctxError("conflict", f"native Dolt read-session {args[0]} failed")

    def __enter__(self) -> DoltReadSession:
        if self._closed or self._temporary is not None:
            raise KctxError("conflict", "Dolt read session cannot be entered twice")
        started = time.monotonic()
        deadline = started + self.startup_timeout
        self._owner = threading.get_ident()
        try:
            if not (self.db_dir / ".dolt").is_dir():
                raise KctxError("not-found", "Dolt read-session source is not initialized")
            self._temporary = tempfile.TemporaryDirectory(prefix="kctx-read-")
            private = Path(self._temporary.name)
            private.chmod(0o700)
            environment = dict(os.environ)
            environment.pop("DOLT_ROOT_PASSWORD", None)
            environment.pop("DOLT_ROOT_HOST", None)
            environment["DOLT_ROOT_PATH"] = str(private / "root")
            Path(environment["DOLT_ROOT_PATH"]).mkdir(mode=0o700)
            backup = private / "backup"
            self._native(
                ["backup", "sync-url", backup.as_uri()], self.db_dir, environment, deadline
            )
            self._native(
                [
                    "config",
                    "--global",
                    "--add",
                    "user.name",
                    "kctx-reader",
                    "user.email",
                    "kctx-reader@localhost",
                ],
                private,
                environment,
                deadline,
            )
            self._native(
                ["backup", "restore", backup.as_uri(), "snapshot"], private, environment, deadline
            )
            # Dolt has no supported Unix-only listener. A loopback port is not a
            # security boundary: random authentication is installed before accept.
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                address: tuple[str, int] = reservation.getsockname()
                self.port = address[1]
            self.socket_path = private / "mysql.sock"
            password = secrets.token_urlsafe(48)
            environment["DOLT_ROOT_PASSWORD"] = password
            environment["DOLT_ROOT_HOST"] = "localhost"
            configuration = {
                "log_level": "error",
                "behavior": {
                    "read_only": True,
                    "autocommit": True,
                    "disable_client_multi_statements": True,
                    "event_scheduler": "OFF",
                    "auto_gc_behavior": {"enable": False},
                    "branch_activity_tracking": False,
                },
                "listener": {
                    "host": "127.0.0.1",
                    "port": self.port,
                    "socket": str(self.socket_path),
                    "max_connections": 2,
                    "read_timeout_millis": max(1, int(self.query_timeout * 1000)),
                    "write_timeout_millis": max(1, int(self.query_timeout * 1000)),
                },
                "data_dir": str(private / "snapshot"),
                "cfg_dir": str(private / "cfg"),
                "privilege_file": str(private / "cfg" / "privileges.db"),
                "branch_control_file": str(private / "cfg" / "branch_control.db"),
                "system_variables": {"secure_file_priv": str(private / "no-files")},
            }
            config_path = private / "server.yaml"
            config_path.write_text(json.dumps(configuration), encoding="utf-8")
            config_path.chmod(0o600)
            self._process = subprocess.Popen(
                [self.dolt_bin, "sql-server", "--config", str(config_path)],
                cwd=private / "snapshot",
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            while True:
                remaining = self._remaining(deadline)
                if self._process.poll() is not None:
                    raise KctxError("conflict", "Dolt read-only server exited before readiness")
                transport = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    transport.settimeout(min(remaining, 1.0))
                    transport.connect(str(self.socket_path))
                except (FileNotFoundError, ConnectionRefusedError):
                    transport.close()
                    time.sleep(min(0.025, self._remaining(deadline)))
                    continue
                except BaseException:
                    transport.close()
                    raise
                try:
                    self._connection = pymysql.Connection(
                        unix_socket=str(self.socket_path),
                        user="root",
                        password=password,
                        database="snapshot",
                        charset="utf8mb4",
                        autocommit=True,
                        local_infile=False,
                        cursorclass=_ReadCursor,
                        defer_connect=True,
                        connect_timeout=max(1, min(2, int(remaining))),
                        read_timeout=min(remaining, self.query_timeout),
                        write_timeout=min(remaining, self.query_timeout),
                    )
                    self._connection.connect(transport)
                except BaseException:
                    transport.close()
                    raise
                break
            self._remaining(deadline)
            self.startup_seconds = time.monotonic() - started
            return self
        except subprocess.TimeoutExpired as exc:
            self.close()
            raise KctxError("timeout", "Dolt read-session startup deadline exceeded") from exc
        except pymysql.MySQLError as exc:
            self.close()
            if exc.args and exc.args[0] == 1045:
                raise KctxError("permission", "Dolt reader authentication failed") from exc
            raise KctxError("malformed", "Dolt reader handshake failed") from exc
        except OSError as exc:
            self.close()
            raise KctxError(
                "not-found", "Dolt read-session executable or transport unavailable"
            ) from exc
        except BaseException:
            self.close()
            raise

    def sql_read(self, query: str) -> list[JsonObject]:
        connection = self._connection
        if connection is None or self._closed:
            raise KctxError("conflict", "Dolt read session is not open")
        if self._owner != threading.get_ident():
            raise KctxError("conflict", "Dolt read session belongs to another thread")
        if not query.lstrip().upper().startswith("SELECT "):
            raise KctxError("permission", "Dolt read sessions accept SELECT queries only")
        if len(query.encode("utf-8")) > self.max_query_bytes:
            raise KctxError("incomplete", "Dolt query exceeds the read-session byte limit")
        expired = threading.Event()
        process = self._process

        def expire() -> None:
            expired.set()
            if process is not None and process.poll() is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass

        timer = threading.Timer(self.query_timeout, expire)
        timer.daemon = True
        timer.start()
        cursor = connection.cursor()
        try:
            # Streaming avoids buffering an unbounded result before enforcing limits.
            cursor.execute(query)
            description = _columns(cursor.description)
            rows: list[JsonObject] = []
            response_bytes = 0
            while True:
                raw: tuple[object, ...] | None = cursor.fetchone()
                if raw is None:
                    break
                if len(raw) != len(description):
                    raise KctxError("malformed", "Dolt returned a row with the wrong column count")
                if len(rows) >= self.max_rows:
                    raise KctxError("incomplete", "Dolt result exceeds the read-session row limit")
                row: JsonObject = {}
                for column, value in zip(description, raw, strict=True):
                    # Native CLI omits SQL NULL keys rather than serializing null.
                    if value is not None:
                        row[column[0]] = _value(value, column[1])
                response_bytes += len(json.dumps(row, ensure_ascii=False).encode("utf-8"))
                if response_bytes > self.max_response_bytes:
                    raise KctxError("incomplete", "Dolt result exceeds the read-session byte limit")
                rows.append(row)
            cursor.close()
            if expired.is_set():
                raise KctxError("timeout", "Dolt read-session query deadline exceeded")
            return rows
        except pymysql.MySQLError as exc:
            cursor.abort()
            self.close()
            if expired.is_set() or (exc.args and exc.args[0] in (2013, 2006)):
                raise KctxError(
                    "timeout", "Dolt read-session query interrupted or timed out"
                ) from exc
            raise KctxError("malformed", "Dolt read-session query failed") from exc
        except BaseException:
            cursor.abort()
            self.close()
            raise
        finally:
            timer.cancel()
            timer.join()

    def close(self) -> None:
        """Idempotently terminate the child before releasing private native files."""
        self._closed = True
        connection, self._connection = self._connection, None
        process, self._process = self._process, None
        if process is not None:
            try:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            except ProcessLookupError:
                process.wait()
        if connection is not None:
            try:
                connection.close()
            except (OSError, pymysql.MySQLError):
                pass
        temporary, self._temporary = self._temporary, None
        if temporary is not None:
            temporary.cleanup()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
