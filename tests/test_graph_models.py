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
        self.assertEqual(n.id.val, "sig:foo")
        self.assertIsNone(n.label)
        self.assertIsNone(n.home_path)

    def test_from_row_rejects_missing_id(self):
        from kctx.graph.models import Node

        with self.assertRaises(pydantic.ValidationError):
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
        from kctx.graph.models import Edge, GraphEdgeId, GraphNodeId

        e = Edge(edge_id=GraphEdgeId("x"), src_node=GraphNodeId("a"), dst_node=GraphNodeId("b"), rel="mentions")
        dumped = e.to_wire()
        self.assertEqual(dumped["rel"], "mentions")
        self.assertIn("illus", dumped)
        self.assertEqual(dumped["edge_id"], "x")
        self.assertEqual(dumped["src_node"], "a")
        self.assertEqual(Edge.from_row(dumped), e)

    def test_illus_accepts_only_explicit_dolt_booleans(self):
        from kctx.graph.models import Edge

        for value, expected in [(False, False), (True, True), (0, False), (1, True), ("0", False), ("1", True)]:
            with self.subTest(value=value):
                edge = Edge.from_row({"edge_id": "x", "src_node": "a", "dst_node": "b", "rel": "cites", "illus": value})
                self.assertIs(edge.illus, expected)
        for value in [2, -1, "false", "true", "", None, 0.0, [], {}]:
            with self.subTest(value=value), self.assertRaises(pydantic.ValidationError):
                Edge.from_row({"edge_id": "x", "src_node": "a", "dst_node": "b", "rel": "cites", "illus": value})

    def test_projection_ids_have_separate_namespaces(self):
        from kctx.graph.models import GraphNodeId, GraphEdgeId
        from kctx.domain.ids import AssetId

        self.assertNotEqual(GraphNodeId("a"), GraphEdgeId("a"))
        self.assertNotEqual(GraphNodeId("a"), AssetId("a"))
        self.assertNotEqual(GraphNodeId("a"), "a")


@unittest.skipUnless(HAVE_PYDANTIC, "pydantic not installed in ambient interpreter; run via `uv run`")
class SyncStateModelTest(unittest.TestCase):
    def test_from_row_defaults_counts_to_zero(self):
        from kctx.graph.models import SyncState

        st = SyncState.from_row({"kb_sha": "abc123", "synced_at": "2026-10-30T00:00:00Z"})
        self.assertEqual(st.node_count, 0)
        self.assertEqual(st.edge_count, 0)

    def test_counts_reject_blind_coercion(self):
        from kctx.graph.models import SyncState

        for value in [True, 1.5, "1.5", None, ""]:
            with self.subTest(value=value), self.assertRaises(pydantic.ValidationError):
                SyncState.from_row({"kb_sha": "abc", "synced_at": "now", "node_count": value})
        state = SyncState.from_row({"kb_sha": "abc", "synced_at": "now", "node_count": "12"})
        self.assertEqual(state.node_count, 12)


@unittest.skipUnless(HAVE_PYDANTIC, "pydantic not installed; run via uv run")
class QueryRowModelTest(unittest.TestCase):
    def test_dolt_omitted_null_columns_decode_as_none(self):
        from kctx.graph.models import ImpactRow, UsesRow

        uses = UsesRow.model_validate({"src_node": "source", "rel": "mentions"})
        self.assertIsNone(uses.cite_kind)
        self.assertIsNone(uses.seen)
        self.assertIsNone(uses.src_kind)
        self.assertIsNone(uses.src_home_path)
        impact = ImpactRow.model_validate({"node": "source", "depth": 1, "path": "target <- source"})
        self.assertIsNone(impact.kind)
        self.assertIsNone(impact.home_path)


if __name__ == "__main__":
    unittest.main()
