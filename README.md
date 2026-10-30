# kctx

A small CLI over the shared project-knowledge layer: inventory (assets,
relationships), runs (observations, coverage, receipts), and proposals. It
exists so advice, review, and authoring work share one place to record what
was checked, when, and under what evidence — instead of each agent session
reconstructing that from scratch or asserting it from memory.

Python 3 stdlib only. No PyYAML, no third-party packages. Works on the
laptop (bare `python3`) and on a Space (no bare `python3`; the wrapper falls
back to the newest `/opt/bb/bin/python3.1x`).

For durable `⟦cite …⟧` citations (making, re-verifying, and rendering them)
use the separate `cite` tool at `.claude/skills/grounding/cite` in dotfiles,
not a command here — see `LOCATORS.md` next to it. `kctx context` and `kctx
stale` shell out to that same script for citation freshness rather than
re-implementing its blob/span comparison; they look for it via `CITE_BIN`,
then `$CLAUDE_CONFIG_DIR/skills/grounding/cite`, then
`~/.claude/skills/grounding/cite`, then the dotfiles checkout, and report
citations as `unverifiable` (never `fresh`) if none of those exist.

## Running it

```
tools/kctx/kctx <command> [args...]
```

`KCTX_ROOT` overrides where it looks for `inventory/`, `runs/`, and
`proposals/`; otherwise it walks up from its own script location to find the
repo root. Add `--json` before the command for structured output; the
default is readable text.

Exit codes: `0` ok, `2` partial, `3` blocked, `1` error. Errors carry a
category (`not-found`, `malformed`, `stale`, `conflict`, `incomplete`,
`permission`, `timeout`) alongside the message.

## Commands

