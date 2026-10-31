# Configuration

kctx reads one TOML file. `KCTX_CONFIG` selects an existing file; otherwise it
looks for `$XDG_CONFIG_HOME/kctx/config.toml` (default
`~/.config/kctx/config.toml`). A missing explicitly selected file is an error;
a missing default file uses discovery. There are no per-setting environment
overrides, external citation executable, or command-line root override.

```toml
root = "/srv/knowledge"
knowledge_dir = "/srv/kctx/knowledge-dolt"
# Bootstrap SHA-256 of canonical .kctx/knowledge-policy.json, provisioned by operator.
# knowledge_policy_digest = "<64 lowercase hexadecimal digits>"
dolt_bin = "/usr/local/bin/dolt"
gh_bin = "/usr/bin/gh"
cache_dir = "/srv/kctx/cache"
git_url_template = "https://github.com/{org}/{repo}.git"
github_host = "github.com"
fetch_interval_seconds = 900
```

The commented digest is explanatory, not a valid configured trust anchor. Use
the real canonical policy digest before authenticated knowledge publication.
Credentials belong to Git/SSH/`gh` credential configuration, not this file.

## Exact keys and defaults

All keys are top-level; unknown keys and TOML tables are rejected. Path values
must be nonempty strings and expand `~`; relative paths are not rebased to the
configuration file. Prefer absolute paths in unattended deployments.

| Key | Config default | Adapter behavior when absent |
| --- | --- | --- |
| `root` | unset | Walk cwd and ancestors for `inventory/assets/`; any Git repository alone is insufficient. An explicit root must be a directory. |
| `dolt_bin` | unset | Discover `dolt` on PATH; unavailable native storage is an explicit error. |
| `gh_bin` | unset | Discover `gh` on PATH (or invoke `gh` for the normal executable error). |
| `graph_dir` | unset | `/workarea/kb-graph` if `/workarea` exists, otherwise `~/.local/share/kb-graph`. |
| `log_dir` | unset | `$XDG_STATE_HOME/kctx/logs`, otherwise `~/.local/state/kctx/logs`. |
| `cache_dir` | unset | `~/.cache/kctx` for citation repository acquisition. |
| `knowledge_dir` | unset | Required explicitly by the knowledge CLI/engine; separate from the authored graph projection. |
| `knowledge_policy_digest` | unset | Optional at parse time; authenticated bootstrap/restore requires the trusted policy identity. Must be exactly 64 lowercase hexadecimal digits. |
| `git_url_template` | `bbgithub:{org}/{repo}.git` | Used for citation repository acquisition; format fields are `org` and `repo`. |
| `github_host` | `bbgithub.dev.bloomberg.com` | Host for PR acquisition. |
| `fetch_interval_seconds` | `900` | Nonnegative integer; booleans are rejected. |

`Config.effective()` reports `config_file` and each value with origin `config`
or `discovery`. The latter includes literal defaults; it does not mean a tool
has already been found or a directory validated.

## Why one file

A single machine-local configuration avoids competing CLI/environment/repository
layers. Authored policy is separately versioned and cryptographically anchored:
changing a path must not silently change authority. Citation construction and
checking are built into kctx, so there is no external citation protocol to keep
in sync. Standard XDG location discovery is not a legacy per-setting override.

Ownership: `src/kctx/config.py`, `adapters/files/roots.py`,
`adapters/git/citations.py`, `graph/sync.py`, `observability.py`.
Qualification pointers: `tests/test_config.py`, `tests/test_knowledge_boundaries.py`,
`tests/test_citation_sources.py`. These are test locations, not execution claims.
See [workflows](workflows.md) and [flows](flows.md).
