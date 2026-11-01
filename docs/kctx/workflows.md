# Supported workflows

Use `uv run kctx` in the development checkout (or installed `kctx`). Commands
below use shell variables for **real returned IDs and operator inputs**, not
invented identities. Global `--json` goes before the command. Configure the
workspace and native tools using [config.md](config.md). CLI commands are native
Click commands with Rich human presentation; JSON is the automation boundary.
The four [flow diagrams](flows.md) explain the boundaries without duplicating
them here.

## Capture, authorize and publish structured knowledge

Provision an operator-held Ed25519 private key outside the KB. The authored
`.kctx/knowledge-policy.json` has this schema (the key value must be the real raw
public key encoded as hex):

```json
{
  "schema_version": 2,
  "kb_id": "test-kb",
  "policy_version": "review-policy",
  "trusted_keys": {
    "reviewer-key": {
      "public_key": "<raw Ed25519 public key in hex>",
      "target_uses": ["review"]
    }
  }
}
```

This is the policy shape in `tests/test_knowledge.py`, with the generated public
key represented descriptively. Persist canonical bytes with
`kctx.adapters.files.knowledge.save`, then compute their SHA-256 with `canonical`
and `digest` in the trusted provisioning process and set `knowledge_policy_digest`.
The bootstrap reader still hashes exact file bytes, so do not pretty-print the
file after anchoring it. A changed policy cannot replace that trust anchor.
`knowledge_dir` selects the native Dolt destination; the authored root must be a
Git repository.

Capture already acquired exact bytes, identifying the actual immutable upstream
revision and observation time. This command does not fetch a PR URL or parse prose
into facts:

```sh
uv run kctx --json knowledge capture --kind source --source "$SOURCE" --revision "$REVISION" --file "$SOURCE_FILE" --observed-at "$OBSERVED_AT"
uv run kctx --json knowledge capture --kind pr --source "$PR_URL" --revision "$PR_REVISION" --file "$PR_CAPTURE_FILE" --observed-at "$OBSERVED_AT"
uv run kctx --json knowledge capture --kind document --source "$DOCUMENT_SOURCE" --revision "$DOCUMENT_REVISION" --file "$DOCUMENT_FILE" --observed-at "$OBSERVED_AT"
```

Choose the relevant kind; they share the same admission path. Retain each returned
capture record. A new `candidate.json` has exactly these fields:

- `schema_version`: integer `3`.
- `expected_snapshot`: the current completed snapshot, or `bootstrap:<kb_id>` for
  first admission.
- `kb`: the complete candidate KB with a new snapshot and the previous collections
  preserved as immutable prefixes.
- `capture_ids`: actual returned retained capture IDs covering the observations
  and selected sources.
- `contexts`: named records with an `id` and a complete core-v2 `context`. Each
  context identifies the **candidate** snapshot, explicit `--now`, target,
  intended use, policy and exact source/revision/content selections.
- `assignments`: one record per newly added claim, in candidate order, with
  `claim`, the named `context` ID, and its exact `witness`.
- `retired_contexts`: exact IDs intentionally removed from the predecessor;
  use an empty list when retaining all prior context identities.
- `authority_key`: the approving public-key identity.

The KB contains observations, claims, attestations, enumerations, derivations,
corrections and receipts. Captured bytes alone establish no atomic support.
The complete fixture is `KnowledgeAdmissionTests.candidate` in
`tests/test_knowledge.py`; component shapes are in [calculus.md](calculus.md).
Multiple selectors/projects use separate named contexts and explicit assignments,
not an empty selector substituted for a specific claim.

```sh
uv run kctx --json knowledge propose --candidate candidate.json --target-use review --now "$NOW"
uv run kctx --json knowledge sign "$PLAN" --private-key "$PRIVATE_KEY" --key-id reviewer-key > approval.json
uv run kctx --json knowledge admit "$PLAN" --approval approval.json
```

`PLAN` is the ID returned by propose. Review its exact candidate, context
collection, assignments, retirements, policies, inputs, operation use and
predecessor before signing. The declared `--target-use` must occur in the
contexts; the key must permit that use **and every context's intended use**.
Sources and policies are never merged between contexts. Zero added claims are
allowed for an explicit signed context/correction change.

The schema-3 approval authorizes that complete plan, not future revisions.
Preserve the returned release and snapshot. Identical replay is idempotent;
changed inputs or a competing predecessor conflict. Operators retain private
signing authority; `kctx serve` does not expose signing.

## Retrieve, explain and continue at one release

First discover the selected release's authenticated context IDs and full values:

```sh
uv run kctx --json knowledge contexts --release "$RELEASE"
```

