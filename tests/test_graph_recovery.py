"""Real-process interruption and native Dolt recovery; no mocked database IO."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from _base import KctxTestCase
from test_graph_integration import _skip_reason


# Exiting at a real Python/native boundary releases flock just as process death
# does, without running sync cleanup or replacing any implementation method.
_CRASH_WORKER = r'''
import json, os, sys
from pathlib import Path
from kctx.graph import sync
boundary = sys.argv[2]
commits = 0
def trace(frame, event, arg):
    global commits
    module = frame.f_globals.get("__name__", "")
    name = frame.f_code.co_name
    caller = frame.f_back.f_code.co_name if frame.f_back else ""
    hit = False
    if module == "kctx.adapters.files.storage" and name == "exclusive_write_json" and event == "return" and caller == "start":
        hit = boundary == "intent"
    if module == "kctx.graph.operations" and event == "return":
        hit = hit or (name == "start" and boundary == "candidate-ready")
        hit = hit or (name == "_write_active" and boundary == "active-written")
        hit = hit or (name == "activate" and boundary == "activated")
    if module == "kctx.graph.dolt_store":
        if name == "replace_table" and event == "return" and frame.f_locals.get("table") == "nodes":
            hit = hit or boundary == "nodes-imported"
        if name == "commit" and event == "call":
            commits += 1
        if name == "commit" and event == "return":
            hit = hit or (boundary == "data-committed" and commits == 1)
            hit = hit or (boundary == "metadata-committed" and commits == 2)
    if module == "kctx.graph.generation" and name == "publish" and event == "return":
        hit = hit or boundary == "published"
    if hit:
        os._exit(97)
    return trace
sys.settrace(trace)
result = sync.sync(Path(sys.argv[1]), **json.loads(sys.argv[3]))
sys.settrace(None)
print(json.dumps(result))
'''


@unittest.skipUnless(_skip_reason() is None, _skip_reason() or "")
class GraphRecoveryTest(KctxTestCase):
    def setUp(self):
        super().setUp()
        from kctx.graph import sync
        self.sync = sync
        self.repo = self.make_git_repo("recovery-kb")
        self.home = self.root / "graph"
        self.set_config(graph_dir=str(self.home))

    def _target(self, value):
        return self.commit_file(
            self.repo, "inventory/relationships/link.json",
            json.dumps({"from": "source", "to": value, "type": "consumes"}) + "\n",
            "target " + value,
        )

    def _crash(self, boundary, **options):
        environment = os.environ.copy()
        source = str(Path(__file__).resolve().parents[1] / "src")
        environment["PYTHONPATH"] = source + os.pathsep + environment.get("PYTHONPATH", "")
        process = subprocess.run(
            [sys.executable, "-c", _CRASH_WORKER, str(self.repo), boundary, json.dumps(options)],
            cwd=self.repo, env=environment, capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(process.returncode, 97, process.stdout + process.stderr)

    def _operations(self):
        return {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in (self.home / "operations").glob("*.json")
        }

    def _store(self, path=None):
        from kctx.graph.dolt_store import DoltStore
        return DoltStore(path if path is not None else self.sync.dolt_db_dir())

    def _uses(self, target):
        from kctx.graph.models import GraphNodeId
        from kctx.graph.queries import uses
        return uses(GraphNodeId(target), kb_root=self.repo)["total"]

    def test_pre_activation_crashes_keep_published_and_retry_without_reset(self):
        from kctx.graph.generation import completed_snapshot
        boundaries = ("intent", "candidate-ready", "nodes-imported", "data-committed", "metadata-committed", "published")
        for boundary in boundaries:
            with self.subTest(boundary=boundary):
                self.home = self.root / boundary
                self.set_config(graph_dir=str(self.home))
                old_target = "old-" + boundary
                new_target = "new-" + boundary
                self._target(old_target)
                self.sync.sync(self.repo)
                old = self._store()
                before = completed_snapshot(old)
                self._target(new_target)
                self._crash(boundary)
                self.assertEqual(self.sync.dolt_db_dir(), old.db_dir)
                self.assertEqual(completed_snapshot(old), before)
                self.assertEqual(self._uses(old_target), 1)
                self.assertEqual(self._uses(new_target), 0)
                pending = [record for record in self._operations().values() if record["status"] == "pending"]
                self.assertEqual(len(pending), 1)
                record = pending[0]
                candidate = self.home / record["candidate_path"]
                had_candidate = candidate.exists()
                result = self.sync.sync(self.repo)
                self.assertEqual(result["status"], "synced")
                self.assertEqual(self._uses(new_target), 1)
                self.assertEqual(completed_snapshot(old), before)
                self.assertEqual(old.head_commit_hash(), before.metadata_commit.val)
                updated = self._operations()[record["operation_id"]]
                if boundary in ("metadata-committed", "published"):
                    self.assertEqual(updated["status"], "activated")
                    self.assertEqual(self.sync.dolt_db_dir(), candidate)
                    self.assertEqual(len(self._operations()), 2)
                else:
                    self.assertEqual(updated["status"], "abandoned")
                    self.assertNotEqual(self.sync.dolt_db_dir(), candidate)
                    self.assertEqual(len(self._operations()), 3)
                    if had_candidate:
                        self.assertTrue(candidate.is_dir())
                current = self._store()
                rows = current.sql_read(f"SELECT hashof('{before.metadata_commit.val}') AS h")
                self.assertEqual(rows[0]["h"], before.metadata_commit.val)
                self.assertEqual(self.sync.sync(self.repo)["status"], "up-to-date")

    def test_first_generation_crash_recovers_without_publishing_incomplete_state(self):
        from kctx.graph.queries import status
        self._target("first")
        self._crash("nodes-imported")
        self.assertFalse((self.home / "active.json").exists())
        self.assertFalse(status(self.repo)["initialized"])
        pending = next(iter(self._operations().values()))
        dirty = self._store(self.home / pending["candidate_path"])
        self.assertTrue(dirty.sql_read("SELECT table_name FROM dolt_status"))
        self.sync.sync(self.repo)
        self.assertEqual(self._uses("first"), 1)
        self.assertEqual(self._operations()[pending["operation_id"]]["status"], "abandoned")
        self.assertTrue(dirty.sql_read("SELECT table_name FROM dolt_status"))

    def test_active_manifest_crash_finishes_journal_without_rebuilding(self):
        self._target("old")
        self.sync.sync(self.repo)
        self._target("new")
        self._crash("active-written")
        active = self._store()
        before = active.head_commit_hash()
        ready = [record for record in self._operations().values() if record["status"] == "ready"]
        self.assertEqual(len(ready), 1)
        self.assertEqual(self._uses("new"), 1)
        result = self.sync.sync(self.repo)
        self.assertEqual(result["status"], "synced")
        self.assertEqual(self.sync.dolt_db_dir(), active.db_dir)
        self.assertEqual(active.head_commit_hash(), before)
        self.assertEqual(len(self._operations()), 2)
        self.assertEqual(self._operations()[ready[0]["operation_id"]]["status"], "activated")
        self.assertEqual(self.sync.sync(self.repo)["status"], "up-to-date")

    def test_dirty_completed_candidate_is_retained_and_abandoned(self):
        self._target("old")
        self.sync.sync(self.repo)
        self._target("new")
        self._crash("published")
        pending = next(record for record in self._operations().values() if record["status"] == "pending")
        candidate = self._store(self.home / pending["candidate_path"])
        candidate._run("sql", "-q", "UPDATE edges SET dst_node='manual' WHERE rel='consumes'")
        head = candidate.head_commit_hash()
        dirty = candidate.sql_read("SELECT * FROM dolt_status")
        self.sync.sync(self.repo)
        self.assertEqual(self._uses("new"), 1)
        self.assertNotEqual(self.sync.dolt_db_dir(), candidate.db_dir)
        self.assertEqual(candidate.head_commit_hash(), head)
        self.assertEqual(candidate.sql_read("SELECT * FROM dolt_status"), dirty)
        self.assertEqual(candidate.sql_read("SELECT dst_node FROM edges WHERE rel='consumes'")[0]["dst_node"], "manual")
        self.assertEqual(self._operations()[pending["operation_id"]]["status"], "abandoned")

    def test_current_input_digest_controls_recovery_and_noop(self):
        self._target("old")
        self.sync.sync(self.repo)
        self._target("new")
        self._crash("published")
        pending = next(record for record in self._operations().values() if record["status"] == "pending")
        candidate = self._store(self.home / pending["candidate_path"])
        before = candidate.head_commit_hash()
        self.set_config(github_host="changed.example.invalid")
        result = self.sync.sync(self.repo)
        self.assertEqual(result["status"], "synced")
        self.assertNotEqual(result["input_digest"], pending["input_digest"])
        self.assertEqual(candidate.head_commit_hash(), before)
        self.assertEqual(self._operations()[pending["operation_id"]]["status"], "abandoned")
        self.assertEqual(self.sync.sync(self.repo)["status"], "up-to-date")
        current = self.sync.dolt_db_dir()
        self.set_config(github_host="another.example.invalid")
        changed = self.sync.sync(self.repo)
        self.assertEqual(changed["status"], "synced")
        self.assertNotEqual(changed["input_digest"], result["input_digest"])
        self.assertNotEqual(self.sync.dolt_db_dir(), current)

    def test_rebuild_recovery_reuses_completed_candidate(self):
        self._target("same-head")
        self.sync.sync(self.repo)
        old = self.sync.dolt_db_dir()
        self._crash("published", rebuild=True)
        pending = next(record for record in self._operations().values() if record["status"] == "pending")
        candidate = self._store(self.home / pending["candidate_path"])
        before = candidate.head_commit_hash()
        self.assertEqual(self.sync.dolt_db_dir(), old)
        self.assertEqual(self.sync.sync(self.repo, rebuild=True)["status"], "synced")
        self.assertEqual(self.sync.dolt_db_dir(), candidate.db_dir)
        self.assertEqual(candidate.head_commit_hash(), before)
        self.assertEqual(len(self._operations()), 2)

    def test_unowned_pending_candidate_is_preserved_not_adopted(self):
        self._target("old")
        self.sync.sync(self.repo)
        self._target("new")
        self._crash("published")
        pending = next(record for record in self._operations().values() if record["status"] == "pending")
        candidate = self._store(self.home / pending["candidate_path"])
        owner = candidate.db_dir.with_name("dolt.owner.json")
        owner.rename(owner.with_name("preserved-owner.json"))
        before = candidate.head_commit_hash()
        self.sync.sync(self.repo)
        self.assertEqual(candidate.head_commit_hash(), before)
        self.assertFalse(owner.exists())
        self.assertEqual(self._operations()[pending["operation_id"]]["status"], "abandoned")
        self.assertEqual(self._uses("new"), 1)

    def test_native_restore_retains_legacy_owned_history(self):
        from kctx.graph.extract import commit_date, commit_subject
        from kctx.graph.generation import completed_snapshot, publish
        from kctx.graph.inputs import generation_inputs
        from kctx.graph.operations import writer
        sha = self._target("legacy")
        with writer(self.home, self.repo) as legacy:
            legacy.ensure_init()
            inputs = generation_inputs(self.repo, kb_sha=sha)
            _, _, metadata = self.sync._write_one(legacy, self.repo, sha, commit_date(self.repo, sha), commit_subject(self.repo, sha), 1, inputs)
            publish(legacy, metadata, None)
        before = completed_snapshot(legacy)
        self.assertEqual(self.sync.dolt_db_dir(), self.home / "dolt")
        self.sync.sync(self.repo, rebuild=True)
        self.assertNotEqual(self.sync.dolt_db_dir(), legacy.db_dir)
        self.assertEqual(completed_snapshot(legacy), before)
        self.assertEqual(self._store().sql_read(f"SELECT hashof('{metadata.val}') AS h")[0]["h"], metadata.val)
        self.assertTrue((self.home / "dolt" / ".dolt").is_dir())

    def test_stable_lock_remains_same_after_activation(self):
        from kctx.graph.operations import writer
        self._target("old")
        self.sync.sync(self.repo)
        lock = self.home / "dolt.writer.lock"
        inode = lock.stat().st_ino
        self._target("new")
        self.sync.sync(self.repo)
        self.assertEqual(lock.stat().st_ino, inode)
        code = "import fcntl,sys; f=open(sys.argv[1],'a+b'); fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)"
        with writer(self.home, self.repo):
            result = subprocess.run([sys.executable, "-c", code, str(lock)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
        self.assertEqual(subprocess.run([sys.executable, "-c", code, str(lock)], capture_output=True).returncode, 0)

    def test_active_selector_rejects_escape_and_symlink_paths(self):
        from kctx.errors import KctxError
        self._target("old")
        self.sync.sync(self.repo)
        active_path = self.home / "active.json"
        active = json.loads(active_path.read_text(encoding="utf-8"))
        for path in ("../outside/dolt", str(self.root / "outside" / "dolt")):
            with self.subTest(path=path):
                changed = dict(active, db_path=path)
                active_path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(KctxError):
                    self.sync.dolt_db_dir()
        active_path.write_text(json.dumps(active), encoding="utf-8")
        generation = self.home / "generations" / active["operation_id"]
        retained = generation.with_name(generation.name + "-retained")
        generation.rename(retained)
        generation.symlink_to(retained, target_is_directory=True)
        with self.assertRaises(KctxError):
            self.sync.dolt_db_dir()
        with self.assertRaises(KctxError):
            self.sync.sync(self.repo)

    def test_history_recovery_preserves_every_replayed_native_commit(self):
        from kctx.graph.extract import first_parent_record_commits
        oldest = self._target("oldest")
        self.sync.sync(self.repo)
        middle = self._target("middle")
        newest = self._target("newest")
        self._crash("published", history=3)
        pending = next(record for record in self._operations().values() if record["status"] == "pending")
        candidate = self._store(self.home / pending["candidate_path"])
        before = candidate.head_commit_hash()
        result = self.sync.sync(self.repo, history=3)
        self.assertEqual(result["commits_replayed"], len(first_parent_record_commits(self.repo, limit=3)))
        self.assertEqual(candidate.head_commit_hash(), before)
        self.assertEqual(self.sync.dolt_db_dir(), candidate.db_dir)
        rows = candidate.sql_read("SELECT kb_sha,dolt_commit FROM kb_commits")
        commits = {row["kb_sha"]: row["dolt_commit"] for row in rows}
        self.assertEqual(set(commits), {oldest, middle, newest})
        for commit in commits.values():
            self.assertEqual(candidate.sql_read(f"SELECT hashof('{commit}') AS h")[0]["h"], commit)
        self.assertEqual(self._uses("newest"), 1)

    def test_dirty_published_database_blocks_recovery_without_touching_candidate(self):
        from kctx.errors import KctxError
        self._target("old")
        self.sync.sync(self.repo)
        old = self._store()
        self._target("new")
        self._crash("published")
        pending = next(record for record in self._operations().values() if record["status"] == "pending")
        candidate = self._store(self.home / pending["candidate_path"])
        candidate_head = candidate.head_commit_hash()
        old._run("sql", "-q", "UPDATE edges SET dst_node='manual' WHERE rel='consumes'")
        with self.assertRaises(KctxError):
            self.sync.sync(self.repo)
        self.assertEqual(self.sync.dolt_db_dir(), old.db_dir)
        self.assertEqual(self._operations()[pending["operation_id"]], pending)
        self.assertEqual(candidate.head_commit_hash(), candidate_head)
        self.assertEqual(old.sql_read("SELECT dst_node FROM edges WHERE rel='consumes'")[0]["dst_node"], "manual")

    def test_native_restore_uses_operation_identity_without_global_author(self):
        self._target("scoped-author")
        self.sync.sync(self.repo)
        user_root = self.root / "user-dolt-config"
        global_config = user_root / ".dolt" / "config_global.json"
        global_config.parent.mkdir(parents=True)
        original = '{"metrics.disabled":"true"}\n'
        global_config.write_text(original, encoding="utf-8")
        environment = os.environ.copy()
        environment["DOLT_ROOT_PATH"] = str(user_root)
        source = str(Path(__file__).resolve().parents[1] / "src")
        environment["PYTHONPATH"] = source + os.pathsep + environment.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-c", _CRASH_WORKER, str(self.repo), "no-interruption", '{"rebuild":true}'],
            cwd=self.repo, env=environment, capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(global_config.read_text(encoding="utf-8"), original)
        current = self._store()
        self.assertEqual(current._run("config", "--local", "--get", "user.name").strip(), "kctx-restore")
        self.assertEqual(current._run("config", "--local", "--get", "user.email").strip(), "kctx-restore@localhost")
        scoped = current.db_dir.parent / "restore-config" / ".dolt" / "config_global.json"
        self.assertEqual(json.loads(scoped.read_text(encoding="utf-8"))["user.name"], "kctx-restore")
