"""End-to-end extraction tests: a synthetic kb-shaped git repo, committed,
read back via `git archive` (graph.extract.read_tree_at_sha) and fed through
graph.extract.extract_graph -- the same path `kctx graph sync` uses.

Needs pydantic/structlog (graph.models/graph.observability) and the real
cite.py (reused, not reimplemented -- see tests/_base.py's
dotfiles_cite_available()/use_dotfiles_cite()). Skips cleanly when either is
unavailable in the ambient interpreter.
"""

import os
import unittest

from _base import KctxTestCase, dotfiles_cite_available, use_dotfiles_cite

try:
    import pydantic  # noqa: F401
    import structlog  # noqa: F401

    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


def _skip_reason():
    if not HAVE_DEPS:
        return "pydantic/structlog not installed in ambient interpreter; run via `uv run`"
    if not dotfiles_cite_available():
        return "dotfiles checkout's cite.py not available"
    return None


@unittest.skipUnless(_skip_reason() is None, _skip_reason() or "")
class ExtractGraphTest(KctxTestCase):
    def setUp(self):
        super().setUp()
        self._cite_ctx = use_dotfiles_cite()
        self._cite_ctx.__enter__()
        from graph import cite_loader

        cite_loader.reset_cache()
        os.environ.pop("KCTX_CITE_PY", None)
        self.repo = self.make_git_repo("kb")

    def tearDown(self):
        from graph import cite_loader

        cite_loader.reset_cache()
        self._cite_ctx.__exit__(None, None, None)
        super().tearDown()

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
        from graph.extract import extract_graph, read_tree_at_sha

        files = read_tree_at_sha(self.repo, sha)
        return extract_graph(files, sha, "2026-10-30T00:00:00Z", self.repo)

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
        self.assertIn("service-foo", b.nodes)
        self.assertIn("store-bar", b.nodes)
        rel_edges = [e for e in b.edges.values() if e.rel == "consumes"]
        self.assertEqual(len(rel_edges), 1)
        self.assertEqual(rel_edges[0].src_node, "service-foo")
        self.assertEqual(rel_edges[0].dst_node, "store-bar")
        # directionality: store-bar's own relationship file must not be
        # misread as an inbound dependency of service-foo (the uses() false
        # positive the prototype found) -- there is exactly one `consumes`
        # edge and its dst is store-bar, not service-foo.
        dst_nodes = {e.dst_node for e in rel_edges}
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
        cite_edges = [e for e in b.edges.values() if e.src_node == "sig:some-sig" and e.rel == "cites"]
        self.assertEqual(len(cite_edges), 2)
        illus_flags = sorted(e.illus for e in cite_edges)
        self.assertEqual(illus_flags, [False, True])
        dst_nodes = {e.dst_node for e in cite_edges}
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
        self.assertIn(doc_id, b.nodes)
        mention_dsts = {e.dst_node for e in b.edges.values() if e.src_node == doc_id and e.rel == "mentions"}
        self.assertIn("repo-pbp-lua", mention_dsts)
        self.assertIn("repo-pbp-lua-extra", mention_dsts)

    def test_evidence_file_gets_its_own_node_and_is_scanned(self):
        self._write(
            "kb-knowledge-engine/evidence/2026-10-30-sample.md",
            "---\ntitle: Sample evidence\n---\nSome findings here.\n",
        )
        sha = self._commit()
        b = self._extract(sha)
        self.assertIn("ev:kb-knowledge-engine/2026-10-30-sample", b.nodes)

    def test_fallback_doc_node_for_unrecognized_md_still_scans_cites(self):
        self._write(
            "kb-knowledge-engine/STATUS.md",
            "---\ntitle: status\n---\n"
            'See ⟦cite kind=ticket id=DRQS-12345 seen=2026-10-30T00:00Z⟧ for details.\n',
        )
        sha = self._commit()
        b = self._extract(sha)
        doc_id = "doc:kb-knowledge-engine/STATUS.md"
        self.assertIn(doc_id, b.nodes)
        cite_edges = [e for e in b.edges.values() if e.src_node == doc_id and e.rel == "cites"]
        self.assertEqual(len(cite_edges), 1)
        self.assertEqual(cite_edges[0].dst_node, "ticket:DRQS-12345")

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
        self.assertEqual(sup_edges[0].src_node, "proposal:decision/2026-01-01-old-one")
        self.assertEqual(sup_edges[0].dst_node, "proposal:decision/2026-01-02-new-one")

    def test_two_cites_to_same_target_on_one_line_keep_separate_rows(self):
        self._write(
            "kb-knowledge-engine/NOTE.md",
            "---\ntitle: n\n---\n"
            "Twice: ⟦cite kind=ticket id=DRQS-9 seen=2026-10-30T00:00Z⟧ and "
            "⟦cite kind=ticket id=DRQS-9 seen=2026-10-30T00:00Z⟧\n",
        )
        b = self._extract(self._commit())
        rows = [e for e in b.edges.values() if e.rel == "cites" and e.dst_node == "ticket:DRQS-9"]
        self.assertEqual(len(rows), 2)

    def test_frontmatter_cites_are_scanned_and_kindless_tokens_itemized(self):
        self._write(
            "proposals/decision/2026-01-01-x/proposal.md",
            "---\nid: decision/2026-01-01-x\ntitle: X\nstatus: proposed\n"
            "references: [⟦cite kind=ticket id=DRQS-3 seen=2026-10-30T00:00Z⟧]\n---\n"
            "prose mentions a bare ⟦cite⟧ token with no fields\n",
        )
        b = self._extract(self._commit())
        self.assertIn("ticket:DRQS-3", {e.dst_node for e in b.edges.values()})
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


if __name__ == "__main__":
    unittest.main()
