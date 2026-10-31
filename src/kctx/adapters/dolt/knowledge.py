"""Native, normalized Dolt generations; no whole-state JSON storage."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from kctx.adapters.files.knowledge import canonical
from kctx.config import Config
from kctx.domain.ids import DoltCommitId, PlanId
from kctx.domain.json import JsonObject, JsonValue, object_value, text
from kctx.errors import KctxError

# Only structured propositions, proof trees, finite domains and dependencies use
# bounded per-record JSON. Every identity and relational attribute is a column.
COLUMNS: dict[str, dict[str, str]] = {
    "observations": {
        "id": "TEXT",
        "source": "TEXT",
        "revision": "TEXT",
        "content": "TEXT",
        "observed_at": "BIGINT",
        "outcome": "TEXT",
    },
    "claims": {"id": "TEXT", "revision": "TEXT", "statement": "JSON"},
    "attestations": {
        "id": "TEXT",
        "claim": "JSON",
        "observation": "TEXT",
        "statement": "JSON",
        "authority": "TEXT",
    },
    "enumerations": {
        "id": "TEXT",
        "source": "TEXT",
        "revision": "TEXT",
        "query": "TEXT",
        "scope": "JSON",
        "observation": "TEXT",
        "members": "JSON",
        "universe": "JSON",
        "method": "TEXT",
    },
    "derivations": {"id": "TEXT", "claim": "JSON", "witness": "JSON"},
    "corrections": {
        "id": "TEXT",
        "kind": "TEXT",
        "target": "JSON",
        "replacement": "JSON",
        "recorded_at": "BIGINT",
    },
    "receipts": {
        "id": "TEXT",
        "claim": "JSON",
        "context": "JSON",
        "witness": "JSON",
        "dependencies": "JSON",
        "result": "TEXT",
        "expires_at": "BIGINT",
    },
    "captures": {
        "id": "TEXT",
        "kind": "TEXT",
        "source": "TEXT",
        "revision": "TEXT",
        "content": "TEXT",
        "observed_at": "BIGINT",
    },
    "admissions": {
        "id": "TEXT",
        "actor": "TEXT",
        "signature": "TEXT",
        "policy": "TEXT",
        "target_use": "TEXT",
        "base": "TEXT",
    },
}
SEMANTIC_TABLES = tuple(name for name in COLUMNS if name not in ("captures", "admissions"))


def literal(value: JsonValue) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    raw = value if isinstance(value, str) else canonical(value).decode()
    return "CONVERT(0x" + raw.encode().hex() + " USING utf8mb4)" if raw else "''"


class KnowledgeDolt:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        configured = Config.load().dolt_bin
        binary = shutil.which(str(configured) if configured is not None else "dolt")
        if binary is None:
            detail = (
                f"configured dolt executable is unavailable: {configured}"
                if configured is not None
                else "native dolt executable is required"
            )
            raise KctxError("not-found", detail)
        self.binary = binary

    def run(self, *args: str, cwd: Path | None = None) -> str:
        result = subprocess.run(
            [self.binary, *args],
            cwd=cwd if cwd is not None else self.path,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise KctxError("conflict", result.stderr.strip() or result.stdout.strip())
        return result.stdout

    def sql(self, query: str) -> list[JsonObject]:
        result = object_value(json.loads(self.run("sql", "-r", "json", "-q", query)))
        # Native Dolt encodes a successful empty SELECT as {}, not rows:[].
        if not result:
            return []
        rows = result.get("rows")
        if not isinstance(rows, list):
            raise KctxError("malformed", "Dolt returned no row array")
        return [object_value(row) for row in rows]

    def execute(self, statement: str) -> None:
        self.run("sql", "-q", statement)

    def initialize(self) -> None:
        if not (self.path / ".dolt").is_dir():
            self.path.mkdir(parents=True, exist_ok=True)
            self.run("init", "--name", "kctx-knowledge", "--email", "kctx@localhost")
        self.execute(
            "CREATE TABLE IF NOT EXISTS knowledge_meta (`name` VARCHAR(80) PRIMARY KEY, `value` TEXT NOT NULL)"
        )
        for table, columns in COLUMNS.items():
            fields = ", ".join(f"`{key}` {kind}" for key, kind in columns.items())
            self.execute(
                f"CREATE TABLE IF NOT EXISTS `{table}` (`ordinal` BIGINT PRIMARY KEY, {fields})"
            )

    def commit_candidate(
        self,
        plan: PlanId,
        base: DoltCommitId | None,
        kb: JsonObject,
        captures: list[JsonObject],
        admission: JsonObject,
        owner: str,
    ) -> DoltCommitId:
        self.initialize()
        prior_admissions = self.rows("admissions", base) if base else []
        branch = "kctx-candidate-" + plan.val
        # An abandoned branch is never reused as authoritative input. New branch
        # is based only on the pinned predecessor, or the native initial commit.
        start = (
            base.val if base else text(self.sql("SELECT DOLT_HASHOF('HEAD') AS h")[0]["h"], "head")
        )
        self.run("checkout", "-B", branch, start)
        for table in COLUMNS:
            self.execute(f"DELETE FROM `{table}`")
        self.execute("DELETE FROM knowledge_meta")
        for key, value in (("snapshot", kb["snapshot"]), ("owner", owner), ("schema", "2")):
            self.execute(f"INSERT INTO knowledge_meta VALUES ({literal(key)},{literal(value)})")
        for table, columns in COLUMNS.items():
            entries: JsonValue = (
                [*captures]
                if table == "captures"
                else [admission, *prior_admissions]
                if table == "admissions"
                else kb[table]
            )
            if not isinstance(entries, list):
                raise KctxError("malformed", f"{table} must be an array")
            for index, entry in enumerate(entries):
                row = object_value(entry)
                if set(row) != set(columns):
                    raise KctxError("malformed", f"unexpected {table} columns")
                values = [str(index)] + [literal(row[key]) for key in columns]
                self.execute(f"INSERT INTO `{table}` VALUES ({','.join(values)})")
        self.run("add", ".")
        self.run(
            "commit",
            "--allow-empty",
            "--author",
            "kctx-knowledge <kctx@localhost>",
            "-m",
            "Approved candidate " + plan.val,
        )
        return DoltCommitId(text(self.sql("SELECT DOLT_HASHOF('HEAD') AS h")[0]["h"], "commit"))

    def rows(self, table: str, commit: DoltCommitId) -> list[JsonObject]:
        if table not in COLUMNS:
            raise KctxError("malformed", "unknown normalized table")
        rows = self.sql(f"SELECT * FROM `{table}` AS OF '{commit.val}' ORDER BY ordinal")
        result: list[JsonObject] = []
        for row in rows:
            entry: JsonObject = {}
            for key, kind in COLUMNS[table].items():
                # Native Dolt JSON omits keys whose SQL value is NULL.
                value = row.get(key)
                entry[key] = (
                    json.loads(value) if kind == "JSON" and isinstance(value, str) else value
                )
            result.append(entry)
        return result

    def read(self, commit: DoltCommitId, owner: str) -> JsonObject:
        meta = self.sql(f"SELECT * FROM knowledge_meta AS OF '{commit.val}'")
        values = {text(row["name"], "name"): row["value"] for row in meta}
        if values.get("owner") != owner or values.get("schema") != "2":
            raise KctxError("conflict", "Dolt generation belongs to another KB or schema")
        kb: JsonObject = {"snapshot": values["snapshot"]}
        for table in SEMANTIC_TABLES:
            kb[table] = list(self.rows(table, commit))
        return kb
