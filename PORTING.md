# Package cutover and ownership

The flat-module port queue is complete: production code lives in `src/kctx`,
imports use `kctx.*`, and callers use the package entry point. This inventory is
an ownership map, **not** a statement that every qualification gate passed.
Current evidence is maintained in [gates](docs/kctx/gates.md); historical test
counts and earlier v1 conformance results are not current assurance claims.

| Completed boundary | Current owner and contract |
| --- | --- |
| Domain identities | `src/kctx/domain/ids.py`: validated nominal identities for authored assets, claims/revisions, named contexts, observations, captures, actors, policies, source revisions, plans, releases and native commits. Git, Dolt and content identities are not one interchangeable SHA type. |
| Domain records and vocabulary | `domain/records.py`, `proposals.py`, `incidents.py`, `capture.py`, `corrections.py`, `targets.py`, `vocabulary.py`, `time.py`, `json.py`: typed records, closed variants, parsed targets and boundary JSON. |
| Codecs | `codecs/records.py`, `frontmatter.py`, `documents.py`, `gates.py`, `proposals.py`, `capture.py`, `validation.py`: explicit decode/encode boundaries and span-preserving authored document updates. |
| Filesystem adapters | `adapters/files/`: contained reads, conditional mutations, root discovery and retained knowledge artifacts. |
| Git adapters | `adapters/git/`: exact citation objects, local pinned-commit diffs, captured worktree identities and retained release manifests/publication refs. |
| Dolt adapters | `adapters/dolt/`: native candidate commits, normalized structured knowledge, backup/restore and pinned read sessions. |
| Semantic decisions | `semantics/model.py`, `checker.py`, `wellformed.py`, `workflow.py`, `time.py`, `wire.py`: unchanged v2 finite-witness language and retained v2 operation interpretation. `workflow_models.py`, `portfolio.py`, `design_workflow.py`, `workflow_wire.py`: proved workflow-3 context authorization and design/implementation separation. |
| Application services | `services/`: inventory/navigation, proposals/gates, investigations/signatures/KTLO/dossiers, observations/coverage/runs, corrections, citation refresh, validation and authenticated knowledge admission/retrieval. |
| Citation implementation | `citations/`: built-in construction, syntax, classification, scanning, rendering and redaction. No external citation executable or separate legacy protocol. |
| Authored graph | `graph/`: pinned extraction, exact citation occurrence bindings, native Dolt query projection and its own candidate/active-pointer recovery. It is not a substitute semantic inference engine. |
| Configuration and presentation | `config.py`, `observability.py`, `presentation.py`, `redaction.py`: single machine config, structured diagnostics, audience output and privacy boundaries. |
| CLI | `cli/app.py` plus command modules and `citations/cli.py`, `graph/cli_graph.py`: native Click commands registered by `register(root)`, Rich human rendering, typed service calls and JSON replies. The old Arguments/dispatch/registration compatibility architecture is removed. |
| Agent/API protocol | `engine/`: one JSON-RPC 2.0 JSONL server, `from kctx.engine import serve`, surfaced as `kctx serve`; initialized protocol version `"2"`. Citation/graph/knowledge methods share the engine; operator private signing stays CLI-only. |
| Packaging | `src/kctx/__main__.py`, package entry points and `py.typed`: ordinary installed Python runtime; Lean is development/qualification infrastructure, not runtime execution. |

## Nominal values are a boundary rule

Decode external strings once, operate on domain values internally, and encode at
the output boundary. A claim revision, source revision, file mutation revision,
proposal material revision and Dolt commit name different things. Keeping their
external spellings does not justify aliasing their types. Python nominal classes
and Lean `Ids.lean` prevent accidental substitutions; strict codecs enforce
shape/value constraints but do not establish external authenticity.

Use `kctx.semantics` for current pure functions, not removed v1 derivation APIs.
Use `kctx.engine` for the production protocol, not the development reference
codec as an agent service. No flat-root import shims or parallel citation server
are required. The authored navigation command `context` and authenticated
`knowledge context` intentionally retain different contracts.

## Workflow 3 cutover

The inference language remains `2.0.0`/core wire 2. The incompatible changes are
explicitly versioned: knowledge operation/manifest/approval/journal schema 3,
authored `workflow_version: 3` within physical document schema 1, and stdio
initialization protocol `"2"`. Old RPC clients must adopt the advertised schemas;
there is no implicit context or protocol-1 compatibility route.

- `PortfolioPlan` signs the candidate, actor, complete named-context collection,
  exact added-claim context/witness assignments and explicit retired context IDs.
  Contexts are framed at the candidate snapshot; `expected_snapshot` names the
  predecessor. Queries supply a `ContextId` plus the full evaluation context.
  `knowledge contexts` discovers the authenticated values.
