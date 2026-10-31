"""Literal binding goldens and qualification against native Git/Dolt history.

The oracle tests never call extract_graph. Native tests deliberately publish a
well-formed generation with wrong bindings: matching row counts are insufficient.
"""

import json
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from _base import KctxTestCase
from kctx.errors import KctxError
from kctx.graph import queries, sync
from kctx.graph.dolt_store import DoltStore
from kctx.graph.generation import COMPLETED_BRANCH, completed_snapshot
from kctx.graph.identity import RepositoryIdentity
from kctx.graph.models import Edge, ExtractionDiagnostic, GraphEdgeId, GraphNodeId
from kctx.graph.parity import ExpectedBindings, compare_bindings, expected_bindings
from kctx.graph.quoting import sql_quote


SEEN = "2026-10-31T12:00:00Z"
IDENTITY = RepositoryIdentity("kb", "git@github.com:acme/kb.git")
HAVE_DOLT = shutil.which("dolt") is not None or os.access(
    Path.home() / ".local/bin/dolt", os.X_OK,
)


def binding_fields(edge):
    """Only the opaque row key is excluded from the authored-field goldens."""
    row = edge.to_wire()
    del row["edge_id"]
    return row


class ExpectedBindingsGoldenTest(unittest.TestCase):
    def test_markdown_multiple_bindings_physical_lines_and_diagnostics(self):
        source = (
            "---\nid: deploy\n---\n"
            'First ⟦cite kind=code repo=kb path="src/a b.py" rev=abcdef1 '
            'L=4-8 span=0123456789abcdef blob=abcdef0123456789 seen=2026-10-30⟧ '
            'then ⟦cite kind=commit repo=alias url=https://github.com/other/lib.git rev=1234567⟧\n'
            '⟦cite illus kind=ticket id=OPS-9⟧\n'
            '⟦cite id=missing⟧\n'
            '⟦cite kind=ticket id=A id=B⟧\n'
            '⟦cite illus kind=ticket id=unfinished'
        )
        result = expected_bindings({"signatures/deploy.md": source}, SEEN, IDENTITY)
        self.assertEqual([binding_fields(edge) for edge in result.edges], [
            {
                "src_node": "sig:deploy", "dst_node": "code:acme/kb:src/a b.py",
                "rel": "cites", "src_path": "signatures/deploy.md", "src_line": 4,
                "cite_kind": "code", "rev": "abcdef1", "blob_sha": "abcdef0123456789",
                "span": "0123456789abcdef", "line_selector": "4-8", "seen": "2026-10-30",
                "state": None, "illus": False,
                "raw": '⟦cite kind=code repo=kb path="src/a b.py" rev=abcdef1 L=4-8 span=0123456789abcdef blob=abcdef0123456789 seen=2026-10-30⟧',
            },
            {
                "src_node": "sig:deploy", "dst_node": "code:other/lib@1234567",
                "rel": "cites", "src_path": "signatures/deploy.md", "src_line": 4,
                "cite_kind": "commit", "rev": "1234567", "blob_sha": None,
                "span": None, "line_selector": None, "seen": SEEN,
                "state": None, "illus": False,
                "raw": "⟦cite kind=commit repo=alias url=https://github.com/other/lib.git rev=1234567⟧",
            },
            {
                "src_node": "sig:deploy", "dst_node": "ticket:OPS-9",
                "rel": "cites", "src_path": "signatures/deploy.md", "src_line": 5,
                "cite_kind": "ticket", "rev": None, "blob_sha": None,
                "span": None, "line_selector": None, "seen": SEEN,
                "state": None, "illus": True, "raw": "⟦cite illus kind=ticket id=OPS-9⟧",
            },
        ])
        self.assertEqual([item.to_wire() for item in result.skips], [
            {"category": "citation-skip", "src_path": "signatures/deploy.md", "src_line": 6,
             "reason": "no kind= field", "raw": "⟦cite id=missing⟧", "illus": False},
            {"category": "citation-skip", "src_path": "signatures/deploy.md", "src_line": 7,
             "reason": "duplicate citation field 'id'", "raw": "⟦cite kind=ticket id=A id=B⟧", "illus": False},
            {"category": "citation-skip", "src_path": "signatures/deploy.md", "src_line": 8,
             "reason": "unterminated citation token", "raw": "⟦cite illus kind=ticket id=unfinished", "illus": True},
        ])
        self.assertEqual(result.token_count, 6)
        self.assertEqual(result.illustrative_count, 2)
        self.assertEqual(result.token_ids, frozenset(edge.edge_id for edge in result.edges))
        self.assertEqual(len(result.token_ids), 3)

    def test_json_asset_preserves_escaped_raw_and_physical_not_decoded_line(self):
        source = (
            '{\n  "id": "service-\\u0061pi",\n'
            r'  "notes": "prefix\n\u27e6cite kind=code repo=kb path=\"src\/a b.py\" rev=abcdef1 L=9-12 span=fedcba9876543210\u27e7 and ⟦cite kind=record path=\"notes\/design doc.md\" state=accepted⟧"'
            '\n}\n'
        )
        result = expected_bindings({"inventory/assets/api.json": source}, SEEN, IDENTITY)
        self.assertEqual([binding_fields(edge) for edge in result.edges], [
            {
                "src_node": "service-api", "dst_node": "code:acme/kb:src/a b.py",
                "rel": "cites", "src_path": "inventory/assets/api.json", "src_line": 3,
                "cite_kind": "code", "rev": "abcdef1", "blob_sha": None,
                "span": "fedcba9876543210", "line_selector": "9-12", "seen": SEEN,
                "state": None, "illus": False,
                "raw": r'\u27e6cite kind=code repo=kb path=\"src\/a b.py\" rev=abcdef1 L=9-12 span=fedcba9876543210\u27e7',
            },
            {
                "src_node": "service-api", "dst_node": "doc:notes/design doc.md",
                "rel": "cites", "src_path": "inventory/assets/api.json", "src_line": 3,
                "cite_kind": "record", "rev": None, "blob_sha": None,
                "span": None, "line_selector": None, "seen": SEEN,
                "state": "accepted", "illus": False,
                "raw": r'⟦cite kind=record path=\"notes\/design doc.md\" state=accepted⟧',
            },
        ])
        self.assertEqual(result.token_count, 2)
        self.assertEqual(result.skips, ())

    def test_json_relationship_source_and_short_locator_are_literal_bindings(self):
        source = (
            '{\n  "from": "service-\\u0061pi", "to": "store-db", "type": "consumes",\n'
            '  "evidence": [\n'
            r'    "kb@abcdef1:src\/db.py:20-23",' '\n'
            r'    "before\n⟦cite kind=code repo=alias url=https:\/\/github.com\/acme\/lib.git path=\"src\/client.py\" rev=1234567 L=2 span=0123456789abcdef⟧"' '\n'
            '  ]\n}\n'
        )
        result = expected_bindings({"inventory/relationships/api-db.json": source}, SEEN, IDENTITY)
        self.assertEqual([binding_fields(edge) for edge in result.edges], [
            {
                "src_node": "service-api", "dst_node": "code:acme/lib:src/client.py",
                "rel": "cites", "src_path": "inventory/relationships/api-db.json", "src_line": 5,
                "cite_kind": "code", "rev": "1234567", "blob_sha": None,
                "span": "0123456789abcdef", "line_selector": "2", "seen": SEEN,
                "state": None, "illus": False,
                "raw": r'⟦cite kind=code repo=alias url=https:\/\/github.com\/acme\/lib.git path=\"src\/client.py\" rev=1234567 L=2 span=0123456789abcdef⟧',
            },
            {
                "src_node": "service-api", "dst_node": "code:acme/kb:src/db.py",
                "rel": "cites", "src_path": "inventory/relationships/api-db.json", "src_line": 4,
                "cite_kind": "code", "rev": "abcdef1", "blob_sha": None,
                "span": None, "line_selector": "20-23", "seen": SEEN,
                "state": None, "illus": False, "raw": r'kb@abcdef1:src\/db.py:20-23',
            },
        ])
        self.assertEqual(result.token_count, 1)
        self.assertEqual(result.token_ids, frozenset([result.edges[0].edge_id]))
        self.assertEqual(result.skips, ())

    def test_duplicate_citations_remain_distinct_even_on_one_line(self):
        result = expected_bindings(
            {"notes.md": "⟦cite kind=ticket id=OPS-1⟧ ⟦cite kind=ticket id=OPS-1⟧"},
            SEEN, IDENTITY,
        )
        self.assertEqual(len(result.edges), 2)
        self.assertNotEqual(result.edges[0].edge_id, result.edges[1].edge_id)
        self.assertEqual([edge.src_line for edge in result.edges], [1, 1])
        self.assertEqual([edge.dst_node.val for edge in result.edges], ["ticket:OPS-1", "ticket:OPS-1"])
        self.assertEqual(result.token_count, 2)


    def test_proposal_authored_references_have_literal_fields_and_source_lines(self):
        source = (
            "---\nid: deploy\nstatus: accepted\n"
            "references: [kb@abcdef1:src/a.py:4-8, https://example.test/design, "
            "team/2026-10-30-baseline, ev:deploy/evidence/note]\n"
            "---\n"
        )
        result = expected_bindings({"proposals/deploy/proposal.md": source}, SEEN, IDENTITY)
        self.assertEqual([binding_fields(edge) for edge in result.edges], [
            {
                "src_node": "proposal:deploy", "dst_node": "code:acme/kb:src/a.py",
                "rel": "references", "src_path": "proposals/deploy/proposal.md", "src_line": 4,
                "cite_kind": "code", "rev": "abcdef1", "blob_sha": None,
                "span": None, "line_selector": "4-8", "seen": SEEN,
                "state": "accepted", "illus": False, "raw": "kb@abcdef1:src/a.py:4-8",
            },
            {
                "src_node": "proposal:deploy", "dst_node": "web:https://example.test/design",
                "rel": "references", "src_path": "proposals/deploy/proposal.md", "src_line": 4,
                "cite_kind": "web", "rev": None, "blob_sha": None,
                "span": None, "line_selector": None, "seen": SEEN,
                "state": "accepted", "illus": False, "raw": "https://example.test/design",
            },
            {
                "src_node": "proposal:deploy", "dst_node": "proposal:team/2026-10-30-baseline",
                "rel": "references", "src_path": "proposals/deploy/proposal.md", "src_line": 4,
                "cite_kind": "proposal", "rev": None, "blob_sha": None,
                "span": None, "line_selector": None, "seen": SEEN,
                "state": "accepted", "illus": False, "raw": "team/2026-10-30-baseline",
            },
            {
                "src_node": "proposal:deploy", "dst_node": "ev:deploy/evidence/note",
                "rel": "references", "src_path": "proposals/deploy/proposal.md", "src_line": 4,
                "cite_kind": "ev", "rev": None, "blob_sha": None,
                "span": None, "line_selector": None, "seen": SEEN,
                "state": "accepted", "illus": False, "raw": "ev:deploy/evidence/note",
            },
        ])
        self.assertEqual(result.token_count, 0)
        self.assertEqual(result.token_ids, frozenset())
        self.assertEqual(result.skips, ())
        self.assertEqual(result.other_diagnostics, ())

    def test_record_and_unresolved_alias_diagnostics_are_literal_goldens(self):
        result = expected_bindings({
            "inventory/assets/broken.json": "{}\n",
            "notes.md": "heading\n⟦cite illus kind=code repo=unknown path=a.py rev=abcdef1⟧\n",
        }, SEEN, IDENTITY)
        self.assertEqual([item.to_wire() for item in result.other_diagnostics], [
            {
                "category": "record-malformed", "src_path": "inventory/assets/broken.json",
                "src_line": 1, "reason": "asset.id is required and must not be empty",
                "raw": "{}\n", "illus": False,
            },
            {
                "category": "unresolved-repo", "src_path": "notes.md", "src_line": 2,
                "reason": "repository alias 'unknown' has no canonical org/repo identity",
                "raw": "⟦cite illus kind=code repo=unknown path=a.py rev=abcdef1⟧", "illus": True,
            },
        ])
        self.assertEqual(result.skips, ())
        self.assertEqual(result.token_count, 1)
        self.assertEqual(result.illustrative_count, 1)