A request file has exactly `context_id`, `context`, and `claims`; each claim
reference is `{"id":"reviewed","revision":"r1"}`. Copy the chosen discovery entry's
ID and context; it already names the published snapshot. Policy, source selections,
versions, checker and intended use remain exact. The target may narrow within
that entry's authorization, and `now` may advance but cannot predate it. Supplying
another context's target or sources under this ID is rejected.

```sh
uv run kctx --json knowledge context --request request.json --release "$RELEASE" --limit 20
uv run kctx --json knowledge explain --request one-claim.json --release "$RELEASE"
uv run kctx --json knowledge context --request request.json --release "$RELEASE" --limit 20 --continuation continuation.json
```

Save **only the returned `continuation` object** as `continuation.json`. Keep the
same request; continuation binds context identity, complete query and release,
not “whatever is latest.” An explicitly supplied release must agree with the
continuation. An empty claims list selects active claims applicable to this one
context. Each record identifies `context_id`. `knowledge explain` requires one
exact claim revision and does not accept pagination options.

The response ceiling is 64 KiB, not a fixed record count. Evidence may be omitted
before records are dropped; inspect `evidence_omitted`, `complete`, contrary
evidence, missing refs and omission counts. Smaller limits can help but cannot
guarantee complete evidence, because provenance and individual records also have
a size. Continuation advances records; it does not recover evidence omitted from
already returned records. Retry a narrower exact query at the same release and
context, and preserve any remaining limitation.

For authored navigation, use `context ID`, `home ID`, `uses TARGET`, or
`timeline ID`; those are not alternative sources of proved claim support.

The programmatic server is `uv run kctx serve`, JSON-RPC 2.0 over JSONL. Initialize
with `protocol_version: "2"` and use its advertised schemas. `knowledge.contexts`
discovers named contexts; `knowledge.context` and `knowledge.explain` require
`context_id`. Python embedding imports `serve` from `kctx.engine`. Engine protocol
2, workflow schema 3 and core calculus schema 2 identify different contracts.

## Citation maintenance is not knowledge admission

```sh
uv run kctx cite make code "$REPO" "$PATH_IN_REPO" "$LINE_RANGE" --rev "$GIT_REVISION"
uv run kctx --json cite check notes.md
uv run kctx --json cite check notes.md --touch --mark
uv run kctx cite render notes.md --format md --audience internal
uv run kctx --json admit "$PR_REF" --dry-run
uv run kctx --json admit "$PR_REF"
uv run kctx --json admit --repo "$ORG_REPO" --since "$BASE_REVISION" --dry-run
uv run kctx --json admit --repo "$ORG_REPO" --since "$BASE_REVISION"
uv run kctx --json stale --drain
```

The top-level `admit` is the existing PR/repository citation-refresh and judgment
workflow, not authenticated structured `knowledge admit`. `--since` is required
when a repository has no cursor. A dry run previews changes; the durable cursor
must not skip unresolved judgment work. PR refresh records current state as an
advisory; a merged PR can still require review. Neither refresh nor `--touch`
retargets the original cited revision, range, state or `seen`. Exact historical
binding and current advisory fields are described in [flows.md](flows.md).
Dirty code citation construction requires explicit `--allow-dirty`; do not
mistake that permission for authenticated admission of worktree facts.

## Review a local diff before pushing

```sh
uv run kctx --json impact --diff 'HEAD~1..HEAD'
uv run kctx --json impact --diff "$BASE..$HEAD" --repo /path/to/local/checkout --depth 2
```

`--repo` here is a **local path**, not the `org/repo` acquisition argument of
`admit`. Without it, use the current directory. Both endpoints resolve once to
local commits; unpushed commits work, but uncommitted/index changes are not
included. Triple-dot ranges are rejected. No fetch, clone, PR lookup, external
diff or textconv helper runs. `impact <asset>` retains its existing behavior.

The reply gives exact `base`/`head` identities and a `files` checklist:

- Old/new paths, Git change status, binary flag and zero-context hunks.
- All same-file code citation occurrences for that repository. `cited_range`
  preserves the authored range; `overlaps` indexes the file's `hunks` and names
  the `old` or `new` coordinate side. Endpoint pins and identical historical
  blobs permit comparison. Other pins remain `unmapped_revision`, not a false
  `nonoverlap`. Zero-count sides are gaps, not changed lines. Illustrative
  citations are excluded; malformed tokens and unreadable sources are disclosed.
- Repository-locator assets, inbound/outbound relationships, bounded impact and
  related assets, plus signatures explicitly listing those assets. This is
  repository-level candidate ownership, not a guessed path ownership proof.
