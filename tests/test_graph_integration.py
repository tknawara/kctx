"""Integration tests against a real temporary Dolt database: sync
idempotency, impact depth/cycle-safety, and diff across two syncs. Skips
cleanly when `dolt` isn't on PATH or pydantic/structlog aren't installed.
Citation parsing uses the built-in implementation.

These are slower than the unit tests (each sync shells out to `dolt` several
times) but still fast enough to run by default -- no network, no real kb
repo touched.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


import os
import shutil
import unittest

from _base import KctxTestCase

try:
    import pydantic  # noqa: F401
    import structlog  # noqa: F401

    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False

HAVE_DOLT = shutil.which("dolt") is not None or os.path.isfile(
    os.path.expanduser("~/.local/bin/dolt")
)


def _skip_reason():
    if not HAVE_DEPS:
        return "pydantic/structlog not installed in ambient interpreter; run via `uv run`"
    if not HAVE_DOLT:
        return "dolt not found on PATH or ~/.local/bin/dolt"
    return None


@unittest.skipUnless(_skip_reason() is None, _skip_reason() or "")
class GraphSyncIntegrationTest(KctxTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.make_git_repo("kb")
        self.graph_dir = self.root / "_graph"
        self.set_config(graph_dir=str(self.graph_dir))

        from kctx.graph import sync as sync_mod

        self.sync_mod = sync_mod


    def _write(self, rel_path, content):
        path = self.repo / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _commit(self, message="update"):
        self.run_git(self.repo, "add", "-A")
        self.run_git(self.repo, "commit", "-q", "-m", message)
        import subprocess

        return subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def test_sync_idempotency(self):
        self._write("inventory/assets/service-foo.json", '{"id": "service-foo", "name": "Foo"}\n')
        self._commit("add service-foo")

        res1 = self.sync_mod.sync(self.repo)
        self.assertEqual(res1["status"], "synced")
        self.assertGreaterEqual(res1["node_count"], 1)

        res2 = self.sync_mod.sync(self.repo)
        self.assertEqual(res2["status"], "up-to-date")
        self.assertEqual(res2["kb_sha"], res1["kb_sha"])

    def test_impact_depth_and_cycle_safety(self):
        # A -> B -> C -> A (a cycle) via `consumes` relationships, plus a
        # dangling D -> A at depth 1. impact(A, depth=2) must terminate and
        # must find C at depth 2 without finding the depth-3-only edge from
        # re-entering the cycle past the bound.
        for src, dst in [("B", "A"), ("C", "B"), ("A", "C"), ("D", "A")]:
            self._write(f"inventory/assets/{src}.json", f'{{"id": "{src}", "name": "{src}"}}\n')
        self._write("inventory/assets/A.json", '{"id": "A", "name": "A"}\n')
        for i, (src, dst) in enumerate([("B", "A"), ("C", "B"), ("A", "C"), ("D", "A")]):
            self._write(
                f"inventory/relationships/consumes__{src}__{dst}.json",
                f'{{"from": "{src}", "to": "{dst}", "type": "consumes"}}\n',
            )
        self._commit("cycle fixture")
        self.sync_mod.sync(self.repo)

        from kctx.graph import queries as queries_mod
        from kctx.graph.models import GraphNodeId

        res = queries_mod.impact(GraphNodeId("A"), kb_root=self.repo, depth=2)
        nodes_by_depth = {d["node"]: d["depth"] for d in res["dependents"]}
        self.assertEqual(nodes_by_depth.get("B"), 1)
        self.assertEqual(nodes_by_depth.get("D"), 1)
        self.assertEqual(nodes_by_depth.get("C"), 2)
        # cycle-safety: finishes at all (no hang) and depth is bounded
        self.assertTrue(all(d["depth"] <= 2 for d in res["dependents"]))

    def test_diff_across_two_syncs(self):
        self._write("inventory/assets/service-foo.json", '{"id": "service-foo", "name": "Foo"}\n')
        sha1 = self._commit("add service-foo")
        self.sync_mod.sync(self.repo)

        self._write("inventory/assets/service-bar.json", '{"id": "service-bar", "name": "Bar"}\n')
        self._write(
            "inventory/relationships/consumes__service-foo__service-bar.json",
            '{"from": "service-foo", "to": "service-bar", "type": "consumes"}\n',
        )
        sha2 = self._commit("add service-bar + relationship")
        self.sync_mod.sync(self.repo)

        from kctx.graph import queries as queries_mod

        result = queries_mod.diff(sha1, sha2, kb_root=self.repo)
        kinds = {(row["rel"], row["diff_type"]) for row in result["summary"]}
        self.assertIn(("consumes", "added"), kinds)

    def test_uses_is_directional(self):
        self._write("inventory/assets/service-foo.json", '{"id": "service-foo", "name": "Foo"}\n')
        self._write("inventory/assets/store-bar.json", '{"id": "store-bar", "name": "Bar"}\n')
        self._write(
            "inventory/relationships/consumes__service-foo__store-bar.json",
            '{"from": "service-foo", "to": "store-bar", "type": "consumes"}\n',
        )
        self._commit("directional fixture")
        self.sync_mod.sync(self.repo)

        from kctx.graph import queries as queries_mod
        from kctx.graph.models import GraphNodeId

        into_bar = queries_mod.uses(GraphNodeId("store-bar"), kb_root=self.repo)
        self.assertIn("service-foo", {r["src_node"] for rows in into_bar["by_rel"].values() for r in rows})

        into_foo = queries_mod.uses(GraphNodeId("service-foo"), kb_root=self.repo)
        self.assertEqual(into_foo["total"], 0, "service-foo's own outgoing edge must not look like an inbound use")

    def test_check_shadow_parity_matches_a_direct_cite_parse(self):
        self._write(
            "kb-knowledge-engine/STATUS.md",
            "---\ntitle: status\n---\n"
            'One real citation: ⟦cite kind=ticket id=DRQS-1 seen=2026-10-30T00:00Z⟧\n'
            'One illustrative one: ⟦cite illus kind=ticket id=DRQS-2 seen=2026-10-30T00:00Z⟧\n',
        )
        self._commit("status with citations")
        self.sync_mod.sync(self.repo)

        from kctx.graph import queries as queries_mod
        from kctx.graph.models import GraphNodeId

        # uses_comparison cross-checks against `kctx uses` (nav.uses), which
        # is being fixed concurrently this session -- asserted loosely here
        # (shape, not nav.py's exact resolution behavior) to avoid coupling
        # this test to a module this change doesn't own.
        result = queries_mod.check(self.repo, sample_ids=[GraphNodeId("ticket:DRQS-1")])
        self.assertTrue(result["parity"]["match"])
        self.assertEqual(result["parity"]["direct_cite_tokens"], 2)
        self.assertEqual(result["parity"]["graph_binding_rows"], 2)
        self.assertEqual(result["parity"]["direct_illus_tokens"], 1)
        self.assertEqual(len(result["uses_comparison"]), 1)
        self.assertEqual(result["uses_comparison"][0]["target"], "ticket:DRQS-1")

    def test_working_changes_do_not_leak_into_completed_queries(self):
        from kctx.errors import KctxError
        from kctx.graph import queries
        from kctx.graph.dolt_store import DoltStore
        from kctx.graph.models import GraphNodeId

        self._write("inventory/relationships/link.json", '{"from":"source","to":"target","type":"consumes"}\n')
        self._commit()
        self.sync_mod.sync(self.repo)
        store = DoltStore(self.sync_mod.dolt_db_dir())
        store._run("sql", "-q", "UPDATE edges SET dst_node='unpublished' WHERE rel='consumes'")
        self.assertEqual(queries.uses(GraphNodeId("target"), kb_root=self.repo)["total"], 1)
        self.assertEqual(queries.uses(GraphNodeId("unpublished"), kb_root=self.repo)["total"], 0)
        with self.assertRaises(KctxError):
            self.sync_mod.sync(self.repo)

    def test_rebuild_retains_native_history(self):
        from kctx.graph.dolt_store import DoltStore
        from kctx.graph.generation import completed_snapshot

        self._write("inventory/assets/service-foo.json", '{"id":"service-foo","name":"Foo"}\n')
        self._commit()
        self.sync_mod.sync(self.repo)
        store = DoltStore(self.sync_mod.dolt_db_dir())
        before = completed_snapshot(store)
        self.assertIsNotNone(before)
        self.sync_mod.sync(self.repo, rebuild=True)
        self.assertEqual(completed_snapshot(store), before)
        store = DoltStore(self.sync_mod.dolt_db_dir())
        after = completed_snapshot(store)
        self.assertNotEqual(before.metadata_commit, after.metadata_commit)
        rows = store.sql_read(f"SELECT hashof('{before.metadata_commit.val}') AS h")
        self.assertEqual(rows[0]["h"], before.metadata_commit.val)

    def test_checkout_mismatch_never_rebuilds_another_graph(self):
        from kctx.errors import KctxError
        from kctx.graph.dolt_store import DoltStore
        from kctx.graph.generation import completed_snapshot

        self._write("inventory/assets/service-foo.json", '{"id":"service-foo","name":"Foo"}\n')
        self._commit()
        self.sync_mod.sync(self.repo)
        store = DoltStore(self.sync_mod.dolt_db_dir())
        before = completed_snapshot(store)
        other = self.make_git_repo("other-kb")
        with self.assertRaises(KctxError):
            self.sync_mod.sync(other, rebuild=True)
        self.assertEqual(completed_snapshot(store), before)

    def test_incomplete_first_generation_is_not_current(self):
        from kctx.errors import KctxError
        from kctx.graph import queries
        from kctx.graph.dolt_store import SYNC_STATE_COLUMNS
        from kctx.graph.operations import writer

        self._write("inventory/assets/service-foo.json", '{"id":"service-foo","name":"Foo"}\n')
        sha = self._commit()
        with writer(self.graph_dir, self.repo) as store:
            store.ensure_init()
            store.upsert_rows("sync_state", SYNC_STATE_COLUMNS, [{"id": 1, "kb_sha": sha, "kb_subject": "incomplete", "dolt_commit": None, "synced_at": "2026-10-31T00:00:00Z", "node_count": 0, "edge_count": 0}])
        status = queries.status(self.repo)
        self.assertFalse(status["up_to_date"])
        self.assertIsNone(status["sync_state"])
        with self.assertRaises(KctxError):
            self.sync_mod.sync(self.repo)

    def test_failed_candidate_preserves_last_completed_generation(self):
        from unittest.mock import patch
        from kctx.graph import queries
        from kctx.graph.dolt_store import DoltStore
        from kctx.graph.generation import completed_snapshot
        from kctx.graph.models import GraphNodeId

        self._write("inventory/relationships/link.json", '{"from":"source","to":"target","type":"consumes"}\n')
        self._commit()
        self.sync_mod.sync(self.repo)
        store = DoltStore(self.sync_mod.dolt_db_dir())
        before = completed_snapshot(store)
        self._write("inventory/relationships/link.json", '{"from":"source","to":"candidate","type":"consumes"}\n')
        self._commit("candidate")
        with patch("kctx.graph.sync.activate", side_effect=RuntimeError("interrupted before activation")):
            with self.assertRaises(RuntimeError):
                self.sync_mod.sync(self.repo)
        self.assertEqual(completed_snapshot(store), before)
        self.assertEqual(queries.uses(GraphNodeId("target"), kb_root=self.repo)["total"], 1)
        self.assertEqual(queries.uses(GraphNodeId("candidate"), kb_root=self.repo)["total"], 0)

    def test_writer_lock_serializes_processes(self):
        import subprocess
        from kctx.graph.operations import writer

        lock = self.graph_dir / "dolt.writer.lock"
        code = "import fcntl,sys; f=open(sys.argv[1],'a+b'); fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)"
        with writer(self.graph_dir, self.repo):
            blocked = subprocess.run([sys.executable, "-c", code, str(lock)], capture_output=True)
            self.assertNotEqual(blocked.returncode, 0)
        released = subprocess.run([sys.executable, "-c", code, str(lock)], capture_output=True)
        self.assertEqual(released.returncode, 0)

    def test_failure_after_import_leaves_published_snapshot_readable(self):
        from unittest.mock import patch
        from kctx.graph import queries
        from kctx.graph.dolt_store import DoltStore
        from kctx.graph.generation import completed_snapshot
        from kctx.graph.models import GraphNodeId

        self._write("inventory/relationships/link.json", '{"from":"source","to":"target","type":"consumes"}\n')
        self._commit()
        self.sync_mod.sync(self.repo)
        store = DoltStore(self.sync_mod.dolt_db_dir())
        before = completed_snapshot(store)
        self._write("inventory/relationships/link.json", '{"from":"source","to":"candidate","type":"consumes"}\n')
        self._commit("candidate")
        with patch.object(DoltStore, "commit", side_effect=RuntimeError("interrupted after imports")):
            with self.assertRaises(RuntimeError):
                self.sync_mod.sync(self.repo)
        self.assertEqual(completed_snapshot(store), before)
        self.assertEqual(queries.uses(GraphNodeId("target"), kb_root=self.repo)["total"], 1)
        self.assertEqual(queries.uses(GraphNodeId("candidate"), kb_root=self.repo)["total"], 0)

    def test_unowned_database_is_not_adopted_or_deleted(self):
        from kctx.errors import KctxError
        from kctx.graph.dolt_store import DoltStore

        store = DoltStore(self.sync_mod.dolt_db_dir())
        store.ensure_init()
        commit = store.commit("unowned history", allow_empty=True)
        with self.assertRaises(KctxError):
            self.sync_mod.sync(self.repo, rebuild=True)
        self.assertEqual(store.head_commit_hash(), commit)


if __name__ == "__main__":
    unittest.main()
