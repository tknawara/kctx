"""Real pinned-Dolt read transport, parity, limits, and lifecycle qualification."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymysql

from kctx.adapters.dolt.read_session import DoltReadSession, _value
from kctx.errors import KctxError
from kctx.graph.dolt_store import DoltStore


class ReadValueTest(unittest.TestCase):
    def test_malformed_wire_value_is_not_coerced(self) -> None:
        with self.assertRaises(KctxError):
            _value(object(), 253)
        with self.assertRaises(KctxError):
            _value("{broken", 245)


@unittest.skipUnless(shutil.which("dolt"), "requires pinned native Dolt in verify image")
class ReadSessionIntegrationTest(unittest.TestCase):
    def test_native_session_security_parity_and_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kctx-reader-test-") as name:
            root = Path(name)
            store = DoltStore(root / "db")
            store.ensure_init()
            store._run("sql", "-q", "CREATE TABLE sample (id INT PRIMARY KEY, value TEXT, flag TINYINT)")
            store._run("sql", "-q", "INSERT INTO sample VALUES (1, 'first', 1), (2, NULL, 0)")
            store._run("add", ".")
            store._run("commit", "--author", "reader <reader@localhost>", "-m", "read fixture")
            commit = store.head_commit_hash()
            query = f"SELECT * FROM sample AS OF '{commit}' ORDER BY id"
            expected = store.sql_read(query)
            scalar = (
                "SELECT CAST(NULL AS CHAR) AS n, "
                "CAST(1.25 AS DECIMAL(8,2)) AS d, CAST(1.5 AS DOUBLE) AS f, "
                "CAST('2026-01-02' AS DATE) AS dt, "
                "CAST('2026-01-02 03:04:05' AS DATETIME) AS ts, "
                "CAST('03:04:05' AS TIME) AS tm, CAST('{\"a\":1}' AS JSON) AS j"
            )
            scalar_expected = store.sql_read(scalar)
            session = store.read_session()
            with session as reader:
                rows = reader.sql_read(query)
                self.assertEqual(json.dumps(rows, sort_keys=True), json.dumps(expected, sort_keys=True))
                self.assertIs(type(rows[0]["flag"]), int)
                scalars = reader.sql_read(scalar)
                self.assertEqual(json.dumps(scalars, sort_keys=True), json.dumps(scalar_expected, sort_keys=True))
                # Native MySQL metadata cannot distinguish boolean expressions from
                # TINYINT. Preserve protocol integers, never guess from column width.
                booleans = reader.sql_read("SELECT TRUE AS b, FALSE AS f")
                self.assertEqual(booleans, [{"b": 1, "f": 0}])
                self.assertIs(type(booleans[0]["b"]), int)
                self.assertIs(type(scalars[0]["f"]), float)
                self.assertIs(type(scalars[0]["tm"]), int)
                self.assertNotIn("n", scalars[0])
                self.assertEqual(reader.sql_read("SELECT id FROM sample WHERE FALSE"), [])
                self.assertEqual(reader.sql_read(query), expected)
                # The original source remains available to native publication/backup.
                self.assertEqual(store.sql_read(query), expected)
                assert reader.socket_path is not None
                assert reader.port is not None
                private = reader.socket_path.parent
                self.assertEqual(private.stat().st_mode & 0o777, 0o700)
                self.assertTrue(reader.socket_path.is_socket())
                self.assertIsNotNone(reader.startup_seconds)
                identity = reader.resource_identity()
                self.assertIs(type(identity["native_server_pid"]), int)
                self.assertEqual(identity["private_directory"], str(private))
                self.assertEqual(identity["snapshot_directory"], str(private / "snapshot"))
                self.assertEqual(identity["backup_directory"], str(private / "backup"))
                self.assertEqual(identity["startup_seconds"], reader.startup_seconds)
                for user in ("", "root", "unknown"):
                    with self.subTest(user=user), self.assertRaises(pymysql.OperationalError):
                        pymysql.connect(host="127.0.0.1", port=reader.port,
                                        user=user, password="", connect_timeout=1)
                with self.assertRaises(KctxError) as denied:
                    reader.sql_read("DELETE FROM sample")
                self.assertEqual(denied.exception.category, "permission")
                # Verify the actual server, not merely the adapter's lexical guard.
                assert reader._connection is not None
                with reader._connection.cursor() as cursor:
                    with self.assertRaises(pymysql.MySQLError):
                        cursor.execute("DELETE FROM sample")
                self.assertEqual(reader.sql_read(query), expected)
                process = reader._process
            assert process is not None
            self.assertIsNotNone(process.poll())
            self.assertFalse(private.exists())
            session.close()
            self.assertIsNone(session.resource_identity()["native_server_pid"])
            self.assertIsNone(session.resource_identity()["private_directory"])
            self.assertEqual(store.sql_read(query), expected)

            for limits, statement, category in (
                ({"max_rows": 1}, "SELECT * FROM sample", "incomplete"),
                ({"max_response_bytes": 1}, "SELECT * FROM sample", "incomplete"),
                ({}, "SELECT nonexistent FROM sample", "malformed"),
                ({}, "SELECT SLEEP(5)", "timeout"),
            ):
                with self.subTest(statement=statement, limits=limits):
                    bounded = DoltReadSession(store.db_dir, store.dolt_bin, **limits)
                    with bounded:
                        assert bounded.socket_path is not None
                        private = bounded.socket_path.parent
                        process = bounded._process
                        if category == "timeout":
                            bounded.query_timeout = 0.05
                        with self.assertRaises(KctxError) as failure:
                            bounded.sql_read(statement)
                        self.assertEqual(failure.exception.category, category)
                    assert process is not None
                    self.assertIsNotNone(process.poll())
                    self.assertFalse(private.exists())

            interrupted = store.read_session()
            with self.assertRaises(KeyboardInterrupt), interrupted:
                assert interrupted.socket_path is not None
                private = interrupted.socket_path.parent
                process = interrupted._process
                raise KeyboardInterrupt
            assert process is not None
            self.assertIsNotNone(process.poll())
            self.assertFalse(private.exists())

            unavailable = DoltReadSession(store.db_dir, str(root / "missing"))
            with self.assertRaises(KctxError) as missing, unavailable:
                self.fail("unavailable native executable cannot enter a reader")
            self.assertEqual(missing.exception.category, "not-found")
            self.assertIsNone(unavailable._temporary)

            startup_timeout = DoltReadSession(store.db_dir, store.dolt_bin, startup_timeout=1e-9)
            with self.assertRaises(KctxError) as timed, startup_timeout:
                self.fail("expired startup deadline cannot enter a reader")
            self.assertEqual(timed.exception.category, "timeout")
            self.assertIsNone(startup_timeout._temporary)

            canceled = store.read_session()
            with patch.object(canceled, "_native", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt), canceled:
                    self.fail("canceled startup cannot enter a reader")
            self.assertIsNone(canceled._temporary)
            self.assertNotIn("DOLT_ROOT_PASSWORD", os.environ)
