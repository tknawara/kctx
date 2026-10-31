"""Graph identity normalization through the built-in citation Git adapter."""

import unittest

from _base import KctxTestCase
from kctx.graph.identity import canonical_repo, capture_repository_identity


class CanonicalRepoTest(KctxTestCase):
    def setUp(self):
        super().setUp()
        self.kb_root = self.make_git_repo("kb")

    def _identity(self):
        return capture_repository_identity(self.kb_root)

    def test_url_field_wins(self):
        got = canonical_repo("whatever", "bbgithub:tnawara/scratch.git", self._identity())
        self.assertEqual(got, "tnawara/scratch")

    def test_org_repo_shaped_field_is_already_canonical(self):
        self.assertEqual(canonical_repo("pbp/pbp-lua", None, self._identity()), "pbp/pbp-lua")

    def test_bare_alias_matching_checkout_name_resolves_via_origin(self):
        self.run_git(self.kb_root, "remote", "add", "origin", "bbgithub:tnawara/kb")
        self.assertEqual(canonical_repo(self.kb_root.name, None, self._identity()), "tnawara/kb")

    def test_repo_alias_and_canonical_repo_normalize_to_one_id(self):
        self.run_git(self.kb_root, "remote", "add", "origin", "bbgithub:tnawara/kb")
        self.assertEqual(canonical_repo(self.kb_root.name, None, self._identity()), canonical_repo("tnawara/kb", None, self._identity()))

    def test_unresolvable_bare_alias_returned_unchanged(self):
        self.assertEqual(canonical_repo("not-this-checkout", None, self._identity()), "not-this-checkout")
        self.assertEqual(canonical_repo(self.kb_root.name, None, self._identity()), self.kb_root.name)

    def test_no_repo_field_returns_empty_string(self):
        self.assertEqual(canonical_repo(None, None, self._identity()), "")

    def test_url_spellings_share_one_identity(self):
        for url in ["git@github.com:tnawara/kb.git", "https://github.com/tnawara/kb.git"]:
            with self.subTest(url=url):
                self.assertEqual(canonical_repo("alias", url, self._identity()), "tnawara/kb")

    def test_captured_identity_does_not_follow_later_remote_edits(self):
        self.run_git(self.kb_root, "remote", "add", "origin", "bbgithub:tnawara/kb")
        identity = self._identity()
        self.run_git(self.kb_root, "remote", "set-url", "origin", "bbgithub:other/kb")
        self.assertEqual(canonical_repo(self.kb_root.name, None, identity), "tnawara/kb")


if __name__ == "__main__":
    unittest.main()