class CompareBindingsGoldenTest(unittest.TestCase):
    def setUp(self):
        # Construct the expected contract without invoking either source scanner.
        self.row = {
            "edge_id": "literal-golden-binding", "src_node": "proposal:release",
            "dst_node": "code:acme/lib:src/a.py", "rel": "cites",
            "src_path": "proposals/release/proposal.md", "src_line": 8,
            "cite_kind": "code", "rev": "abcdef1", "blob_sha": "abcdef0123456789",
            "span": "0123456789abcdef", "line_selector": "5-9", "seen": SEEN,
            "state": None, "illus": False,
            "raw": "⟦cite kind=code repo=acme/lib path=src/a.py rev=abcdef1 L=5-9 span=0123456789abcdef blob=abcdef0123456789⟧",
        }
        self.skip_row = {
            "category": "citation-skip", "src_path": "notes.md", "src_line": 2,
            "reason": "no kind= field", "raw": "⟦cite id=bad⟧", "illus": False,
        }
        self.expected = ExpectedBindings(
            (Edge.model_validate(self.row),), (ExtractionDiagnostic.model_validate(self.skip_row),),
            frozenset([GraphEdgeId("literal-golden-binding")]), 2, 0,
        )

    def test_literal_rows_match_independent_expected_contract(self):
        result = compare_bindings(
            self.expected, [Edge.model_validate(dict(self.row))],
            [ExtractionDiagnostic.model_validate(dict(self.skip_row))],
        )
        self.assertTrue(result["match"])
        self.assertEqual(result["binding_mismatches"], [])
        self.assertEqual(result["binding_mismatch_count"], 0)
        self.assertTrue(result["diagnostics_match"])
        self.assertEqual(result["expected_binding_rows"], 1)
        self.assertEqual(result["actual_binding_rows"], 1)
        self.assertEqual(result["skipped_tokens"], 1)

    def test_equal_counts_do_not_hide_any_changed_binding_field(self):
        changes = {
            "edge_id": "another-binding", "src_node": "proposal:wrong",
            "dst_node": "code:acme/lib:src/wrong.py", "rel": "mentions",
            "src_path": "wrong.md", "src_line": 9, "cite_kind": "commit",
            "rev": "1234567", "blob_sha": "0000000", "span": "ffffffffffffffff",
            "line_selector": "10-12", "seen": "2020-01-01", "state": "closed",
            "illus": True, "raw": "rewritten raw token",
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                actual = Edge.model_validate({**self.row, field: value})
                result = compare_bindings(self.expected, [actual], self.expected.skips)
                self.assertFalse(result["match"])
                self.assertEqual(result["expected_binding_rows"], result["actual_binding_rows"])
                self.assertEqual(result["binding_mismatch_count"], 2 if field == "edge_id" else 1)
                if field != "edge_id":
                    self.assertEqual(result["binding_mismatches"], [{
                        "edge_id": "literal-golden-binding", "expected": self.row,
                        "actual": {**self.row, field: value},
                    }])

    def test_missing_and_duplicate_rows_are_not_set_equal(self):
        missing = compare_bindings(self.expected, [], self.expected.skips)
        self.assertFalse(missing["match"])
        self.assertEqual(missing["binding_mismatches"], [{
            "edge_id": "literal-golden-binding", "expected": self.row, "actual": None,
        }])
        actual = Edge.model_validate(self.row)
        duplicate = compare_bindings(self.expected, [actual, actual], self.expected.skips)
        self.assertFalse(duplicate["match"])
        self.assertEqual(duplicate["binding_mismatch_count"], 1)
        self.assertEqual(duplicate["binding_mismatches"], [{
            "edge_id": "literal-golden-binding", "expected": None, "actual": self.row,
        }])

    def test_diagnostic_content_and_multiplicity_are_part_of_parity(self):
        changed = ExtractionDiagnostic.model_validate({**self.skip_row, "src_line": 3})
        for diagnostics in ([], [changed], [self.expected.skips[0]] * 2):
            with self.subTest(diagnostics=diagnostics):
                result = compare_bindings(self.expected, [Edge.model_validate(self.row)], diagnostics)
                self.assertFalse(result["match"])
                self.assertFalse(result["diagnostics_match"])
                self.assertEqual(result["binding_mismatch_count"], 0)

    def test_mismatch_samples_are_bounded_without_truncating_total(self):
        actual = [Edge.model_validate({**self.row, "edge_id": f"extra-{index}"}) for index in range(105)]
        result = compare_bindings(self.expected, actual, self.expected.skips)
        self.assertFalse(result["match"])
        self.assertEqual(result["binding_mismatch_count"], 106)
        self.assertEqual(len(result["binding_mismatches"]), 100)


    def test_all_diagnostic_categories_require_exact_content_and_multiplicity(self):
        record = ExtractionDiagnostic.model_validate({
            "category": "record-malformed", "src_path": "inventory/assets/broken.json",
            "src_line": 1, "reason": "asset.id is required and must not be empty",
            "raw": "{}\n", "illus": False,
        })
        unresolved = ExtractionDiagnostic.model_validate({
            "category": "unresolved-repo", "src_path": "notes.md", "src_line": 5,
            "reason": "repository alias 'unknown' has no canonical org/repo identity",
            "raw": "⟦cite kind=code repo=unknown path=a.py rev=abcdef1⟧", "illus": False,
        })
        expected = ExpectedBindings(
            self.expected.edges, self.expected.skips, self.expected.token_ids,
            self.expected.token_count, self.expected.illustrative_count, (record, unresolved),
        )
        diagnostics = [*self.expected.skips, record, unresolved]
        valid = compare_bindings(expected, [Edge.model_validate(self.row)], list(reversed(diagnostics)))
        self.assertTrue(valid["match"], "diagnostic order is not authored semantics")
        self.assertTrue(valid["diagnostics_match"])
        self.assertFalse(valid["representation_complete"])
        self.assertEqual(valid["diagnostic_count"], 3)
        self.assertFalse(valid["diagnostics_truncated"])
        for changed in (
            diagnostics[:-1],
            [*diagnostics, record],
            [*self.expected.skips, record.model_copy(update={"raw": "[]"}), unresolved],
            [*self.expected.skips, record, unresolved.model_copy(update={"reason": "different reason"})],
            [*self.expected.skips, record, unresolved.model_copy(update={"illus": True})],
            [*self.expected.skips, record, unresolved.model_copy(update={"category": "record-malformed"})],
        ):
            with self.subTest(diagnostics=changed):
                result = compare_bindings(expected, [Edge.model_validate(self.row)], changed)
                self.assertFalse(result["match"])
                self.assertFalse(result["diagnostics_match"])
                self.assertEqual(result["binding_mismatch_count"], 0)

    def test_diagnostic_sampling_does_not_hide_total_or_incompleteness(self):
        diagnostics = tuple(
            ExtractionDiagnostic.model_validate({**self.skip_row, "src_line": index + 1})
            for index in range(105)
        )
        expected = ExpectedBindings((), diagnostics, frozenset(), 105, 0)
        result = compare_bindings(expected, [], diagnostics)
        self.assertTrue(result["match"])
        self.assertFalse(result["representation_complete"])
        self.assertTrue(result["diagnostics_truncated"])
        self.assertEqual(result["diagnostic_count"], 105)
        self.assertEqual(len(result["diagnostics"]), 100)
        self.assertEqual(len(result["skips"]), 100)


class GraphArgumentBoundsTest(unittest.TestCase):
    def test_invalid_limits_fail_before_constructing_native_store(self):
        root = Path("unused-kb")
        target = GraphNodeId("service-api")
        operations = {
            "uses": lambda value: queries.uses(target, kb_root=root, limit=value),
            "impact": lambda value: queries.impact(target, kb_root=root, limit=value),
            "diff": lambda value: queries.diff("HEAD", "HEAD", kb_root=root, limit=value),
            "history": lambda value: sync.sync(root, history=value),
        }
        with patch.object(queries, "DoltStore") as query_store, patch.object(sync, "DoltStore") as sync_store:
            for name, operation in operations.items():
                for value in (0, -1, 1001, True, False, 1.5, "1"):
                    with self.subTest(operation=name, value=value):
                        with self.assertRaises(KctxError) as error:
                            operation(value)
                        self.assertEqual(error.exception.category, "malformed")
            query_store.assert_not_called()
            sync_store.assert_not_called()

    def test_traversal_and_sample_bounds_precede_native_operations(self):
        root = Path("unused-kb")
        target = GraphNodeId("service-api")
        with patch.object(queries, "DoltStore") as store:
            for depth in (0, -1, 11, True, 1.5, "1"):
                with self.subTest(depth=depth), self.assertRaises(KctxError):
                    queries.impact(target, kb_root=root, depth=depth)
            with self.assertRaises(KctxError):
                queries.impact(target, kb_root=root, rel=["consumes"] * 33)
            with self.assertRaises(KctxError):
                queries.check(root, sample_ids=[target] * 33)
            store.assert_not_called()


@unittest.skipUnless(HAVE_DOLT, "native dolt is not installed")
class NativeGraphParityTest(KctxTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.make_git_repo("parity-kb")
        self.set_config(graph_dir=str(self.root / "graph"))
        self.run_git(self.repo, "remote", "add", "origin", "https://github.com/acme/kb.git")
        self.sha = self.commit_file(
            self.repo, "signatures/deploy.md",
            '---\nid: deploy\n---\n'
            f'⟦cite kind=code repo={self.repo.name} path=src/a.py rev=abcdef1 L=4-8 span=0123456789abcdef⟧\n',
            "add literal source binding",
        )

    def _store(self):
        # Recovery may rotate the active database; never cache the old directory.
        return DoltStore(sync.dolt_db_dir())

    def _snapshot(self, store):
        snapshot = completed_snapshot(store)
        self.assertIsNotNone(snapshot)
        return snapshot

    def _manifest_rows(self, store, commit):
        return store.sql_read(
            f"SELECT * FROM generation_inputs AS OF {sql_quote(commit.val)} ORDER BY id"
        )

    def test_native_published_wrong_bindings_fail_with_unchanged_counts_and_inputs(self):
        synced = sync.sync(self.repo)
        self.assertEqual(synced["status"], "synced")
        self.assertTrue(queries.check(self.repo)["parity"]["match"])
        store = self._store()
        before = self._snapshot(store)
        manifest = self._manifest_rows(store, before.data_commit)
        self.assertEqual(manifest, self._manifest_rows(store, before.metadata_commit))
        self.assertEqual(json.loads(manifest[0]["manifest"]), before.inputs)
        self.assertEqual(manifest[0]["input_digest"], before.state.input_digest)

        store._run("sql", "-q", "UPDATE edges SET rev='7654321', dst_node='code:acme/kb:src/wrong.py' WHERE rel='cites'")
        store._run("sql", "-q", "UPDATE sync_state SET dolt_commit=NULL WHERE id=1")
        store._run("sql", "-q", f"UPDATE kb_commits SET dolt_commit=NULL WHERE kb_sha={sql_quote(self.sha)}")
        data = store.commit("qualification: corrupt binding without changing counts")
        store._run("sql", "-q", f"UPDATE sync_state SET dolt_commit={sql_quote(data)} WHERE id=1")
        store._run("sql", "-q", f"UPDATE kb_commits SET dolt_commit={sql_quote(data)} WHERE kb_sha={sql_quote(self.sha)}")
        metadata = store.commit("qualification: metadata names native corrupt data parent")
        store._run("branch", "-f", COMPLETED_BRANCH, metadata)

        after = self._snapshot(store)
        self.assertEqual(after.data_commit.val, data)
        self.assertEqual(after.metadata_commit.val, metadata)
        self.assertEqual(after.state.edge_count, before.state.edge_count)
        self.assertEqual(after.state.node_count, before.state.node_count)
        self.assertEqual(after.inputs, before.inputs)
        self.assertEqual(after.state.input_digest, before.state.input_digest)
        self.assertEqual(self._manifest_rows(store, after.data_commit), manifest)
        self.assertEqual(self._manifest_rows(store, after.metadata_commit), manifest)
        self.assertEqual(self._manifest_rows(store, before.metadata_commit), manifest)
        parent = store.sql_read(f"SELECT hashof({sql_quote(metadata + '~1')}) AS h")
        self.assertEqual(parent, [{"h": data}])

        result = queries.check(self.repo)["parity"]
        self.assertFalse(result["match"])
        self.assertTrue(result["inputs_match"])
        self.assertTrue(result["diagnostics_match"])
        self.assertEqual(result["direct_cite_tokens"], 1)
        self.assertEqual(result["graph_binding_rows"], 1)
        self.assertEqual(result["expected_binding_rows"], result["actual_binding_rows"])
        self.assertEqual(result["binding_mismatch_count"], 1)
        mismatch = result["binding_mismatches"][0]
        self.assertEqual(mismatch["expected"]["rev"], "abcdef1")
        self.assertEqual(mismatch["actual"]["rev"], "7654321")
        self.assertEqual(mismatch["expected"]["dst_node"], "code:acme/kb:src/a.py")
        self.assertEqual(mismatch["actual"]["dst_node"], "code:acme/kb:src/wrong.py")
        self.assertEqual(mismatch["expected"]["src_node"], "sig:deploy")
        self.assertEqual(mismatch["expected"]["line_selector"], "4-8")

    def test_origin_change_at_same_git_sha_forces_new_generation_and_preserves_old_manifest(self):
        first = sync.sync(self.repo)
        store = self._store()
        before = self._snapshot(store)
        original_manifest = self._manifest_rows(store, before.metadata_commit)
        self.assertEqual(sync.sync(self.repo)["status"], "up-to-date")
        self.assertEqual(self._snapshot(self._store()), before)
        self.run_git(self.repo, "remote", "set-url", "origin", "https://github.com/other/kb.git")
        status = queries.status(self.repo)
        self.assertEqual(status["kb_head"], self.sha)
        self.assertFalse(status["up_to_date"])
        stale = queries.check(self.repo)["parity"]
        self.assertFalse(stale["match"])
        self.assertFalse(stale["inputs_match"])
        self.assertEqual(stale["binding_mismatch_count"], 0, "old graph must use its captured origin")
        second = sync.sync(self.repo)
        self.assertEqual(second["status"], "synced")
        self.assertEqual(second["kb_sha"], first["kb_sha"])
        self.assertNotEqual(second["input_digest"], first["input_digest"])
        store = self._store()
        after = self._snapshot(store)
        self.assertNotEqual(after.data_commit, before.data_commit)
        self.assertNotEqual(after.metadata_commit, before.metadata_commit)
        self.assertEqual(self._manifest_rows(store, before.metadata_commit), original_manifest)
        self.assertEqual(after.inputs["repository_identity"], {
            "checkout_name": self.repo.name, "origin_url": "https://github.com/other/kb.git",
        })
        self.assertEqual(before.inputs["repository_identity"]["origin_url"], "https://github.com/acme/kb.git")
        rows = store.sql_read(f"SELECT dst_node FROM edges AS OF {sql_quote(after.data_commit.val)} WHERE rel='cites'")
        self.assertEqual(rows, [{"dst_node": "code:other/kb:src/a.py"}])
        self.assertTrue(queries.check(self.repo)["parity"]["match"])
        self.assertEqual(sync.sync(self.repo)["status"], "up-to-date")

    def test_installed_parser_source_change_at_same_sha_forces_sync(self):
        from kctx.citations import syntax

        first = sync.sync(self.repo)
        before = self._snapshot(self._store())
        # Relocate actual built-in grammar source with a harmless byte change.
        # Parsing is not mocked; only source acquisition sees an installed update.
        installed_parser = self.root / "installed-syntax.py"
        self.assertIsNotNone(syntax.__file__)
        installed_parser.write_bytes(
            Path(syntax.__file__).read_bytes() + b"\n# installed grammar source revision\n"
        )
        with patch.object(syntax, "__file__", str(installed_parser)):
            self.assertFalse(queries.status(self.repo)["up_to_date"])
            result = sync.sync(self.repo)
            self.assertEqual(result["status"], "synced")
            self.assertEqual(result["kb_sha"], first["kb_sha"])
            self.assertNotEqual(result["input_digest"], first["input_digest"])
            after = self._snapshot(self._store())
            self.assertNotEqual(
                before.inputs["source_hashes"]["kctx.citations.syntax"],
                after.inputs["source_hashes"]["kctx.citations.syntax"],
            )
            self.assertEqual(before.inputs["repository_identity"], after.inputs["repository_identity"])
            self.assertTrue(queries.check(self.repo)["parity"]["match"])
            self.assertEqual(sync.sync(self.repo)["status"], "up-to-date")

    def test_completed_snapshot_rejects_metadata_naming_a_nonparent_commit(self):
        sync.sync(self.repo)
        store = self._store()
        before = self._snapshot(store)
        # A native child of the metadata commit cannot keep naming the older
        # data commit as its direct parent, even if all counts/manifests agree.
        unrelated = store.commit("qualification: invalid extra metadata layer", allow_empty=True)
        store._run("branch", "-f", COMPLETED_BRANCH, unrelated)
        with self.assertRaises(KctxError) as error:
            completed_snapshot(store)
        self.assertEqual(error.exception.category, "malformed")
        self.assertIn("native data parent", str(error.exception))
        self.assertEqual(self._manifest_rows(store, before.metadata_commit),
                         self._manifest_rows(store, before.data_commit))

    def test_ambiguous_git_prefix_uses_real_published_native_mappings(self):
        # Seventeen distinct real Git commits guarantee a one-hex-digit collision.
        first_by_prefix = {}
        pair = None
        for index in range(17):
            sha = self.commit_file(self.repo, "collision.md", f"revision {index}\n", f"collision {index}")
            if sha[0] in first_by_prefix:
                pair = (first_by_prefix[sha[0]], sha)
                break
            first_by_prefix[sha[0]] = sha
        self.assertIsNotNone(pair)
        first_sha, second_sha = pair
        self.run_git(self.repo, "checkout", "--detach", first_sha)
        sync.sync(self.repo)
        first = self._snapshot(self._store())
        self.run_git(self.repo, "checkout", "--detach", second_sha)
        sync.sync(self.repo)
        second = self._snapshot(self._store())
        with self.assertRaises(KctxError) as error:
            queries.diff(first_sha[0], "HEAD", kb_root=self.repo)
        self.assertEqual(error.exception.category, "conflict")
        self.assertIn("ambiguous KB revision prefix", str(error.exception))
        exact = queries.diff(first_sha, second_sha, kb_root=self.repo)
        self.assertEqual(exact["dolt_ref_a"], first.data_commit.val)
        self.assertEqual(exact["dolt_ref_b"], second.data_commit.val)


if __name__ == "__main__":
    unittest.main()
