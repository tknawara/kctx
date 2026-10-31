# Port queue: flat modules → `src/kctx` package (handover §7.1)

The full typed refactor, executed as reviewable slices with the suite green
at each step (handover §1.8 forbids the one-diff big-bang; G18 rejects
unreviewable changes). Each landed slice: types threaded, all tests green,
committed and pushed. The frozen fixture suite (322 tests) is the behavior
contract throughout — "faithful to the handover" means behavior-preserving
except where the handover itself mandates a change (readiness predicate,
corrections ordering, cursor semantics, gate binding — all landed earlier).

## Landed

| Slice | What moved | Notes |
| --- | --- | --- |
| semantics | `src/kctx/semantics/` | The proved core: pure typed decisions, Lean-mirrored, conformance 35/35. |
| domain ids | `src/kctx/domain/ids.py` | Nominal validated ids (asset/evidence/relationship namespaces); wired at the inventory boundary. |
| domain targets | `src/kctx/domain/targets.py` | `uses`-target spellings parsed once into a closed sum; fixtures pin the six variants and widening rules. (nav.py wiring is queued below — the parse module + tests land first.) |
| graph package | `graph/` → `src/kctx/graph/` | Self-bootstrapping under both import styles; all imports fixed (cli, kctx.py, 7 test files). |
| observability seam | `src/kctx/observability.py` | Entry-point logging no longer couples every invocation to the graph package (§7.2); graph owns the structlog impl behind the seam during the port. |
| config layer | `src/kctx/config.py` | One `config.toml`, no layering (`docs/kctx/config.md`). Wired: root/cite_bin/cite_py/graph_dir/log_dir. All legacy env vars (KCTX_ROOT, CITE_BIN, KCTX_CITE_PY, KCTX_GRAPH_DIR, KCTX_LOG_DIR) removed from production modules; `KCTX_CONFIG` is the single remaining knob. 13 fixtures. |
| frontmatter codec | `src/kctx/codecs/frontmatter.py` | Shared parser with duplicate-key diagnostics; `storage.py` delegates. |
| entry | `kctx.py` | Puts `src` on sys.path; logging via the seam; `-v` consumed at the boundary. |

## Queue (dependency order)

1. **domain records + codecs** — typed `Asset`/`Relationship`/`Observation`/
   `Proposal` decode→validate→object in `domain/` + `codecs/` (flat-Markdown
   document codec with span preservation per §7.4); `records.py` and the
   storage frontmatter helpers become codecs clients.
2. **storage → adapters/files** — root precedence fix (§7.3: `--root` →
   `KCTX_ROOT` → config → KB marker from cwd; never any git repo), JSON
   codecs, time utilities split out.
3. **services** — inventory, proposals/gates, investigations/signatures/
   ktlo/dossiers, corrections, runs (observation/coverage/receipts), admit,
   nav (context/stale/uses/home/timeline), validate orchestrator; each calls
   `kctx.semantics` for decisions and `domain` types internally.
4. **cli dispatch** — `cli/` package; flat `cli.py` deleted at the end of
   the slice that removes its last import.
5. **root-module deletion** — when the last service lands, the flat modules
   are deleted (no shims): imports in tests move to the package in the same
   commit.

## Constraint notes

- Tests are the contract: any red test stops the slice.
- The conformance harness (`scripts/conformance_check.py`) and contracts
  check (`scripts/check_contracts.py`) run at every checkpoint.
- Nagini/Viper: **landed for the freshness leaf** — compose profile `nagini`
  (JVM + Viper + nagini 1.3.1, python 3.12) verifies `assess_fresh_contracts.py`
  ("Verification successful"), `twin_drift_check.py` asserts the executed
  runtime twin is token-identical to the verified body, and
  `equivalence_grid.py` runs 100 cases against production `assess_fresh`.
  Extending to further leaves (checker guards, usable_for) follows the same
  twin+guard+grid pattern; whole-core refinement remains out of scope.
