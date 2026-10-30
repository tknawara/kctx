"""Covers the system-dossiers proposal's gates G1-G3 (record type, context
integration, stale scoping) and G7 (admit reaches dossiers). G4/G5/G6 are the
pilot-content/retirement/docs gates, not exercised by unit tests.
proposals/config/2026-10-26-system-dossiers-.../proposal.md."""

import json
from pathlib import Path

from _base import KctxTestCase, dotfiles_cite_available, use_dotfiles_cite

import admit
import dossiers
import inventory
import nav
import validate as validate_mod
from errors import KctxError


class DossierRecordTest(KctxTestCase):
    """G1: dossier record type is valid and enforced."""

    def test_new_scaffolds_five_headings_and_fails_without_a_matching_asset(self):
        with self.assertRaises(KctxError):
            dossiers.new(self.root, "repo-nope")

        inventory.asset_add(
            root=self.root, kind="repo", name="widget", id="repo-widget"
        )
        res = dossiers.new(self.root, "repo-widget")
        parsed = dossiers.parse(Path(res["path"]).read_text(encoding="utf-8"))
        self.assertEqual(
            [h for h in dossiers.HEADINGS if h in parsed["body"]], dossiers.HEADINGS
        )

    def test_new_refuses_when_dossier_already_exists(self):
        inventory.asset_add(
            root=self.root, kind="repo", name="widget", id="repo-widget"
        )
        dossiers.new(self.root, "repo-widget")
        with self.assertRaises(KctxError):
            dossiers.new(self.root, "repo-widget")

    def test_validate_fails_on_missing_asset_and_missing_heading_passes_on_scaffold(
        self,
    ):
        inventory.asset_add(
            root=self.root, kind="repo", name="widget", id="repo-widget"
        )
        dossiers.new(self.root, "repo-widget")
        result = validate_mod.validate(self.root)
        self.assertTrue(result["ok"], result["problems"])

        orphan = dossiers.dossier_path(self.root, "repo-ghost")
        orphan.write_text(
            "---\nasset: repo-ghost\nupdated: 2026-01-01\n---\n\n## Purpose\n\nx\n",
            encoding="utf-8",
        )
        result2 = validate_mod.validate(self.root)
        self.assertFalse(result2["ok"])
        self.assertTrue(any("repo-ghost" in p["message"] for p in result2["problems"]))
        orphan.unlink()

        incomplete = dossiers.dossier_path(self.root, "repo-widget")
        incomplete.write_text(
            "---\nasset: repo-widget\nupdated: 2026-01-01\n---\n\n"
            "## Purpose\n\nonly one heading\n",
            encoding="utf-8",
        )
        result3 = validate_mod.validate(self.root)
        self.assertFalse(result3["ok"])
        self.assertTrue(
            any("missing heading" in p["message"] for p in result3["problems"])
        )

    def test_archive_requires_retired_lifecycle_unless_forced(self):
        inventory.asset_add(
            root=self.root, kind="repo", name="widget", id="repo-widget"
        )
        dossiers.new(self.root, "repo-widget")
        with self.assertRaises(KctxError):
            dossiers.archive(self.root, "repo-widget")
        res = dossiers.archive(self.root, "repo-widget", force=True)
        self.assertTrue(res["path"].endswith(str(Path("archive") / "repo-widget.md")))
        self.assertFalse(dossiers.dossier_path(self.root, "repo-widget").exists())


class DossierContextTest(KctxTestCase):
    """G2: context pack surfaces the dossier with its citation status."""

    def test_context_includes_dossier_path_and_headings_asset_count_unchanged(self):
        inventory.asset_add(
            root=self.root, kind="repo", name="widget", id="repo-widget"
        )
        dossiers.new(self.root, "repo-widget")

        before_count = len(inventory.load_all_assets(self.root))
        ctx = nav.context(self.root, "repo-widget")
        self.assertIsNotNone(ctx["dossier"])
        self.assertTrue(ctx["dossier"]["path"].endswith("repo-widget.md"))
        self.assertEqual(ctx["dossier"]["headings"], dossiers.HEADINGS)
        after_count = len(inventory.load_all_assets(self.root))
        self.assertEqual(before_count, after_count)

    def test_context_has_no_dossier_when_none_exists(self):
        inventory.asset_add(
            root=self.root, kind="repo", name="widget", id="repo-widget"
        )
        ctx = nav.context(self.root, "repo-widget")
        self.assertIsNone(ctx["dossier"])


