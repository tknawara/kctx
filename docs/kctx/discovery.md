# G00 discovery report — kctx baseline

Date: 2026-10-30. Inspector: local agent, WSL2 linux 6.18.33, x64.
Repository: `tknawara/kctx` (freshly initialized from the supplied baseline; this
report is committed alongside it).

## 1. Source identity

- Authoritative baseline: `kctx.zip`, SHA-256
  `81e8278a057cb94b4a676cad2b4b20781165553e132be604ae33ce7b655e7f62` — matches the
  handover's recorded digest exactly. 54 archive members, 49 Python files,
  12,902 lines. The workspace tree is the zip's `kctx/` prefix extracted at repo
  root; `diff -rq` shows zero content differences.
- The zip (22:02 today) postdates the newest workspace files (14:44), i.e. the
  zip was cut from this tree. The tree is the baseline.

## 2. Environment

| Tool | Present | Notes |
| --- | --- | --- |
| python3 | 3.12.3 (`/usr/bin/python3`) | Handover's inspection env used 3.12.14; pyproject floor is >=3.11. |
| uv | 0.9.27 | `python-preference = "only-system"`, `python-downloads = "never"`. |
| git | 2.43.0 | |
| docker | 29.9.2 | Available for the pinned Lean proof environment. |
| dolt | **missing** | Graph integration tests skip. |
| ruff / pyright | **missing** | To be provisioned via `uv` dev group. |
| lean/elan | **missing** | Proofs run in the pinned container only (by design). |
| structlog / pydantic | **missing in ambient interpreter** | Graph package deps; installed by `script` → `uv run --project`. |

GitHub auth: `gh` authenticated as `tknawara` (HTTPS+SSH); remote
`git@github.com:tknawara/kctx.git` verified writable (M0 pushed).

## 3. Package layout (top level)

| Module | LOC (approx) | Responsibility |
| --- | --- | --- |
| `cli.py` | 700 | argparse registration + dispatch for all commands except `graph`/`logs`. |
| `kctx.py` | 30 | Entry point; wires observability (`graph.observability`), consumes `-v`. |
| `script` | — | Bash wrapper: `uv run --project <dir> python kctx.py "$@"`; Space fallback to `/opt/bb/bin/python3.1x`; refuses to run without uv. |
| `records.py` | 340 | Dataclasses + enum sets (all record families), `require_choice`. |
| `storage.py` | 220 | `find_root`, atomic/exclusive JSON writes, sha256, slug/time helpers, flat frontmatter parser, `⟦…⟧`-aware comma splitting. |
| `inventory.py` | 190 | Asset/relationship services, alias lookup. |
| `proposals.py` | 520 | Proposal lifecycle, readiness checks, gate parsing, transitions. |
| `gates.py` | 180 | `gates.json` append-only gate results. |
| `admit.py` | 640 | Event-driven refresh from git/`gh`; cursors; `⟦cite⟧` scanning (`CITE_LINE_RE` at admit.py:33). |
| `nav.py` | 1250 | `home`/`context`/`stale`(+`--drain`)/`uses`/`timeline`/`match`; citation freshness via external `cite`. |
| `runs.py` | 330 | Runs, observations, coverage, `check` receipts, resume. |
| `git_utils.py` | 40 | HEAD/dirty-digest helpers. |
| `corrections.py` | 240 | `retract` → corrections files with pending referrer rows. |
| `investigations.py` | 300 | Investigation scaffolding, list/show/conclude/promote. |
| `ktlo.py` | 180 | KTLO ticket records + promotion pointers. |
| `signatures.py` | 200 | Known-error signatures + `match`. |
| `dossiers.py` | 160 | Asset dossiers, archive. |
| `validate.py` | 420 | Cross-record validation scan. |
| `errors.py` | 20 | `KctxError(category, message)`. |
| `graph/` (12 files) | ~1900 | M2 shadow Dolt graph: `extract`, `sync`, `queries`, `dolt_store` (CLI/CSV adapter), `identity`, `cite_loader`, `models` (pydantic), `observability` (structlog), `cli_graph`, `quoting`, `render`. |
| `tests/` (18 files + `_base.py`) | 266 test methods | Deterministic; git-backed throwaway repos under temp `KCTX_ROOT`. |

Test-method counts: nav 50, proposals 32, validate 33, cli_commands 19, gates 15,
runs 13, ktlo 12, investigations 18, admit 9, dossiers 9, signatures 9,
graph_extract 9, graph_identity 8, graph_integration 5, graph_models 6,
graph_quoting 10, graph_cite_loader 5, inventory 4.

## 4. CLI surface

Global: `--json` **before** the subcommand (default: readable text); `-v/--verbose`
consumed by `kctx.py`. Exit codes `0` ok / `2` partial / `3` blocked / `1` error
(README.md:33; `cli.py:736-742` returns 1 on `KctxError`). Error categories:
`not-found, malformed, stale, conflict, incomplete, permission, timeout`.

