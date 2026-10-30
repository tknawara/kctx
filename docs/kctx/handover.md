# kctx consolidated handover — proved calculus, typed core, Dolt query engine, Git assets

Date: 30 October 2026. Status: implementation specification and acceptance
contract. **Supersedes** both `kctx-lean-and-typed-refactoring-handover.md`
(30 Oct 2026) and `dolt-knowledge-engine-handover.md` (28 Oct 2026). Those
remain in Downloads; this document carries their normative content forward,
de-duplicated, with one gate numbering, one scenario registry, and one
milestone sequence. Where they conflicted, the newer Lean handover wins
(Python-only runtime, no Lean at agents' machines; Dolt promoted only through
its own gates).

## 0. Goal

kctx is a knowledge calculus with **proved verbs** (a small Lean-verified
model of claims, evidence, derivations, freshness, corrections, and workflow
transitions) implemented by a **typed Python core**, with **Git as the
canonical store for authored assets** (ordinary files: Markdown, JSON records)
and **Dolt as the query engine** for relations/graph over those assets — a
rebuildable projection until, and only until, its independent acceptance gates
pass. Agents get compact, scoped, reusable assessments.

The proof target is the language and its operations, universally over every
well-formed KB expressible in the model — not Tarek's corpus. Data updates
never run Lean. Runtime checks establish premises of already-proved rules.

## 1. Implementation mandate

1. Preserve the useful system: code citations, authored Markdown, project and
   asset navigation, investigations, signatures, proposals, corrections,
   coverage, agent integrations, and the existing `⟦cite …⟧` citation scheme.
2. Define *supported, fresh, applicable, validated, usable* as separate
   represented dimensions; never one status string.
3. Prove the generic contracts of a bounded first calculus (§4); implement the
   production rules in a small pure Python module; check conformance against a
   Lean reference evaluator in CI. Assurance label: **model proved, Python
   conformance checked** — not a refinement proof.
4. Replace unstructured IDs/references/status strings/`Dict[str, Any]` with
   domain types; preserve external spellings via explicit codecs.
5. Admitted mutations preserve the invariants validation checks; drafts exist
   without being presented as admitted knowledge.
6. Historical identity and evidence are retained; refresh creates new
   versions/assessments and never retargets an old citation.
7. Strict typing, formatting, linting, locked dependencies, meaningful tests,
   migration checks, recovery checks, measured agent outcomes.
8. Reviewable slices. No custom VM, extraction platform, graph database,
   generic workflow framework, or special filesystem.
9. Lean and its reference evaluator live only in development/CI (Docker).
   Runtime ships Python only (G16). `uv` is the supported runner; dependencies
   through the existing Gripsack setup at work.

Routine implementation decisions within this scope do not require re-asking
Tarek. A failed gate blocks its dependent guarantee, not unrelated work.
Record unresolved decisions with a concrete reason and safe supported
behavior. Push coherent checkpoints to `tknawara/kctx` regularly.

### 1.1 Established baseline (verified this session)

See `docs/kctx/discovery.md` for the full G00 report. Summary: `kctx.zip`
SHA-256 `81e8278a057cb94b4a676cad2b4b20781165553e132be604ae33ce7b655e7f62`,
49 Python files / 12,902 lines, imported verbatim at repo root; ambient suite
266 tests OK (30 skips = absent structlog/pydantic/dolt). The source-observation
table in the older Lean handover §1.1 (records.py stringly fields, REL_STATUSES
dimension-mixing, draft→proposed readiness bypass, `_gate_block` legacy
wave-through, `has_landed_evidence` looseness, no real concurrency control,
lossy Markdown re-rendering, corrections ordering, `atomic/exclusive_write_json`
limits, TTL boundary semantics, validate.py monolith, admit cursor semantics,
graph generation identity gaps) was spot-checked against the tree and stands.

## 2. Architecture and ownership

| Layer | Responsibility | Excluded responsibility |
| --- | --- | --- |
| Lean specification + reference evaluator (`formal/Kctx`) | Generic syntax, declarative semantics, proofs, executable reference behavior; dev/CI only. | Production execution, fetching, networking, SQL, prose interpretation. |
| Python semantic core (`kctx.semantics`) | Pure typed implementations of the specified decisions; same semantic version; conformance-checked. | Filesystem, clock reads, SQL, network, policy overrides. |
| Python domain + codecs | Validated domain objects, explicit references, lossless legacy decoding, typed requests/results, fixture/protocol conversion. | Policy decisions in parsers; duplicating core rules. |
| Python application services | Resolve pinned context, collect dependencies, call the core, prepare changes, coordinate persistence, return receipts. | Ad-hoc freshness booleans. |
| Storage/collection adapters | Git, filesystem, Dolt, existing index, evidence acquisition, subprocesses, clock, rendering. | Defining semantic truth. |
| CLI and agent adapters | Parse args, invoke services, stable diagnostics, bounded context. | Reimplementing validation; mutating stores directly. |

Production calls ordinary Python functions in `kctx.semantics`. The shared
test interchange is versioned JSON; not a production IPC service. Python-only
smoke tests must pass with no Lean/Lake/Elan/Docker present.

### 2.1 Storage authority by phase

| Phase | Canonical authored assets | Canonical structured records | Dolt role |
| --- | --- | --- | --- |
| Baseline + refactor | Git/filesystem | Existing files | Existing M2 shadow graph; files authoritative. |
| Shadow evaluation | Git | Existing files | Rebuildable candidate from the same pinned input; compare. |
| Accepted Dolt cutover | Git | Explicitly assigned Dolt tables | Versioned structured authority; generated JSON/Markdown projections are not alternate writers. |

Ownership is per field/record family. Narrative bodies can stay authored in
Git while indexed properties are projections; if lifecycle metadata moves to
Dolt, frontmatter becomes a generated or explicitly imported representation.
Never let both stores silently own the same status. No dual authoritative
writes. Large/operational evidence needs a retained artifact store with exact
identity — a hash without retrievable bytes is insufficient for replay.

Git holds code, policies, Lean specs, schemas, tests, authored documents,
migrations, release manifests. Dolt (after cutover) holds structured claims,
citations, derivations, observations, validation receipts, corrections, and
their history. Versioned storage + immutable release references provide the
logical snapshot boundary; no copy-on-write filesystem required. Cache/index
files are disposable only when all rebuild inputs are retained.

## 3. Identities

