# First-admission feedback: decisions and calculus-first work

## Review basis and status

Originally reviewed on 2026-11-01 against `2da7036` and the working-tree FR1/FR2
changes subsequently committed as `11f8911`. Their earlier
[decision and qualification record](review-feature-requests.md) remains intact.
The original dispositions and source-line references below describe that reviewed
snapshot, not a claim that the later implementation still lacks these features.

The supplied report's observations at `3a2bcd7` and `2da7036` are accepted as
historical evidence. Its reported passing reruns are not new executions by this
review. Source inspection and the isolated review smoke established the original
dispositions. The subsequent workflow-3 implementation is separate from that
review evidence. The current normative contract is [calculus.md](calculus.md):
unchanged inference version `2.0.0`, core wire 2, workflow schema 3.

## Implementation follow-through

FR5 and FR6 were implemented **Lean first**, then mirrored in Python and connected
to the production services. Named-context portfolios, explicit per-claim witness
assignments, context retirement, retained selection, design binding and reopening
now have executable definitions, registered proofs and nonvacuous examples.
The original inference constructors and scope relation were not weakened.

New knowledge envelopes/signatures use schema/domain 3, authored design revisions
use `design-v3:<sha256>`, and public RPC initialization is protocol `"2"`.
Historical signed schema-2 data retains its original interpretation; old custom
authored metadata never becomes binding authority. Open proposal migration is
explicit, drops old acceptance, and requires a fresh review. See
[PORTING.md](../../PORTING.md#workflow-3-cutover) and [workflows](workflows.md).

Schema-3 preflight diagnoses every failed assignment with its claim and context,
addressing FR4's missing non-designated-claim attribution. C1's operational recipe
now distinguishes draft/proposed adoption, accepted/landing reopening, and
supersession of finalized history. The other independent P1/P2 requests below,
including replication/read-only replicas, are not claimed implemented by this
calculus cutover. Current exercised evidence is recorded in [gates.md](gates.md).


## Decision and implementation order

1. **P0 — resolve the semantic contracts first: FR5 and FR6.** Extend explicit
   release authorization to multiple assessment contexts, and separate authored
   design acceptance from implementation binding. Define the model, operations,
   proof obligations, wire version and historical migration before changing the
   Python adapters or planning a Rust translation. Neither issue is permission
   to weaken an existing check.
2. **P1 — repair current adapter/reader defects:** FR8, FR9, FR3, FR4, FR10 and
   FR11. Their acceptance criteria below preserve current eligibility decisions.
   They do not require a new inference rule. Diagnostic/read isolation work must
   not quietly implement a different scope or acceptance model.
3. **P2 — make native replication a supported operation: FR7/FR12.** Specify and
   qualify the two-store publication contract, read-only capability boundary,
   ownership and retention after the release contract is settled. Restore and
   missing-generation diagnostics are prerequisites to a usable recovery story.
4. **P3 — finish operational guidance:** clarify C1's recipe precondition,
   describe bounded evidence retrieval, and expose signed context-policy changes
   separately from claim deltas. Retain the existing FR1/FR2 implementation rather
   than creating competing reference grammars or retrieval paths.

## P0: accepted calculus changes

### FR5 — one KB must be able to retain several authorized targets

**Accept the limitation as a model-design issue, not a demonstrated soundness
failure.** The implementation is enforcing the current contract:

- [`narrower`](../../src/kctx/semantics/model.py#L76-L85) requires the same
  project and an empty source selector or exact selector equality.
- [`plan_valid`](../../src/kctx/semantics/workflow.py#L50-L84) evaluates the
  designated claim and every added claim in one candidate context. Lean's
  [`planValid`](../../formal/Kctx/Workflow.lean#L61-L75) also uses one context.
- [`_validate_query_context`](../../src/kctx/services/knowledge.py#L562-L583)
  compares queries to the latest operation's one approved context; it rejects
  widening even though older claims remain in the accumulated KB.

**Chosen direction:** a release authorizes a finite, explicitly identified
collection of assessment contexts. Keep each `Context` single-target and keep
`narrower` unchanged. This is a release/admission authorization extension, not
set-valued truth, prefix matching, or a new specialization rule.

Required contract before implementation:

1. The signed plan covers the complete candidate, expected predecessor and full
   context collection. Each context includes its target, policy (including TTL),
   intended use, sources, versions, checker and explicit time. A context name
   alone is not authorization.
2. Every added claim has an explicit approved assessment-context assignment;
   its witness and usability must check in that context at the candidate
   snapshot. Mixed-selector and mixed-project batches must have a positive,
   inhabited example. Evaluating each claim in its own *unsigned* scope is not
   an alternative.
3. Preserve authorized target coverage for carried selected claims, unless its
   removal is an explicit signed change. Adding selector `b` must not implicitly
   remove access to selector `a`. Coverage does not mean old claims remain fresh
   or usable: readers still assess them at the requested permitted time against
   current selected evidence and corrections.
4. Queries select a named authenticated context and may narrow within it. Do not
   choose the most permissive context, merge sources/policies from several
   contexts, or derive authority from the requested claim. Cross-context
   retrieval, including diff impact, must retain a context identity on each
   assessment rather than present a fictitious global verdict.
5. Receipts, computed dependencies, canonical operation identities, replay,
   retained selection and continuation tokens must bind the selected context
   and release. Historical reads retain the policy/context actually signed for
   that release; context additions cannot retroactively authorize an old one.

**Rejected shortcuts:** removing the query-target guard; reversing applicability
so a narrow observation proves a broad claim; or erasing selectors and placing
project names only in claim IDs. An empty claim selector is semantically broad
within its project, not just a missing search tag. Distinct project values still
cannot narrow to one another. Until the extension exists, separate KBs or
explicit historical-release reads preserve the boundary; rewriting specific
claims as broad ones is not an equivalent migration.

### FR6 — design approval and execution binding are different decisions

**Accept the workflow gap; narrow the title.** The CLI can accept a proposal
without an implementing revision. The failure is subsequently binding or changing
that revision while retaining valid acceptance and reaching `applied`.

[`material_revision`](../../src/kctx/services/proposals.py#L151-L185) includes
`target_revision`; [`set_status`](../../src/kctx/services/proposals.py#L578-L685)
can update it without a status transition and without validating the current
status. Acceptance is pinned only on the transition to `accepted`.
[`authored_candidate_problems`](../../src/kctx/semantics/workflow.py#L258-L340)
then rejects the changed acceptance, while `authored_edge` has no reopening
edge. These rules also exist in Lean's
[`AuthoredProposal`/`authoredCandidateValid`](../../formal/Kctx/Workflow.lean#L200-L281).
Changing only the CLI would leave the formal contract behind.

**Chosen direction:** model an accepted design revision separately from an
explicit, audited implementation binding to that design.

- Design identity continues to cover intent, acceptance-gate definitions,
  intended target constraints, scope and environment. A separate execution
  binding names the exact implementation revision, accepted design revision,
  recorded actor and operation history. Do not merely omit arbitrary material
  fields from the current digest.
- Permit binding/rebinding an implementation in `accepted`/`landing` without
  silently rewriting design acceptance. Require the accepted design to be
  unchanged and the binding to satisfy its target constraints.
- Every execution gate remains bound to the accepted design, exact current
  implementation, definition, environment, scope, checker, actor and time.
  **Old passes remain historical; rebinding never turns them into new passes.**
  New target evidence must be recorded before `applied`/`verified` is possible.
- A material design change requires an explicit audited reopening and fresh
  acceptance, rather than the present metadata-only mutation that leaves a
  decided status invalid. Define the reopening edge and rejection semantics in
  the model. Already applied/verified history must not be silently retargeted.
- Keep exact landed-object resolution and the distinction between authored
  workflow status and signed knowledge admission. A local checkout reference
  can already resolve an unpushed commit; the remote-only restriction belongs
  to `org/repo` acquisition, not the calculus. See
  [`resolve_landed`](../../src/kctx/services/proposal_targets.py#L28-L93).
- Report the actual failed candidate predicates in transition errors using the
  existing predicate reporting, rather than the generic E105 alternatives.

Reject automatic re-acceptance, automatic gate re-signing, unvalidated target
swaps and a blanket backwards state edge. A logged actor in this authored
workflow is not an Ed25519 release approval.

### Proof, version and migration gate for both changes

These are accepted design directions with concrete obligations, not claims that
the current proofs cover them. Before changing runtime acceptance:

- Update the Lean model/decision functions and Python twin together. Review
  `Model`, `Workflow`, `Selection`, retrieval and their wire codecs. Preserve
  the [revision contract](calculus-revision.md), especially exact scope, complete
  context, expected predecessor and full-plan approval.
- Re-establish the affected [theorem registry](../../formal/theorems.json)
  obligations: T02 codecs, T03 state preservation, T08 receipt mismatch, T12
  scope/origins, T15 history, T17 policy, T18 authorization/workflow, T20–T21
  rejection/replay and T22 explicit-input determinism. Add laws specifically
  covering context membership and design/implementation separation; a re-run of
  old theorem names alone is insufficient.
- Retain positive examples of two targets readable at one head and acceptance
  before implementation, plus negative cases for unsigned contexts, unsupported
  second claims, cross-context receipts, changed designs, stale target gates and
  conflicting implementation binds. Include rollback and continuation across a
  later publication, not just first admission.
- Make an explicit incompatible semantic/wire revision and migration decision;
  do not silently change `2.0.0`/schema `2`. Retain old signed bytes and their
  original interpretation. A v2 single-context approval cannot be treated as
  approval of a new context collection, and an old material digest cannot be
  reinterpreted as the new design digest without an explicit transition.
- Exercise production adapters after conformance: actual source resolution,
  hashing/projection of material fields, signer verification, conditional
  publication and interrupted recovery. Lean's opaque IDs do not prove that a
  Python file projection or Git/Dolt transport implements the modeled binding.

### C10 — retain context-policy TTL; disclose policy changes

No TTL calculus change is accepted. The current
[calculus card](calculus.md#explicit-context-receipts-and-operations) explicitly
answers the question, and
[`witness_freshness`](../../src/kctx/semantics/checker.py#L268-L279) uses
`context.policy.ttl`. T11's monotonicity premise fixes TTL; a new signed TTL is a
changed input, not renewed observation evidence or a counterexample to expiry.

Accept a separate signed-context/policy diff in plan review, showing old/new TTL
and the reassessment boundary. Do not fabricate claim edits or observation events
for that change. Under FR5 this disclosure belongs to the affected context, not
to a single implicit policy for every target.

## Original C-items: disposition against the reviewed tree

The earlier implementation record is
[migration-hardening.md](migration-hardening.md). Closing a reported case here
is not a claim that every reader or every input variant is tolerant.

| Item | Disposition and current evidence |
| --- | --- |
| C1 | Keep strict decided-status invariants and named validation failures. The adoption recipe needs a narrower precondition: its [test starts at `proposed`](../../tests/test_validate.py#L308-L339), while the [legal edges](../../src/kctx/semantics/workflow.py#L216-L231) do not reset an already accepted/applied record to acceptance. [INFERENCE] The recipe cannot repair every already-decided record unchanged. State the starting status explicitly and retain documented supersession as the current route for historical records that cannot honestly re-earn bindings; do not waive them. |
| C2 | Reported address rejection/impact abort fixed: [relationship decoding](../../src/kctx/codecs/records.py#L130-L160) uses `parse_evidence_address`; [impact](../../src/kctx/services/inventory.py#L166-L175) requests tolerant relationship loading. Arbitrary prose/bare slugs remain invalid; skipping them with disclosure is not lossless conversion into evidence. |
| C3 | Original scoped-reader failure addressed: [signature listing](../../src/kctx/services/signatures.py#L167-L178) supports `skipped`, and [stale](../../src/kctx/services/freshness.py#L273-L282) passes it through. Do not close the broader reader-consistency issue: FR8 remains. The old assertion that `fix` is only `ProposalId` is stale in this working tree. |
| C5 | Remains dropped. `deferred` is not a land/deploy/use gate timing; deferred proposal lifecycle and gate timing are different concepts. No new gate phase accepted here. |
| C6 | Reported multi-token scan abort fixed by [located per-token handling](../../src/kctx/citations/scan.py#L200-L259) and the corresponding stale loop. `cite check` reports unverifiable with exit 3; stale reports non-clean with exit 2. Strict duplicate/unterminated rejection is retained. |
| C7 | Reported non-Markdown symlink abort fixed. [The current walk](../../src/kctx/adapters/files/contained.py#L178-L221) skips non-`.md` links unread, including implicitly encountered directory links; explicit links, link ancestors and `.md` links are refused. This is not a promise to follow directory links or honor `.gitignore`. |
| C8 | Closed: [explain's CLI](../../src/kctx/cli/knowledge.py#L163-L169) declares only request/release; its live help agrees. No ignored pagination options remain. |
| C9 | Closed: [gate recording](../../src/kctx/services/proposals.py#L758-L774) always computes the table digest for `rev` and stores repository evidence separately as `repo_rev`. |
| C11 | Partial, not fully closed: the designated-claim diagnosis exists, but the [preflight error path](../../src/kctx/services/knowledge.py#L791-L801) still inspects only that claim. Track the remaining work as FR4, not a second fix. |
| C12 | Reported read-only descriptor exhaustion fixed: [read-only acquisition](../../src/kctx/adapters/files/contained.py#L146-L175) reads and closes each leaf. Write-back mode still retains descriptors deliberately; this does not certify unlimited-size `--touch`/`--mark` batches. Raising the process fd limit is not the accepted fix. |

## FR1/FR2: existing local implementation, not new gaps

### FR1 — keep the chosen evidence-address union

The current [fix reference type](../../src/kctx/domain/targets.py#L102-L139) is
`ProposalId | EvidenceAddress`, and
[signature decoding/writing](../../src/kctx/services/signatures.py#L41-L104)
uses it. Accept that provider-neutral choice: proposal ID, `ev:<home>/<stem>`, or
pinned code locator. PRs/tickets can be represented by evidence records; no second
PR/ticket grammar or implicit merge-time lookup is needed. Raw historical
`org/repo#7`/`TICKET 1234` values still need explicit conversion; this does not
make FR8 disappear.

One correction to the report's rationale: regression detection reads
[`fixed_at`, not `fix`](../../src/kctx/services/freshness.py#L123-L152). It can
work with an empty fix list. The narrowed decoder excluded some useful records;
it did not establish a rule that only proposal-backed fixes can have regression
flags. Keep `fixed_at` explicit and the regression flag advisory, not proof of
causality or of a successful fix.

### FR2 — keep local diff retrieval separate from inference

[`impact --diff`](../../src/kctx/cli/inventory.py#L142-L179),
[`read_local_diff`](../../src/kctx/adapters/git/diff.py#L168-L227),
[`impact_diff`](../../src/kctx/services/diff_impact.py#L75-L171) and
`authored.impact_diff` already implement the requested local-commit entry point.
The existing decision record defines repository matching, citation coordinates,
bidirectional relationships, signatures, claim relevance and omissions.

Scope is **committed but unpushed** `base..head`, not index/worktree changes or
triple-dot merge-base selection. Citations/dependencies are review candidates,
not a contradiction verdict. Current admitted-claim retrieval goes through
[`context_for_assets`](../../src/kctx/services/knowledge.py#L1247-L1267), so it
inherits FR5's one-context limitation; extending its scope later depends on the
P0 contract rather than bypassing authorization in diff code.

## P1: accepted adapter and reader repairs

### FR8 — context must disclose malformed incident records

Accept. [`context`](../../src/kctx/services/context.py#L141-L153) still calls
both investigation and signature collection loaders without `skipped`, before
filtering their results. Its result type has no top-level warnings field.
Changing which valid values `fix` accepts cannot substitute for fault isolation.

Pass collection diagnostics through the aggregate result and CLI/RPC partial
status; cover both incident collections and warnings from composed readers.
Keep exact requested-record failures and `validate` strict. Acceptance: an
unrelated bad signature/investigation cannot suppress a good asset's context;
the output locates the skipped record, retains readable results and is not
reported complete. This is source-supported remaining work, not a newly executed
FR8 repro.

### FR9 — restore must support the ordinary unborn destination

Accept both the fetch failure and leaked temporary ref.
[`restore`](../../src/kctx/services/knowledge.py#L1297-L1363) has empty-target
guards but fetches directly into `refs/heads/*` without `--update-head-ok`, then
leaves `refs/kctx/restore-candidate` after publication.

Use `--update-head-ok` only for this guarded empty-destination restore fetch;
retain verification before checkout and completed-ref publication. Clean up the
temporary ref owned by the operation on success and failure, without deleting
pre-existing unrelated refs. Do not loosen restore into a general pull or
recommend a detached unborn HEAD without an actual commit to detach to.
Acceptance: matching and differing default branch names restore, restored head
and historical reads agree with the backup, verification failure never publishes
a completed ref, and no temporary restore ref is left behind.

### FR3 — canonicalize bootstrap policy, not historical artifact bytes

Accept; this is also a documentation/implementation contract mismatch, not just
a poor error. [Configuration](config.md) and [workflows](workflows.md) specify a
canonical digest, while [`_policy`](../../src/kctx/services/knowledge.py#L180-L200)
hashes raw bootstrap bytes.

For new bootstrap identity: bounded strict decode, validate policy shape,
canonicalize, compare the canonical digest to the configured anchor, then retain
those same canonical bytes. Reuse the existing
[duplicate-key rejecting decoder](../../src/kctx/adapters/files/knowledge.py#L20-L46)
and [policy validation](../../src/kctx/services/knowledge_models.py#L52-L71).
Report the computed digest and which representation it identifies on mismatch.

Do not canonicalize already signed artifacts in place, silently change their
anchor, or accept either raw/canonical hashes as an unlabelled fallback. Existing
release artifacts remain exact-byte, content-addressed historical inputs; any
re-anchoring needs an explicit migration decision. Acceptance: whitespace/key
order do not alter new bootstrap identity; duplicate/unknown/changed policy data
remain rejected appropriately; canonical retained bytes agree with the anchor;
historical signed-object verification is unchanged.

### FR4 — diagnose all checked claims, not only the designated one

Accept as the remaining part of C11. Compare the
[all-added-claims predicate](../../src/kctx/semantics/workflow.py#L75-L84) with the
[one-claim error path](../../src/kctx/services/knowledge.py#L791-L801).

Collect assessment gaps for the designated claim and every added claim, dedupe
by exact reference and prefix each diagnostic with `id@revision`. Preserve
structural/authority/designated-witness rejection as distinct causes: a usable
claim does not imply the whole plan is valid. The checker remains the decision
source; do not create a permissive second preflight while improving messages.
Acceptance: supported first + unsupported or inapplicable second identifies the
second claim; multiple failures remain attributable; rejected candidates stay
rejected. No inference-rule change is required.

### FR10 — distinguish unavailable native generations from invalid ones

Accept. [Native execution](../../src/kctx/adapters/dolt/knowledge.py#L108-L118)
forwards raw Dolt errors; [generation reads](../../src/kctx/adapters/dolt/knowledge.py#L196-L220)
address immutable commit IDs. Missing directories can fail before Dolt runs.

At the release/native-storage boundary, name the requested release, missing
commit (including a predecessor if that is what failed), and configured store.
Distinguish absent store, unavailable commit, permission failure, corrupt data and
wrong KB/policy. Suggest cloning/restoring an absent store or fetching a retained
published generation. **`dolt fetch` is not a guaranteed repair**: the writer may
never have published the object, remote retention may have removed it, or the
failure may be corruption/authentication. Never answer from an older release as
fallback. Acceptance covers these distinct failures and a healthy pinned read.

### FR11 — move locks, do not unlink them after use

Accept the authored-tree pollution. [`file_lock`](../../src/kctx/adapters/files/mutations.py#L42-L52)
creates adjacent stable files, and
[proposal readers](../../src/kctx/services/proposals.py#L427-L477) acquire them
because they also recover interrupted mutations.

Move the shared lock namespace to managed local state: Git common-directory
state for Git workspaces, a deterministic configured local-state location for
non-Git workspaces, keyed by canonical record/worktree identity. Every reader,
writer and recovery path must use the same namespace. Preserve locking and
conditional writes; do not remove recovery from readers to hide the artifact.
Deleting a lock on unlock can split waiting/open users across different inodes
and break exclusion. Existing old lock-file cleanup must occur only with writers
quiescent, not opportunistically during a read. Acceptance: ordinary proposal
reads leave the authored tree unchanged, while competing writes and interrupted
recovery retain their existing behavior.

## P2: FR7/FR12 — supported replication and read-only readers

Accept the operational gap. The live knowledge CLI has no sync operation.
[`KnowledgeEngine.__init__`](../../src/kctx/services/knowledge.py#L123-L145)
creates operation state and writes an absolute-path owner marker even for reads.
The [writer lock](../../src/kctx/adapters/files/knowledge.py#L90-L98) is local.
The Rust [design document](greenfield-design.md) explicitly labels itself
unshipped; its `sync` statement is a product goal, not evidence that the Python
CLI already promised that command.

Adopt the following adapter contract; it does not add a proof rule:

- Freeze one exact completed release to transfer. Publish required Dolt objects
  and durable retention refs before advancing the Git completed-release ref.
  On receive, acquire Dolt first, fetch Git into staging refs, authenticate the
  complete selected release/history and required artifacts, then conditionally
  advance the visible local completed pointer. Failed/incomplete transfer leaves
  the previous completed release usable. Ordering is not a two-store transaction.
- Transfer the closure of **published** releases, not blindly every candidate
  branch. [`commit_candidate`](../../src/kctx/adapters/dolt/knowledge.py#L146-L194)
  creates branches for operations; `push --all` can transport unadmitted work.
  Every advertised head/historical release's native commit must remain reachable
  under the remote's real retention/GC policy. One tested head branch may retain
  its ancestors; that is not proof for every backend or pruning policy.
- Git's [release trees](../../src/kctx/adapters/git/knowledge.py#L154-L192)
  already retain manifests and content-addressed artifacts. A read replica should
  not need copied writer journals or `.knowledge-owner.json`. Backup/restore is
  disaster recovery, not incremental synchronization.
- Read-only is a service capability, checked at CLI, RPC and embedding boundaries,
  not merely hiding four commands. Block capture, proposal/signing/admission,
  selection, migration, restore and recovery mutations. Read construction must
  not initialize operation state, claim writer ownership or auto-recover.
  Explicit replica refresh may update replicated objects/pointers; ordinary reads
  must not become refresh operations. A config flag is not an OS security boundary;
  protect filesystem/remote credentials as well.
- Separate logical KB/trust identity from local writer-instance ownership. A
  portable read replica may associate with the same authenticated KB; replacing
  the absolute writer marker with `kb_id` alone must not let two checkouts mutate
  one native working directory or overwrite each other's operation state. Do not
  make deleting an ownership marker the supported relocation protocol.
- Keep one publishing writer as the supported initial deployment. Local `flock`
  and private-key custody are not distributed fencing. In particular, `admit`
  consumes a signed approval rather than requiring the private key itself.
  Conditional remote ref updates and remote access controls are required; this
  review does not accept an implicit multi-writer merge design.

Qualification must exercise two real local clients, an intentionally lagging
Dolt replica, interruption between transports, a conflicting completed-pointer
update, relocation, denied mutation in read-only mode, first/head/history reads,
continuation parity and retained-object availability after supported pruning.
Hosted transport and remote-side GC claims require that actual endpoint; the
report's local qualification is useful but explicitly did not establish them.

## Consumer note — evidence omission is a byte budget, not a record threshold

Accept documentation, not a calculus change. The
[response bound](../../src/kctx/services/knowledge.py#L1206-L1233) is 65,536 bytes.
Evidence/provenance are reduced before records are removed; `evidence_omitted`
and `complete` expose the loss. Roughly forty records is fixture-dependent, not
an API threshold. Empty `contrary`/attestation arrays under omission do not mean
no contrary/supporting evidence exists.

Small limits can help, but are not a guarantee: the initial provenance includes
whole-snapshot observations/corrections, and even one large claim can exceed the
budget. A continuation advances records; it does not recover evidence omitted
from records already returned. Evidence-consuming clients must inspect the flags,
retry a narrower exact query at the **same release/context**, and treat continuing
omission as an explicit retrieval limitation rather than complete evidence.

## Executed verification for this review

No reported failing repro was rerun just to confirm the report. No runtime source,
formal model, permanent tests or existing user changes were modified by this
review. This is not a new full-suite, Lean, native admission/restore or remote
replication qualification.

The installed `.venv/bin/kctx` was exercised directly:

- `impact --help`, `knowledge --help`, and `knowledge explain --help` exposed the
  local diff options, absence of sync, and absence of explain pagination options.
- A temporary KB and local source repo with two unpushed commits and deliberately
  different dirty worktree bytes exercised `sig new`, `sig show`, `uses`, and
  `impact --diff`. The evidence-address fix round-tripped with explicit
  `fixed_at`; `uses` returned its signature referrer.
- The exact commit diff returned one changed hunk at line 2, one same-file
  nonoverlapping citation and one old-side overlapping citation, matching repo
  asset, both relationship directions and attached signature. It returned
  `no_release`, `complete: false`, exit 2 rather than invented admitted claims.
- Real JSON-RPC `initialize` + `authored.impact_diff` returned an identical payload
  and partial status. The temporary fixture initially used invalid singleton
  citation ranges (`L=1`); after correcting the fixture to the actual grammar
  (`L=1-1`, `L=2-2`), the overlap checks passed without changing application code.
- Temporary repositories/configuration were removed. The signed-release path's
  earlier qualification remains attributed to the existing FR1/FR2 record; it
  was not independently re-executed here.
