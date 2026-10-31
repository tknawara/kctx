"""graph.cite_loader has no third-party deps -- runs unconditionally."""

import unittest
from pathlib import Path
import sys

from _base import KctxTestCase, no_cite_available, set_config, clear_config

# after _base: it puts the repo root on sys.path, where the kctx.py entry
# script would otherwise shadow the kctx package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from errors import KctxError
from kctx.graph import cite_loader


class LocateCitePyTest(KctxTestCase):
    def setUp(self):
        super().setUp()
        self._saved = {
            k: __import__("os").environ.get(k)
            for k in ("CLAUDE_CONFIG_DIR",)
        }
        clear_config("cite_py")
        cite_loader.reset_cache()

    def tearDown(self):
        import os

        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cite_loader.reset_cache()
        super().tearDown()

    def test_config_override_points_at_a_file(self):
        stub = self.root / "cite_stub.py"
        stub.write_text("MARKER = 'stub-cite'\n", encoding="utf-8")
        set_config(cite_py=str(stub))
        self.assertEqual(cite_loader.locate_cite_py(), stub)

    def test_config_override_missing_file_raises(self):
        set_config(cite_py=str(self.root / "does-not-exist.py"))
        with self.assertRaises(KctxError):
            cite_loader.locate_cite_py()

    def test_claude_config_dir_candidate(self):
        import os

        clear_config("cite_py")
        config_dir = self.root / "_config"
        skill_dir = config_dir / "skills" / "grounding"
        skill_dir.mkdir(parents=True)
        (skill_dir / "cite.py").write_text("MARKER = 'from-config-dir'\n", encoding="utf-8")
        os.environ["CLAUDE_CONFIG_DIR"] = str(config_dir)
        self.assertEqual(cite_loader.locate_cite_py(), skill_dir / "cite.py")

    def test_nothing_found_raises_not_found(self):
        import os

        clear_config("cite_py")
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        with no_cite_available():
            with self.assertRaises(KctxError) as cm:
                cite_loader.locate_cite_py()
            self.assertEqual(cm.exception.category, "not-found")

    def test_load_cite_module_executes_and_caches(self):
        import os

        stub = self.root / "cite_stub2.py"
        stub.write_text("MARKER = 'loaded-once'\n", encoding="utf-8")
        set_config(cite_py=str(stub))
        mod1 = cite_loader.load_cite_module()
        self.assertEqual(mod1.MARKER, "loaded-once")
        stub.write_text("MARKER = 'changed'\n", encoding="utf-8")
        mod2 = cite_loader.load_cite_module()
        self.assertIs(mod1, mod2)
        self.assertEqual(mod2.MARKER, "loaded-once")


if __name__ == "__main__":
    unittest.main()
