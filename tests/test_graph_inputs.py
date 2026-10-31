"""Generation identity binds code, configuration, schema and repository context."""

import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import shutil
import sys
import subprocess
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from _base import KctxTestCase
import kctx
from kctx.config import Config
from kctx.domain.json import object_value
from kctx.errors import KctxError
from kctx.graph import dolt_store, inputs
from kctx.graph.identity import canonical_repo
from kctx.graph.inputs import generation_inputs, manifest_digest
from kctx.semantics import model as semantic_model


class GenerationInputsTest(KctxTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.kb_root = self.make_git_repo("kb")
        self.run_git(self.kb_root, "remote", "add", "origin", "https://example.test/acme/kb.git")
        self.dolt_bin = self.root / "installed-dolt"
        resolve = patch.object(dolt_store, "resolve_dolt_bin", return_value=str(self.dolt_bin))
        self.resolve_dolt = resolve.start()
        self.addCleanup(resolve.stop)
        version = patch.object(
            inputs,
            "run_logged",
            return_value=subprocess.CompletedProcess(
                [str(self.dolt_bin), "version"],
                0,
                "dolt version test-release\n",
                "",
            ),
        )
        self.dolt_version = version.start()
        self.addCleanup(version.stop)

    def test_digest_is_canonical_manifest_sha256(self) -> None:
        captured = generation_inputs(self.kb_root)
        wire = captured.to_wire()
        encoded = json.dumps(
            wire,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        self.assertEqual(captured.digest, hashlib.sha256(encoded).hexdigest())
        self.assertEqual(manifest_digest(wire), captured.digest)
        self.assertEqual(captured, generation_inputs(self.kb_root))
        self.assertEqual(wire["kb_root"], str(self.kb_root.resolve()))
        self.assertEqual(wire["semantic_version"], semantic_model.SEMANTIC_VERSION)
        self.assertEqual(wire["semantic_schema_version"], semantic_model.SCHEMA_VERSION)
        self.assertEqual(wire["dolt_version"], "dolt version test-release")
        self.assertEqual(object_value(wire["config"])["resolved_dolt_bin"], str(self.dolt_bin))
        versions = object_value(wire["distribution_versions"])
        self.assertEqual(versions["kctx"], importlib.metadata.version("kctx"))
        self.assertEqual(
            wire["schema_sha256"],
            hashlib.sha256(dolt_store.SCHEMA_SQL.encode("utf-8")).hexdigest(),
        )

    def test_upgrade_check_warning_does_not_change_generation_identity(self) -> None:
        """Dolt's advisory upgrade warning shares stdout and appears only on
        some invocations of a non-latest engine; it must not turn a sync's own
        candidate into an apparent input change before publication."""
        quiet = generation_inputs(self.kb_root)
        with patch.object(
            inputs,
            "run_logged",
            return_value=subprocess.CompletedProcess(
                [str(self.dolt_bin), "version"],
                0,
                "dolt version test-release\n"
                "Warning: you are on an old version of Dolt. The newest version is 2.6.2.\n",
                "",
            ),
        ):
            warned = generation_inputs(self.kb_root)
        self.assertEqual(warned.dolt_version, "dolt version test-release")
        self.assertEqual(quiet.digest, warned.digest)

    def test_persisted_manifest_digest_does_not_read_live_inputs(self) -> None:
        captured = generation_inputs(self.kb_root)
        persisted = object_value(json.loads(json.dumps(captured.to_wire())))
        with (
            patch.object(inputs, "generation_inputs", side_effect=AssertionError("live inputs")),
            patch.object(inputs, "_source_digest", side_effect=AssertionError("live source")),
            patch.object(Config, "load", side_effect=AssertionError("live config")),
        ):
            self.assertEqual(manifest_digest(persisted), captured.digest)

    def test_manifest_is_frozen_and_wire_objects_are_detached(self) -> None:
        captured = generation_inputs(self.kb_root)
        original = captured.to_wire()
        wire = captured.to_wire()
        config = wire["config"]
        self.assertIsInstance(config, dict)
        if not isinstance(config, dict):
            self.fail("configuration is not a JSON object")
        config["github_host"] = "mutated.invalid"
        sources = wire["source_hashes"]
        self.assertIsInstance(sources, dict)
        if not isinstance(sources, dict):
            self.fail("source hashes are not a JSON object")
        sources.clear()
        self.assertEqual(captured.to_wire(), original)
        with self.assertRaises(FrozenInstanceError):
            setattr(captured, "kb_sha", "changed")
        with self.assertRaises(FrozenInstanceError):
            setattr(captured.repository_identity, "origin_url", "changed")

    def test_digest_does_not_depend_on_manifest_map_order(self) -> None:
        captured = generation_inputs(self.kb_root)
        reordered = replace(
            captured,
            config=tuple(reversed(captured.config)),
            source_hashes=tuple(reversed(captured.source_hashes)),
            distribution_versions=tuple(reversed(captured.distribution_versions)),
        )
        self.assertEqual(captured.digest, reordered.digest)

    @unittest.skipUnless(shutil.which("dolt"), "native Dolt required")
    def test_installed_decoder_and_new_module_change_generation_identity(self) -> None:
        package = self.root / "installed" / "kctx"
        shutil.copytree(
            Path(kctx.__file__).parent, package, ignore=shutil.ignore_patterns("__pycache__")
        )
        environment = {**os.environ, "PYTHONPATH": str(package.parent)}
        program = (
            "import sys; from pathlib import Path; "
            "from kctx.observability import init_logging; "
            "from kctx.graph.inputs import generation_inputs; "
            "init_logging(machine=True); print(generation_inputs(Path(sys.argv[1])).digest)"
        )

        def identity() -> str:
            return subprocess.check_output(
                [sys.executable, "-c", program, str(self.kb_root)],
                env=environment,
                text=True,
            ).strip()

        before = identity()
        decoder = package / "adapters" / "files" / "storage.py"
        decoder.write_bytes(decoder.read_bytes() + b"\n# changed installed decoder artifact\n")
        changed = identity()
        self.assertNotEqual(before, changed)
        (package / "new_catalog.py").write_text(
            "raise RuntimeError('fingerprinting must not import this module')\n"
        )
        self.assertNotEqual(changed, identity())

    def test_sources_are_located_in_installed_modules_not_checkout(self) -> None:
        module = importlib.import_module("kctx.citations.syntax")
        source_path = module.__file__
        self.assertIsNotNone(source_path)
        if source_path is None:
            self.fail("citation parser source is missing")
        relocated = self.root / "installed-parser.py"
        relocated.write_bytes(Path(source_path).read_bytes())
        before = generation_inputs(self.kb_root)
        with patch.object(module, "__file__", str(relocated)):
            after = generation_inputs(self.kb_root)
        self.assertEqual(before.digest, after.digest)

    def test_schema_sql_changes_identity_without_source_version_change(self) -> None:
        before = generation_inputs(self.kb_root)
        with patch.object(
            dolt_store, "SCHEMA_SQL", dolt_store.SCHEMA_SQL + "\n-- changed schema\n"
        ):
            after = generation_inputs(self.kb_root)
        self.assertNotEqual(before.digest, after.digest)
        self.assertNotEqual(before.schema_sha256, after.schema_sha256)

    def test_semantic_versions_change_identity(self) -> None:
        before = generation_inputs(self.kb_root)
        for field, value in (("SEMANTIC_VERSION", "changed-version"), ("SCHEMA_VERSION", 999)):
            with self.subTest(field=field), patch.object(semantic_model, field, value):
                self.assertNotEqual(before.digest, generation_inputs(self.kb_root).digest)

    def test_installed_release_version_changes_identity(self) -> None:
        before = generation_inputs(self.kb_root)
        original_version = importlib.metadata.version

        def changed_version(name: str) -> str:
            return "changed-release" if name == "kctx" else original_version(name)

        with patch.object(importlib.metadata, "version", side_effect=changed_version):
            self.assertNotEqual(before.digest, generation_inputs(self.kb_root).digest)

    def test_relevant_config_values_change_identity(self) -> None:
        baseline_config = Config.load()
        before = generation_inputs(self.kb_root)
        variants = (
            replace(baseline_config, root=self.root / "another-root"),
            replace(baseline_config, graph_dir=self.root / "another-graph"),
            replace(baseline_config, dolt_bin=self.root / "another-dolt"),
            replace(baseline_config, cache_dir=self.root / "another-cache"),
            replace(baseline_config, git_url_template="https://another.test/{org}/{repo}"),
            replace(baseline_config, github_host="another.test"),
            replace(baseline_config, fetch_interval_seconds=1234),
            replace(baseline_config, knowledge_dir=self.root / "another-knowledge"),
            replace(baseline_config, knowledge_policy_digest="a" * 64),
        )
        for config in variants:
            with self.subTest(config=config), patch.object(Config, "load", return_value=config):
                self.assertNotEqual(before.digest, generation_inputs(self.kb_root).digest)
        self.set_config(github_host="file-config.test")
        self.assertNotEqual(before.digest, generation_inputs(self.kb_root).digest)
        self.assertEqual(
            object_value(before.to_wire()["config"])["github_host"], baseline_config.github_host
        )

    def test_resolved_root_changes_identity(self) -> None:
        before = generation_inputs(self.kb_root)
        other = self.make_git_repo("other")
        self.run_git(other, "remote", "add", "origin", before.repository_identity.origin_url or "")
        after = generation_inputs(other, kb_sha=before.kb_sha)
        self.assertNotEqual(before.digest, after.digest)
        alias = self.root / "alias"
        alias.symlink_to(self.kb_root, target_is_directory=True)
        self.assertEqual(before.digest, generation_inputs(alias).digest)

    def test_origin_changes_digest_and_frozen_normalization_survives_change(self) -> None:
        before = generation_inputs(self.kb_root)
        self.run_git(
            self.kb_root, "remote", "set-url", "origin", "https://example.test/other/kb.git"
        )
        after = generation_inputs(self.kb_root)
        self.assertNotEqual(before.digest, after.digest)
        self.assertEqual(before.kb_sha, after.kb_sha)
        self.assertEqual(
            canonical_repo(self.kb_root.name, None, before.repository_identity), "acme/kb"
        )
        self.assertEqual(
            canonical_repo(self.kb_root.name, None, after.repository_identity), "other/kb"
        )
        identity = object_value(before.to_wire()["repository_identity"])
        self.assertEqual(
            identity,
            {
                "checkout_name": self.kb_root.name,
                "origin_url": "https://example.test/acme/kb.git",
            },
        )

    def test_missing_origin_is_an_explicit_input(self) -> None:
        before = generation_inputs(self.kb_root)
        self.run_git(self.kb_root, "remote", "remove", "origin")
        after = generation_inputs(self.kb_root)
        self.assertNotEqual(before.digest, after.digest)
        self.assertIsNone(after.repository_identity.origin_url)
        self.assertIsNone(object_value(after.to_wire()["repository_identity"])["origin_url"])

    def test_repository_identity_is_captured_once(self) -> None:
        from kctx.graph import identity

        with patch.object(identity, "get_origin_url", wraps=identity.get_origin_url) as get_origin:
            generation_inputs(self.kb_root)
        get_origin.assert_called_once_with(self.kb_root.resolve())

    def test_pinned_kb_commit_is_manifest_input_not_live_head(self) -> None:
        before = generation_inputs(self.kb_root)
        self.commit_file(self.kb_root, "changed.md", "a new committed document\n")
        self.assertNotEqual(before.digest, generation_inputs(self.kb_root).digest)
        self.assertEqual(
            before.digest, generation_inputs(self.kb_root, kb_sha=before.kb_sha).digest
        )
        with patch.object(inputs, "git_rev_parse") as resolve:
            generation_inputs(self.kb_root, kb_sha=before.kb_sha)
        resolve.assert_not_called()

    def test_missing_commit_fails_closed(self) -> None:
        with self.assertRaises(KctxError):
            generation_inputs(self.root)

    def test_missing_source_fails_closed(self) -> None:
        parser = importlib.import_module("kctx.citations.syntax")
        for filename in (None, str(self.root / "missing.py"), str(self.root / "parser.so")):
            with self.subTest(filename=filename), patch.object(parser, "__file__", filename):
                with self.assertRaises(KctxError):
                    generation_inputs(self.kb_root)

    def test_cached_bytecode_requires_actual_source(self) -> None:
        module = ModuleType("installed_parser")
        source = self.root / "parser.py"
        source.write_bytes(b"# actual installed parser\n")
        module.__file__ = importlib.util.cache_from_source(str(source))
        self.assertEqual(
            inputs._source_digest(module), hashlib.sha256(source.read_bytes()).hexdigest()
        )
        source.unlink()
        with self.assertRaises(KctxError):
            inputs._source_digest(module)

    def test_native_engine_version_changes_identity(self) -> None:
        before = generation_inputs(self.kb_root)
        self.dolt_version.return_value = subprocess.CompletedProcess(
            [str(self.dolt_bin), "version"],
            0,
            "dolt version newer-release\n",
            "",
        )
        after = generation_inputs(self.kb_root)
        self.assertNotEqual(before.digest, after.digest)
        self.assertEqual(after.dolt_version, "dolt version newer-release")
        self.dolt_version.assert_called_with(
            [str(self.dolt_bin), "version"],
            check=True,
            timeout=15,
        )

    def test_resolved_native_binary_changes_identity(self) -> None:
        before = generation_inputs(self.kb_root)
        other = self.root / "another-installed-dolt"
        self.resolve_dolt.return_value = str(other)
        after = generation_inputs(self.kb_root)
        self.assertNotEqual(before.digest, after.digest)
        self.assertEqual(object_value(after.to_wire()["config"])["resolved_dolt_bin"], str(other))
        self.resolve_dolt.assert_called_with(config=Config.load())

    def test_missing_native_engine_version_fails_closed(self) -> None:
        self.dolt_version.return_value = subprocess.CompletedProcess([], 0, " \n", "")
        with self.assertRaises(KctxError):
            generation_inputs(self.kb_root)
        for error in (
            OSError("missing binary"),
            subprocess.CalledProcessError(1, [str(self.dolt_bin), "version"]),
            subprocess.TimeoutExpired([str(self.dolt_bin), "version"], 15),
        ):
            with self.subTest(error=error):
                self.dolt_version.side_effect = error
                with self.assertRaises(KctxError):
                    generation_inputs(self.kb_root)

    def test_missing_distribution_metadata_fails_closed(self) -> None:
        with patch.object(
            importlib.metadata,
            "version",
            side_effect=importlib.metadata.PackageNotFoundError("kctx"),
        ):
            with self.assertRaises(KctxError):
                generation_inputs(self.kb_root)


if __name__ == "__main__":
    unittest.main()