- The declared operation use and every context's intended use must be permitted
  by the signing key. Different contexts may select different sources/policies;
  their witnesses and assessments remain separate. Asset/diff pages contain
  context–claim pairs, not a merged global answer.
- New signatures use the `kctx-operation-v3` domain. Explicit `Legacy*` readers
  authenticate completed schema-2 history using only its original signature
  domain and exact bytes. Its one approved context is named `legacy` for reads.
  A new schema-3 plan must preserve that context or explicitly retire it.
  Schema-2 operations cannot follow a schema-3 predecessor.
- Historical completed journals can report authenticated `already_applied`;
  pending schema-2 operations cannot be signed, admitted or resumed by the new
  writer. Re-author an explicit schema-3 candidate against the current release;
  do not relabel an old plan or approval.
- New authored proposals declare an intended `target_source`, explicitly or
  inferred from an exactly resolved supplied revision. Design hashes include
  this constraint, scope, environment and gate definitions but exclude concrete
  implementation-binding bookkeeping. `bind` records the exact source/target
  and accepted design; `reopen` clears acceptance and execution authority.
  New identities use `design-v3:<sha256>`, disjoint from unprefixed v2 material
  hashes even when an old record carried similarly named custom fields.
  Historical v2 hashes retain their original interpretation; their custom
  source/binding fields remain material, never newly inferred execution authority.
- `adopt` migrates a v2 draft/proposed record with an actor and reason; `reopen`
  migrates accepted/landing records with renewed acceptance required. Migration
  uses the modern readiness profile even for flat-file homes. Applied/verified
  records require a superseding proposal. `backfill-landed --dry-run` remains
  advisory discovery, not authority to rewrite finalized landing evidence.

Lean owns `Portfolio.lean`, `DesignWorkflow.lean`, their examples and strict
workflow-3 codecs. Query projection and assignment derivability reuse the
unchanged checker; no new inference constructor or scope-widening rule exists.
The registry distinguishes logical proof from adapter signature/source-resolution
assumptions and finite Python conformance.


## Deliberate changes, not compatibility accidents

- Readiness cannot be bypassed by jumping from draft to proposed.
- Gates bind material, target/environment/scope, checker, time and actor; changing
  inputs requires new evidence rather than carrying an old pass forward.
- Cross-cutting readers (`impact`, `match`, `stale`) skip an undecodable record,
  disclose it as a warning and exit partial; named-record readers and `validate`
  stay strict. Relationship evidence holds evidence addresses (`ev:<home>/<stem>`
  or a code locator), not bare slugs.
- Signature fixes retain valid proposal IDs and also accept the closed evidence
  address grammar. External PRs/tickets use evidence records; `fixed_at` remains
  explicit authored metadata, not an inferred merge time or proof.
- `impact --diff BASE..HEAD` / `authored.impact_diff` join local citation hunks,
  authored inventory and release-pinned admitted claims without changing the
  calculus. The query reports absent releases, unmapped ranges and omissions.
- `proposal gate --rev` is repository evidence retained verbatim in `repo_rev`;
  the gate-definition binding digest is always computed from the authored table.
- Corrections persist recoverable operation intent before review projections;
  exact replay and conflicts are explicit.
- Observation provenance retains worktree identity and dependency roots, not just
  a repository HEAD or several copies counted as independent evidence.
- Citation refresh preserves historical binding; current-state fields are
  advisory, not silently rewritten observations.
- Authenticated knowledge uses native Dolt candidates and a completed release
  boundary; the authored graph remains separately rebuildable.
- Version 2 replaces the unsound v1 assurance model rather than wrapping it.
  Support, freshness, validation, applicability and contestation are independent.

See [calculus](docs/kctx/calculus.md), [configuration](docs/kctx/config.md),
[workflows](docs/kctx/workflows.md) and [flow diagrams](docs/kctx/flows.md).

## Qualification scope

Lean definitions/proofs, Python conformance, adapter qualification and leaf-level
Nagini contracts answer different questions. Nagini's time/Boolean leaves are
not a whole-core refinement proof. Named pointers include
`tests/test_domain_ids.py`, `tests/test_domain_targets.py`,
`tests/test_record_codecs.py`, `tests/test_cli_commands.py`,
`tests/test_engine_protocol.py`, `tests/test_knowledge_boundaries.py`,
`tests/test_storage_publication.py`, `tests/semantics/` and `tests/conformance/`.
Consult source-identified reports in the gate record for exercised results; no
frozen historical test count is used as a completion criterion here.
