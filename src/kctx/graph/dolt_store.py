"""Native Dolt graph access: CLI mutations and explicit managed read sessions.

One-off reads retain native CLI JSON decoding. ``read_session`` owns an isolated,
authenticated read-only SQL server and reuses its MySQL connection for steady
product queries; the published repository never carries that server's lock.
"""

import csv
import io
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from kctx.adapters.dolt.read_session import DoltReadSession
from kctx.config import Config
from kctx.domain.json import JsonObject, JsonValue, object_value, text
from kctx.errors import KctxError
from kctx.observability import run_logged, span

DOLT_INSTALL_HINT = (
    "dolt is not installed. Install the sha-pinned release manually into "
    "~/.local/bin (see kb-knowledge-engine/evidence/"
    "2026-10-30-dolt-bbgithub-remote-qual.md for the pinned v2.6.1 install "
    "steps); a gripsack module is deferred to the 0.50 dotfiles upgrade."
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nodes (
    id VARCHAR(600) PRIMARY KEY,
    kind VARCHAR(32),
    label TEXT,
    home_path VARCHAR(600)
);
CREATE TABLE IF NOT EXISTS edges (
    edge_id VARCHAR(40) PRIMARY KEY,
    src_node VARCHAR(600),
    src_path VARCHAR(600),
    src_line INT,
    dst_node VARCHAR(600),
    rel VARCHAR(32),
    cite_kind VARCHAR(16),
    rev VARCHAR(64),
    blob_sha VARCHAR(64),
    span VARCHAR(32),
    line_selector TEXT,
    seen VARCHAR(40),
    state VARCHAR(64),
    illus TINYINT,
    raw LONGTEXT
);
CREATE TABLE IF NOT EXISTS kb_commits (
    kb_sha VARCHAR(64) PRIMARY KEY,
    dolt_commit VARCHAR(64),
    subject TEXT,
    committed_date VARCHAR(40),
    seq INT,
    input_digest VARCHAR(64)
);
CREATE TABLE IF NOT EXISTS sync_state (
    id INT PRIMARY KEY,
    kb_sha VARCHAR(64),
    kb_subject TEXT,
    dolt_commit VARCHAR(64),
    synced_at VARCHAR(40),
    node_count INT,
    edge_count INT,
    input_digest VARCHAR(64)
);
CREATE TABLE IF NOT EXISTS generation_inputs (
    id INT PRIMARY KEY,
    input_digest VARCHAR(64),
    manifest LONGTEXT
);
CREATE TABLE IF NOT EXISTS extraction_diagnostics (
    diagnostic_id INT PRIMARY KEY,
    details LONGTEXT
);
"""

NODE_COLUMNS = ["id", "kind", "label", "home_path"]
EDGE_COLUMNS = [
    "edge_id",
    "src_node",
    "src_path",
    "src_line",
    "dst_node",
    "rel",
    "cite_kind",
    "rev",
    "blob_sha",
    "span",
    "line_selector",
    "seen",
    "state",
    "illus",
    "raw",
]
KB_COMMIT_COLUMNS = ["kb_sha", "dolt_commit", "subject", "committed_date", "seq", "input_digest"]
SYNC_STATE_COLUMNS = [
    "id",
    "kb_sha",
    "kb_subject",
    "dolt_commit",
    "synced_at",
    "node_count",
    "edge_count",
    "input_digest",
]
GENERATION_INPUT_COLUMNS = ["id", "input_digest", "manifest"]
DIAGNOSTIC_COLUMNS = ["diagnostic_id", "details"]


def resolve_dolt_bin(config: Config | None = None) -> str:
    configured = (config if config is not None else Config.load()).dolt_bin
    if configured is not None:
        found = shutil.which(str(configured))
        if found:
            return found
        raise KctxError("not-found", f"configured dolt binary is not executable: {configured}")
    found = shutil.which("dolt")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "dolt"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    raise KctxError("not-found", DOLT_INSTALL_HINT)


class DoltStore:
    def __init__(self, db_dir: Path, dolt_bin: str | None = None) -> None:
        self.db_dir = Path(db_dir)
        self.dolt_bin = dolt_bin or resolve_dolt_bin()

    # -- plumbing ----------------------------------------------------------
    def _run(self, *args: str, input: str | None = None) -> str:
        proc = run_logged([self.dolt_bin, *args], cwd=self.db_dir, input=input, check=True)
        return proc.stdout

    def is_initialized(self) -> bool:
        return (self.db_dir / ".dolt").is_dir()

    def backup_to(self, destination: Path) -> None:
        """Transfer native history using Dolt's backup protocol."""
        self._run("backup", "sync-url", destination.resolve().as_uri())

    def checkout(self, branch: str) -> None:
        self._run("checkout", branch)

    def move_branch(self, branch: str, commit: str) -> None:
        self._run("branch", "-f", branch, commit)

    def ensure_init(self) -> None:
        with span("dolt.ensure_init", db_dir=str(self.db_dir)):
            if not self.is_initialized():
                self.db_dir.mkdir(parents=True, exist_ok=True)
                run_logged(
                    [
                        self.dolt_bin,
                        "init",
                        "--name",
                        "kctx-graph",
                        "--email",
                        "kctx-graph@localhost",
                    ],
                    cwd=self.db_dir,
                    check=True,
                )
            self._run("sql", input=SCHEMA_SQL)
            self._upgrade_schema()

    def _upgrade_schema(self) -> None:
        """Retain native history while admitting the current projection schema."""
        for table, column, declaration in (
            ("edges", "line_selector", "TEXT"),
            ("sync_state", "input_digest", "VARCHAR(64)"),
            ("kb_commits", "input_digest", "VARCHAR(64)"),
        ):
            rows = self.sql_read(
                "SELECT COLUMN_NAME AS name FROM information_schema.columns "
                f"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table}' AND COLUMN_NAME = '{column}'"
            )
            if not rows:
                self._run("sql", "-q", f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
        raw = self.sql_read(
            "SELECT DATA_TYPE AS kind FROM information_schema.columns "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'edges' AND COLUMN_NAME = 'raw'"
        )
        if raw and raw[0].get("kind") != "longtext":
            self._run("sql", "-q", "ALTER TABLE edges MODIFY COLUMN raw LONGTEXT")

    # -- reads ---------------------------------------------------------------
    def read_session(self) -> DoltReadSession:
        """Open a reusable private reader without changing native writer behavior."""
        return DoltReadSession(self.db_dir, self.dolt_bin)

    def sql_read(self, query: str) -> list[JsonObject]:
        """Runs a read-only query and returns rows as plain dicts. Caller is
        responsible for quoting/validating any interpolated value via
        graph.quoting -- this method does not alter the query text."""
        with span("dolt.sql_read", query_len=len(query)):
            out = self._run("sql", "-r", "json", "-q", query)
        out = out.strip()
        if not out:
            return []
        try:
            parsed: object = json.loads(out)
        except json.JSONDecodeError as e:
            raise KctxError("malformed", f"dolt sql -r json returned non-JSON output: {e}") from e
        payload = object_value(parsed, "Dolt SQL response")
        # Dolt emits exactly {} for a successful query with no result rows.
        if not payload:
            return []
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise KctxError("malformed", "Dolt SQL response requires a rows array")
        return [object_value(row, "Dolt SQL row") for row in rows]

    def head_commit_hash(self) -> str | None:
        rows = self.sql_read("SELECT hashof('HEAD') AS h")
        return text(rows[0]["h"], "Dolt HEAD hash") if rows else None

    # -- writes (bulk, via dolt table import -- no hand-built INSERT SQL) ---
    def _write_csv(self, columns: Sequence[str], rows: Sequence[Mapping[str, JsonValue]]) -> Path:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            out_row: JsonObject = {}
            for col in columns:
                v = row.get(col)
                if isinstance(v, bool):
                    v = 1 if v else 0
                out_row[col] = "" if v is None else v
            writer.writerow(out_row)
        fd, path_str = tempfile.mkstemp(suffix=".csv", dir=str(self.db_dir))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(buf.getvalue())
        return Path(path_str)

    def replace_table(
        self, table: str, columns: Sequence[str], rows: Sequence[Mapping[str, JsonValue]]
    ) -> None:
        """Wholesale replace of `table`'s contents with `rows` (TRUNCATE +
        bulk insert, via `dolt table import -r`). Used for nodes/edges on
        every `kctx graph sync`: the shadow graph always reflects exactly
        the latest extraction, never an accumulation of stale rows."""
        csv_path = self._write_csv(columns, rows)
        try:
            with span("dolt.replace_table", table=table, rows=len(rows)):
                self._run("table", "import", "-r", table, str(csv_path))
        finally:
            csv_path.unlink(missing_ok=True)

    def upsert_rows(
        self, table: str, columns: Sequence[str], rows: Sequence[Mapping[str, JsonValue]]
    ) -> None:
        """Upsert rows into `table` by primary key (via `dolt table import
        -u`), leaving other rows untouched. Used for kb_commits (append-only
        history) and sync_state (one row, overwritten)."""
        if not rows:
            return
        csv_path = self._write_csv(columns, rows)
        try:
            with span("dolt.upsert_rows", table=table, rows=len(rows)):
                self._run("table", "import", "-u", table, str(csv_path))
        finally:
            csv_path.unlink(missing_ok=True)

    # -- version control -----------------------------------------------------
    def commit(self, message: str, date: str | None = None, allow_empty: bool = False) -> str:
        args = ["commit", "-m", message]
        if date:
            args += ["--date", date]
        if allow_empty:
            args.append("--allow-empty")
        with span("dolt.commit", message=message):
            self._run("add", "-A")
            try:
                self._run(*args)
            except subprocess.CalledProcessError as e:
                stderr = (e.stderr or "").lower()
                if "no changes added to commit" not in stderr:
                    raise
        return self.head_commit_hash() or ""