| Command | Does |
|---|---|
| `kctx validate` | Checks schema fields/enums, id uniqueness, relationship endpoint resolution, that every accepted/applied/landing proposal has `decided_by`, that every applied/verified proposal carries a `repo@sha` in `landed` or its Decision log, that every `ktlo/` record's `assets:` resolve to known asset ids (and that duplicate tickets are flagged), and the same for any `<project>/changes/*.md` change brief that carries an `assets:` frontmatter field. Also checks every investigation's `trigger`/`status` enums and `assets`/`alerts`/`signatures`/`spawned` id resolution, that a `concluded` investigation still carries non-empty Checked against + Scope and limits sections and no open Hypotheses bullet, every signature's `status` enum and `assets` resolution, and any `runbooks/*/*.md` frontmatter's `layer` enum and `alerts`/`assets` resolution (a runbook with no frontmatter at all is skipped, not flagged). Also checks that every `corrections/*.md` record's `target` resolves and every referrer row's `status` is one of `pending`/`corrected`/`superseded`/`unresolved`/`unchanged:<evidence>`. A ktlo record or change brief with an empty `assets:` list, a new-format proposal missing `origin`, or an investigation linked to a signature after that signature's `fixed_at` (`possible regression`), is a warning (`warnings`, not `problems`) rather than a failure. Never touches legacy per-project journal files. |
| `kctx asset add/show/list` | Manage `inventory/assets/*.json`. `show` resolves by id or by alias. |
| `kctx rel add` | Manage `inventory/relationships/*.json`. |
| `kctx dossier new <asset-id>` | Scaffolds `inventory/dossiers/<asset-id>.md`: frontmatter `asset:`/`updated:` plus the five fixed headings (Purpose, Interfaces, Main flows, Config & BREGs, Gotchas), filled in by hand with cited claims the same way a ktlo record's body is. Fails if the asset doesn't exist or the dossier already does. |
| `kctx dossier archive <asset-id> [--force]` | Moves `inventory/dossiers/<asset-id>.md` to `inventory/dossiers/archive/`. Refuses (`incomplete`) unless the asset's `lifecycle` is `retired`; `--force` overrides. |
| `kctx impact <asset> [--depth N]` | Bounded BFS over relationships in both directions. Always prints the coverage-boundary note: inventory absence is not proof of no consumers, and reports edges left unexplored when the depth budget runs out. |
| `kctx home <repo\|asset\|ticket>` | Resolves which project(s), `ktlo/` ticket record, or investigation a change or ticket belongs to: asset id/alias/locator, each project's `inventory.md`/`README.md`, `ktlo/` records' `ticket:`/`assets:`, and investigations' `tickets:`/`assets:`/`alerts:`. Each candidate carries its match evidence. No match still exits 2 with the coverage-boundary note, never silently empty. |
| `kctx context <repo\|asset> [--depth N]` | Compact context pack for an asset: the asset record (plus sibling assets sharing its locator), `kctx impact`, doc/dashboard/alert/runbook assets reached by impact, projects and `ktlo/` records that reference it (via `kctx home`), investigations touching it (via `kctx timeline`) plus the signatures they link and any runbook referencing it, runs whose manifest mentions it, its `inventory/dossiers/<asset-id>.md` if one exists (path + headings present), and a freshness block (`verified_at`/`ttl` plus a batched `cite check` over every referenced file, dossier included). |
| `kctx stale [--project P] [--offline]` | Assets past `verified_at` + `ttl`, citations due for attention over the project dir (or the whole repo) via `cite stale` (`--offline`: no network, due-by-age only; default: live reclassification), runs with `needs-recheck` coverage entries, `possible regression` flags (an investigation linked to a signature after that signature's `fixed_at`), and open (`pending`/`unresolved`) rows across `corrections/*.md`. A dossier citation is excluded from these totals unless its asset is listed by a project whose `STATUS.md` `phase` isn't `done`/`closed` — an unread dossier never floods the drain nag; `kctx context`/`kctx admit` still reach it directly. |
| `kctx stale --drain --project P` (or explicit paths) | Writes back `cite check --touch --mark` over the given project/paths, then reports what's left as judgment items grouped `expired_noncode`/`changed_gone_code`/`changed_gone_other`/`unverifiable` with `file:line`, plus any lines the write-back itself changed. Also reports every open (`pending`/`unresolved`) row across `corrections/*.md` (same as `kctx stale`'s own `open_corrections`, not scoped to `--project`) so a resumed session sees an open correction even when it only ran `--drain`. Exit `0` once nothing remains, `2` otherwise, `3` if citations are unavailable (never reported as clean). |
| `kctx admit --repo <org/repo> [--since <sha\|date>] [--dry-run]` | Event-driven complement to `stale --drain`: sweeps every commit on the default branch from the repo's cursor (`inventory/cursors/<org>__<repo>.json`) to head. Marks/touches only `kind=code` citations on changed paths (or a rename source) via `cite check --touch --mark`, rewrites `state=`/`seen=` on `kind=pr` citations found merged (via `gh`), and reports — never edits — the judgment items a merged change raises: STATUS/inventory lines, ktlo records, investigation follow-ups, open (`fixed_at`-less) signatures, and assets/dossiers whose locator is the repo. First run with no cursor requires `--since`; a cursor no longer reachable from head (force-push/rewrite) blocks rather than resets. `--dry-run` writes nothing. Exit `0` nothing left, `2` items remain, `3` blocked (no `gh`/clone, or an unreachable cursor — never reported as clean). |
| `kctx admit <PR url\|org/repo#N>` | Shortcut: resolves the PR's `merge_commit_sha` via `gh api`, diffs just that commit, and runs the same refresh/report as `--repo` without touching the cursor. Refuses an unmerged PR with exit `2`. |
| `kctx ktlo new <ticket> --title "..." [--asset ID]...` | Scaffolds `ktlo/<YYYY>/<ticket-slug>-<title-slug>.md`. Accepts `DRQS 123`, `{DRQS 123}`, `drqs-123`, or `RDTSPBP-123` and normalizes to a canonical `PREFIX-NUMBER` id. |
| `kctx ktlo promote <ticket> <project>` | Sets `promoted_to` on the ticket record and appends a pointer line to `<project>/log/<today>.md` (created from the template if missing). Idempotent: re-running after promotion is a no-op beyond confirming the pointer is still there. |
| `kctx inv new <slug> --trigger alert\|drqs\|wp\|rota\|request\|adhoc [--title ...] [--ticket ...]... [--alert ID]... [--asset ID]... [--window START/END]... [--impact-summary ...]` | Scaffolds `investigations/<YYYY>/<YYYY-MM-DD>-<slug>/README.md` plus sibling `evidence/` and `queries/` dirs, `status: open`. Section text, `signatures:`, and `follow_ups:` are filled in by editing the file directly, the same way a ktlo record's body is never driven through CLI flags. |
| `kctx inv list [--open] [--asset ID]` | Lists investigation frontmatter, optionally filtered to `open`/`monitoring` status or to one touching a given asset/alert id. |
| `kctx inv show <id>` | Frontmatter, section headings present, and the `evidence/`/`queries/` file listing. |
| `kctx inv conclude <id>` | Flips `status: concluded`. Refuses (`incomplete`) unless the Checked against and Scope and limits sections are non-empty and no `Hypotheses` bullet is still `open` (`unk` is allowed). |
| `kctx inv promote <id> <project>` | Sets `promoted_to` and appends a pointer line to `<project>/log/<today>.md`, mirroring `kctx ktlo promote`. Idempotent. |
| `kctx sig new <slug> [--title ...] [--match PATTERN]... [--match-where ...] [--asset ID]... [--owner-group ...] [--status ...] [--workaround ...] [--fix ...]... [--fixed-at ...] [--first-seen/--last-seen/--verified-at/--ttl ...]` | Scaffolds `signatures/<slug>.md`. `--match` patterns are literal substrings unless prefixed `re:`, in which case the remainder is a regex. |
| `kctx sig list` / `kctx sig show <id>` | List/show signature frontmatter and section headings. |
| `kctx match "<text>"` | Ranks known signatures whose `match` patterns hit the text (most patterns matched first), then full-text hits against investigation bodies and ktlo `Symptom` sections. Exits `2` with a coverage-boundary note when nothing hits anywhere — absence is never proof the failure is new. |
| `kctx timeline <asset\|alert\|sig\|ticket>` | Every investigation touching the given id (via `assets`/`alerts`/`signatures`/`tickets`), oldest first — "the 4th spike this month" made visible. |
| `kctx uses <ev:id\|sig:id\|inv:id\|proposal/kind/date-slug\|asset-id\|repo@sha:path:L>` | Reverse lookup over the citation/id graph: every tracked file (`git ls-files`) that literally mentions the target, grouped by kind (`notes/log`, `dossier`, `signature`, `investigation`, `ktlo`, `proposal`, `run coverage`, `other`); a `sig:`/`inv:`/`proposal/` id is also searched in its bare form, since both are used live in this repo. A `repo@sha:path:L` locator is matched against a citation's own `path=`/`L=` fields, not free-text file:line mentions. The target's own home record is flagged `self` rather than listed as a referrer. Always prints the coverage-boundary note: uncited reliance isn't traced. Exits `2` with no referrers. |
| `kctx retract <ev:id\|asset-id\|sig:id\|proposal/kind/date-slug> --reason "..." --kind retract\|dispute\|supersede [--by-replacement <target>]` | Appends a dated entry to the target's own `## Corrections` section (an `ev:`/dossier/`sig:` target) or `## Decision log` (a `proposal/` target), then runs `kctx uses` on it and writes every non-self referrer into `corrections/<date>-<slug>.md` with `status: pending` and a blank owner. Never edits a referrer. A dossier target also flips `kctx context`'s dossier block to show `open_corrections: true`. |
| `kctx run new --project P --mode advice\|review\|authoring --task "..."` | Creates `runs/<run-id>/` and prints the run id. |
| `kctx observe <run> --system ... --locator L [...]` | Records an immutable observation. With `--system git --locator <local path>`, auto-resolves the HEAD revision and, if the worktree is dirty, the sha256 of `git diff HEAD` — a test run against a dirty checkout is never silently attributed to the clean commit. |
| `kctx cover <run> --item I --outcome O [--evidence obs...] [--reason R]` | Records a coverage entry. Refuses `--outcome supported` unless at least one observation is cited and every cited observation has `status: ok` — no implicit pass. With two or more cited observations, also refuses when they all share the same `(source.system, source.locator)` origin — no independent corroboration at all; two-plus-one, where at least one observation traces to a distinct origin, is allowed. Any other outcome requires `--reason`. |
| `kctx check <run> [--require ITEM]...` | Re-resolves every git observation's revision/dirty state; anything that moved marks its dependent coverage entries `needs-recheck` (without deleting them) and gets listed as stale. Writes a numbered, revision-bound receipt under `receipts/` — an old receipt never certifies a later revision. Computes readiness: `ready`, `partial`, or `blocked` (when a `--require`d item isn't supported/violated). |
| `kctx resume <run>` | Prints the manifest, latest checkpoint, coverage summary, stale/needs-recheck items, and the last receipt. Read-only. |
| `kctx checkpoint <run> --note "..."` | Appends a dated section to `checkpoint.md`. |
| `kctx proposal add/list/set/gate/show` | Manage proposal records (see Proposals below for the lifecycle and the two on-disk layouts). `add` is idempotent on kind+title+date (refuses with `conflict` unless `--force`) and always creates a directory home. `set [--status S]` moves through the lifecycle one legal transition at a time (`accepted\|rejected\|applied\|landing` require `--by`; `regressed` requires `--note`; `applied\|verified` require their `land`/`deploy`+`use` gates to have passed); omit `--status` to update `--origin`/`--proposed-by`/`--requested-by`/`--swept-at`/`--landed` alone. `gate <id> <G#> --outcome pass\|fail\|unk --evidence ...` records a gate result. `show <id>` prints frontmatter, section headings, and gate status. `list --pending-gates` lists `applied` proposals with unrun `deploy`/`use` gates. |

