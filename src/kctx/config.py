"""One config.toml for the KB, storage and built-in citation acquisition.

KCTX_CONFIG locates the file; otherwise XDG_CONFIG_HOME/kctx/config.toml is
used. There is no per-setting environment override and no external cite binary.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypedDict

from kctx.errors import KctxError

PATH_KEYS = ("root", "dolt_bin", "gh_bin", "graph_dir", "log_dir", "cache_dir", "knowledge_dir")
TEXT_KEYS = ("git_url_template", "github_host")
KEYS = (*PATH_KEYS, *TEXT_KEYS, "fetch_interval_seconds", "knowledge_policy_digest")
DEFAULT_GIT_URL_TEMPLATE = "bbgithub:{org}/{repo}.git"
DEFAULT_GITHUB_HOST = "bbgithub.dev.bloomberg.com"


class EffectiveSetting(TypedDict):
    origin: Literal["config", "discovery"]
    value: str | int | None


class EffectiveConfig(TypedDict):
    config_file: str | None
    root: EffectiveSetting
    dolt_bin: EffectiveSetting
    gh_bin: EffectiveSetting
    graph_dir: EffectiveSetting
    log_dir: EffectiveSetting
    cache_dir: EffectiveSetting
    git_url_template: EffectiveSetting
    github_host: EffectiveSetting
    fetch_interval_seconds: EffectiveSetting
    knowledge_dir: EffectiveSetting
    knowledge_policy_digest: EffectiveSetting


def config_path(env: Mapping[str, str] | None = None) -> Path | None:
    environment = os.environ if env is None else env
    explicit = environment.get("KCTX_CONFIG")
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise KctxError("not-found", f"KCTX_CONFIG={explicit!r} does not point at a file")
        return path
    base = Path(environment.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    candidate = base / "kctx/config.toml"
    return candidate if candidate.is_file() else None


@dataclass(frozen=True, slots=True)
class Config:
    root: Path | None = None
    dolt_bin: Path | None = None
    gh_bin: Path | None = None
    graph_dir: Path | None = None
    log_dir: Path | None = None
    cache_dir: Path | None = None
    git_url_template: str = DEFAULT_GIT_URL_TEMPLATE
    github_host: str = DEFAULT_GITHUB_HOST
    fetch_interval_seconds: int = 900
    knowledge_dir: Path | None = None
    knowledge_policy_digest: str | None = None
    source: Path | None = None
    _configured: frozenset[str] = field(default=frozenset(), repr=False)

    @classmethod
    def load(cls, env: Mapping[str, str] | None = None) -> Config:
        path = config_path(env)
        if path is None:
            return cls()
        try:
            data: dict[str, object] = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError) as exc:
            raise KctxError("malformed", f"config {path}: {exc}") from exc
        unknown = sorted(set(data) - set(KEYS))
        if unknown:
            raise KctxError(
                "malformed", f"config {path}: unknown keys {unknown}; supported: {list(KEYS)}"
            )
        paths: dict[str, Path | None] = {}
        for key in PATH_KEYS:
            raw = data.get(key)
            if raw is None:
                paths[key] = None
            elif isinstance(raw, str) and raw.strip():
                paths[key] = Path(raw).expanduser()
            else:
                raise KctxError("malformed", f"config {path}: key {key!r} must be a path string")
        template = data.get("git_url_template", DEFAULT_GIT_URL_TEMPLATE)
        host = data.get("github_host", DEFAULT_GITHUB_HOST)
        interval = data.get("fetch_interval_seconds", 900)
        if not isinstance(template, str) or not template.strip():
            raise KctxError("malformed", "git_url_template must be a nonempty string")
        try:
            template.format(org="example", repo="repository")
        except (KeyError, ValueError, IndexError) as exc:
            raise KctxError(
                "malformed", "git_url_template permits only {org} and {repo} fields"
            ) from exc
        if not isinstance(host, str) or not host.strip():
            raise KctxError("malformed", "github_host must be a nonempty string")
        if type(interval) is not int or interval < 0:
            raise KctxError("malformed", "fetch_interval_seconds must be a nonnegative integer")
        policy_digest = data.get("knowledge_policy_digest")
        if policy_digest is not None and (
            not isinstance(policy_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", policy_digest) is None
        ):
            raise KctxError(
                "malformed", "knowledge_policy_digest must be a lowercase SHA256 digest"
            )
        return cls(
            root=paths["root"],
            dolt_bin=paths["dolt_bin"],
            gh_bin=paths["gh_bin"],
            graph_dir=paths["graph_dir"],
            log_dir=paths["log_dir"],
            cache_dir=paths["cache_dir"],
            git_url_template=template,
            github_host=host,
            fetch_interval_seconds=interval,
            knowledge_dir=paths["knowledge_dir"],
            knowledge_policy_digest=policy_digest,
            source=path,
            _configured=frozenset(data),
        )

    def _settings(self) -> dict[str, Path | str | int | None]:
        return {
            "root": self.root,
            "dolt_bin": self.dolt_bin,
            "gh_bin": self.gh_bin,
            "graph_dir": self.graph_dir,
            "log_dir": self.log_dir,
            "cache_dir": self.cache_dir,
            "git_url_template": self.git_url_template,
            "github_host": self.github_host,
            "fetch_interval_seconds": self.fetch_interval_seconds,
            "knowledge_dir": self.knowledge_dir,
            "knowledge_policy_digest": self.knowledge_policy_digest,
        }

    def get(self, key: str) -> Path | str | int | None:
        if key not in KEYS:
            raise KctxError("malformed", f"unknown config key {key!r}")
        return self._settings()[key]

    def effective(self) -> EffectiveConfig:
        def setting(key: str) -> EffectiveSetting:
            value = self.get(key)
            return {
                "origin": "config" if key in self._configured else "discovery",
                "value": str(value) if isinstance(value, Path) else value,
            }

        return {
            "config_file": str(self.source) if self.source else None,
            "root": setting("root"),
            "dolt_bin": setting("dolt_bin"),
            "gh_bin": setting("gh_bin"),
            "graph_dir": setting("graph_dir"),
            "log_dir": setting("log_dir"),
            "cache_dir": setting("cache_dir"),
            "git_url_template": setting("git_url_template"),
            "github_host": setting("github_host"),
            "fetch_interval_seconds": setting("fetch_interval_seconds"),
            "knowledge_dir": setting("knowledge_dir"),
            "knowledge_policy_digest": setting("knowledge_policy_digest"),
        }


def write_config(path: Path, **keys: str | int) -> Path:
    unknown = sorted(set(keys) - set(KEYS))
    if unknown:
        raise KctxError("malformed", f"unknown config keys {unknown}; supported: {list(KEYS)}")
    lines = [f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in keys.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