Distinct types (never one bare `sha: str`): asset ID, claim ID, claim revision,
source reference/revision, observation ID, evidence ID, citation ID + scope,
proposal ID/revision, investigation ID, signature ID, rule ID + version,
operation ID, snapshot ID, Dolt commit, Git release commit, index artifact
digest, idempotency key. Native commit identifiers are opaque with native
validation; Dolt and Git hashes share nothing. Abbreviated legacy references
are unresolved hints until uniquely resolved; ambiguity is an explicit outcome,
never latest-match. A logical ID survives renames; a revision identifies
particular wording/scope/evidence; a commit identifies a state containing
records; these are different things.

## 4. Vocabulary of the calculus (v1, versioned)

| Concept | Required meaning |
| --- | --- |
| Entity identity | Stable identity of an asset/claim/observation/proposal/rule; independent of contents. |
| Record revision | Immutable version of entity content. |
| Source reference | Typed locator for a repo object, retained document, runtime capture, or other supported kind. |
| Citation | Preserved public text + parsed structure + exact resolution; historical and current resolution are distinct operations. |
| Observation | Recorded acquisition attempt: outcome (ok/timeout/partial/truncated/denied/unavailable), source, observed time, capture context, retained result identity. |
| Claim | Versioned proposition: structured subject/predicate/arguments + explicit scope + optional narrative. |
| Relationship | Typed relation between entities; a navigation link is not an implication. |
| Evidence binding | Specific observation/citation revision supporting or challenging a claim revision (supports/contradicts/contextualizes). |
| Derivation | Rule application: premise groups, conclusion, rule version, scope, dependencies. Alternatives remain distinct. |
| Dependency footprint | All inputs whose relevant change can invalidate a result, including membership and policy/checker inputs. |
| Validation receipt | Named checker version on exact inputs: outcome, scope, evaluation time, expiry policy. |
| World snapshot | Selected immutable set of repo revisions, KB revisions, observations, configuration. Not a live global view. |
| Evaluation context | Snapshot + policy version + ruleset version + explicit evaluation time + target scope + intended use. |
| Correction | Versioned retract/dispute/supersede event on an identified revision or explicit range. |
| Assessment | Structured results and blockers for a claim in a context; provenance + reusable validity conditions. |
| Coverage witness | Evidence a required set was enumerated within scope at a revision, with method and completeness. |
| Operation plan | Pure proposed state change with preconditions, expected predecessor, outputs; persistence executes conditionally. |

State dimensions stay independent: acquisition outcome, extraction origin,
admission, lifecycle, contestation, applicability, evidence support, freshness.
Support distinguishes none/positive/negative/both; contradictions stay visible;
policy may refuse contested conclusions while displaying both derivations.
`Freshness = fresh | stale | unknown` is an assessment relative to a context,
never a stored property. `not-applicable`, `not-examined`, `unavailable` stay
distinct from false/refuted.

### 4.1 Claim language v1

Structured atomic claims; explicit conjunction where required; a finite
registry of typed derivation rules; prose stays prose; LLM assertions are
proposals/attestations with a named source, not axioms. Preserve existing
relation labels (`depends-on`, `documents`, …) for navigation; transitive
reachability is a separate typed query, not an inference. Derivation witnesses
are acyclic in v1 (asset dependency cycles are a separate concern). No general
Datalog, negation-as-failure, quantified NL, or probabilistic composition.

Universal/absence premises ("all callers checked") require an explicit finite
coverage witness; empty/truncated search never establishes absence. Scope:
exact matching by default; weakening only via a specified, proved rule.

### 4.2 Freshness and dependency semantics

Separate predicates, then compose: `ResolvesExactly`, `Applicable`,
`DependenciesMatch`, `ValidationCurrent`, `Supported`, `Contested`,
`UsableFor`. Reuse of derivation `d` in context `E` with footprint `F(d)`
requires all relevant dependency observations to match required versions,
required validation applicable, temporal conditions holding; missing
information yields unknown/incomplete with explicit missing premises.

Footprint covers (where relevant): source file/span content and surrounding
definitions/contracts/callers/configs; selected repo/worktree state including
retained dirty content; discovery inputs (membership, caller sets, scope,
index version, completeness); claim/citation revisions, rule/checker/policy
versions, environment, deployment target; relevant corrections. A small
footprint is an optimization with a correctness obligation; a whole relevant
source tree is an acceptable conservative initial footprint.

Clock convention: with duration `ttl`, recency holds iff
`observed_at ≤ now ≤ observed_at + ttl` (inclusive boundary, matching current
behavior). Future timestamps are rejected or handled under a bounded skew
policy. Missing TTL = explicit no-expiry policy or missing policy, never
implicit freshness. Civil display dates never acquire observation-time
assurance. Copies/summaries/derived claims retain originating observation
times and dependency conditions — summarizing today does not renew yesterday's
evidence; reevaluation on unchanged bytes creates a new receipt only when a
real scoped validation occurred.

### 4.3 Alternative support and corrections

`claim c` supported by `(a AND b) OR c2`: if `a` becomes unusable the second
derivation may still justify; never mark descendants globally unusable without
checking other paths. Provenance semirings are the design reference; a DAG
with explicit premise groups suffices for v1. Corrections change current
assessment or add events; they never rewrite history. Supersession confers
nothing automatically; the replacement earns its own evidence. Backlinks
enumerate impact; logical invalidation follows declared dependencies, not
textual links.

## 5. Lean specification and theorem obligations

Small Lean package `formal/Kctx`: identifiers/values, syntax, contexts,
declarative semantics, executable checking, dependency reuse, derivations,
workflow transitions, protocol conversion. No large dependencies (no mathlib);
Lean core + `Lean.Data.Json` for the reference evaluator.

