"""graph.models needs pydantic. Skips cleanly under plain `python3 -m
unittest` when it isn't installed in the ambient interpreter -- it's always
present under `uv run` (the supported way to run kctx)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import unittest

try:
    import pydantic  # noqa: F401

    HAVE_PYDANTIC = True
except ImportError:
    HAVE_PYDANTIC = False


@unittest.skipUnless(HAVE_PYDANTIC, "pydantic not installed in ambient interpreter; run via `uv run`")
class NodeModelTest(unittest.TestCase):
    def test_from_row_fills_optional_fields(self):
        from kctx.graph.models import Node

        n = Node.from_row({"id": "sig:foo", "kind": "sig"})
        self.assertEqual(n.id, "sig:foo")
        self.assertIsNone(n.label)
        self.assertIsNone(n.home_path)

    def test_from_row_rejects_missing_id(self):
        from kctx.graph.models import Node

        with self.assertRaises(KeyError):
            Node.from_row({"kind": "sig"})


@unittest.skipUnless(HAVE_PYDANTIC, "pydantic not installed in ambient interpreter; run via `uv run`")
class EdgeModelTest(unittest.TestCase):
    def test_from_row_illus_defaults_false(self):
        from kctx.graph.models import Edge

        e = Edge.from_row({"edge_id": "x", "src_node": "a", "dst_node": "b", "rel": "cites"})
        self.assertFalse(e.illus)
        self.assertIsNone(e.rev)

    def test_from_row_illus_true(self):
        from kctx.graph.models import Edge

        e = Edge.from_row({"edge_id": "x", "src_node": "a", "dst_node": "b", "rel": "cites", "illus": 1})
        self.assertTrue(e.illus)

    def test_model_dump_round_trips(self):
        from kctx.graph.models import Edge

        e = Edge(edge_id="x", src_node="a", dst_node="b", rel="mentions")
        dumped = e.model_dump()
        self.assertEqual(dumped["rel"], "mentions")
        self.assertIn("illus", dumped)


@unittest.skipUnless(HAVE_PYDANTIC, "pydantic not installed in ambient interpreter; run via `uv run`")
class SyncStateModelTest(unittest.TestCase):
    def test_from_row_defaults_counts_to_zero(self):
        from kctx.graph.models import SyncState

        st = SyncState.from_row({"kb_sha": "abc123", "synced_at": "2026-10-30T00:00:00Z"})
        self.assertEqual(st.node_count, 0)
        self.assertEqual(st.edge_count, 0)


if __name__ == "__main__":
    unittest.main()
