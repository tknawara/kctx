"""End-to-end extraction tests: a synthetic kb-shaped git repo, committed,
read back via `git archive` (graph.extract.read_tree_at_sha) and fed through
graph.extract.extract_graph -- the same path `kctx graph sync` uses.

Uses the built-in citation syntax parser and pydantic/structlog. Skips only
when the graph dependencies are unavailable in the ambient interpreter.
"""

import unittest

from _base import KctxTestCase

try:
    import pydantic  # noqa: F401
    import structlog  # noqa: F401

    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


def _skip_reason():
    if not HAVE_DEPS:
        return "pydantic/structlog not installed in ambient interpreter; run via `uv run`"
    return None


@unittest.skipUnless(_skip_reason() is None, _skip_reason() or "")
class ExtractGraphTest(KctxTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.make_git_repo("kb")


    def _write(self, rel_path, content):
        path = self.repo / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _commit(self, message="add fixtures"):
        self.run_git(self.repo, "add", "-A")
        self.run_git(self.repo, "commit", "-q", "-m", message)
        import subprocess

        return subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def _extract(self, sha):
        from kctx.graph.extract import extract_graph, read_tree_at_sha

        files = read_tree_at_sha(self.repo, sha)
        return extract_graph(files, sha, "2026-10-30T00:00:00Z", self.repo)

    def test_typed_signature_fixes_are_mentions_not_support(self):
        self._write(
            "signatures/repaired.md",
            "---\nid: repaired\nstatus: fixed\nfixed_at: 2026-01-01\n"
            "fix: [config/2026-01-01-repair, ev:project/fixing-pr, "
            "acme/widget@abcdef1234:src/fix.py:10-20, "
            "acme/widget@abcdef1234:src/fix.py:30]\n---\n",
        )
        graph = self._extract(self._commit())
        edges = [
            edge for edge in graph.edges.values()
            if edge.src_node.val == "sig:repaired" and edge.cite_kind is not None
        ]
        self.assertEqual(len(edges), 4)
        self.assertEqual({edge.rel for edge in edges}, {"mentions"})
        self.assertEqual(
            {(edge.dst_node.val, edge.cite_kind, edge.rev, edge.line_selector) for edge in edges},
            {
                ("proposal:config/2026-01-01-repair", "proposal", None, None),
                ("ev:project/fixing-pr", "ev", None, None),
                ("code:acme/widget:src/fix.py", "code", "abcdef1234", "10-20"),
                ("code:acme/widget:src/fix.py", "code", "abcdef1234", "30"),
            },
        )
        self.assertEqual(graph.stats.diagnostics, [])

    def test_malformed_signature_fix_diagnosed_without_losing_citations(self):
        self._write(
            "signatures/broken.md",
            "---\nid: broken\nfix: [acme/widget#7, TICKET 1234]\n---\n"
            "⟦cite kind=ticket id=OPS-1⟧\n",
        )
        graph = self._extract(self._commit())
        self.assertEqual(
            [(row.category, row.raw) for row in graph.stats.diagnostics],
            [("record-malformed", "acme/widget#7"), ("record-malformed", "TICKET 1234")],
        )
        self.assertFalse(any(node.kind == "pr" for node in graph.nodes.values()))
        self.assertTrue(any(edge.rel == "cites" and edge.dst_node.val == "ticket:OPS-1" for edge in graph.edges.values()))

    def test_asset_and_directional_relationship(self):
        self._write(
            "inventory/assets/service-foo.json",
            '{"id": "service-foo", "name": "Foo Service"}\n',
        )
        self._write(
            "inventory/assets/store-bar.json",
            '{"id": "store-bar", "name": "Bar Store"}\n',
        )
        self._write(
            "inventory/relationships/consumes__service-foo__store-bar.json",
            '{"from": "service-foo", "to": "store-bar", "type": "consumes", "status": "active"}\n',
        )
        sha = self._commit()
        b = self._extract(sha)
        self.assertIn("service-foo", {node.val for node in b.nodes})
        self.assertIn("store-bar", {node.val for node in b.nodes})
        rel_edges = [e for e in b.edges.values() if e.rel == "consumes"]
        self.assertEqual(len(rel_edges), 1)
        self.assertEqual(rel_edges[0].src_node.val, "service-foo")
        self.assertEqual(rel_edges[0].dst_node.val, "store-bar")
        # directionality: store-bar's own relationship file must not be
        # misread as an inbound dependency of service-foo (the uses() false
        # positive the prototype found) -- there is exactly one `consumes`
        # edge and its dst is store-bar, not service-foo.
        dst_nodes = {e.dst_node.val for e in rel_edges}
        self.assertEqual(dst_nodes, {"store-bar"})

    def test_cite_token_illus_is_flagged_and_identity_normalized(self):
        self._write(
            "signatures/some-sig.md",
            "---\n"
            "id: some-sig\n"
            "title: Some Signature\n"
            "---\n"
            "Real citation: ⟦cite kind=code repo=pbp/pbp-lua "
            'rev=abc1234567 path=foo.py span=deadbeefcafefeed seen=2026-10-30T00:00Z⟧\n'
            "Illustrative example: ⟦cite illus kind=code repo=pbp/pbp-lua "
            'rev=abc1234567 path=bar.py span=deadbeefcafefeed seen=2026-10-30T00:00Z⟧\n',
        )
        sha = self._commit()
        b = self._extract(sha)
        cite_edges = [e for e in b.edges.values() if e.src_node.val == "sig:some-sig" and e.rel == "cites"]
        self.assertEqual(len(cite_edges), 2)
        illus_flags = sorted(e.illus for e in cite_edges)
        self.assertEqual(illus_flags, [False, True])
        dst_nodes = {e.dst_node.val for e in cite_edges}
        self.assertEqual(dst_nodes, {"code:pbp/pbp-lua:foo.py", "code:pbp/pbp-lua:bar.py"})

    def test_mentions_use_id_boundary_not_substring(self):
        self._write(
            "inventory/assets/repo-pbp-lua.json",
            '{"id": "repo-pbp-lua", "name": "pbp-lua"}\n',
        )
        self._write(
            "inventory/assets/repo-pbp-lua-extra.json",
            '{"id": "repo-pbp-lua-extra", "name": "pbp-lua-extra"}\n',
        )
        self._write(
            "ktlo/2026/some-note.md",
            "---\ntitle: a ktlo note\n---\n"
            "This note mentions repo-pbp-lua directly, and separately "
            "repo-pbp-lua-extra as a different asset.\n",
        )
        sha = self._commit()
        b = self._extract(sha)
        doc_id = "doc:ktlo/2026/some-note.md"
        self.assertIn(doc_id, {node.val for node in b.nodes})
        mention_dsts = {e.dst_node.val for e in b.edges.values() if e.src_node.val == doc_id and e.rel == "mentions"}
        self.assertIn("repo-pbp-lua", mention_dsts)
        self.assertIn("repo-pbp-lua-extra", mention_dsts)

    def test_evidence_file_gets_its_own_node_and_is_scanned(self):
        self._write(
            "kb-knowledge-engine/evidence/2026-10-30-sample.md",
            "---\ntitle: Sample evidence\n---\nSome findings here.\n",
        )
        sha = self._commit()
        b = self._extract(sha)
        self.assertIn("ev:kb-knowledge-engine/2026-10-30-sample", {node.val for node in b.nodes})

    def test_fallback_doc_node_for_unrecognized_md_still_scans_cites(self):
        self._write(
            "kb-knowledge-engine/STATUS.md",
            "---\ntitle: status\n---\n"
            'See ⟦cite kind=ticket id=DRQS-12345 seen=2026-10-30T00:00Z⟧ for details.\n',
        )
        sha = self._commit()
        b = self._extract(sha)
        doc_id = "doc:kb-knowledge-engine/STATUS.md"
        self.assertIn(doc_id, {node.val for node in b.nodes})
        cite_edges = [e for e in b.edges.values() if e.src_node.val == doc_id and e.rel == "cites"]
        self.assertEqual(len(cite_edges), 1)
        self.assertEqual(cite_edges[0].dst_node.val, "ticket:DRQS-12345")

    def test_proposal_superseded_by_becomes_supersedes_edge(self):
        self._write(
            "proposals/decision/2026-01-01-old-one/proposal.md",
            "---\nid: decision/2026-01-01-old-one\ntitle: Old\nstatus: applied\n"
            "superseded_by: decision/2026-01-02-new-one\n---\nbody text\n",
        )
        sha = self._commit()
        b = self._extract(sha)
        sup_edges = [e for e in b.edges.values() if e.rel == "supersedes"]
        self.assertEqual(len(sup_edges), 1)
        self.assertEqual(sup_edges[0].src_node.val, "proposal:decision/2026-01-01-old-one")
        self.assertEqual(sup_edges[0].dst_node.val, "proposal:decision/2026-01-02-new-one")

    def test_two_cites_to_same_target_on_one_line_keep_separate_rows(self):
        self._write(
            "kb-knowledge-engine/NOTE.md",
            "---\ntitle: n\n---\n"
            "Twice: ⟦cite kind=ticket id=DRQS-9 seen=2026-10-30T00:00Z⟧ and "
            "⟦cite kind=ticket id=DRQS-9 seen=2026-10-30T00:00Z⟧\n",
        )
        b = self._extract(self._commit())
        rows = [e for e in b.edges.values() if e.rel == "cites" and e.dst_node.val == "ticket:DRQS-9"]
        self.assertEqual(len(rows), 2)

    def test_frontmatter_cites_are_scanned_and_kindless_tokens_itemized(self):
        self._write(
            "proposals/decision/2026-01-01-x/proposal.md",
            "---\nid: decision/2026-01-01-x\ntitle: X\nstatus: proposed\n"
            "references: [⟦cite kind=ticket id=DRQS-3 seen=2026-10-30T00:00Z⟧]\n---\n"
            "prose mentions a bare ⟦cite⟧ token with no fields\n",
        )
        b = self._extract(self._commit())
        self.assertIn("ticket:DRQS-3", {e.dst_node.val for e in b.edges.values()})
        self.assertEqual(len(b.stats.cite_tokens_dropped), 1)
        self.assertEqual(b.stats.cite_tokens_dropped[0]["reason"], "no kind= field")

    def test_no_cite_tokens_dropped_without_a_reason(self):
        self._write(
            "pbp-slm/notes/misc.md",
            "random note with no citations at all\n",
        )
        sha = self._commit()
        b = self._extract(sha)
        self.assertEqual(b.stats.cite_tokens_seen, 0)
        self.assertEqual(b.stats.cite_tokens_dropped, [])

    @staticmethod
    def _binding(edge):
        return (
            edge.src_node.val, edge.dst_node.val, edge.src_path, edge.src_line,
            edge.cite_kind, edge.rev, edge.blob_sha, edge.span,
            edge.line_selector, edge.raw, edge.seen, edge.state, edge.illus,
        )

    def test_golden_markdown_record_source_bindings(self):
        token = (
            "⟦cite kind=code repo=acme/core rev=abcdef012345 path=src/a.py "
            "blob=0123456789abcdef span=deadbeefcafefeed L=12-19 seen=2026-10-31⟧"
        )
        fixtures = [
            ("inventory/dossiers/a.md", "---\nasset: service-a\n---\n", "dossier:service-a", 4),
            ("signatures/s.md", "---\nid: s\n---\n", "sig:s", 4),
            ("investigations/i/README.md", "---\nid: i\n---\n", "inv:i", 4),
            ("proposals/p/proposal.md", "---\nid: p\n---\n", "proposal:p", 4),
            ("project/evidence/e.md", "# Evidence\n", "ev:project/e", 2),
            ("notes/n.md", "# Note\n", "doc:notes/n.md", 2),
        ]
        for path, prefix, _, _ in fixtures:
            self._write(path, prefix + token + " " + token + "\n")
        graph = self._extract(self._commit())
        for path, _, source, line in fixtures:
            with self.subTest(path=path):
                rows = [edge for edge in graph.edges.values() if edge.rel == "cites" and edge.src_path == path]
                expected = (
                    source, "code:acme/core:src/a.py", path, line, "code",
                    "abcdef012345", "0123456789abcdef", "deadbeefcafefeed",
                    "12-19",
                    "⟦cite kind=code repo=acme/core rev=abcdef012345 path=src/a.py "
                    "blob=0123456789abcdef span=deadbeefcafefeed L=12-19 seen=2026-10-31⟧",
                    "2026-10-31", None, False,
                )
                self.assertEqual([self._binding(edge) for edge in rows], [expected, expected])
                self.assertEqual(len({edge.edge_id for edge in rows}), 2)
        self.assertEqual(graph.stats.files_scanned, 6)
        self.assertEqual(graph.stats.cite_tokens_seen, 12)
        self.assertEqual(graph.stats.diagnostics, [])

    def test_golden_json_citations_preserve_source_spelling_and_lines(self):
        self._write(
            "inventory/assets/a.json",
            '{\n  "id": "service-a",\n  "note": '
            r'"⟦cite kind=code repo=acme/core rev=abcdef0 path=\"src/a b.py\" L=3-7 span=0123456789abcdef⟧"'
            "\n}\n",
        )
        self._write(
            "inventory/relationships/r.json",
            '{\n  "from": "service-a", "to": "store-b", "type": "uses",\n'
            '  "evidence": ["⟦cite kind=ticket id=OPS-7⟧", "⟦cite kind=ticket id=OPS-7⟧",\n'
            '    "acme/core@abcdef0:src/a.py:8-9", "acme/core@abcdef0:src/a.py:8-9"]\n}\n',
        )
        self._write(
            "notes/other.json",
            '{\n  "nested": ['
            r'"\ud83d\ude00 before \u27e6cite kind=code repo=acme/core\nrev=1234567 path=other.py L=2-5 span=fedcba9876543210\u27e7"'
            "]\n}\n",
        )
        graph = self._extract(self._commit())
        rows = [edge for edge in graph.edges.values() if edge.rel == "cites"]
        self.assertEqual(
            [self._binding(edge) for edge in rows],
            [
                (
                    "service-a", "code:acme/core:src/a b.py", "inventory/assets/a.json", 3,
                    "code", "abcdef0", None, "0123456789abcdef", "3-7",
                    r'⟦cite kind=code repo=acme/core rev=abcdef0 path=\"src/a b.py\" L=3-7 span=0123456789abcdef⟧',
                    "2026-10-30T00:00:00Z", None, False,
                ),
                *[(
                    "service-a", "ticket:OPS-7", "inventory/relationships/r.json", 3,
                    "ticket", None, None, None, None, "⟦cite kind=ticket id=OPS-7⟧",
                    "2026-10-30T00:00:00Z", None, False,
                )] * 2,
                *[(
                    "service-a", "code:acme/core:src/a.py", "inventory/relationships/r.json", 4,
                    "code", "abcdef0", None, None, "8-9", "acme/core@abcdef0:src/a.py:8-9",
                    "2026-10-30T00:00:00Z", None, False,
                )] * 2,
                (
                    "doc:notes/other.json", "code:acme/core:other.py", "notes/other.json", 2,
                    "code", "1234567", None, "fedcba9876543210", "2-5",
                    r"\u27e6cite kind=code repo=acme/core\nrev=1234567 path=other.py L=2-5 span=fedcba9876543210\u27e7",
                    "2026-10-30T00:00:00Z", None, False,
                ),
            ],
        )
        self.assertEqual(len({edge.edge_id for edge in rows}), 6)
        self.assertEqual(graph.stats.cite_tokens_seen, 4)
        self.assertEqual(graph.stats.diagnostics, [])

    def test_full_raw_tokens_and_durable_skip_diagnostics(self):
        long_token = "⟦cite kind=ticket id=OPS-9 detail=" + "x" * 800 + "⟧"
        dropped = "⟦cite illus detail=" + "y" * 800 + "⟧"
        self._write(
            "notes/raw.md",
            long_token + "\n" + dropped + "\n"
            "⟦cite kind=ticket id=ONE id=TWO⟧\n"
            "⟦cite kind=ticket id=unfinished",
        )
        graph = self._extract(self._commit())
        rows = [edge for edge in graph.edges.values() if edge.rel == "cites"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].raw, "⟦cite kind=ticket id=OPS-9 detail=" + "x" * 800 + "⟧")
        self.assertEqual(graph.stats.cite_tokens_seen, 4)
        self.assertEqual(graph.stats.cite_tokens_illus, 1)
        self.assertEqual(
            [(item.category, item.src_path, item.src_line, item.reason, item.raw, item.illus)
             for item in graph.stats.diagnostics],
            [
                ("citation-skip", "notes/raw.md", 2, "no kind= field",
                 "⟦cite illus detail=" + "y" * 800 + "⟧", True),
                ("citation-skip", "notes/raw.md", 3, "duplicate citation field 'id'",
                 "⟦cite kind=ticket id=ONE id=TWO⟧", False),
                ("citation-skip", "notes/raw.md", 4, "unterminated citation token",
                 "⟦cite kind=ticket id=unfinished", False),
            ],
        )
        self.assertEqual(graph.stats.cite_tokens_dropped[0], {
            "src_path": "notes/raw.md", "line": 2, "reason": "no kind= field",
            "illus": True, "raw": "⟦cite illus detail=" + "y" * 800 + "⟧",
        })
        graph.stats.cite_tokens_dropped.clear()
        self.assertEqual(len(graph.stats.diagnostics), 3)

    def test_malformed_json_records_diagnose_and_still_scan_tokens(self):
        fixtures = {
            "inventory/assets/bad.json": '{"id": 7, "note": "⟦cite kind=ticket id=OPS-1⟧"}',
            "inventory/assets/missing.json": '{"note": "⟦cite kind=ticket id=OPS-2⟧"}',
            "inventory/relationships/bad.json": '{"from": "a", "to": "b", "type": "uses", "evidence": 8, "note": "⟦cite kind=ticket id=OPS-3⟧"}',
            "notes/broken.json": '{\n "note": "⟦cite kind=ticket id=OPS-4⟧",\n}',
            "inventory/assets/array.json": '["⟦cite kind=ticket id=OPS-5⟧"]',
        }
        for path, text in fixtures.items():
            self._write(path, text)
        graph = self._extract(self._commit())
        self.assertEqual(
            sorted((edge.src_node.val, edge.dst_node.val, edge.src_line)
                   for edge in graph.edges.values() if edge.rel == "cites"),
            [
                ("doc:inventory/assets/array.json", "ticket:OPS-5", 1),
                ("doc:inventory/assets/bad.json", "ticket:OPS-1", 1),
                ("doc:inventory/assets/missing.json", "ticket:OPS-2", 1),
                ("doc:inventory/relationships/bad.json", "ticket:OPS-3", 1),
                ("doc:notes/broken.json", "ticket:OPS-4", 2),
            ],
        )
        diagnostics = {item.src_path: item for item in graph.stats.diagnostics}
        self.assertEqual(set(diagnostics), set(fixtures))
        for path, item in diagnostics.items():
            self.assertEqual(item.category, "record-malformed")
            self.assertEqual(item.raw, fixtures[path])
            self.assertTrue(item.reason)
        self.assertEqual(diagnostics["inventory/assets/bad.json"].reason, "asset.id must be a string")
        self.assertEqual(diagnostics["inventory/assets/missing.json"].reason, "asset.id is required and must not be empty")
        self.assertEqual(diagnostics["inventory/relationships/bad.json"].reason, "relationship.evidence must be an array")
        self.assertEqual(diagnostics["notes/broken.json"].src_line, 3)
        self.assertEqual(graph.stats.files_scanned, 5)
        self.assertEqual(graph.stats.cite_tokens_seen, 5)
        self.assertEqual(graph.stats.cite_tokens_dropped, [])

    def test_frozen_repository_identity_and_unresolved_alias_diagnostic(self):
        from kctx.graph.extract import extract_graph
        from kctx.graph.identity import RepositoryIdentity

        self.run_git(self.repo, "remote", "add", "origin", "https://github.com/live/changed.git")
        graph = extract_graph(
            {"notes.md": "⟦cite kind=code repo=kb rev=abcdef0 path=a.py⟧\n"
                         "⟦cite kind=code repo=unknown rev=abcdef0 path=b.py⟧"},
            "abcdef0", "2026-10-31", self.repo,
            repository_identity=RepositoryIdentity(checkout_name="kb", origin_url="https://github.com/frozen/original.git"),
        )
        self.assertEqual(
            [edge.dst_node.val for edge in graph.edges.values() if edge.rel == "cites"],
            ["code:frozen/original:a.py", "code:unknown:b.py"],
        )
        self.assertEqual(graph.stats.unresolved_repo_aliases, ["unknown"])
        self.assertEqual(
            [(item.category, item.src_path, item.src_line, item.raw) for item in graph.stats.diagnostics],
            [("unresolved-repo", "notes.md", 2, "⟦cite kind=code repo=unknown rev=abcdef0 path=b.py⟧")],
        )

    def test_extraction_limits_fail_explicitly_without_truncation(self):
        from unittest.mock import patch
        from kctx.errors import KctxError
        from kctx.graph.extract import GraphBuilder, extract_graph

        for constant, limit, files, message in [
            ("MAX_SOURCE_FILES", 1, {"a.md": "", "b.md": ""}, "file count"),
            ("MAX_FILE_BYTES", 2, {"a.md": "abc"}, "source bytes"),
            ("MAX_SOURCE_BYTES", 3, {"a.md": "ab", "b.md": "cd"}, "aggregate source bytes"),
            ("MAX_MENTION_WORK", 1, {"a.md": "a", "b.md": "b"}, "mention candidate/document"),
            ("MAX_DIAGNOSTICS", 1, {"a.md": "⟦cite⟧ ⟦cite⟧"}, "diagnostic count"),
            ("MAX_DIAGNOSTICS", 1, {"a.json": "{", "b.json": "{"}, "diagnostic count"),
            ("MAX_DIAGNOSTICS", 1, {"a.md": "⟦cite kind=code repo=unknown path=a.py⟧ ⟦cite kind=code repo=other path=b.py⟧"}, "diagnostic count"),
        ]:
            with self.subTest(constant=constant), patch("kctx.graph.extract." + constant, limit):
                with self.assertRaisesRegex(KctxError, message):
                    extract_graph(files, "abcdef0", "2026-10-31", self.repo)
        with patch("kctx.graph.extract.MAX_GRAPH_NODES", 1):
            graph = GraphBuilder("abcdef0", "2026-10-31")
            graph.add_node("a", "asset")
            with self.assertRaisesRegex(KctxError, "node count"):
                graph.add_node("b", "asset")
        with patch("kctx.graph.extract.MAX_GRAPH_EDGES", 1):
            graph = GraphBuilder("abcdef0", "2026-10-31")
            graph.add_edge("a", "b", "uses")
            with self.assertRaisesRegex(KctxError, "edge count"):
                graph.add_edge("a", "c", "uses")


    def test_ambiguous_frontmatter_diagnoses_and_retains_citations(self):
        self._write(
            "signatures/ambiguous.md",
            "---\nid: first\nid: second\n---\n⟦cite kind=ticket id=OPS-8⟧\n",
        )
        graph = self._extract(self._commit())
        self.assertEqual(
            [(edge.src_node.val, edge.dst_node.val, edge.src_line)
             for edge in graph.edges.values() if edge.rel == "cites"],
            [("doc:signatures/ambiguous.md", "ticket:OPS-8", 5)],
        )
        self.assertEqual(len(graph.stats.diagnostics), 1)
        diagnostic = graph.stats.diagnostics[0]
        self.assertEqual(diagnostic.category, "record-malformed")
        self.assertEqual(diagnostic.src_path, "signatures/ambiguous.md")
        self.assertIn("duplicate", diagnostic.reason.lower())

    def test_duplicate_record_identities_refuse_conflicting_home_paths(self):
        from kctx.errors import KctxError
        from kctx.graph.extract import extract_graph

        for files in [
            {"inventory/assets/a.json": '{"id":"same"}',
             "inventory/assets/b.json": '{"id":"same"}'},
            {"signatures/a.md": "---\nid: same\n---\n",
             "signatures/b.md": "---\nid: same\n---\n"},
            {"proposals/a/proposal.md": "---\nid: same\n---\n",
             "proposals/b/proposal.md": "---\nid: same\n---\n"},
        ]:
            with self.subTest(paths=tuple(files)):
                with self.assertRaisesRegex(KctxError, "ambiguous graph identity"):
                    extract_graph(files, "abcdef0", "2026-10-31", self.repo)

    def test_record_node_upgrades_inferred_reference_home(self):
        from kctx.graph.extract import GraphBuilder
        from kctx.graph.models import GraphNodeId

        graph = GraphBuilder("abcdef0", "2026-10-31")
        graph.add_node("sig:later", "sig")
        graph.add_node("sig:later", "sig", "Actual title", "signatures/later.md")
        node = graph.nodes[GraphNodeId("sig:later")]
        self.assertEqual((node.label, node.home_path), ("Actual title", "signatures/later.md"))


    def test_duplicate_json_fields_are_diagnosed_without_losing_tokens(self):
        self._write(
            "inventory/assets/duplicate.json",
            '{"id": "first", "id": "second", "note": "⟦cite kind=ticket id=OPS-6⟧"}',
        )
        graph = self._extract(self._commit())
        self.assertEqual(
            [(edge.src_node.val, edge.dst_node.val, edge.src_line)
             for edge in graph.edges.values() if edge.rel == "cites"],
            [("doc:inventory/assets/duplicate.json", "ticket:OPS-6", 1)],
        )
        self.assertEqual(
            [(item.category, item.src_path, item.reason) for item in graph.stats.diagnostics],
            [("record-malformed", "inventory/assets/duplicate.json", "duplicate JSON field 'id'")],
        )

    def test_golden_repeated_proposal_short_references(self):
        self._write(
            "proposals/p/proposal.md",
            "---\nid: p\nstatus: proposed\n"
            "references: [acme/core@abcdef0:src/a.py:2-8, acme/core@abcdef0:src/a.py:2-8]\n"
            "---\n",
        )
        graph = self._extract(self._commit())
        rows = [edge for edge in graph.edges.values() if edge.rel == "references"]
        self.assertEqual(
            [self._binding(edge) for edge in rows],
            [(
                "proposal:p", "code:acme/core:src/a.py", "proposals/p/proposal.md", 4,
                "code", "abcdef0", None, None, "2-8", "acme/core@abcdef0:src/a.py:2-8",
                "2026-10-30T00:00:00Z", "proposed", False,
            )] * 2,
        )
        self.assertEqual(len({edge.edge_id for edge in rows}), 2)


    def test_golden_relationship_locators_use_actual_top_level_evidence_field(self):
        self._write(
            "inventory/relationships/position.json",
            '{\n'
            '  "from": "service-a", "to": "store-b", "type": "uses",\n'
            '  "notes": "evidence",\n'
            '  "unrelated": "acme/core@abcdef0:src/a.py:8-9",\n'
            '  "nested": {"evidence": ["acme/core@abcdef0:src/a.py:8-9"]},\n'
            r'  "\u0065vidence": [' + "\n"
            r'    "acme\/core@abcdef0:src/a.py:8-9",' + "\n"
            '    "acme/core@abcdef0:src/a.py:8-9"]\n'
            '}\n',
        )
        graph = self._extract(self._commit())
        rows = [edge for edge in graph.edges.values() if edge.rel == "cites"]
        self.assertEqual(
            [self._binding(edge) for edge in rows],
            [
                (
                    "service-a", "code:acme/core:src/a.py",
                    "inventory/relationships/position.json", 7,
                    "code", "abcdef0", None, None, "8-9",
                    r"acme\/core@abcdef0:src/a.py:8-9",
                    "2026-10-30T00:00:00Z", None, False,
                ),
                (
                    "service-a", "code:acme/core:src/a.py",
                    "inventory/relationships/position.json", 8,
                    "code", "abcdef0", None, None, "8-9",
                    "acme/core@abcdef0:src/a.py:8-9",
                    "2026-10-30T00:00:00Z", None, False,
                ),
            ],
        )
        self.assertEqual(len({edge.edge_id for edge in rows}), 2)
        self.assertEqual(graph.stats.diagnostics, [])


if __name__ == "__main__":
    unittest.main()