- `claims` from all authorized contexts of one completed release, retaining
  `context_id` on each assessment, contrary refs and evidence. Exact asset IDs in
  structured formula subjects, arguments or scope selectors determine relevance;
  names/prose are not aliases. Scope filtering remains authoritative.

Top-level `knowledge` carries the pinned release, approved named `contexts`,
provenance, omission counts and continuation. Each context uses its approved
explicit time, not the wall clock. A claim can appear under more than one context
with different assessments; these are not pooled into a global verdict. A newer
publication cannot mix generations within a reply. With no completed publication
the status is `no_release`; broken storage/configuration is `unavailable`, never
an empty admitted result. Both are partial (`complete: false`, exit 2), as are
warnings, depth cutoffs or omissions.

Use `--claims-limit 1..100` to bound context–claim pairs per page (default 100).
Save only `knowledge.continuation` and continue with the same resolved diff and
asset set:

```sh
uv run kctx --json impact --diff "$BASE..$HEAD" --repo /path/to/local/checkout \
  --claims-continuation claim-page.json
```

JSON-RPC exposes the same service after initialization:

```jsonl
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocol_version":"2"}}
{"jsonrpc":"2.0","id":2,"method":"authored.impact_diff","params":{"diff":"HEAD~1..HEAD","repo":"/path/to/local/checkout","depth":2,"claims_limit":100}}
```

Supply the returned continuation object as `claims_continuation` for the next
RPC page. The result is a review checklist, **not** contradiction detection or
admission. Workspace citations/inventory are separate from the authenticated
release, and an empty checklist proves neither safety nor absence of dependents.
See the [acceptance rationale](review-feature-requests.md).

## Authored proposals and gates

New proposals use `workflow_version: 3` within document schema 1. Declare the
intended source with `--target-source` before the implementation exists, or let
an already supplied, exactly resolving `--target-revision` establish it. Use
`./path` or an absolute path for an uncreated local file/repository; `org/repo`
names a remote repository, not a local two-component path.

```sh
uv run kctx --json proposal add --kind decision --origin user-request --title "$TITLE" --target "$TARGET" --context "$CONTEXT" --evidence "$EVIDENCE" --change "$CHANGE" --why "$WHY" --research "$RESEARCH" --alternatives "$ALTERNATIVES" --gates gates.md --target-source "$SOURCE" --environment "$ENVIRONMENT" --scope "$SCOPE"
uv run kctx --json proposal set "$PROPOSAL" --status accepted --by "$ACCEPTOR"
# Implement the accepted design, then bind its exact retained revision.
uv run kctx --json proposal show "$PROPOSAL"
uv run kctx --json proposal bind "$PROPOSAL" --target-revision "$TARGET_REVISION" --by "$EXECUTOR" --expected-revision "$FILE_REVISION"
uv run kctx --json proposal set "$PROPOSAL" --status landing --by "$EXECUTOR"
uv run kctx --json proposal gate "$PROPOSAL" "$GATE" --outcome pass --evidence "$GATE_EVIDENCE" --by "$ACTOR" --rev "$REPO_AT_SHA" --checker "$CHECKER_VERSION" --expires-at "$EXPIRY_EPOCH"
uv run kctx --json proposal set "$PROPOSAL" --status applied --by "$EXECUTOR" --landed "$SOURCE_AT_REVISION"
```

Use actual returned proposal/gate IDs and source revisions. Research, at least
two alternatives and a real gate table establish modern review readiness; an
incomplete new record remains draft. `--gates` accepts a file or multiline table.
Gate phases remain land/deploy/use. `show` supplies the file revision for optional
conditional writes; reread after each mutation before reusing `--expected-revision`.
`accepted_revision` is a `design-v3:<sha256>` design identity, not the `revision`
file hash returned by `show`. Never use one in place of the other.

Acceptance binds design intent, intended source, environment, scope and gate
definitions. `bind` records the accepted design, resolved source/target, actor
and time, preserves acceptance, and clears previous landing refs. Rebinding in
accepted/landing to a different target makes old-target gates ineligible.
Matching evidence must be recorded for the new target before application.
An identical-target/context pass can remain reusable while unexpired; binding
itself never attests landing.

Gate evidence still binds exact design revision, target, definition, environment,
scope, checker, observation/expiry times and actor. `--rev` is repository evidence
retained in `repo_rev`, never the computed gate-table digest or the proposal file
revision. A text label `pass` cannot authorize changed inputs. Applied proposals
can record deploy/use evidence and advance to verified; finalized records cannot
be retargeted or reopened.
Gate outcomes remain observations recorded by an actor; the tool does not execute
arbitrary check prose or infer that an implementation satisfies natural-language
intent merely because its metadata is structurally eligible.

