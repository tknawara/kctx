# kctx gate report

This report supersedes the earlier v1 “22/22” delivery claim. The audit found
substantive semantic and persistence defects; the current implementation uses
semantic version **2.0.0**, nominal Python/Lean identities, authenticated admission,
immutable native snapshots, and one Click/stdio application.

A kernel build, host correspondence, adapter qualification, and model usefulness
are different evidence. A fixture name or a skipped capability is not a pass.
Enterprise endpoint qualification is explicitly owned by the user's work agent;
local native transports do not stand in for it.

## Verified checkpoint

The complete Compose `verify` job exited zero and printed `VERIFY_ALL_OK`.
A final human-help color correction was then checked with the full Python
quality job and rebuilt installed-runtime smoke; backend and formal sources
were unchanged.

- Ruff lint/format and strict Pyright: **127 files, zero diagnostics**.
- Python boundary contracts: valid consumer accepted; **10 ID/enum misuse sites rejected**.
- Final behavioral suite: **663 passed, zero failures/errors/skips** (`test-report.json`).
- Clean Lean 4.21.0 build: T01–T22 mapped, **194 registered declarations audited**,
  no open obligations or unapproved axioms (`formal/proof-report.json`).
- Six Lean namespace/nonempty misuse fixtures rejected.
- Lean/Python: **280 cases, zero mismatches** — 149 reviewed fixtures,
  112 generated cases, 19 stateful cases; **7/7 semantic mutants killed**.
- Real CLI/Dolt smoke checks exact source, target, revision and citation bytes.
- Nagini/Viper: two annotated leaves verified; twin-body guards pass; production
  equivalence grids pass **100 freshness cases and 128 policy inputs**, no skipped corners.
- Installed runtime without Lean/Lake/Elan/Docker/formal files passes the ordinary
  CLI smoke and real TTY/JSON/JSON-RPC stream probes. Final evidence: [runtime-ui-final.json](reports/runtime-ui-final.json).

Execution reports record the checkout parent revision plus source/fixture digests;
those digests identify the tested working tree, not the parent revision alone.
The behavioral source/fixture SHA256 is
`0373e4de96b181be97bc3e31c94402f57adb62e22afc75db1ab16ef00739bdc2`.
The clean formal source SHA256 is
`50e7b86725191aed583861a33aa73a2aba28aa5d6d0d4b7a8d043a154ad82b68`.
The native/evaluation campaigns share the `921437a` runtime source snapshot.
Only `cli/app.py` and `cli/help.py` changed afterward, to apply explicit color
before Click's eager help and honor that choice in both renderers.
[Exact source-delta linkage](reports/qualification-linkage.json) records both
hashes and the final verification; old reports keep their original identities.

## G00–G18 disposition

