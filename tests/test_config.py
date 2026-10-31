"""config.toml fixtures: the single configuration surface (docs/kctx/config.md)."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from errors import KctxError  # noqa: E402
from kctx.config import Config, config_path, write_config  # noqa: E402


def _isolated_env(test):
    def wrapper(self):
        saved = {k: os.environ.get(k) for k in ("KCTX_CONFIG", "XDG_CONFIG_HOME")}
        for k in saved:
            os.environ.pop(k, None)
        try:
            test(self)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    return wrapper


class ConfigLoadTests(unittest.TestCase):
    def _write(self, tmp: Path, text: str) -> Path:
        p = tmp / "config.toml"
        p.write_text(text, encoding="utf-8")
        os.environ["KCTX_CONFIG"] = str(p)
        return p

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._saved = os.environ.get("KCTX_CONFIG")

    def tearDown(self):
        self._tmp.cleanup()
        if self._saved is None:
            os.environ.pop("KCTX_CONFIG", None)
        else:
            os.environ["KCTX_CONFIG"] = self._saved

    def test_empty_config_is_all_none(self):
        self._write(self.tmp, "")
        cfg = Config.load()
        self.assertIsNone(cfg.root)
        # source points at the (empty but existing) file
        self.assertEqual(cfg.source, Path(os.environ['KCTX_CONFIG']))

    def test_all_keys_parse_to_paths(self):
        self._write(
            self.tmp,
            'root = "/kb"\ncite_py = "/c/cite.py"\ncite_bin = "/c/cite"\n'
            'dolt_bin = "/usr/bin/dolt"\ngraph_dir = "/g"\nlog_dir = "/l"\n',
        )
        cfg = Config.load()
        self.assertEqual(cfg.root, Path("/kb"))
        self.assertEqual(cfg.cite_py, Path("/c/cite.py"))
        self.assertEqual(cfg.dolt_bin, Path("/usr/bin/dolt"))
        self.assertEqual(cfg.get("graph_dir"), Path("/g"))

    def test_unknown_keys_rejected(self):
        self._write(self.tmp, 'graphdir = "/typo"\n')
        with self.assertRaises(KctxError) as ctx:
            Config.load()
        self.assertEqual(ctx.exception.category, "malformed")
        self.assertIn("graphdir", str(ctx.exception))

    def test_non_string_value_rejected(self):
        self._write(self.tmp, "root = 42\n")
        with self.assertRaises(KctxError):
            Config.load()

    def test_kctx_config_pointing_at_missing_file_is_an_error(self):
        os.environ["KCTX_CONFIG"] = str(self.tmp / "nope.toml")
        with self.assertRaises(KctxError) as ctx:
            Config.load()
        self.assertEqual(ctx.exception.category, "not-found")

    def test_malformed_toml_rejected(self):
        self._write(self.tmp, "root = [unclosed\n")
        with self.assertRaises(KctxError):
            Config.load()

    def test_unknown_get_key_rejected(self):
        with self.assertRaises(KctxError):
            Config.load().get("nope")

    def test_effective_reports_origins(self):
        self._write(self.tmp, 'root = "/kb"\n')
        eff = Config.load().effective()
        self.assertEqual(eff["root"]["origin"], "config")
        self.assertEqual(eff["cite_py"]["origin"], "discovery")
        self.assertIsNotNone(eff["config_file"])


class ConfigLocationTests(unittest.TestCase):
    @_isolated_env
    def test_xdg_location_found(self):
        base = Path(self.tmp) if hasattr(self, "tmp") else Path("/tmp")
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            os.environ["XDG_CONFIG_HOME"] = td
            p = Path(td) / "kctx" / "config.toml"
            p.parent.mkdir(parents=True)
            p.write_text('root = "/kb"\n')
            self.assertEqual(config_path(), p)

    @_isolated_env
    def test_kctx_config_wins_over_xdg(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            xdg = Path(td) / "kctx" / "config.toml"
            xdg.parent.mkdir(parents=True)
            xdg.write_text('root = "/xdg"\n')
            os.environ["XDG_CONFIG_HOME"] = td
            explicit = Path(td) / "explicit.toml"
            explicit.write_text('root = "/explicit"\n')
            os.environ["KCTX_CONFIG"] = str(explicit)
            self.assertEqual(config_path(), explicit)

    @_isolated_env
    def test_absent_everywhere_is_none(self):
        os.environ["XDG_CONFIG_HOME"] = "/nonexistent-xdg"
        self.assertIsNone(config_path())


class WriteConfigTests(unittest.TestCase):
    def test_write_config_round_trips(self):
        import tempfile

        saved = os.environ.get("KCTX_CONFIG")
        try:
            with tempfile.TemporaryDirectory() as td:
                p = write_config(Path(td) / "c.toml", root="/kb", graph_dir="/g")
                os.environ["KCTX_CONFIG"] = str(p)
                cfg = Config.load()
                self.assertEqual(cfg.root, Path("/kb"))
                self.assertEqual(cfg.graph_dir, Path("/g"))
        finally:
            if saved is None:
                os.environ.pop("KCTX_CONFIG", None)
            else:
                os.environ["KCTX_CONFIG"] = saved

    def test_write_config_rejects_unknown_keys(self):
        with self.assertRaises(KctxError):
            write_config(Path("/tmp/x.toml"), bogus="/x")


if __name__ == "__main__":
    unittest.main()
