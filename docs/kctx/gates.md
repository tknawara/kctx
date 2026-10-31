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

The complete Compose `verify` job exited zero and printed `VERIFY_ALL_OK`:

- Ruff lint/format and strict Pyright: **127 files, zero diagnostics**.
- Python boundary contracts: valid consumer accepted; **10 ID/enum misuse sites rejected**.
- Behavioral suite: **662 passed, zero failures/errors/skips** (`test-report.json`).
- Clean Lean 4.21.0 build: T01–T22 mapped, **194 registered declarations audited**,
  no open obligations or unapproved axioms (`formal/proof-report.json`).
- Six Lean namespace/nonempty misuse fixtures rejected.
- Lean/Python: **280 cases, zero mismatches** — 149 reviewed fixtures,
  112 generated cases, 19 stateful cases; **7/7 semantic mutants killed**.
- Real CLI/Dolt smoke checks exact source, target, revision and citation bytes.
- Nagini/Viper: two annotated leaves verified; twin-body guards pass; production
  equivalence grids pass **100 freshness cases and 128 policy inputs**, no skipped corners.
- Installed runtime without Lean/Lake/Elan/Docker/formal files passes the ordinary
  CLI smoke and real TTY/JSON/JSON-RPC stream probes. Evidence: [runtime-ui.json](reports/runtime-ui.json).

Execution reports record the checkout parent revision plus source/fixture digests;
those digests identify the tested working tree, not the parent revision alone.
The behavioral source/fixture SHA256 is
`75cf3b480d8f500c2537280989f5f0372266a7a8e84c080d6c826868fe06f71b`.
The clean formal source SHA256 is
`50e7b86725191aed583861a33aa73a2aba28aa5d6d0d4b7a8d043a154ad82b68`.

## G00–G18 disposition

| Gate | Current disposition | Evidence and boundary |
| --- | --- | --- |
| G00 Baseline | Pass | [Discovery](discovery.md), original archive identity and compatibility inventory retained. |
| G01 Toolchains | Pass on Linux amd64 Compose | Locked Python quality job, Lean 4.21.0, native Dolt 2.6.1; no required dependency skips. Git and the GitHub CLI ship in images. |
| G02 Types | Pass on migrated package | Frozen nominal IDs, plain enums, strict codecs, whole-package strict typing, Python negative consumers and Lean compile-fail fixtures. Unknown optional identities are `None`/`Option`, never empty valid IDs. |
| G03 Language | Pass for declared v2 vocabulary | [Calculus](calculus.md), [revision decisions](calculus-revision.md), independent derivability/interpretation, exact inventory certificates, four-valued support and inhabited negative examples. No source/provider/Dolt primitives in the kernel. |
| G04 Proofs | Pass for registered bounded contracts | Clean registry-driven proof report. [Theorem registry](../../formal/theorems.json) states each meaning and assumption; it does not claim Python, signatures or durable storage are kernel-proved. |
| G05 Correspondence | Pass | `conformance-report.json`: full response/cardinality/identity checking, reviewed/generated/stateful fixtures, mutation campaign; separate Nagini leaf assurance. |
| G06 Workflows | Pass for implemented operations | Real proposal/gate/landed-ref, investigation, correction, run/provenance and authenticated knowledge tests in the 662-case suite; services use shared semantic predicates. Acquisition, structural completion, admission and usability remain separate. |
| G07 Compatibility | Pass with documented intentional changes | Built-in citation grammar replaces supplied external script; lossless Markdown/CRLF/unknown-section edits, legacy layouts and explicit schema refusal exercised. v1 semantic wire is replaced by strict v2; old citation executable and argparse shims are removed. Native Click global options precede commands. |
| G08 Persistence | Final process qualification running | Real concurrent publication and failure/recovery regressions pass in the suite; final source-bound fault campaign is `reports/qualification-final/storage/report.json`. POSIX/cooperating-writer scope, not a cross-store transaction or hostile-writer filesystem proof. |
| G09 CLI/agent use | Pass for current CLI and protocol | Installed Click commands and JSON-RPC initialize/citation/signed admission/retrieval/graph-refresh/EOF paths exercised. Structured errors, bounded contexts, honest completeness, explicit config roots, terminal escaping and clean machine streams. |
| G10 Migration | Final process qualification running | Implemented account/quarantine/stage/apply/repeat/restore and retained selection; representative synthetic legacy-copy campaign is part of final storage qualification, not a claim that the user's production KB was migrated. |
| G11 Graph snapshots | Pass regressions; final fault campaign running | Complete installed-package fingerprints, config/schema/engine/repository identity, isolated candidates, pinned reads, exact binding parity, real native recovery tests. Module-shortlist omission reproduced and repaired. |
| G12 Dolt backend | Pass native integration; final campaign running | Native Dolt 2.6.1, normalized typed rows, immutable commits, managed read-only SQL sessions and publication checks. No mock SQL/storage semantics counted as native qualification. |
| G13 Remote | Local transports passed; enterprise user-owned | Final local report exercises independent Git/native-Dolt clients and interrupted pushes. Actual enterprise authentication/policy/retention remains with the work agent by explicit user decision; no enterprise-pass claim. |
| G14 Restore/history | Final process qualification running | Independent native restore, retained historical objects and authorized rollback/rollforward are exercised by the final storage campaign. Missing objects fail explicitly; normal Git clone alone is not a complete restore. |
| G15 Cost/usefulness | Corrected-corpus final evaluation pending | Frozen task protocol retained. Prior mechanical thresholds passed; first real model trials exposed ambiguous evidence identity metadata. The corrected corpus is frozen as 1.0.2 before new measurements/calls; original failures are retained, never relabelled. |
| G16 Runtime separation | Pass on installed Linux artifact | Runtime contains Python/Git/Dolt/gh, not Lean/Docker/formal files. Installed and module CLI paths, citation RPC and human/machine output probes pass. |
| G17 Cutover | Local capability qualification being finalized | Authored files remain authoritative for authored records; native structured knowledge is authoritative only through authenticated completed releases. No two independent writers for a field, no silent legacy adapter fallback. Remote deployment is not promoted by local evidence. |
| G18 Delivery | Verified implementation checkpoint; final receipts pending | Source, current operator/design docs, proof/conformance results and runtime evidence are being committed together. Final process/evaluation receipts will complete the gate table. |

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
