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
key represented descriptively. Compute the canonical policy digest with
`kctx.adapters.files.knowledge.canonical` and `digest` in the trusted provisioning
process, then set `knowledge_policy_digest` in the single config file. A modified
policy under the same name cannot replace that bootstrap anchor. `knowledge_dir`
selects the native Dolt destination; the authored root must be a Git repository.

Capture already acquired exact bytes, identifying the actual immutable upstream
revision and observation time. This command does not fetch a PR URL or parse prose
into facts:

```sh
uv run kctx --json knowledge capture --kind source --source "$SOURCE" --revision "$REVISION" --file "$SOURCE_FILE" --observed-at "$OBSERVED_AT"
uv run kctx --json knowledge capture --kind pr --source "$PR_URL" --revision "$PR_REVISION" --file "$PR_CAPTURE_FILE" --observed-at "$OBSERVED_AT"
uv run kctx --json knowledge capture --kind document --source "$DOCUMENT_SOURCE" --revision "$DOCUMENT_REVISION" --file "$DOCUMENT_FILE" --observed-at "$OBSERVED_AT"
```

Choose the relevant kind; they share the same admission path. Retain each returned
capture record. Author `candidate.json` with exactly `kb`, `capture_ids`,
`context`, `claim`, `witness`, and `authority_key`. The KB contains observations,
claims, attestations, enumerations, derivations, corrections and receipts. Bind
observations and context source selections to returned source/revision/content
identities; name the retained capture IDs. Use a new candidate snapshot and the
completed predecessor in the context (`bootstrap:<kb_id>` for first admission).
The initial complete working fixture is
`KnowledgeAdmissionTests.candidate` in `tests/test_knowledge.py`; wire components
are shown in [calculus.md](calculus.md). It deliberately requires an explicit
attestation and witness, not just a successful capture.

```sh
uv run kctx --json knowledge propose --candidate candidate.json --target-use review --now "$NOW"
uv run kctx --json knowledge sign "$PLAN" --private-key "$PRIVATE_KEY" --key-id reviewer-key > approval.json
uv run kctx --json knowledge admit "$PLAN" --approval approval.json
```

`PLAN` is the ID returned by propose. Review its exact candidate, policy, inputs,
target use and predecessor before signing. The approval JSON authorizes that
plan, not arbitrary future revisions. Preserve the returned `release` and
snapshot. Identical replay is idempotent; changed inputs or a competing completed
predecessor conflict. Operators retain private signing authority; `kctx serve`
does not expose a signing method.

## Retrieve, explain and continue at one release

A request file has exactly `context` and `claims`; each claim reference is
`{"id":"reviewed","revision":"r1"}`. Use the admitted context with its snapshot
updated to the published candidate snapshot. Its source selections, semantic
version, policy, checker, scope and intended use must still match the selected
release; `now` is an explicit evaluation time.

```sh
uv run kctx --json knowledge context --request request.json --release "$RELEASE" --limit 20
uv run kctx --json knowledge explain --request one-claim.json --release "$RELEASE"
uv run kctx --json knowledge context --request request.json --release "$RELEASE" --limit 20 --continuation continuation.json
```

Save **only the returned `continuation` object** as `continuation.json`. Keep the
same request; the continuation binds the query digest and release, not “whatever
is latest.” An empty claims list selects in-scope active claims. Read omissions,
missing refs, contrary evidence, assessment and provenance before using results.
`knowledge explain` requires one exact claim revision. For authored navigation,
use `context ID`, `home ID`, `uses TARGET`, or `timeline ID` instead; those are not
an alternative source of proved claim support.

The single programmatic server is `uv run kctx serve`, JSON-RPC 2.0 over JSONL.
Initialize with `protocol_version: 1`, then use the advertised citation, graph
and knowledge methods. Python embedding imports `serve` from `kctx.engine`.
Engine protocol version 1 and calculus schema 2 identify different contracts.

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

## Authored proposals and gates

```sh
uv run kctx --json proposal add --kind decision --origin user-request --title "$TITLE" --target "$TARGET" --context "$CONTEXT" --evidence "$EVIDENCE" --change "$CHANGE" --why "$WHY" --gates gates.md --target-revision "$TARGET_REVISION" --environment "$ENVIRONMENT" --scope "$SCOPE"
uv run kctx --json proposal show "$PROPOSAL"
uv run kctx --json proposal gate "$PROPOSAL" "$GATE" --outcome pass --evidence "$GATE_EVIDENCE" --by "$ACTOR" --rev "$REPO_AT_SHA" --target-revision "$TARGET_REVISION" --checker "$CHECKER_VERSION" --expires-at "$EXPIRY_EPOCH" --environment "$ENVIRONMENT" --scope "$SCOPE" --expected-revision "$FILE_REVISION"
uv run kctx --json proposal show "$PROPOSAL"
uv run kctx --json proposal set "$PROPOSAL" --status proposed --by "$ACTOR" --expected-revision "$NEW_FILE_REVISION"
```

Author a real gate table in `gates.md` and use its returned gate ID; gates have
land/deploy/use timing. `show` supplies the source revision used for conditional
writes; reread after a gate append before the next mutation. Gate evidence binds
proposal material revision, target revision, environment, scope, checker,
checked time, expiry and actor. `--rev` is repository evidence such as
`org/repo@<sha>`; it is not interchangeable with proposal material revision or
`--expected-revision`. A text label `pass` cannot authorize changed material.
Use `fail` or `unk` honestly; required missing/expired/mismatched gates block the
relevant transition. Proposed/accepted/landing/applied/verified are distinct
states; record actual landing evidence with `proposal set --landed ...`, not a
fabricated status shortcut. This authored workflow does not replace the separate
Ed25519 knowledge approval protocol.

Owners: `cli/proposals.py`, `services/proposals.py`, `codecs/gates.py`,
`semantics/workflow.py`. Qualification pointers: `tests/test_gates_rev.py`,
`tests/test_proposal_boundaries.py`, `tests/test_proposals.py`.

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