| Gate | Current disposition | Evidence and boundary |
| --- | --- | --- |
| G00 Baseline | Pass | [Discovery](discovery.md), original archive identity and compatibility inventory retained. |
| G01 Toolchains | Pass on Linux amd64 Compose | Locked Python quality job, Lean 4.21.0, native Dolt 2.6.1; no required dependency skips. Git and the GitHub CLI ship in images. |
| G02 Types | Pass on migrated package | Frozen nominal IDs, plain enums, strict codecs, whole-package strict typing, Python negative consumers and Lean compile-fail fixtures. Unknown optional identities are `None`/`Option`, never empty valid IDs. |
| G03 Language | Pass for declared v2 vocabulary | [Calculus](calculus.md), [revision decisions](calculus-revision.md), independent derivability/interpretation, exact inventory certificates, four-valued support and inhabited negative examples. No source/provider/Dolt primitives in the kernel. |
| G04 Proofs | Pass for registered bounded contracts | Clean registry-driven proof report. [Theorem registry](../../formal/theorems.json) states each meaning and assumption; it does not claim Python, signatures or durable storage are kernel-proved. |
| G05 Correspondence | Pass | `conformance-report.json`: full response/cardinality/identity checking, reviewed/generated/stateful fixtures, mutation campaign; separate Nagini leaf assurance. |
| G06 Workflows | Pass for implemented operations | Real proposal/gate/landed-ref, investigation, correction, run/provenance and authenticated knowledge tests in the final suite; services use shared semantic predicates. Acquisition, structural completion, admission and usability remain separate. |
| G07 Compatibility | Pass with documented intentional changes | Built-in citation grammar replaces supplied external script; lossless Markdown/CRLF/unknown-section edits, legacy layouts and explicit schema refusal exercised. v1 semantic wire is replaced by strict v2; old citation executable and argparse shims are removed. Native Click global options precede commands. |
| G08 Persistence | Pass for local POSIX process-failure scope | Full native fault campaign plus corrected concurrency capture; immutable files, competing publishers, pinned readers and replay are exercised. See the source-bound storage/repair reports below. Not a cross-store transaction or hostile-writer/hardware-power-loss proof. |
| G09 CLI/agent use | Pass for current CLI and protocol | Installed Click commands and JSON-RPC initialize/citation/signed admission/retrieval/graph-refresh/EOF paths exercised. Structured errors, bounded contexts, honest completeness, explicit config roots, terminal escaping and clean machine streams. |
| G10 Migration | Pass on representative synthetic copies | Account/quarantine/stage/apply/repeat/restore and retained-selection cases passed. Exact bytes and IDs are checked; no claim that the user's production KB was migrated. |
| G11 Graph snapshots | Pass for local native generations | Complete package fingerprints, config/schema/engine/repository identity, isolated candidates, exact binding parity, 14 graph process-death boundaries, competing writers and pinned reads exercised. |
| G12 Dolt backend | Pass for pinned local Dolt 2.6.1 | Normalized typed rows, immutable commits, read-only SQL sessions, real SQL errors and historical publication checks. Native tests are not replaced with mock SQL/storage semantics. |
| G13 Remote | Local transports passed; enterprise user-owned | Final local report exercises independent Git/native-Dolt clients and interrupted pushes. Actual enterprise authentication/policy/retention remains with the work agent by explicit user decision; no enterprise-pass claim. |
| G14 Restore/history | Pass for local native restore profile | Independent restore after source removal, retained objects after native GC, explicit missing-store failure and authorized rollback/rollforward passed. Normal Git clone alone is not a complete restore; enterprise retention policy remains separate. |
| G15 Cost/usefulness | Candidate meets frozen local profile; baseline failure retained | Mechanical cost thresholds pass. Candidate answers match every frozen label with no regressions. The strict both-arm importer remains nonzero for one baseline-only label mismatch; it is not relabelled or retried away. See measured results and the explicit profile limits below. |
| G16 Runtime separation | Pass on installed Linux artifact | Runtime contains Python/Git/Dolt/gh, not Lean/Docker/formal files. Installed and module CLI paths, citation RPC and human/machine output probes pass. |
| G17 Cutover | Qualified for implemented local capabilities | Authored files remain authoritative for authored records; native structured knowledge is authoritative only through authenticated completed releases. No two independent writers for a field or silent legacy fallback. Enterprise deployment and production-corpus qualification are not inferred from local fixtures. |
| G18 Delivery | Complete implementation and evidence | Verified source checkpoint `921437a`; current operator/design docs, proof/conformance results and retained qualification receipts are delivered in this Git tree. Failed attempts and scope limits remain visible. |

## Native process evidence

The [full storage campaign](reports/qualification-final/storage/report.json)
retains **31 passed case rows and one timeout**. The timeout exposed a harness
hazard: it collected concurrent workers' pipes sequentially. A later writer could
fill stderr while holding the writer lock, while collection waited for the first.

The [concurrency repair campaign](reports/qualification-final/concurrency-repair/report.json)
uses independent temporary capture files and supervised process cleanup; all four
case rows pass, including prerequisites. It repeats immutable-file creators,
graph writers with a pinned reader, and competing signed knowledge publication.
The graph reader made 76 unchanged historical reads; the writers returned
`synced` and `up-to-date`. The retained captures include 92,664 reader stderr bytes
and 71,037 publishing-writer stderr bytes, without pipe backpressure.
Production storage semantics and timeout thresholds were not weakened.

Together these reports cover every case in the full campaign. The original
nonzero report is not rewritten into a pass. Runtime source fingerprints match;
the capture-harness revision is recorded separately. The final
[local transport report](reports/qualification-final/remote/report.json) also
passes after using the corrected capture primitive.

## Material findings retained

- v1's blanket evidence-truth premise and nonrecursive support were not a sound
  knowledge-admission model. V2 requires exact proposition-specific attestation
  leaves, recursive witnesses and independent finite-domain interpretation.
- False coverage, scope widening, incomplete replay identity and self-issued
  approval were repaired in both hosts and exercised with independent expectations.