Commands (from `cli.py` registrations + README command table):

- `validate` — full cross-record scan.
- `asset add/show/list`; `rel add`; `impact <asset> [--depth N]`.
- `home <repo|asset|ticket>`; `context <repo|asset> [--depth N]`;
  `stale [--project P] [--offline] [--drain]`.
- `admit --repo <org/repo> [--since …] [--dry-run]`; `admit <PR url|org/repo#N>`.
- `dossier new|archive`; `ktlo new|promote`; `inv new|list|show|conclude|promote`;
  `sig new|list|show`; `match "<text>"`; `timeline <id>`.
- `uses <target>`; `retract <target> --reason … --kind retract|dispute|supersede`.
- `run new`; `observe`; `cover`; `check [--require …]`; `resume`; `checkpoint`.
- `proposal add|list|set|gate|show`.
- `graph sync|status|uses|impact|diff|check` (registered in `graph/cli_graph.py`).
- `logs [--run <id>] [--last N]`.

## 5. Citation grammar (public contract)

- Durable citations are `⟦cite …⟧` tokens. The **only real parser** is the
  external `cite` tool in dotfiles at `.claude/skills/grounding/cite`
  (README.md:13-20); `kctx` shells out for freshness (`context`, `stale`) and
  the graph delegates via `graph/cite_loader.py`.
- Provider discovery chain: `$CITE_BIN` → `$CLAUDE_CONFIG_DIR/skills/grounding/cite`
  → `~/.claude/skills/grounding/cite` → dotfiles checkout. If absent: citations
  are reported `unverifiable` — **never** `fresh`.
- In-repo regexes are recognition-only: `⟦cite(?P<body>.*?)⟧` DOTALL
  (`admit.py:33`, `nav.py:623`). Bodies carry `kind=pr` / `kind=code`
  (`admit.py:195,261`), `path=`, `L=`, and `repo@sha:path:L` locator forms
  (README.md:64, `nav.py:890`).
- List values split on top-level commas while protecting `⟦…⟧` spans
  (`storage.py:185-213`) — comma-containing citations must survive (fixture:
  `test_proposals.py`).
- The complete grammar is **not** recoverable locally (external tool + LOCATORS.md
  live in dotfiles). Do not invent it from `test_proposals.py`.

## 6. Record families (`records.py`)

`SCHEMA_VERSION = 1` on every JSON record and proposal frontmatter. Dataclasses:
`Asset` (records.py:184), `Relationship` (:210), `ObservationSource` (:235),
`Observation` (:252), `CoverageEntry` (:278), `Proposal` (:297) — fields are
largely `str`/`Optional[str]`; evidence payloads are unrestricted dicts
(handover §1.1 finding confirmed).

Enum sets (all `set[str]`, validated by `require_choice`):

| Set | Values |
| --- | --- |
| `ASSET_KINDS` | service, dashboard, alert, doc, runbook, pipeline, deployment, environment, store, other (partial list; see records.py:14-29) |
| `LIFECYCLES` | active, deprecated, retired |
| `REL_TYPES` | produces, consumes, implements, defines-contract-for, documents, depends-on, monitors, alerts-on, deploys, owned-by |
| `REL_STATUSES` | explicit, inferred, confirmed, disputed, retired (mixes extraction/validation/contestation/lifecycle — split per refactor) |
| `OBS_ROLES` | contract, code, runtime, doc, deployment, note |
| `COVERAGE_OUTCOMES` | human outcomes + runtime `needs-recheck` (added by `check`) |
| `PROPOSAL_KINDS` | steward*, skill*, config, decision, other (*legacy) |
| `PROPOSAL_STATUSES` | draft, proposed, accepted, rejected, deferred, landing, applied, verified, regressed, superseded |
| `PROPOSAL_TRANSITIONS` | `draft→proposed→accepted→landing→applied→verified`, `proposed→rejected/deferred`, `applied→regressed`, any→superseded (records.py:124-137) |
| `GATE_OUTCOMES` / `GATE_WHENS` | pass/fail/unk; land/deploy/use |
| `KTLO_STATUSES` | todo, investigating, in-progress, blocked, done, n/a |
| `INVESTIGATION_*` / `HYPOTHESIS_STATUSES` | open/monitoring/concluded/abandoned; open/supported/refuted/unk |
| `CORRECTION_KINDS` / row statuses | retract/dispute/supersede; pending/corrected/superseded/unresolved |

Readiness asymmetry (confirmed, handover §1.1): `proposal add` files as `draft`
when Research/Alternatives/gates are missing; `set --status proposed` from a
draft does **not** repeat those checks (`test_draft_to_proposed_is_legal`) —
intentional change required by the refactor.

Legacy gate exemption (confirmed): a proposal with **no** parseable Acceptance
gates table is let through with a warning (README.md:170-171); a *malformed*
modern table is an error. Legacy = "no table", not "failed parse".

## 7. Stores and write paths