## Records

Every JSON record and proposal frontmatter block carries `schema_version: 1`.
See `records.py` for the exact dataclass fields and `proposals.py` for the
frontmatter/body shape. One file per asset/relationship/observation keeps
concurrent writers merge-friendly — there's no single inventory file for two
runs to race on.

An asset's `verified_at` (when it was last checked) and `ttl` (`Nd`, `Nh`, or
`none`; set via `asset add --verified-at ... --ttl ...`) are both optional —
`kctx stale` only flags an asset past its ttl once both are set. `ktlo/`
records (one per one-off KTLO/DRQS ticket; see projects `CLAUDE.md` and
`ktlo.py`) are frontmatter + Markdown the same way proposals are, but with
Symptom/Evidence/Change/Outcome sections instead of proposals' five.

`investigations/` (`investigations.py`) and `signatures/` (`signatures.py`)
are the ops-knowledge-layer records for on-call and ad-hoc work: see projects
`CLAUDE.md` for the full section lists and frontmatter shapes, and the
`investigate` skill (dotfiles) for the workflow that drives them. `runbooks/`
is not a schema-enforced kctx record — it's free-form Markdown with optional
flat frontmatter (`layer`, `alerts`, `assets`), found by `kctx context`/
`kctx home` the same grep-ish way a project's `README.md` is.