- Mutable Dolt working-state reads, null/incomplete “current” snapshots, cross-KB
  ownership, destructive rebuild history and count-only parity were repaired.
  [Original native counterexamples](reports/dolt-before-repair.json) remain retained.
- Historical citation coordinates and originating times are no longer rewritten
  into current observations; current checks use separate advisory fields.
- Acquisition helpers now reject source escapes and repository-controlled helpers;
  regex redaction is isolated/bounded; signing/recovery revalidate complete inputs.
- Lone UTF-16 surrogate escapes previously diverged between Lean and Python;
  both now reject them. Deep malformed RPC arrays no longer terminate the server.
- A changed installed JSON decoder previously left graph identity unchanged.
  Complete package fingerprints now include it and newly added modules without
  importing those modules just to hash them.

## Evaluation identity correction

The first 48 real stateless model calls matched all outcome/scope/inference
fields but failed every exact result because the source notes did not explicitly
name an evidence-record ID separately from their ticket citation target. Raw
receipts and the failing importer result are retained under
[model-trials](reports/model-trials/validation/report.json).

Corpus 1.0.2 adds validated `evidence_id` metadata to the authored notes. It does
not change task prompts, expected labels, partitions, thresholds or the model
system prompt/schema. The correction and generator digest are frozen in
`fixtures/qualification/corpus-lock.json`. Both attempts remain distinguishable.
The completion harness exposes its `default` routing alias and invocation IDs,
not a resolved provider-model identity; this limitation is recorded, not invented.
Byte/IO/context proxies are labelled as proxies, never actual model-token usage.

## Measured local results

[Mechanical report](reports/qualification-final/evaluation/report.json):
432 matched retrieval measurements, two projects, frozen task protocol, source
stable throughout. Warm totals aggregate five repetitions per task.

| Measurement | File baseline | Existing index | Native Dolt session |
| --- | ---: | ---: | ---: |
| Cold p95, ms | 238.53 | 326.89 | 1499.49 |
| Warm p95, ms | 12.58 | 4.12 | 6.31 |
| Warm source bytes read, proxy | 563420 | 71222 | 54310 |
| Warm subprocess count | 650 | 302 | 290 |
| Warm context bytes, proxy | 87320 | 87320 | 87320 |

The candidate meets the predeclared file-baseline limits for warm latency,
context size and repeated source reads. It does **not** beat the warm existing
index, and its native startup cost remains material. Memory, native private
storage, refresh/setup costs and history growth are retained in the report;
worker/child RSS samples are not summed into fictitious simultaneous peak memory.
The benefit is persistent, pinned relational/history queries with reduced repeated
source reads, not a claim that Dolt wins every latency comparison.

[Actual model receipts](reports/model-trials-1.0.2/receipts.json) and
[strict validation](reports/model-trials-1.0.2/validation/report.json):

| Arm | Exact labelled answers | Tasks |
| --- | ---: | ---: |
| File baseline | 23 | 24 |
| Dolt candidate | 24 | 24 |

All paired retrieved payloads are byte-identical. The one baseline answer used
`incomplete` rather than `unknown` for `atlas-07`; it retained the correct evidence
ID/scope and made no unsupported positive inference. This difference is not
attributed to the database or presented as improved model reasoning.

The unmodified strict importer requires perfect answers in both arms, so its
nonzero result is retained. The handover's candidate acceptance criterion is no
correctness regression or new unresolved candidate failure; the candidate meets
that criterion without changing any label, threshold, prompt, schema or model
answer. [Reviewed assessment](reports/evaluation-assessment.json) binds those
decisions to the raw report hashes. These are synthetic, stateless matched
judgment tasks under the recorded routing configuration—not production-corpus
generalization, autonomous tool-use quality, or a resolved-provider-model pin.

## Reproduce

```sh
docker compose --profile verify run --build --rm verify
docker compose --profile nagini run --build --rm nagini
docker compose --profile verify run --build --rm runtime

docker compose --profile verify run --rm verify python scripts/qualify_storage.py \
  --section all --output docs/kctx/reports/qualification-final/storage
docker compose --profile verify run --rm verify python scripts/qualify_remote.py \
  --local-only --output docs/kctx/reports/qualification-final/remote
docker compose --profile verify run --rm verify python scripts/evaluate_kctx.py \
  --output docs/kctx/reports/qualification-final/evaluation
```

Proof and conformance are required, not silent optional jobs. Failed or blocked
qualification cases return nonzero. Reports retain exact commands, input/source
identities and raw failures; only explicitly exercised scopes receive pass claims.
