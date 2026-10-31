"""Real filesystem/process regressions for published-record visibility."""

import json
import select
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from _base import KctxTestCase
from kctx.adapters.files import storage
from kctx.adapters.files.mutations import compare_and_write, file_lock, read_revision
from kctx.errors import KctxError


class PublicationTests(KctxTestCase):
    def test_immutable_name_is_absent_before_bytes_are_written(self):
        target = self.root / "observation.json"
        original = storage.os.fdopen

        def open_private_inode(descriptor, *args, **kwargs):
            self.assertFalse(target.exists(), "empty/partial public record became visible")
            return original(descriptor, *args, **kwargs)

        with patch.object(storage.os, "fdopen", side_effect=open_private_inode):
            storage.exclusive_write_json(target, {"id": "observation-1", "payload": "retained"})
        self.assertEqual(json.loads(target.read_bytes()), {"id": "observation-1", "payload": "retained"})

    def test_process_interruption_before_publication_never_exposes_partial_json(self):
        target = self.root / "observation.json"
        code = '''
import signal,sys
from pathlib import Path
from kctx.adapters.files import storage
def pause_before_publish(*args, **kwargs):
    print("prepared", flush=True)
    signal.pause()
storage.os.link = pause_before_publish
storage.exclusive_write_json(Path(sys.argv[1]), {"id":"interrupted"})
'''
        process = subprocess.Popen([sys.executable, "-c", code, str(target)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            ready, _, _ = select.select([process.stdout], [], [], 10)
            self.assertTrue(ready, "child failed to prepare its immutable record")
            self.assertEqual(process.stdout.readline(), b"prepared\n")
            self.assertFalse(target.exists())
        finally:
            process.kill()
            process.communicate(timeout=5)
        self.assertEqual(storage.list_json_files(self.root), [])
        storage.exclusive_write_json(target, {"id": "retry"})
        self.assertEqual(storage.read_json(target), {"id": "retry"})

    def test_two_processes_cannot_replace_an_immutable_winner(self):
        target = self.root / "observation.json"
        code = '''
import sys
from pathlib import Path
from kctx.adapters.files.storage import exclusive_write_json
from kctx.errors import KctxError
try:
    exclusive_write_json(Path(sys.argv[1]), {"winner":sys.argv[2]})
except KctxError as error:
    if error.category != "conflict": raise
    raise SystemExit(10)
'''
        children = [subprocess.Popen([sys.executable, "-c", code, str(target), value], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for value in ("first", "second")]
        outputs = [child.communicate(timeout=10) for child in children]
        self.assertEqual(sorted(child.returncode for child in children), [0, 10], outputs)
        winner = next(value for value, child in zip(("first", "second"), children, strict=True) if child.returncode == 0)
        self.assertEqual(storage.read_json(target), {"winner": winner})

    def test_stale_candidate_cannot_overwrite_a_newer_authored_record(self):
        target = self.root / "proposal.md"
        target.write_bytes(b"original\n")
        original = read_revision(target)
        target.write_bytes(b"newer author edit\n")
        with file_lock(target), self.assertRaises(KctxError) as caught:
            compare_and_write(target, b"stale candidate\n", expected=original)
        self.assertEqual(caught.exception.category, "conflict")
        self.assertEqual(target.read_bytes(), b"newer author edit\n")

    def test_matching_predecessor_publishes_exact_candidate_bytes(self):
        target = self.root / "proposal.md"
        with file_lock(target):
            first = compare_and_write(target, b"first\r\n", expected=None)
            second = compare_and_write(target, b"second\r\n", expected=first)
        self.assertEqual(read_revision(target), second)
        self.assertEqual(target.read_bytes(), b"second\r\n")
