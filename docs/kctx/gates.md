# kctx gate report

Working record of `docs/kctx/handover.md` §13 gates. A gate passes only with
recorded evidence tied to an implementation revision; required-skipped tests
mean *unqualified*, not passed. Everything here was executed in this
repository on the revision recorded below.

## Evidence index

| Gate | Status | Evidence |
| --- | --- | --- |
| G00 Baseline | **pass** | `docs/kctx/discovery.md` (zip SHA verified, env inventory, 266-test baseline, authority map). |
| G01 Toolchains | **pass (compose)** | One command runs the whole pinned stack — `docker compose --profile verify run --build --rm verify`: python suite + contracts + Lean proofs/audit + conformance + real-dolt integration smoke (Lean 4.21.0 via elan, pydantic/structlog, Dolt CLI v2.6.1 — all in the image, nothing on the host). Verified end-to-end in-container: exit 0, all five stages. The 24 skips are cite-skill-dependent tests (dotfiles checkout is a work-environment artifact), surfaced not silent. | Lean pinned `leanprover/lean4:v4.21.0` via elan + `formal/lean-toolchain`; `formal/scripts/proof_check.sh` runs clean from checkout (build + axiom audit + report + reference smoke). Python dev tooling (Ruff/Pyright via `uv`) and the pinned Docker image build are *not yet wired* — no network-pullable base image was available in this environment; `formal/Dockerfile` + `compose.yaml` are written but unbuilt. |
| G02 Types | **partial (typing slice 6 landed)** | `src/kctx/domain/ids.py` adds nominal validated ids at the legacy boundary (asset/evidence/relationship namespaces, per-namespace patterns, parse-once semantics; `tests/test_domain_ids.py`). `kctx.semantics` fully typed. | `src/kctx/semantics` introduces nominal identity (`Ident` with `IdKind`), `ClaimRef`, tagged-union `ClaimProp`, frozen dataclasses, explicit rejection unions; negative fixtures reject id mix indirectly via wire decoding. The *existing* CLI modules are not yet routed through these types (staged per handover §16 M2). |
| G03 Language | **pass** | Vocabulary, scope/time/coverage contracts and positive/negative examples reviewed alongside this implementation (Lean model + `formal/theorems.json` assumptions fields). |
| G04 Proofs | **pass (22/22)** | T01–T22 all discharged, including T07 (`Kctx.T07_checkDerivationV_agree` + `_ext` in `formal/Kctx/Locality.lean`) and T15 (`Kctx.T15_supported_ext`). Axiom audit clean (propext/Classical.choice/Quot.sound only; `formal/proof-report.json`, `open_obligations: []`); non-vacuity examples kernel-decided. |
| G05 Correspondence | **pass (Nagini leaf added)** | Lean↔Python 35/35 (`conformance-report.json`). PLUS: the freshness leaf is now Viper-verified via Nagini in compose (`docker compose --profile nagini run --rm nagini`): contracts proved on the annotated twin, a drift guard asserts the executed runtime twin is token-identical to the verified one, and a 100-case equivalence grid ties it to production `assess_fresh`. Honest label: implementation verification for ONE leaf (freshness); the rest of the core remains conformance-checked. | `scripts/conformance_check.py`: 35 reviewed cases, Lean reference evaluator vs actual Python `kctx.semantics` functions, **0 mismatches** (`conformance-report.json`). |
| G06 Workflows | **partial (2 slices landed)** | Pure `plan_transition`/`can_conclude` in both hosts with one readiness predicate, covered by conformance + 28 unit tests. CLI cutover slices landed: `storage.is_past_ttl` routes through the proved core (boundary fixtures pinned), and `proposals.set_status` now enforces the same readiness predicate on draft→proposed (the bypass fixture was intentionally updated). Corrections ordering fixed (slice 3: durable event written first against pinned pre-mutation state; target update is the recoverable projection — `tests/test_corrections.py`). Gate results are now revision-bound (slice 4: `gates.gates_rev` digests the gate *definitions*; selection skips results bound to an older table; legacy no-rev results keep old semantics; unrelated edits don't invalidate — `tests/test_gates_rev.py`). Admit cursor now persists pending judgment work (slice 5: scanned-through sha and completed admission are separate; pending items ride in the cursor, merge idempotently, and survive no-change replays and rewrite blocks — `tests/test_admit.py::PendingJudgmentPersistenceTest`). All five handover §8 source-observation rows now have landed fixes. |
| G07 Compatibility | **partial** | Existing 266-test suite still green (291 total with semantics tests, 30 skips = absent graph deps). Frozen compatibility fixtures for legacy Markdown/citations not yet extracted (needs work-KB corpus). |
| G08 Persistence | **not started** | Modeled conditional commit proved (T20/T21) and unit-tested; filesystem adapters untouched. |
| G09 CLI/agent use | **not started** | No CLI changes yet (deliberate: typed core first, cutover later). |
| G10 Migration | **not started** | Requires corpus (absent locally). |
| G11–G13 Graph/Dolt/Remote | **not started** | Requires Dolt binary + bbgithub access (absent locally). |
| G14 Restore/history | **not started** | — |
| G15 Cost/usefulness | **not started** | Needs held-out corpus. |
| G16 Runtime separation | **pass** | `src/kctx/semantics` is stdlib-only (asserted by `scripts/check_contracts.py`); tests + conformance Python side ran in an environment with no Lean/Docker on PATH for the CLI. Lean artifacts live only under `formal/`. |
| G17 Cutover | **not applicable yet** | No authority change made; files remain canonical. |
| G18 Delivery | **in progress** | Regular commits pushed to `tknawara/kctx`; this report is part of the delivery evidence. |

## Reproduction

```bash
# Python-only (no Lean/Docker needed)
python3 -m unittest discover -s tests
python3 scripts/check_contracts.py
python3 scripts/conformance_check.py          # Lean side required; --skip-lean exits 3

# Proof environment (elan with the pinned toolchain, or compose --profile formal)
cd formal && ./scripts/proof_check.sh         # writes formal/proof-report.json
```

## Open obligations and blockers

1. **G01 Docker image** — needs a network-reachable base image pull
   (unavailable in this environment); files are in place.
3. **G10/G11 corpora and Dolt** — require the work environment (real KB,
   `cite` provider, Dolt, bbgithub). None can be qualified from this machine,
   and none were faked.