To change accepted/landing design material, first run:

```sh
uv run kctx --json proposal reopen "$PROPOSAL" --by "$ACTOR" --note "$REASON"
```

This returns to proposed and clears acceptance, execution roles, binding, target
and landing refs while preserving material and historical gate records. Edit the
design, earn fresh acceptance, then bind and check the implementation. Generic
`set` and `add --force` cannot bypass this boundary. Authored workflow eligibility
does not replace the separate Ed25519 knowledge approval protocol.

Owners: `cli/proposals.py`, `services/proposals.py`, `proposal_targets.py`,
`semantics/design_workflow.py`. Qualification pointers:
`tests/test_authored_design.py`, `tests/test_authored_design_cli.py`,
`tests/test_gates_rev.py`, `tests/test_proposal_boundaries.py`.

### Adopting a historical proposal

Records without `workflow_version` retain workflow 2: their original material
hashes, validation rules and historical gate bindings are not reinterpreted.
Flat-file paths remain readable. A legacy readiness exemption does not waive
decided-status bindings or confer signed release authority.

For a workflow-2 **draft/proposed** record:

```sh
uv run kctx --json proposal adopt "$LEGACY" --by "$ACTOR" --note "$REASON" --target-source "$SOURCE"
```

For a workflow-2 **accepted/landing** record:

```sh
uv run kctx --json proposal reopen "$LEGACY" --by "$ACTOR" --note "$REASON" --target-source "$SOURCE"
```

An exactly resolvable existing target may supply the source when it is omitted.
Both operations retain authored content/history, switch to workflow 3's modern
readiness profile, and discard old acceptance/execution authority. Adoption
chooses draft or proposed according to readiness; reopening requires a new review.
Supply real research, alternatives and gates before fresh acceptance. Then use
`bind`, evidence recording and the normal landing transitions.

Already applied/verified history is not migrated in place. Create and review a
new proposal, then supersede the old record with an explicit resolving
`--superseded-by` reference. `backfill-landed --dry-run` only discovers historical
text hints; it does not authorize writing finalized landing evidence.

## Investigations can conclude unknown

```sh
uv run kctx --json inv new "$SLUG" --trigger adhoc --title "$TITLE"
uv run kctx --json inv show "$INVESTIGATION"
# Edit the returned authored document, retaining its structure and provenance.
uv run kctx --json inv conclude "$INVESTIGATION"
uv run kctx --json inv promote "$INVESTIGATION" "$PROJECT"
```

Fill `Checked against` and `Scope and limits`; resolve open hypotheses into
supported, refuted or `unk` with honest evidence and limits. Structural conclusion
allows empty/unknown hypotheses when required sections are present and no open
hypothesis remains. It does **not** prove an incident cause or admit factual
claims. Malformed hypotheses are errors, not silently accepted unknowns.
`services/investigations.py::conclusion_problems` is shared by mutation and
validation; see `tests/test_investigations.py` and `tests/test_validate.py`.

## Track a signature's external fix

```sh
uv run kctx --json sig new cache-timeout --asset service-cache \
  --fix ev:cache-project/fixing-pr --fixed-at 2026-10-31
uv run kctx --json sig new retry-loop --asset service-cache \
  --fix 'example-org/example-repo@abcdef1234567:src/retry.py:20-30'
uv run kctx --json uses ev:cache-project/fixing-pr
uv run kctx --json uses 'example-org/example-repo@abcdef1234567:src/retry.py:20-30'
```

`fix` accepts existing valid proposal IDs, evidence-record addresses, and pinned
code locators. Record a PR or ticket in an evidence record and use its `ev:`
address; raw `example-org/example-repo#7` and `TICKET 1234` remain invalid fix
values. Use the recorded SHA spelling for code-fix reverse lookup. `uses` retains
its existing tracked-file coverage in Git workspaces, so add the signature to
Git before querying it.

A fix link does not set `fixed_at`, change signature status or prove resolution.
Set the date explicitly when warranted. An investigation citing the signature
and created after that date remains an advisory regression candidate regardless
of whether the fix names a proposal, evidence record or code location. No merge
time is fetched and no semantic support is inferred from the reference.

## Observation worktrees, provenance and coverage

