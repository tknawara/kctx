"""graph.identity has no third-party deps and doesn't need the real cite.py
-- a tiny stub mirroring its three relevant helpers is enough to pin the
normalization rules down (the real cite.py's own regex/logic is exercised
by tests/test_graph_extract.py, which does load the real module)."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kctx.graph.identity import canonical_repo


class _StubCite:
    ORG_REPO_RE = __import__("re").compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

    def __init__(self, origin_url=None):
        self._origin_url = origin_url

    def get_origin_url(self, path):
        return self._origin_url

    @staticmethod
    def _repo_field_from_url(url):
        if not url:
            return None
        import re

        m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", url)
        return "/".join(m.groups()) if m else None


class _OldStubCite(_StubCite):
    """A cite.py missing `_repo_field_from_url` -- the gap actually found on
    this laptop's deployed ~/.claude/skills/grounding/cite.py during live
    verification: it only had the narrower `_org_repo_from_url`."""

    _repo_field_from_url = None

    @staticmethod
    def _org_repo_from_url(url):
        import re

        m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", url)
        return m.groups() if m else None


class CanonicalRepoTest(unittest.TestCase):
    def setUp(self):
        self.kb_root = Path("/home/x/workspace/kb")

    def test_url_field_wins(self):
        cite_mod = _StubCite()
        got = canonical_repo("whatever", "bbgithub:tnawara/scratch.git", self.kb_root, cite_mod)
        self.assertEqual(got, "tnawara/scratch")

    def test_org_repo_shaped_field_is_already_canonical(self):
        cite_mod = _StubCite()
        got = canonical_repo("pbp/pbp-lua", None, self.kb_root, cite_mod)
        self.assertEqual(got, "pbp/pbp-lua")

    def test_bare_alias_matching_checkout_name_resolves_via_origin(self):
        cite_mod = _StubCite(origin_url="bbgithub:tnawara/kb")
        got = canonical_repo("kb", None, self.kb_root, cite_mod)
        self.assertEqual(got, "tnawara/kb")

    def test_repo_kb_and_repo_tnawara_kb_normalize_to_one_id(self):
        cite_mod = _StubCite(origin_url="bbgithub:tnawara/kb")
        a = canonical_repo("kb", None, self.kb_root, cite_mod)
        b = canonical_repo("tnawara/kb", None, self.kb_root, cite_mod)
        self.assertEqual(a, b)

    def test_unresolvable_bare_alias_returned_unchanged(self):
        cite_mod = _StubCite(origin_url=None)
        got = canonical_repo("not-this-checkout", None, self.kb_root, cite_mod)
        self.assertEqual(got, "not-this-checkout")

    def test_no_repo_field_returns_empty_string(self):
        cite_mod = _StubCite()
        self.assertEqual(canonical_repo(None, None, self.kb_root, cite_mod), "")

    def test_falls_back_to_org_repo_from_url_on_an_older_cite_module(self):
        cite_mod = _OldStubCite(origin_url="bbgithub:tnawara/kb")
        got = canonical_repo("kb", None, self.kb_root, cite_mod)
        self.assertEqual(got, "tnawara/kb")

    def test_url_field_falls_back_too_on_an_older_cite_module(self):
        cite_mod = _OldStubCite()
        got = canonical_repo("whatever", "bbgithub:tnawara/scratch.git", self.kb_root, cite_mod)
        self.assertEqual(got, "tnawara/scratch")


if __name__ == "__main__":
    unittest.main()
