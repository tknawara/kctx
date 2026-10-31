"""Dolt JSON decoding and configured executable selection boundaries."""

import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from _base import KctxTestCase, set_config
from kctx.errors import KctxError

try:
    import structlog
    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


@unittest.skipUnless(HAVE_DEPS, "structlog not installed; run via uv run")
class DoltStoreBoundaryTest(KctxTestCase):
    def test_configured_binary_is_used(self):
        from kctx.graph.dolt_store import DoltStore

        binary = self.root / "custom-dolt"
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)
        set_config(dolt_bin=str(binary))
        store = DoltStore(self.root / "db")
        self.assertEqual(store.dolt_bin, str(binary))
        with patch("kctx.graph.dolt_store.run_logged") as run:
            run.return_value.stdout = ""
            store._run("version")
        self.assertEqual(run.call_args.args[0], [str(binary), "version"])

    def test_missing_configured_binary_does_not_fall_back(self):
        from kctx.graph.dolt_store import resolve_dolt_bin

        set_config(dolt_bin=str(self.root / "missing-dolt"))
        with self.assertRaises(KctxError) as caught:
            resolve_dolt_bin()
        self.assertIn("configured dolt binary", caught.exception.message)

    def test_sql_response_requires_object_rows(self):
        from kctx.graph.dolt_store import DoltStore

        store = DoltStore(Path("unused"), dolt_bin="unused")
        for response in ['[]', '{"unexpected":1}', '{"rows":null}', '{"rows":[1]}', '{"rows":[[]]}']:
            with self.subTest(response=response), patch.object(store, "_run", return_value=response):
                with self.assertRaises(KctxError):
                    store.sql_read("SELECT 1")
        with patch.object(store, "_run", return_value='{"rows":[{"n":1}]}'):
            self.assertEqual(store.sql_read("SELECT 1"), [{"n": 1}])
        with patch.object(store, "_run", return_value='{}'):
            self.assertEqual(store.sql_read("SELECT 1 WHERE FALSE"), [])

    @unittest.skipUnless(shutil.which("dolt") or (Path.home() / ".local/bin/dolt").is_file(), "Dolt not installed")
    def test_real_dolt_empty_branch_result(self):
        from kctx.graph.dolt_store import DoltStore

        store = DoltStore(self.root / "real-dolt")
        store.ensure_init()
        rows = store.sql_read("SELECT name FROM dolt_branches WHERE name='absent'")
        self.assertEqual(rows, [])
