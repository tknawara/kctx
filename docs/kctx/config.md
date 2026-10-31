# kctx configuration design (`config.toml`)

Traceability record for the configuration layer: the problem, the design
decisions (and the alternatives rejected), and the precedence contract. The
implementation is `src/kctx/config.py`; the fixtures are
`tests/test_config.py`.

## The problem

Tool locations were discovered by scattered environment probes with
machine-specific fallbacks baked into code:

| Concern | Baseline discovery | Portability failure |
| --- | --- | --- |
| Citation parser (`cite.py`) | `KCTX_CITE_PY` → `CLAUDE_CONFIG_DIR` → `~/.claude` → `~/workspace/dotfiles` | the dotfiles path is one machine's layout; the compose stack had to spray env vars per run |
| Shadow graph dir | `KCTX_GRAPH_DIR` → `/workarea/kb-graph` (a Space convention) → `~/.local/share/kb-graph` | two KBs on one machine share a directory by accident; `/workarea` is a work-machine artifact |
| KB root | `KCTX_ROOT` → walk up from the *script* to any `.git` | any Git repo qualifies — wrong for a standalone install (handover §7.3) |
| Dolt binary | whatever is on `PATH` | a conflicting ambient binary can silently win |

The handover anticipated exactly this (§8.3: *"Unify discovery of CITE_BIN,
KCTX_CITE_PY, and deployed skill paths. Report which provider/version was
selected"*).

## Design

**One file, locations only.** `config.toml` holds six optional path keys
(`root`, `cite_py`, `cite_bin`, `dolt_bin`, `graph_dir`, `log_dir`) and
nothing else. Unknown keys are **rejected** with the supported list, not
silently ignored — a typo in `graphdir` must never quietly mean "default".
Never credentials: kctx reads locations, full stop.

**File location:** `$KCTX_CONFIG` (explicit) else
`$XDG_CONFIG_HOME/kctx/config.toml` else `~/.config/kctx/config.toml`. A
`KCTX_CONFIG` pointing at a missing file is an error, not a silent skip.

**No layering — config.toml is the configuration.** An earlier draft had
`CLI arg > env var > config.toml > default`; the final design drops the CLI
and env layers entirely. The agent driving kctx writes one file and starts
the tool (the LSP-server model: one stdio config, no flag soup). Exactly
one environment variable remains — ``KCTX_CONFIG`` — and it does a single
job: say *where the config file is* (tests and containers point it at a
temp file; the XDG default covers interactive use). Absent a configured
value, each consumer falls back to its built-in discovery (root: the KB
marker ``inventory/assets/`` from cwd — never "any Git repo"; cite: the
skill-path chain; graph/log dirs: the documented machine defaults).

**Observable.** `kctx.config.effective()` reports every setting with its
origin (`env:KCTX_GRAPH_DIR`, `config:/home/u/.config/kctx/config.toml`,
`default`) — the `doctor` surface the handover asks for, and the debugging
answer for "why did it pick the wrong cite".

## Decisions and rejected alternatives

| Decision | Why | Rejected alternative |
| --- | --- | --- |
| TOML (`tomllib`, stdlib ≥3.11) | zero new deps; the repo floor is 3.11; comments in the file | YAML (new dep); INI (no nesting, awkward types); more env vars (unportable, unversionable) |
| Flat keys, no `[sections]` | six paths don't need nesting; simpler validation and error messages | per-tool sections (more typing, no added clarity at this size) |
| Config sets *paths*, code keeps *semantics* | the layer decides **where**, never **what it means** (handover's storage-adapter rule) | config-as-feature-flags (scope creep; policy belongs in the calculus/policy versions) |
| Reject unknown keys | silent ignore turns typos into behavior changes | ignore-unknown (a future key would silently no-op on old kctx — the schema_version problem in miniature) |
| No per-KB config in the KB repo | config is machine truth (where tools live), not corpus truth | a `kctx.toml` inside the KB (mixes machine and data; breaks multi-machine sharing of a KB) |
| **No layering at all** | the agent writes config.toml and starts the tool; one artifact to reason about, diff, and mount | `CLI > env > config` (three layers to explain, document, and debug — the original draft, dropped) |
| One env var kept: `KCTX_CONFIG` | something must locate the file itself; same knob LSP servers use; tests/containers point it at a temp config | zero env vars (tests would need to write into `~/.config`, breaking isolation) |
| No `schema_version` yet | six optional paths, additive-only so far | versioned config now (YAGNI; add the key the day a breaking change exists, with a migration) |

## Traceability

- Problem source: handover §7.3 (root precedence), §8.3 (cite discovery
  unification), discovery report §"Missing prerequisites".
- Implementation: `src/kctx/config.py` (`Config.load`, `get`, `effective`,
  `write_config`; `config_path`). Consumers wired: `storage.find_root`
  (root; marker discovery fallback), `nav.locate_cite_bin` (cite_bin),
  `kctx.graph.cite_loader.locate_cite_py` (cite_py; skill-path fallback),
  `kctx.graph.sync.graph_dir` (graph_dir), `kctx.graph.observability`
  (log_dir). `dolt_bin` is read by the graph adapter (queued slice).
- Test seam: `tests/_base.py` keeps session state *on the `kctx.config`
  module instance — necessary because `_base` is imported twice (`_base`
  and `tests._base`); two module-globals split-brain the config (a bug this
  port caught in action).
- Consumers wired in this slice: `kctx.graph.cite_loader.locate_cite_py`
  (config consulted between env and skill-path fallbacks),
  `kctx.graph.sync.graph_dir` (config before the `/workarea` fallback),
  `scripts/dolt_smoke.py` (writes one config.toml instead of four env vars —
  the portability demonstration).
- Not yet wired (queued in PORTING.md): `storage.find_root` awaits the
  §7.3 slice (`adapters/files/roots.py` is already written); `dolt_bin`
  wiring awaits the graph adapter slice.
- Fixtures: `tests/test_config.py` (parsing, precedence, unknown-key
  rejection, `effective()` origins).