`inventory/dossiers/<asset-id>.md` (`dossiers.py`) is per-system knowledge
keyed on an existing asset id — what a system does, how it's called, its main
flows, config/BREGs, and known gotchas — checked lazily by `kctx context`
rather than swept on a schedule. `inventory/dossiers/README.md` is a KB-wide
index, not a dossier, and `inventory/dossiers/archive/` holds retired ones;
both are skipped by `kctx validate`'s dossier checks.

## Operating guide

**Ordinary use (a review/advice/authoring run).**

```
run_id=$(tools/kctx/kctx --json run new --project <proj> --mode review --task "..." | python3 -c 'import json,sys;print(json.load(sys.stdin)["run_id"])')
tools/kctx/kctx observe "$run_id" --system git --locator /path/to/repo --role code
tools/kctx/kctx cover "$run_id" --item "does X still hold" --outcome supported --evidence <obs-id>
tools/kctx/kctx check "$run_id" --require "does X still hold"
```

Run `kctx check` again before delivering any state-dependent conclusion —
it's the thing that catches a moved git HEAD or a now-stale observation.
`kctx resume "$run_id"` at the start of a follow-up session to see where
things stand without re-deriving it from the log.

**Adding an asset.** `kctx asset add --kind <kind> --name <name> [--alias ...] --locator <where> --owner <who-or-unknown> --owner-source <where-that-came-from> ...`, then `kctx rel add` for anything it produces/consumes/depends on, with `--evidence` pointing at the doc or commit that states the relationship. Run `kctx validate` afterward.