```sh
uv run kctx --json run new --project "$PROJECT" --mode review --task "$TASK"
uv run kctx --json observe "$RUN" --system git --locator "$REPO_PATH" --revision "$GIT_REVISION" --role code --status ok --cmd "$OBSERVED_COMMAND" --environment "$ENVIRONMENT" --evidence "$EVIDENCE"
uv run kctx --json cover "$RUN" --item "$ITEM" --outcome supported --evidence "$OBSERVATION" --policy single-source
uv run kctx --json check "$RUN" --require "$ITEM"
uv run kctx --json checkpoint "$RUN" --note "$NOTE"
uv run kctx --json resume "$RUN"
```

Git capture records stable retained worktree inputs, not HEAD alone: index,
tracked/untracked changes and submodule inputs matter. A supplied immutable
revision must match. Unavailable or changing inputs stay explicit rather than
becoming clean evidence. Rechecks invalidate stale/unknown dependencies.
For derived evidence use repeated `--derived-from OBSERVATION`; provenance must
resolve and cannot manufacture independent origins by copying an observation.
`independent-origins` requires multiple independent roots; even multiple entries
under `single-source` must satisfy the service's multi-evidence independence
rule. Non-supported coverage outcomes require `--reason`; not-examined,
unavailable, inconclusive and not-applicable are not false claims.

Owners: `services/runs.py`, `run_inputs.py`, `run_provenance.py`,
`adapters/git/inspection.py`; pointers: `tests/test_observation_quality.py`,
`tests/test_runs.py`. A run readiness receipt is not a whole-domain enumeration
witness for the semantic calculus.

## Corrections, selection and recovery

```sh
uv run kctx --json retract "$EXACT_TARGET" --kind dispute --reason "$REASON" --operation-id "$OPERATION"
uv run kctx --json correction recover
uv run kctx --json knowledge recover
uv run kctx --json knowledge rollback --release "$RETAINED_RELEASE" --context selection-context.json --key-id reviewer-key
```

Authored correction targets are parsed by `services/corrections.py`; use exact
supported target spellings, not a prose substring. Retraction/dispute/supersession
are durable operations with review projections. Retry the same operation ID only
with the same inputs; supersession additionally names `--by-replacement`.
Structured claim corrections belong in a new approved candidate and target an
exact claim revision. `knowledge rollback` only **proposes** forward retained
selection: sign its returned plan and `knowledge admit` it normally. Later
corrections remain; use explicit historical retrieval to inspect the old state.

`selection-context.json` has exactly `contexts` and `target_use`. Copy the current
named contexts from `knowledge contexts`: inputs name the current predecessor
snapshot and explicit desired times. The operation preserves every context's
policy, sources, target and use, allowing only a new snapshot and nondecreasing
times. It selects the retained release's active refs, not every claim stored in
that release's ledger. Sign the returned schema-3 selection plan normally.

### Reading and extending signed schema-2 history

Completed old releases remain authenticated under their exact original operation
bytes, policy anchor and signature domain. Discovery exposes their one approved
context as `legacy`; use that ID for historical queries. A first schema-3
candidate uses the current `expected_snapshot`, preserves the full retained KB
prefix and capture IDs, and explicitly keeps `legacy` or lists it in
`retired_contexts`. Add other contexts and assignments without broadening the old
claim scopes. Never relabel an old plan or approval as schema 3.

Published old journals can be authenticated read-only as already applied.
Unfinished schema-2 operations are not resumed by the new writer: re-author an
explicit candidate against the actual current predecessor and obtain fresh
approval. A schema-2 operation cannot follow a schema-3 completed release.


```sh
uv run kctx --json knowledge backup "$NEW_BACKUP_DIRECTORY"
uv run kctx --json knowledge restore "$BACKUP_DIRECTORY"
uv run kctx --json knowledge migrate --source "$LEGACY_DIRECTORY"
uv run kctx --json knowledge migrate --source "$LEGACY_DIRECTORY" --apply
uv run kctx --json knowledge migrate --migration "$MIGRATION" --restore-to "$NEW_RESTORED_DIRECTORY"
uv run kctx --json knowledge migrate --source "$LEGACY_DIRECTORY" --rollback "$MIGRATION"
```

Restore targets an empty authored Git repository, no completed release and a
nonexistent Dolt destination, with the matching configured trust anchor. Backup
retains Git bundle, native Dolt backup and operation records; it is not a JSON
export substitute. Migration accounts for exact, uniquely resolved, ambiguous,
malformed and unavailable legacy inputs, stages candidates and retains original
bytes. It never autoapproves prose. Migration rollback removes staged migration
state, not admitted history; restored legacy bytes go to a new directory.

Qualification pointers: `tests/test_corrections.py`, `tests/test_knowledge.py`,
`tests/test_storage_publication.py`. No commands in this guide are assertions
that these checks ran; current evidence and endpoint-specific limitations are
recorded in [gates.md](gates.md).