Declarative semantics stay distinct from the algorithm (no
`Sound x := checker pass` tautologies; no assumed axioms "all configured rules
are sound"). Soundness is over all well-formed states and declared
interpretations; each built-in rule discharges its own semantic preservation
obligation. Central form:

> For every well-formed state K and evaluation context E, if the executable
> checker accepts a derivation/operation with declared preconditions, then the
> declarative judgment holds; successful state changes preserve
> well-formedness.

No theorem mentions a particular repository or corpus. Concrete examples live
in tests/non-vacuity cases.

### 5.1 Theorem registry (`formal/theorems.json`)

| ID | Obligation |
| --- | --- |
| T01 | Decoding/admission success produces a well-formed internal value. |
| T02 | Encode∘decode on valid protocol values preserves semantic value (canonicalization/ordering/optionals/versioned). |
| T03 | Successful core operations preserve well-formed admitted state (drafts: weaker invariant). |
| T04 | Checker acceptance implies declarative derivability (arbitrary well-formed contexts, acyclic witnesses). |
| T05 | Each enabled rule preserves its declared proposition semantics (per-rule, no global soundness axiom). |
| T06 | Matching the complete declared footprint preserves the reusable judgment under stated context/time premises. |
| T07 | Changes outside the footprint cannot change the relevant evaluation (locality justified by footprint construction). |
| T08 | Every required mismatching/missing dependency prevents fresh assessment for that derivation (alternatives unaffected). |
| T09 | A surviving accepted alternative derivation preserves positive support (policy blockers separate). |
| T10 | Invalidating every supporting derivation removes the support judgment (does not establish the negation). |
| T11 | With fixed inputs and no new validation, increasing evaluation time cannot restore expired recency. |
| T12 | Composition/copying cannot widen scope, renew evidence age, or drop dependencies. |
| T13 | Missing coverage cannot justify universal coverage or absence (typed witness mandatory). |
| T14 | No reverse inference or relation composition without an enabled typed rule (countermodels for tempting inferences). |
| T15 | Historical resolution/evaluation unchanged by extensions outside the pinned context (retained objects, same semantic version). |
| T16 | A supersession edge alone confers no support or validation on its target. |
| T17 | `UsableFor` success entails every mandatory condition of the selected policy. |
| T18 | Accepted proposal transition satisfies readiness, actor, evidence, gate preconditions (bound to definitions + target revisions). |
| T19 | Investigation conclusion satisfies structural and hypothesis requirements. |
| T20 | Conditional plan application requires its expected predecessor; rejection leaves modeled state unchanged. |
| T21 | Replay of an applied operation ID with same input is idempotent; different input conflicts (state which ops support retries). |
| T22 | Evaluation is deterministic for the same explicit inputs and semantic version (no clock/random/DB order/HEAD in the core). |

For finite complete v1 inputs, prove checker completeness relative to the
declared witness language where tractable. Positive inhabitants for important
preconditions; negative examples for each rejected inference; no theorems over
impossible well-formedness predicates.

### 5.2 Proof integrity and production linkage

- Pin Lean + Lake deps (`lean-toolchain`, `lake-manifest.json`); clean-checkout builds.
- Audit exported theorems' transitive axioms (`#print axioms`); reject `sorryAx`/`admit`/unapproved axioms; allowlist standard Lean logical axioms explicitly.
- No `implemented_by`/native shortcuts in assurance paths without recorded trust-boundary review.
- CI reference evaluator exported from the same checked definitions; mapping to Python production functions tested; neither a reference-only Python model nor a mocked production call suffices.
- `proof-report.json` (revision, toolchain, theorem names/statements, axiom sets, build result, reference identity) and separate `conformance-report.json`.
- Proof maintenance triggers on semantic/rule/core changes; data refresh never runs proofs.

## 6. Python domain model and protocol

- Nominal types: `AssetId`, `ClaimId`, `ClaimRevision`, `CitationId`,
  `ObservationId`, `ProposalId`, `InvestigationId`, `SignatureId`, `RuleId`,
  `RuleVersion`, `OperationId`, `SnapshotId` — frozen dataclasses (slots) where
  validation/formatting/components matter; `NewType` alone is insufficient.
  Prose stays strings. Sum types for mixed references (correction target =
  evidence | dossier | signature | proposal reference); parse prefixes once at
  the boundary, never `startswith('ev:')` in logic.
- Separate types for raw records, parsed drafts, admitted records, assessed
  results. Parsing success ≠ admission. `schema_version` selects a
  decoder/migration; unknown-constructor filtering is not a compat policy.
- No `Any` in domain/service APIs; `object` + narrowing at untyped boundaries;
  `TypedDict` for wire shapes; tuples/frozen collections (a frozen dataclass
  holding a mutable list is not immutable).
- Service boundary (shape, not paste-in): `EvaluateClaims`, `PlanTransition`,
  `CommitPlan(expected: StoreRevision)`, `ResolveCitation`. Results
  distinguish committed / already-committed / predecessor-conflict / rejected /
  uncertain-recovery. Command input, internal model, persistence schema, CLI
  output are four distinct contracts.
- Versioned JSON envelope: correlation ID, operation, schema version, semantic
  version, exact context identity; canonical digests/time; reject invalid
  enums, duplicate identifiers, missing fields, unsupported versions,
  malformed union tags; decide duplicate-key handling before any silent
  mapping. Both implementations validate inputs (never trust fixture flags).
  Compact reasons + dependency IDs; provenance on demand. Receipt hash
  identifies a result, not authenticity or continued validity. CI fails on
  reference timeout/crash/malformed/version mismatch — never silently skips.
  Batch cases in CI, batch evidence acquisition in production; load complete
  relevant slices or disclose incompleteness.

## 7. Repository and modules

Code, formal specs, fixtures, CI in `tknawara/kctx`. Work KB data, real
observation contents, local config, credentials, mutable Dolt data stay in
their data locations; this is not the KB data repository.

| Package/file | Responsibility |
| --- | --- |
| `domain/ids.py`, `domain/refs.py`, `domain/time.py` | Nominal identities, exact/alias references, durations, UTC instants, path values. |
| `domain/knowledge.py`, `domain/workflows.py` | Claims, evidence, derivations, assessments, proposals, investigations, runs. |
| `semantics/` | Pure implementations of the formal rules: freshness, support, eligibility, transitions. |
| `codecs/` | Citation adapter contract, legacy Markdown/JSON decoding, document representation, versioned wire records. |
| `services/` | Use cases: evaluate/context, refresh/admit, workflow changes, corrections, graph sync. |
| `ports.py` / small protocols | Real replaceable boundaries only: repo reader, snapshot store, citation provider, clock, command runner. |
| `adapters/files/`, `adapters/git/`, `adapters/dolt/` | Persistence + acquisition; conditional writes; retained source access. |
| `graph/` | Extraction/navigation projections on shared identities. |
| `cli/` | Registration, dispatch, rendering, exit-code mapping. |
| `observability.py` | Command/operation logging independent of the graph package. |
| `formal/Kctx/` | Lean spec, proofs, CI reference evaluator (excluded from runtime). |
| `tests/`, `tests/conformance/`, `tests/integration/` | Behavior, semantic correspondence, real adapters. |
| `scripts/`, `compose.yaml`, `formal/Dockerfile` | Reproducible dev/CI entry points. |

No abstract repository framework, service locator, record inheritance
hierarchy, or static-utility classes. Pydantic validates external row/wire
shapes only (strict, explicit unknown-field policy); domain dataclasses and
Pydantic models must not compete (`bool(row.get('illus'))` coercing `"0"` →
true is a bug class to eliminate). Preserve the existing top-level module set
during transition (file-by-file obligations table from the Lean handover §7.2
applies; see `docs/kctx/discovery.md` for current responsibilities).

Root resolution (§7.3 of the older doc): precedence `--root` → `KCTX_ROOT` →
documented installed config → recognized KB marker from cwd. Never treat an
arbitrary Git repo as a KB. Test: installed `kctx` from an unrelated directory
against an explicit KB; every read/write stays in that KB.

Lossless document editing (§7.4): one representation retaining frontmatter
entries, heading order, original spans, unknown sections, opaque citation
text. Targeted updates patch spans; scaffolding ≠ editing. Headings recognized
only outside code fences; duplicate required headings/keys diagnosed. Preserve
line endings and unaffected bytes; keep the flat frontmatter format (YAML
migration is a separate, fixtured change).

## 8. Workflow and evidence contracts

**Proposals/gates.** Pure `plan_proposal_transition`: construct the candidate
from every change in the command, validate the whole candidate, then publish
under an expected revision; `validate` applies the same rules. Drafts may be
incomplete; draft→proposed invokes the same readiness predicate as filing
proposed (intentional contract change; update the bypass fixture with a
compatibility note). Preserve "research not needed" justification. Acceptance
records actor + accepted revision; landing records executor and acquires an
actual conditional claim/lock; actor roles are distinct fields. Applied
requires valid land-gate results and resolved landed references for the target
revision; verified requires deploy/use results plus continued applicability.
`GateResult` binds proposal revision, gate-definition identity, target
revision, checker, environment/scope, evidence refs, outcome, actor, time.
"No table" ≠ "malformed table"; legacy exemptions need a migration/profile
fact. Deterministic latest-result selection within bound inputs; an old-target
pass never wins on gate-ID match. Supersession requires a resolving
replacement (cycle-safe) and accepts nothing automatically. Regression
preserves prior verification and attaches the contradiction; add the
verified→regressed path deliberately if needed. A shell command in a Markdown
table is not proof it ran; record execution or identified human attestation;
never auto-execute KB prose.

**Observations, coverage, worktrees.** Immutable observations;
revision-bound receipts. `coverage_complete` ≠ `eligible_to_proceed`
(`check` counting violated items as examined is fine for coverage, never
authorization). Deduplicate provenance roots; named minimum-independent-origin
requirements per policy; two locators are not independent if one copies the
other. Worktree snapshot covers tracked/staged/unstaged/binary/untracked
inputs, modes, submodules — `git diff HEAD` alone misses untracked-only
changes. Missing source → unknown/unavailable, never "unchanged". Numbered
receipt conflicts retry only on actual filename conflicts.

**Citation provider.** Keep `⟦cite …⟧`; Dolt stores normalized bindings and
history, not a replacement dialect. Typed `CitationProvider` contract
(parse/resolve/check/batch refresh + provider/version/capabilities identity).
Unify `CITE_BIN`/`KCTX_CITE_PY`/skill-path discovery; report the selected
provider; absent/incompatible → existing unverifiable behavior. Distinguish
parsing/validation/retargeting: historical citations resolve original
revisions; explicit refresh proposes a new binding linked to its predecessor;
never mutate a citation's revision/timestamp to silence staleness.

**Admit/drain.** Plan/apply stages; "scanned through X" ≠ "admitted through
X"; persist pending judgment work before advancing cursors; unresolved work
survives no-change invocations, restarts, partial failure. Dry run leaves
canonical records, cursors, correction state, published generations unchanged;
returns applied/pending/blockers/retry typed result.

**Corrections/investigations.** Impact at a pinned revision with the
completeness boundary of backlink discovery recorded; correction event +
pending-review tasks written consistently; projection updates replayable;
`unchanged:<evidence>` becomes a structured outcome (who/revision/why);
"no known referrers" is bounded. Investigation conclusion needs typed
hypothesis outcomes + scope/checked-against; malformed hypothesis bullets are
diagnostics. Promotion retains origin, adds idempotent pointer; retry repairs
without duplicating.

## 9. Dolt engine: model, queries, publication, remotes

### 9.1 Relational model (after cutover; shadow schema is the same subset)

Normalized tables where joins/constraints need them; bounded JSON for
provider-specific metadata; no universal triple store; no whole-KB JSON row.

| Record | Required fields |
| --- | --- |
| Asset + alias | Stable ID, kind, scoped name, aliases, owner/unknown, source locator, lifecycle, adapter capabilities. |
| Source version + capture | Provider, immutable source identity, content digest, retained payload locator, collection interval, access status. |
| Observation | Query/command + safe params, environment, observation time, effective interval, input identity, result status, warnings/truncation, evidence refs. |
| Claim + revision | Logical ID, immutable revision ID, statement, epistemic kind, state dimensions, applicability, dependencies, support/contradiction links, change reason. |
| Claim lifecycle event | Supersession/dispute/retraction/retirement/corrected-applicability; exact target revision, reason/evidence, time, scope, authority. |
| Relationship + constraint | Typed endpoints, source role, applicability, authority, verification method or explicit gap, freshness deps. |
| Citation binding | Token/format version + scope, normalized target, exact source/claim revision, historical binding or explicit ambiguity, renderer metadata. |
| Proposal + item delta | Base release, intended changes, per-item deps, source run, evidence, semantic digest, disposition. |
| Admission | Accepted delta digest, proposal revision, base/target revisions, actor/authority evidence, per-item disposition, material-input digests, timestamp. |
| Context + material use | Run, immutable release, task observations, included/omitted requirements, coverage, evidence links, actual/potential reliance. |
| Discovery query dependency | Roots, filters, pagination, scope, index generation, membership digest, incompleteness, expiry policy. |
| Gap/exception/follow-up | Scope, consequence, owner/unknown, attempted evidence, status, recheck/expiry, resolution. |

Separate fields for epistemic status, admission, freshness, availability,
applicability, implementation/deployment state — no single
confidence/`verified=true`. Effective intervals half-open `[from,to)` UTC with
explicit unknowns; observation time stored separately from ingestion time;
release lineage (not source dates) establishes what the KB knew. Dolt supplies
commit history, not effective-time semantics: distinguish knowledge at
release R, current corrected view of an earlier period, and current
applicable knowledge; replay must not select evidence merely by effective
date. Immutable claim revisions + appended lifecycle events (no second custom
event-sourcing engine). Constraints: identity references, permitted
transitions, alias scoping, uniqueness/idempotency, interval validity,
dependency integrity, explicit contradictions; SQL constraints and knowledge
semantics both validated before admission.

Typed backlinks/evidence lineage: record meaning explicitly (`mentions`,
`supports`, `contradicts`, `depends_on`, `supersedes`, material reliance);
reverse lookups derive from canonical relationships with indexes, not
maintained duplicate copies. Version history answers what changed; evidence
lineage answers what supports; use records answer what relied. A retrieved
passage, a mention, and material reliance are different observations; missing
use instrumentation is a coverage gap, never "no dependents".

### 9.2 Citation scheme integration

Keep the public scheme; Dolt becomes its structured backing store where
appropriate. Resolver input: existing token + owning artifact/run + selected
release. Output: original token + format version, scoped alias resolution,
normalized logical target + exact revision; binding to retained source
version/capture/passage; claim revision + role (supports/contradicts/
contextualizes); source provenance and role (a quoted summary is not primary
evidence); availability/integrity/applicability/historical status; optional
current advisory, explicitly separated. Historical resolution uses the
original release/context and immutable identity — never silently replace a
missing old target with today's match. A snapshot citation is an audit
locator, not truth; the chain reaches retained evidence; exact lines at a
pinned revision are acceptable, line numbers without a version are not.

Legacy migration: dry-run classification of every citation (exact / uniquely
recoverable / historically ambiguous / unavailable / malformed / already
broken) from evidence only (run manifests, immutable refs, stored outputs,
identifiable snapshots); record method and uncertainty; never invent an old
revision from the current tip. Hard criterion: zero newly broken or silently
retargeted previously resolvable citations; full accounting, no silent drops.
Exportable citation/evidence bundles are read-only.

Self-reference: never write a commit hash into rows inside that commit;
intrinsic record IDs live in payloads, enclosing commit bindings in external
manifests/post-commit receipts. Runs against R1 may write receipts into later
commits referring back to R1; later recording never backdates knowledge.

### 9.3 Query contract

Every graph result includes generation/source identity, freshness relative to
the requested source, semantic/extractor versions, completeness; `total`
states whether complete or bounded-traversal count; limit/depth/filter/
malformed/missing-capability never disappear. Typed query methods: inbound
references, bounded impact, binding history, generation diffs; arbitrary SQL
stays out of agent workflows (if a SQL adapter remains: centralized
construction, qualified against the pinned Dolt version; `sql_read` is not
read-only enforcement). Navigation and inference stay separate — `cites`/
`mentions` edges navigate; validated `supports` bindings participate in rules;
SQL joins retrieve premises, they do not prove conclusions. Pin a completed
generation once per request; never read `WORKING` for assured results;
pagination stays on one immutable generation; bounded work as well as output
on dense cyclic graphs.

### 9.4 Generation publication protocol

`GenerationManifest`: KB identity + Git revision, content Dolt revision,
extractor/parser/schema/semantic versions, config + alias-map identity,
extraction receipt identity, required retained artifacts. Immutable manifest
identity + movable published pointer.

1. Record expected published predecessor.
2. Stage the candidate generation in isolation (branch/location).
3. Validate schema, references, extraction completeness, parity.
4. Create the Dolt data commit; record its exact returned identity (SQL `COMMIT` is not a Dolt history snapshot).
5. Write the manifest *after* that identity exists (no self-referential hashes).
6. Ensure referenced objects retained/reachable.
7. Publish pointer with conditional predecessor check; readers keep the previous completed generation or select the new completed one.
8. On uncertain completion inspect operation ID + pointer before retrying; never blindly duplicate.

Git and Dolt provide no cross-store transaction; this protocol is the
application consistency boundary (local publication record in shadow mode).
Test crashes after each step, concurrent refreshes, stale predecessors,
missing objects, readers during publication. A storage failure must never
make a half-built graph the latest usable state.

### 9.5 Snapshot/release contract (cutover phase)

A published release = Git commit whose manifest pins the exact Dolt commit and
material inputs (illustrative fields: `format_version`, `previous_release`,
`database{remote_id,commit,schema_version,schema_digest}`,
`source_manifest_digest`, `policy_inputs_digest`, `toolchain_lock_digest`,
`candidate_input_digest`, `validation_receipt_digest`, `indexes[]`). The
protected release branch is the single authoritative pointer; the Dolt data
ref and `main` branch are storage mechanisms, not admission authorities.
Every material update to that branch satisfies release validation, including
document/policy/toolchain-only updates. Candidate input digest covers exact
database state, authored content, policies, source identities, toolchain,
test configuration — explicitly defined, excluding digest-cyclic outputs.
Indexes match pinned inputs + generator versions, or are rebuilt/qualified-
fallback at the same snapshot. Nondeterministic derived artifacts (LLM
summaries) are retained by exact bytes/digest; regeneration is a new identity.
Snapshots reuse unchanged content; ordinary reads never force new releases.

Publication protocol (condensed from the older Dolt handover §8.2, unchanged
in substance): durable operation journal; pin base → collect/propose →
reconcile against current admitted base (no last-writer-wins admission) →
obtain applicable admission (authority bound to exact proposal revision and
delta) → freeze candidate (native Dolt commit; protect retention roots) →
validate the frozen candidate → replicate dependencies + independent-client
verification → prepare Git release change with semantic diff → validate the
actual integration payload (rebase/merge-queue safe) → advance the one
authoritative pointer conditionally → confirm and record. Crash/uncertainty
matrix: before Dolt commit (draft state, release unchanged); after commit
before replication (resume same candidate); during push (determine remote
state, idempotent retry); after replication before Git landing (candidate
non-current); competing publishers (at most one from expected base); after
landing before ack (read remote, complete journal); new release unavailable
locally (keep last complete release, report missing components, no mixed
current view). Rollback = new authorized release selecting earlier retained
state; never rewrites history or discards intervening legitimate work;
prefer corrective forward releases for partial errors.

### 9.6 Remotes, retention, restore

Dolt's Git-backed remotes (`refs/dolt/data`) are a capability to qualify
against the pinned version and the actual bbgithub host — never assumed from
the name. Qualify: init/custom-ref discovery, clone/fetch/push/pull,
branch/tag transfer, immutable historical reads from an independent clone;
auth/certs/proxies; two writers on different Dolt branches sharing the data
ref; divergent changes/conflicts/interrupted uploads/rejected writes/
uncertain results; read-after-push from a clean client; CI/protection
behavior for the release branch vs the data ref (a data-ref write is not
admission); backup/restore and GC including retained native Dolt commits
after transport-ref maintenance. If custom refs can't be qualified, keep the
current workflow and block cutover; no silent redirection to public services.

Retention inventory: every cited/published Dolt commit, required Git
revision, evidence capture, replay-needed index, active proposal; protect
retention refs; verify presence in remote/backup, not just manifest text.
Restore test from a clean machine/profile: current + older cited releases,
structured queries, citation resolution to retained payloads, schema
compatibility, preserved proposal resumption; record recovery time and
missing components. Deletion/revocation policy: scoped tombstones + dependent
reassessment; immutable ≠ undeletable. Use Dolt backup/remote procedures —
never live-file copies as sync. A normal Git clone alone is not a restore.

## 10. Environment, toolchains, and quality

**Proof environment (dev/CI only).** Docker Compose `formal` profile +
one-shot `proofs` service; pinned base-image digest, pinned Lean/deps;
`lean-toolchain`, lakefile + manifest committed; offline after provisioning;
caches scoped by toolchain/lock hashes; clean-cache reproduction; no reliance
on developer-private toolchains/credentials; host ownership handled. Reuse
the actual Sovel setup if the local `../sovel` workspace provides one —
inspect, don't invent. Interfaces:

```bash
docker compose --profile formal build proofs
docker compose --profile formal run --rm proofs ./scripts/proof_check.sh
docker compose --profile formal run --rm proofs ./scripts/conformance_check.sh
```

**Python.** Floor 3.11 unless discovery justifies change; system-only Python,
no auto-downloads (work-environment constraint); dev tools (Ruff, Pyright,
Hypothesis, test tools) pinned in `uv.lock`; `uv sync --locked` /
`uv run --locked` in CI so metadata drift fails. One active Pyright config
(strict on domain/semantics first, expanding to the maintained package;
migration allowlists have named files, reasons, milestones; final gate rejects
blanket `Any`/type ignores/silent suppression). Ruff: E4/E7/E9/F/I/B/UP/ANN/
RUF, line-length 100, py311 target. Keep `unittest`; Hypothesis for
properties. `check_contracts.py` validates schema versions, theorem/function
registry coverage, fixture versions, semantic-version consistency, import
boundaries. Release jobs fail on dependency-based skips; report passed/
failed/skipped separately. Checks:

```bash
uv sync --locked --group dev
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyright
uv run --locked python -m unittest discover -s tests
uv run --locked python scripts/check_contracts.py
```

**Gripsack + host.** Install Dolt/Git/drivers through the actual Gripsack
mechanisms (inspect; don't encode historical suggestions as its API).
Immutable installs separate from mutable DBs/state (never a live `.dolt`
inside an install generation); explicit per-task DB paths; existing credential
sources (never secrets in Git/Dolt/locks/diagnostics); enterprise cert/hostkey
verification preserved; server start/stop/health via existing conventions,
local endpoints by default; effective binary versions + provenance verified;
clean-machine reproduction + interrupted-install recovery; tool-generation
rollback never rewinds durable data. bbgithub qualification per §9.6 on a
disposable repo via the intended transport.

**Code review requirements (condensed).** Pure, deterministic, explicit-time
domain operations; exhaustive enum/union handling; errors carry stable code,
entity, location, failed condition, next step (no raw tracebacks for expected
failures); narrow adapters for SQL/subprocess/hash/publication/providers with
argument arrays (no shell strings from KB text); one owner per parser/utility;
logging outside semantics, correlation IDs survive, JSON stdout stays machine-
readable, no blanket `except: return []` on assurance paths, incompleteness
visible; tests target external contracts. Diagnostics: versioned JSON with
operation ID, run/release ID, phase, duration, outcome, affected IDs,
retryability, precise category (invalid input / unsupported schema /
unsupported capability / auth / permission / missing object / historical
ambiguity / integrity / incomplete evidence / stale / conflict / timeout /
cancellation / outcome-unknown). Gate results `pass|fail|blocked|
not_applicable` (N/A needs policy reason); readiness (`ready|partial|blocked`)
separate from support; non-success exits for unresolved mandatory gates.

## 11. Agent-facing API

Keep command names/exit codes (`0/2/3/1`); `--json` consumers preserved via
explicit output versioning; add fields, never silently repurpose. Converge
`context`, `check`, `admit`, `uses`, `graph` on shared services. Capability
table (final spelling after CLI discovery; the `kb …` names from the older
doc are labels, not renames): inspect effective config/capabilities (`doctor`);
assess claim/context pack; explain receipt (premises, rule IDs, footprint,
why each condition passed/failed); plan/apply refresh + admission; query
backlinks/impact/history (exact generation, typed edges, bounded, completeness
+ continuation); compare snapshots (binding deltas vs presentation movement);
validate/migrate (typed diagnostics, dry-run); recover interrupted operations
(durable phase, already-committed?, repaired projections, blockers); snapshot
build/validate/diff; release publish/status; sync (activate complete pinned
release, preserve dirty work + proposals); correct; backup verify / restore
rehearse; qualify; evaluate. Default context pack: relevant admitted claims,
material contrary evidence, compact citations, unresolved requirements,
assessment receipt; histories expanded on demand; pagination preserves the
snapshot. Reuse: an agent may rely on a successful assessment within its
recorded context/policy; runtime cheaply verifies dependency identity/temporal
conditions before reuse; re-evaluate on world/target/policy/rule/deadline
change. Historical reuse ≠ current-work reuse; at consequential writes recheck
the expected current target under the relevant synchronization boundary.
Learning stays a versioned workflow (candidate lesson → evidence → evaluation
→ admission → correction/retirement); no project-specific calculus primitives.

## 12. Verification strategy

Five forms: (1) Lean proofs (generic model + operator laws); (2) Lean/Python
conformance over shared cases and transition sequences; (3) property/
metamorphic tests (locality, invalidation, identity, serialization,
boundaries); (4) real filesystem/Git/Dolt/citation integration tests; (5)
end-to-end agent evaluations (usefulness, correctness, token cost,
generalization). Never described as a proof of all Python code; never replace
independent expected results with the function under test; manually reviewed
semantic fixtures guard against shared-serialization bugs.

Conformance campaign: deterministic reviewed corpus on every relevant change;
generated valid/invalid fragments (multiple IDs, revisions, times, scopes,
alternative derivations, corrections, incomplete observations); stateful
sequences, not just isolated calls; compare all semantic fields and diagnostic
categories; small exhaustively-enumerated finite domain + property cases with
retained seeds and minimized failures; mutation testing (flip TTL boundary,
drop dependency, accept unknown as fresh, swap source/target, skip gate phase,
erase dispute, latest-revision historical read — each must fail).

### 12.1 Scenario registry

Two complementary sets, IDs preserved:

- **Q01–Q76** (semantics/workflows/types/persistence/agent use): the table in
  the superseded Lean handover §13.2 is normative; reproduced in
  `docs/kctx/scenarios-q.md` (kept verbatim to avoid transcription drift).
- **D01–D72** (Dolt/storage/transport/publication/retention/evaluation): the
  table in the superseded Dolt handover §15 is normative for the Dolt path;
  reproduced in `docs/kctx/scenarios-d.md`.

Both sets apply to their domains; a cutover claim needs the applicable D
scenarios passed with real Dolt/remote evidence.

## 13. Acceptance gates (single numbering)

Evidence requirements: every gate receipt ties implementation revision,
fixture/corpus identity, tool versions, command, result, unresolved limits;
maintained in `docs/kctx/gates.md` + machine-readable reports. Required-skipped
tests mean unqualified, not passed.

| Gate | Pass condition | Failure blocks |
| --- | --- | --- |
| G00 Baseline | Source/env inventory, existing suite result, compatibility fixtures, authority map, reproducible metrics. | Semantic changes from guessed behavior. |
| G01 Toolchains | Locked Python checks + pinned offline-capable proof/conformance env from clean checkout; no dependency-based skips in required jobs. | Reproducible-build claims. |
| G02 Types | Nominal IDs, structured refs, explicit unions, validated values; strict typing on the migrated boundary; negative fixtures reject ID mixing. | Routing production through unvalidated models. |
| G03 Language | Versioned vocabulary, declarative semantics, permitted rules, scope/time/coverage contracts, pos/neg examples reviewed. | Soundness claims / unagreed shortcuts. |
| G04 Proofs | T01–T22 proved for enabled v1; registry complete; axiom audit clean; non-vacuity + clean build report. | "Calculus proved" claims; new semantics under that assurance. |
| G05 Correspondence | Python semantic functions match the Lean reference on reviewed/generated/stateful cases; version mapping + mutation checks. | "Production conforms" claims. |
| G06 Workflows | Shared admission/transition predicates, revision-bound gates, coverage/use distinction, typed correction/conclusion logic, regressions. | Stronger workflow guarantees / cutover. |
| G07 Compatibility | Citation contract, lossless edits, legacy profiles, schema decoding, output compatibility; intentional changes documented. | Replacing readers/writers. |
| G08 Persistence | Conditional writes, immutable publication, concurrency, failure injection, recovery, idempotency on supported filesystems. | Multi-agent authoritative writes. |
| G09 CLI/agent use | Stable command/output contracts, bounded context, honest completeness, explicit roots, real agent smoke tests. | Replacing agent integrations. |
| G10 Migration | Dry-run/actual migration, normalized + byte-preservation checks, idempotency, restore point, rollback rehearsal on a representative copy. | Backfilling/rewriting the corpus. |
| G11 Graph snapshots | Versioned extraction inputs, completed-generation publication, pinned reads, exact binding parity, crash/concurrency. | Treating shadow results as reliable. |
| G12 Dolt backend | Real pinned Dolt: schema, transactions, snapshots, typed rows, history, recovery; no mocks for these semantics. (Covers D-old G03 schema/migration substance.) | Dolt qualification/promotion. |
| G13 Remote | Actual bbgithub/approved remote: independent-client transport, refs, concurrency, interruption, historical retrieval. (Covers D-old G02.) | Remote publication / multi-machine claims. |
| G14 Restore/history | Clean restore reproduces selected releases/citations; explicit missing-object behavior; retention evidence. (Covers D-old G08.) | Historical availability claims; retiring old stores. |
| G15 Cost/usefulness | Predeclared held-out evaluation; latency/memory/IO/token metrics; no correctness regression; documented operational benefit; Dolt adoption only on measured advantage. (Covers D-old G11.) | Performance claims; preference-only adoption. |
| G16 Runtime separation | Python-only artifact works with no Lean/Docker/proof artifacts; formal files in source/CI only. | Release to agents. |
| G17 Cutover | Earlier gates pass for the capability; one authority per field; rollback exercised; unsupported capabilities disabled/labeled. | Authoritative backend/workflow switch. |
| G18 Delivery | Coherent pushed history; docs + gate reports complete; final results + limits linked; no stubs presented as complete. | Declaring finished. |

Dolt-handover gate mapping (old → this doc): G00→G00; G01 Gripsack→G01+§10;
G02 transport→G13; G03 schema/migration→G12+G10; G04 citations→G07(+G11
bindings); G05 immutable reads→G11(+G12); G06 admission/publication→G08(+G17);
G07 concurrency/sync→G08(+G13); G08 retention→G14; G09 context/freshness→
G06/G09(+G15); G10 workflow compat→G07/G09; G11 outcome/cost→G15; G12 quality
→G18.

Dependency order: G00 precedes changes; G03 precedes G04; G04+implementation
feed G05; types/compat/containers proceed while the model is specified;
G11–G15 qualify Dolt independently; G16 mandatory per release; G17 per
switched capability.

## 14. Performance and evaluation

Freeze the protocol before tuning. ≥2 repositories/projects, code +
operational evidence; reviewed fixture corpus + held-out task set (split by
project/time/change family); ≥24 representative agent tasks balanced across
factual questions, reviews, authoring/design, investigations; include stale
evidence, conflicting evidence, new caller, renamed file, missing dependency,
old release, incomplete inventory, scope mismatch; labeled synthetic cases
for rare failures; record model/harness/prompt/tool config/snapshot.
Compare the file path, existing index, and the Dolt candidate on the same
data and query meaning; measure cold/warm p50/p95 latency, peak memory,
files/bytes read, subprocess count, refresh duration, DB/index size, history
growth, context tokens, repeated source reads, end-task quality (label
byte/char proxies as proxies). Mandatory correctness: zero accepted invalid
inferences on the adversarial suite, no silent citation retargeting, no
completeness inflation, no migration data loss, no new unresolved failures on
held-out tasks. Initial targets: warm p95 latency and context size within 25%
of baseline for equivalent requests; material reduction in repeated reads/
tokens on repeated questions; absolute limits from G00 machines; exceptions
need measured benefit + written decision. Dolt adoption names a concrete
benefit (historical queries, joins/backlinks, extraction cost, multi-machine
workflows) with operational cost; no star counts or database pitches.
Dependency-directed invalidation/memoization per build-system correctness
work; cache keys include semantic inputs + versions; hits preserve the
assessment/completeness contract.

Future Rust/Go (§15.1 of the superseded doc): profile first; replace one
adapter at a time; a semantic-core replacement re-runs the full Lean
correspondence campaign; faster languages inherit no proof status.

## 15. Milestones

| # | Work | Exit evidence |
| --- | --- | --- |
| M0 Import + baseline | Import supplied source verbatim, record identity, package/data-root decisions, baseline tests. | G00 report + pushed baseline commit. ✅ done 2026-10-30 |
| M1 Tooling + compatibility | uv/Ruff/Pyright config, proof container, frozen compatibility fixtures, docs repairs, entry point/root contract. | G01 foundation, G07 fixtures, initial G16 smoke. |
| M2 Typed foundations | IDs/refs/enums, raw/admitted distinction, shared document codec, typed providers/adapters. | G02 + compatibility preservation. |
| M3 Calculus | Bounded vocabulary, semantics, dependency/time/coverage rules, transition contracts, examples; Lean model + theorem registry discharged. | G03 + G04. |
| M4 Python semantics | Pure core, correspondence registry, conformance harness, assessment routed through it. | G05 + mutation results. |
| M5 Workflow + persistence | Unified validators/mutations; gate bindings; run coverage; corrections; cursors; conditional publication; recovery. | G06 + G08. |
| M6 Reliable shadow graph | Generation identity, publication, pinned queries, parity, history, diagnostics, rebuild. | G11 + G12 (real Dolt). |
| M7 Agent + migration | Bounded context/receipts, backfill on a copy, old/new behavior, rollback. | G09 + G10 + G16. |
| M8 Remote + outcomes | Qualified remote/restore path; held-out cost/quality comparisons. | G13–G15; explicit adoption decision. |
| M9 Release | Qualified runtime/backend, rollback retained, Gripsack/config integration, final reports. | G17 + G18. |

(Dolt-handover M0–M5 fold in as: its M0→this G00; M1→M1+G13 prep; M2→M6
shadow slice; M3→publication/sync within M5/M6; M4→M7; M5→M9.)

Don't postpone useful type/lossless-edit fixes until all proofs finish;
conversely never switch production to newly claimed semantics before G04/G05.
Split milestones into reviewable changes; never combine package move +
schema migration + semantic rewrite in one diff. Reuse and qualify existing
solutions the repository reveals; update this plan and gate reports around
the resulting implementation.

## 16. Required scripts and delivery

`scripts/proof_check.sh` (clean build, registry/axiom audit, report, no
silent skips); `scripts/conformance_check.sh` + runner (pinned reference,
reviewed/generated/stateful cases vs actual Python functions, mismatches +
reproducible seeds); `scripts/check_contracts.py`; `scripts/check_quality.sh`
(locked lint/format/type/test orchestration); `scripts/qualify_storage.py`
(real filesystem/Dolt publication, interruption, concurrency, restore,
version-bound reports); `scripts/qualify_remote.py` (two independent clients,
never production data); `scripts/evaluate_kctx.py` (frozen corpus, arms,
cold/warm, token/proxy accounting, config identity); migration CLI + fixtures
(dry-run/plan/apply/recover, stable IDs, unresolved reporting, idempotency,
rollback verification); runtime smoke test (Python-only artifact, no proof
tools present, real entry points on fixtures).

Final delivery to Tarek: (1) linked source revision + checkpoint history with
each material behavior change explained; (2) operator guide (install, KB-root
setup, workflows, freshness/receipt meaning, missing-evidence behavior,
recovery); (3) language spec, theorem registry, pinned proof environment,
proof report + separate conformance report, precise statement of what is
proved vs tested; (4) typed domain/reference schemas, migrations,
compatibility codecs, formal↔Python correspondence table; (5) complete gate
report with passed/blocked/N-A status, evidence, skipped counts, limits;
(6) Dolt shadow qualification + adoption decision (remote/restore evidence
where enabled; retain file authority if unqualified); (7) migration/rollback
instructions + receipts from a representative copy; (8) agent task and
performance comparisons + frozen held-out method. Plus the older doc's
delivery items subsumed above (Gripsack changes, transport receipt, citation
compatibility corpus + migration classification, manifest/journal/concurrency
protocol specs, backup/retention + clean-machine restore, G/D traceability
with R/Q regression mapping, matched trial results, operating guide). The
report states plainly: implemented locally / remotely qualified / pilot-ready
/ admitted / cut over.

## 17. References

Union of both superseded documents. R01 Lean proof validation
<https://lean-lang.org/doc/reference/latest/ValidatingProofs/>; R02 Lean
runtime code <https://lean-lang.org/doc/reference/latest/Run-Time-Code/>;
R03 Provenance semirings (Green et al., 2007)
<https://www.cs.ucdavis.edu/~green/papers/pods07.pdf>; R04 Build Systems à la
Carte (2018) <https://simon.peyton-jones.org/assets/pdf/build-systems-original.pdf>;
R05 Dolt branches/revisions <https://www.dolthub.com/docs/sql-reference/version-control/branches/>;
R06 Dolt remotes <https://www.dolthub.com/docs/sql-reference/version-control/remotes/>;
R07 Dolt history/procedures <https://www.dolthub.com/docs/sql-reference/version-control/querying-history/>;
R08 Pyright config <https://github.com/microsoft/pyright/blob/main/docs/configuration.md>;
R09 uv lock/sync <https://docs.astral.sh/uv/concepts/projects/sync/>; R10 Ruff
config <https://docs.astral.sh/ruff/configuration/>; R11 Compose profiles
<https://docs.docker.com/compose/how-tos/profiles/>; S1–S21 as listed in the
superseded Dolt handover §19 (Dolt docs S1–S9, S16, S20; Git data model S21;
Obsidian backlinks/bases/dataview S17–S19; TMS Doyle S11; provenance S12;
sufficient context S13; agentic context S14; XTDB time S15; build systems
S10). These support capability claims, not this project's guarantees; pin and
verify installed versions.