**Recovery.** Observations and relationships are append-only files written
exclusively (`O_EXCL`) or via temp-file-then-rename; a crash mid-write leaves
either nothing (the exclusive case) or an orphaned `.tmp-*` file next to the
real one (everything else), never a corrupted real file. `kctx resume`
ignores stray temp files since it only globs `*.json`. If a run looks
inconsistent, `kctx check` is the re-derive-from-evidence step — it doesn't
trust cached outcomes, it recomputes staleness from the actual observations.

**Reconciling proposals.** `kctx proposal list --status proposed` to see
what's pending. A proposal is an observation/hypothesis/suggestion, not
policy, until a human runs `kctx proposal set <id> --status accepted --by
"<who> <date>"` — `kctx validate` will flag any accepted/applied/landing
proposal missing `decided_by`.

## Proposals

A proposal record lives at `proposals/<kind>/<date>-<slug>/proposal.md` (a
new filing), or `proposals/<kind>/<date>-<slug>.md` (a proposal filed before
this layout existed). Every command reads both layouts; a legacy proposal is
never migrated into a directory, since its id is referenced from commits and
other notes. A new filing's directory also holds `research/` and
`evidence/` (for material too small to belong in scratch) and `gates.json`
(append-only gate results — see `gates.py`).

`kctx proposal add` requires `--origin` (`steward`, `user-request`,
`suggest-skills`, `review-finding`, `consolidation`, `other`, or `unk`) and
takes `--research`, `--alternatives`, `--gates` (a Markdown table, or a path
to a file holding one), `--impact` and `--plan` for the sections between
`Proposed change` and `Why general / justification`. A filing missing a
Research section (or a one-line justified skip), two or more Alternatives
considered, or a parseable Acceptance gates table is written as `draft`
instead of `proposed` — the review flow (the `evolve` skill in dotfiles)
keeps it out of sight until those are filled in.

The lifecycle (`kctx proposal set <id> --status <new>`):

```
draft → proposed → accepted → landing → applied → verified
           ↘ rejected   ↘ deferred         ↘ regressed
any → superseded
```