_DOSSIER_WITH_EXPIRED_CLAIM = (
    "---\nasset: repo-widget\nupdated: 2026-01-01\n---\n\n"
    "## Purpose\n\n"
    '- a claim ⟦cite kind=doc url="https://example.invalid/x" '
    "section=1 q=why seen=2020-01-01T00:00Z ttl=1d⟧\n\n"
    "## Interfaces\n\n## Main flows\n\n## Config & BREGs\n\n## Gotchas\n"
)


class DossierStaleScopingTest(KctxTestCase):
    """G3: unused dossiers don't flood the drain nag."""

    def test_dossier_for_inactive_asset_excluded_then_included_once_active(self):
        if not dotfiles_cite_available():
            self.skipTest("grounding cite.py not found in this environment")
        with use_dotfiles_cite():
            inventory.asset_add(
                root=self.root, kind="repo", name="widget", id="repo-widget"
            )
            dossiers.new(self.root, "repo-widget")
            path = dossiers.dossier_path(self.root, "repo-widget")
            path.write_text(_DOSSIER_WITH_EXPIRED_CLAIM, encoding="utf-8")

            result = nav.stale(self.root, offline=True)
            files_hit = {e["file"] for e in result["citations"]["entries"]}
            self.assertNotIn(str(path), files_hit)

            active = self.root / "active-project"
            active.mkdir()
            (active / "STATUS.md").write_text(
                "updated: 2026-01-01\nphase: active\n", encoding="utf-8"
            )
            asset_path = inventory.assets_dir(self.root) / "repo-widget.json"
            data = json.loads(asset_path.read_text(encoding="utf-8"))
            data["projects"] = ["active-project"]
            asset_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

            result2 = nav.stale(self.root, offline=True)
            files_hit2 = {e["file"] for e in result2["citations"]["entries"]}
            self.assertIn(str(path), files_hit2)

    def test_context_on_the_same_dossier_still_reports_its_stale_citation(self):
        if not dotfiles_cite_available():
            self.skipTest("grounding cite.py not found in this environment")
        with use_dotfiles_cite():
            inventory.asset_add(
                root=self.root, kind="repo", name="widget", id="repo-widget"
            )
            dossiers.new(self.root, "repo-widget")
            dossiers.dossier_path(self.root, "repo-widget").write_text(
                _DOSSIER_WITH_EXPIRED_CLAIM, encoding="utf-8"
            )
            ctx = nav.context(self.root, "repo-widget")
            self.assertTrue(ctx["freshness"]["citations"]["available"])
            statuses = {r["status"] for r in ctx["freshness"]["citations"]["results"]}
            self.assertIn("expired", statuses)


class DossierAdmitReachTest(KctxTestCase):
    """G7: admit reaches dossiers."""

    def test_admit_marks_a_dossier_citation_on_the_touched_path(self):
        if not dotfiles_cite_available():
            self.skipTest("grounding cite.py not found in this environment")
        with self.cache_backed_repo("acme", "widget") as remote:
            sha0 = self.commit_file(remote, "file1.py", "print('v0')\n", "init")

            inventory.asset_add(
                root=self.root, kind="repo", name="widget", id="repo-widget"
            )
            dossiers.new(self.root, "repo-widget")
            path = dossiers.dossier_path(self.root, "repo-widget")

            cite_mod = admit.load_cite_module()
            line = cite_mod.make_code("acme/widget", "file1.py", "1-1", rev=sha0)[
                "line"
            ]
            path.write_text(
                "---\nasset: repo-widget\nupdated: 2026-01-01\n---\n\n"
                f"## Purpose\n\n- a claim. {line}\n\n"
                "## Interfaces\n\n## Main flows\n\n## Config & BREGs\n\n## Gotchas\n",
                encoding="utf-8",
            )

            admit.save_cursor(self.root, "acme", "widget", sha0)
            self.commit_file(remote, "file1.py", "print('v1')\n", "change")

            res = admit.admit_repo(self.root, "acme/widget")
            touched = {
                Path(t["file"]).name for t in res["code_citations"]["touched_files"]
            }
            self.assertIn("repo-widget.md", touched)
