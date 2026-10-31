"""Graph commands preserve service payloads and partial-result exit codes."""

import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

from _base import KctxTestCase
from kctx.cli.app import main
from kctx.graph.models import GraphNodeId


class GraphCommandTest(KctxTestCase):
    def invoke(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--json", "graph", *args])
        return code, json.loads(output.getvalue())

    def test_exact_mismatch_preserves_binding_diagnostics(self):
        result = {
            "parity": {"match": False, "binding_mismatches": [{
                "edge_id": "binding",
                "expected": {"src_path": "note.md", "src_line": 2, "rev": "correct"},
                "actual": {"src_path": "note.md", "src_line": 2, "rev": "wrong"},
            }]},
            "uses_comparison": [],
        }
        with patch("kctx.graph.queries.check", return_value=result) as service:
            code, payload = self.invoke("check", "--sample", "proposal:one")
        self.assertEqual(code, 2)
        self.assertEqual(payload, result)
        self.assertEqual(service.call_args.kwargs["sample_ids"], [GraphNodeId("proposal:one")])

    def test_uses_preserves_bounds_and_illustrative_flag(self):
        result = {"target": "proposal:one", "total": 0, "returned": 0, "by_rel": {}}
        with patch("kctx.graph.queries.uses", return_value=result) as service:
            code, payload = self.invoke("uses", "proposal:one", "--limit", "7", "--include-illus")
        self.assertEqual((code, payload), (2, result))
        self.assertEqual(service.call_args.args, (GraphNodeId("proposal:one"),))
        self.assertEqual(service.call_args.kwargs["limit"], 7)
        self.assertTrue(service.call_args.kwargs["include_illus"])

    def test_sync_retains_history_and_rebuild(self):
        with patch("kctx.graph.sync.sync", return_value={"synced": True}) as service:
            code, payload = self.invoke("sync", "--rebuild", "--history", "4")
        self.assertEqual((code, payload), (0, {"synced": True}))
        self.assertEqual(service.call_args.kwargs, {"rebuild": True, "history": 4})