KB root resolution (`storage.py:17-34`): `$KCTX_ROOT` if set, else walk up from
the **script's own location** to a `.git` dir. → In this standalone repo that
resolves to the code checkout, not the KB. §7.3 of the handover (root
precedence fix) applies before any installed deployment.

| Path (relative to KB root) | Writer | Authority |
| --- | --- | --- |
| `inventory/assets/*.json`, `inventory/relationships/*.json` | `asset/rel add` | canonical (Git) |
| `inventory/dossiers/<asset-id>.md` (+ `archive/`, `README.md` index) | `dossier` | canonical (Git) |
| `inventory/cursors/<org>__<repo>.json` | `admit` | canonical (Git) — scan cursor |
| `proposals/<kind>/<date>-<slug>/` (new) or `proposals/<kind>/<date>-<slug>.md` (legacy, never migrated) | `proposal` | canonical (Git) |
| `proposals/*/gates.json` | `proposal gate` | canonical, append-only |
| `ktlo/<YYYY>/…`, `investigations/<YYYY>/…`, `signatures/<slug>.md`, `corrections/<date>-<slug>.md` | respective commands | canonical (Git) |
| `runs/<run-id>/*` (manifest, observations, coverage, checkpoint) | `run/observe/cover/checkpoint` | canonical (Git) |
| `receipts/…` | `check` | canonical, numbered + revision-bound |
| `<project>/log/<date>.md` | `ktlo/inv promote` | canonical (Git) |
| Graph: `$KCTX_GRAPH_DIR` else `/workarea/kb-graph` (Space) else `~/.local/share/kb-graph`; Dolt db at `<graph>/dolt` | `graph sync` | **derived/shadow** — rebuildable; files win on disagreement (README.md:187-215) |
| Logs: `$KCTX_LOG_DIR` else `$XDG_STATE_HOME/kctx/logs/kctx.jsonl` else `~/.local/state/kctx/logs/kctx.jsonl` | every invocation | derived, rotated |

Write primitives: `atomic_write_json` (temp + fsync + `os.replace`),
`exclusive_write_json` (`O_CREAT|O_EXCL` + fsync) — durability/atomic-publication
limits per handover §1.1; `is_past_ttl` boundary = expired strictly after
`observed_at + ttl` (storage.py:156-163), missing TTL → `None` → never stale.

Graph sync reads `git archive` at HEAD (never worktree), replaces `nodes`/`edges`
tables, upserts `kb_commits` mapping, two commits (data + backfill)
(`graph/sync.py:41-104`). `--history N` replays last N first-parent commits.
Parity check (`graph check`) counts bindings via the real `cite.py` parser.

## 8. Dependencies and tooling

`pyproject.toml`: name `kctx` 0.1.0, `requires-python >=3.11`, deps
`pydantic==2.14.1` (mirror-lag pin documented in-file) and `structlog==26.1.0`
— **graph package only**; every other module is stdlib-only. `uv` never builds
kctx itself (script directory, not a distribution). `pyrightconfig.json`:
`extraPaths` + execution environments only — **no strict mode** (converge per
handover §11.2). `uv.lock` present (43.8 KB).

## 9. Baseline test result (this environment)

```
python3 -m unittest discover -s tests -q
Ran 266 tests in 1.158s — OK (skipped=30)
```

30 skips = graph-package tests probing for pydantic/structlog/dolt (absent in
the ambient interpreter). Handover's reference env (3.12.14): 242 pass / 24
skip. No failures either way. Each test docstring cites a `Qnn` scenario from
the *project-knowledge-workflow* handover (README.md:182-185) — that spec is not
available locally (see §11).

## 10. Corpus inventory — NOT available here

This checkout contains tool code only. No work-KB data (`inventory/`, `runs/`,
`proposals/`, …), no host config, no real citation artifacts. All corpus items
(record-family counts, duplicate IDs, malformed frontmatter, custom sections,
golden citation corpus) must be produced in the work environment before
migration gates (G10) run. Compatibility fixtures until then = the existing
266-test suite (deterministic, no network).

## 11. Missing prerequisites (discover at work, do not infer)

1. `cite` implementation + `LOCATORS.md` (dotfiles `.claude/skills/grounding/cite`) — the citation grammar authority.
2. Work KB corpus + host configuration (Spaces vs laptop paths, `/workarea`).
3. Gripsack environment definitions (Dolt pin, bbgithub remote).
4. `project-knowledge-workflow-handover.md` (R1–R20 / Q01–Q50 baseline) and `kctx-knowledge-base-evaluation-handover.md` — referenced, not locally present.
5. Prior qualification reports referenced by comments; Sovel compose setup (a `../sovel` workspace exists locally — inspect before writing `compose.yaml`).
6. Dolt binary (for G12 integration tests).

## 12. Baseline metrics

Suite wall time 1.16–1.33 s (ambient). Latency/subprocess/token metrics over a
real corpus: deferred to the work environment (G15 needs a corpus; predeclared
protocol lives in the consolidated handover).