`accepted`, `rejected`, `applied` and `landing` require `--by`; `regressed`
requires `--note`. Moving to `applied` or `verified` additionally requires
every gate in the Acceptance gates table whose `when` is `land` (for
`applied`) or `deploy`/`use` (for `verified`) to have its latest recorded
outcome be `pass` — record outcomes with `kctx proposal gate <id> <G#>
--outcome pass|fail|unk --evidence "<cite or obs/ev locator>"`. A legacy
proposal with no Acceptance gates table at all is let through with a warning
rather than blocked, so pre-gates history isn't broken. `kctx proposal list
--status applied --pending-gates` lists applied proposals still waiting on a
`deploy` or `use` gate. `kctx proposal show <id>` prints frontmatter, section
headings, and each gate's latest outcome without a raw file read.

## Tests

```
python3 -m unittest discover -s tools/kctx/tests
```

Deterministic, no network. Git-backed tests create throwaway repos under a
per-test temp directory (via `KCTX_ROOT`), never touching the real
workspace. Each test name/docstring cites the qualification-suite scenario
(Qnn) it covers, from the project-knowledge-workflow handover spec.

## Graph (shadow mode)

M2 shadow mode, per `decision/2026-10-30-adopt-dolt-handover-v2-staged-m2-
shadow-mode-for-citation-bindings-and-relationships-superseding-git-files-
canonical-and-the-sqlite-mirror-decisions`. Files stay the single write
authority — everything under `inventory/`, `signatures/`, `proposals/`,
`investigations/`, every evidence record, and every other tracked
`.md`/`.json` file. `kctx graph sync` extracts citation bindings and typed
relationships from those files at one kb git commit and replays them into a
local Dolt database; `kctx graph uses`/`impact`/`diff`/`check` read and
traverse that graph. No agent writes SQL directly, and the graph is never
authoritative over the files it was built from — where the two disagree,
the files win and the graph is stale until the next sync.

**Running kctx.** `tools/kctx/kctx` now runs everything through `uv run
--project tools/kctx`, which installs the graph package's two dependencies
(pydantic, structlog) into a local `.venv` on first use — there's no silent
fallback to a bare `python3` if `uv` isn't found; the wrapper prints exactly
where it looked (`$PATH`, `~/.local/bin`, `/usr/local/bin`, `/bb/bin`) and
exits. Every other kctx module stays stdlib-only: `tools/kctx/graph/` is the
only part of the tree that imports a third-party package, so
`python3 -m unittest discover -s tools/kctx/tests` still runs every
non-graph test with no venv at all, and the graph package's own tests skip
cleanly (not with an error) when pydantic/structlog/dolt aren't available in
whichever interpreter is running them.

**Location.** `$KCTX_GRAPH_DIR`, else `/workarea/kb-graph` on a Space, else
`~/.local/share/kb-graph` on the laptop — always outside the kb working
tree, so a `rm -rf` of the graph directory never touches a kb file.

**Commands** (all take `--json`; compact text otherwise):

- `kctx graph sync [--rebuild] [--history N]` — extracts from tracked
  `.md`/`.json` files at kb's current HEAD and replays into Dolt. Reads via
  `git archive` at that commit, never the working tree, so an in-progress
  edit in a concurrently-dirty checkout never leaks into the shadow graph.
  A no-op if HEAD is already synced. `--rebuild` deletes and recreates the
  Dolt database first. `--history N` additionally replays the last N
  first-parent kb commits that touched tracked files, so `diff`/`AS OF`
  queries have more than the current snapshot to compare against.
- `kctx graph status` — sync state, node/edge counts, and whether the graph
  matches kb's current HEAD.
- `kctx graph uses <id> [--limit N] [--include-illus]` — direct inbound
  edges into an id, grouped by relationship type. Direction-aware: unlike a
  literal-substring scan, it won't mistake a record's own outgoing
  relationship for something depending on it.
- `kctx graph impact <id> [--depth N] [--rel TYPE ...] [--limit N]` —
  transitive inbound dependents, one row per dependent with its shortest
  path and depth; bounded by `--depth` and cycle-safe (a cycle just means a
  node is reachable at more than one depth, not an infinite query).
- `kctx graph diff <kb-sha-a> <kb-sha-b> [--limit N]` — edges added,
  removed, and modified between two kb commits, grouped by relationship
  type, plus a sample of the individual rows. Each kb sha is resolved to its
  Dolt commit via the `kb_commits` mapping table that `--history` builds.
- `kctx graph check [--sample <id> ...]` — the shadow-parity check: the
  graph's citation-binding count against a direct parse of the same files
  with the grounding skill's own `cite.py` parser, plus (for each `--sample`
  id given) a comparison of `kctx graph uses` against `kctx uses`.

**Logs.** `kctx logs [--run <id>] [--last N]` prints the events of the most
recent (or a given) invocation from the structured JSONL log — the
debugging entry point for an agent when a sync or a query needs explaining,
without needing the original terminal output. Every invocation gets a
run_id and a span around each notable step (dolt/git subprocess calls
included: argv, exit code, duration, a truncated stderr tail). Logs land at
`$KCTX_LOG_DIR`, else `$XDG_STATE_HOME/kctx/logs/kctx.jsonl`, else
`~/.local/state/kctx/logs/kctx.jsonl`, rotated by size. Nothing prints to
the console by default; `-v`/`--verbose` or `KCTX_LOG=debug` turns on
concise human-readable output to stderr too.
