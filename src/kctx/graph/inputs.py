"""Content identity of every input to a graph generation.

Git commits identify KB bytes, not the installed extractor, citation grammar,
semantic engine, schema, or local canonicalization settings. A generation binds
all of those inputs in canonical JSON. Source files are located through loaded
modules, never a checkout-relative path; unavailable source or distribution
metadata is an error, not an identity shared with another installation.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

from kctx.adapters.git.citations import git_rev_parse
from kctx.config import Config
from kctx.domain.json import JsonObject
from kctx.errors import KctxError
from kctx.graph import dolt_store
from kctx.graph.identity import RepositoryIdentity, capture_repository_identity
from kctx.observability import run_logged
from kctx.semantics import model as semantic_model

MANIFEST_VERSION = 1


def _source_path(module: ModuleType) -> Path:
    filename = module.__file__
    if filename is None:
        raise KctxError("not-found", f"generation input source unavailable: {module.__name__}")
    path = Path(filename)
    if path.suffix == ".pyc":
        if path.parent.name == "__pycache__":
            path = Path(importlib.util.source_from_cache(str(path)))
        else:
            path = path.with_suffix(".py")
    if path.suffix != ".py":
        raise KctxError("not-found", f"generation input is not Python source: {path}")
    return path


def _source_digest(module: ModuleType) -> str:
    path = _source_path(module)
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise KctxError(
            "not-found", f"cannot read generation input source {path}: {error}"
        ) from error


def _implementation_sources() -> tuple[tuple[str, str], ...]:
    """Bind the installed package, not a hand-maintained dependency shortlist.

    Loaded modules retain their actual source locations. Unloaded modules are
    hashed as files without executing entry points or importing optional code.
    """
    root = _source_path(importlib.import_module("kctx")).resolve().parent
    paths: dict[str, Path] = {}
    for path in root.rglob("*.py"):
        parts = path.relative_to(root).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        paths[".".join(("kctx", *parts))] = path
    loaded = {
        name: module
        for name, module in tuple(sys.modules.items())
        if name == "kctx" or name.startswith("kctx.")
    }
    names = paths.keys() | loaded.keys()
    sources: list[tuple[str, str]] = []
    for name in sorted(names):
        module = loaded.get(name)
        if module is not None:
            digest = _source_digest(module)
        else:
            if name not in paths:
                raise KctxError("not-found", f"generation input module unavailable: {name}")
            try:
                digest = hashlib.sha256(paths[name].read_bytes()).hexdigest()
            except OSError as error:
                raise KctxError(
                    "not-found", f"generation input source unavailable: {name}"
                ) from error
        sources.append((name, digest))
    return tuple(sources)


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as error:
        raise KctxError(
            "not-found", f"generation input distribution unavailable: {name}"
        ) from error


def _resolved_path(path: Path | None) -> str | None:
    return str(path.expanduser().resolve()) if path is not None else None


def manifest_digest(value: JsonObject) -> str:
    """Hash persisted manifest JSON without consulting the current installation."""
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class GenerationInputs:
    """Immutable captured inputs; each wire conversion returns a fresh object."""

    kb_sha: str
    kb_root: str
    repository_identity: RepositoryIdentity
    config: tuple[tuple[str, str | int | None], ...]
    source_hashes: tuple[tuple[str, str], ...]
    distribution_versions: tuple[tuple[str, str], ...]
    semantic_version: str
    semantic_schema_version: int
    schema_sha256: str
    dolt_version: str
    manifest_version: int = MANIFEST_VERSION
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "digest", manifest_digest(self.to_wire()))

    def to_wire(self) -> JsonObject:
        return {
            "manifest_version": self.manifest_version,
            "kb_sha": self.kb_sha,
            "kb_root": self.kb_root,
            "repository_identity": {
                "checkout_name": self.repository_identity.checkout_name,
                "origin_url": self.repository_identity.origin_url,
            },
            "config": {key: value for key, value in self.config},
            "source_hashes": {name: digest for name, digest in self.source_hashes},
            "distribution_versions": {
                name: version for name, version in self.distribution_versions
            },
            "semantic_version": self.semantic_version,
            "semantic_schema_version": self.semantic_schema_version,
            "schema_sha256": self.schema_sha256,
            "dolt_version": self.dolt_version,
        }


def generation_inputs(kb_root: Path, *, kb_sha: str | None = None) -> GenerationInputs:
    """Freeze a generation's inputs; callers replaying history pass its pinned SHA.

    The repository identity must also be passed to extraction so normalization
    uses this snapshot rather than rereading a subsequently changed Git origin.
    """
    root = kb_root.expanduser().resolve()
    revision = kb_sha if kb_sha is not None else git_rev_parse(root, "HEAD^{commit}")
    if not revision:
        raise KctxError("not-found", f"cannot resolve graph generation KB commit: {root}")
    config = Config.load()
    dolt_bin = Path(dolt_store.resolve_dolt_bin(config=config)).expanduser().resolve()
    try:
        dolt_version = run_logged([str(dolt_bin), "version"], check=True, timeout=15).stdout.strip()
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise KctxError(
            "not-found", f"cannot identify graph Dolt engine {dolt_bin}: {error}"
        ) from error
    if not dolt_version:
        raise KctxError("not-found", f"graph Dolt engine returned no version: {dolt_bin}")
    config_values: tuple[tuple[str, str | int | None], ...] = (
        ("root", _resolved_path(config.root)),
        ("graph_dir", _resolved_path(config.graph_dir)),
        ("dolt_bin", _resolved_path(config.dolt_bin)),
        ("resolved_dolt_bin", str(dolt_bin)),
        ("cache_dir", _resolved_path(config.cache_dir)),
        ("git_url_template", config.git_url_template),
        ("github_host", config.github_host),
        ("fetch_interval_seconds", config.fetch_interval_seconds),
        ("knowledge_dir", _resolved_path(config.knowledge_dir)),
        ("knowledge_policy_digest", config.knowledge_policy_digest),
    )
    return GenerationInputs(
        kb_sha=revision,
        kb_root=str(root),
        repository_identity=capture_repository_identity(root),
        config=config_values,
        source_hashes=_implementation_sources(),
        distribution_versions=tuple(
            (name, _distribution_version(name))
            for name in (
                "kctx",
                "pydantic",
                "structlog",
                "cryptography",
                "PyMySQL",
                "click",
                "rich",
            )
        ),
        semantic_version=semantic_model.SEMANTIC_VERSION,
        semantic_schema_version=semantic_model.SCHEMA_VERSION,
        schema_sha256=hashlib.sha256(dolt_store.SCHEMA_SQL.encode("utf-8")).hexdigest(),
        dolt_version=dolt_version,
    )
