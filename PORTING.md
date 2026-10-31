# Package cutover and ownership

The flat-module port queue is complete: production code lives in `src/kctx`,
imports use `kctx.*`, and callers use the package entry point. This inventory is
an ownership map, **not** a statement that every qualification gate passed.
Current evidence is maintained in [gates](docs/kctx/gates.md); historical test
counts and earlier v1 conformance results are not current assurance claims.

| Completed boundary | Current owner and contract |
| --- | --- |
| Domain identities | `src/kctx/domain/ids.py`: validated nominal identities for authored assets, claims/revisions, observations, captures, actors, policies, source revisions, plans, releases and native commits. Git, Dolt and content identities are not one interchangeable SHA type. |
| Domain records and vocabulary | `domain/records.py`, `proposals.py`, `incidents.py`, `capture.py`, `corrections.py`, `targets.py`, `vocabulary.py`, `time.py`, `json.py`: typed records, closed variants, parsed targets and boundary JSON. |
| Codecs | `codecs/records.py`, `frontmatter.py`, `documents.py`, `gates.py`, `proposals.py`, `capture.py`, `validation.py`: explicit decode/encode boundaries and span-preserving authored document updates. |
| Filesystem adapters | `adapters/files/`: contained reads, conditional mutations, root discovery and retained knowledge artifacts. |
| Git adapters | `adapters/git/`: exact citation objects, captured worktree identities and retained release manifests/publication refs. |
| Dolt adapters | `adapters/dolt/`: native candidate commits, normalized structured knowledge, backup/restore and pinned read sessions. |
| Semantic decisions | `semantics/model.py`, `checker.py`, `wellformed.py`, `workflow.py`, `time.py`, `wire.py`: current version 2 finite witnesses, independent assessments, approval/selection and authored workflow predicates. |
| Application services | `services/`: inventory/navigation, proposals/gates, investigations/signatures/KTLO/dossiers, observations/coverage/runs, corrections, citation refresh, validation and authenticated knowledge admission/retrieval. |
| Citation implementation | `citations/`: built-in construction, syntax, classification, scanning, rendering and redaction. No external citation executable or separate legacy protocol. |
| Authored graph | `graph/`: pinned extraction, exact citation occurrence bindings, native Dolt query projection and its own candidate/active-pointer recovery. It is not a substitute semantic inference engine. |
| Configuration and presentation | `config.py`, `observability.py`, `presentation.py`, `redaction.py`: single machine config, structured diagnostics, audience output and privacy boundaries. |
| CLI | `cli/app.py` plus command modules and `citations/cli.py`, `graph/cli_graph.py`: native Click commands registered by `register(root)`, Rich human rendering, typed service calls and JSON replies. The old Arguments/dispatch/registration compatibility architecture is removed. |
| Agent/API protocol | `engine/`: one JSON-RPC 2.0 JSONL server, `from kctx.engine import serve`, surfaced as `kctx serve`; initialized protocol version 1. Citation/graph/knowledge methods share the engine; operator private signing stays CLI-only. |
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

## Deliberate changes, not compatibility accidents

- Readiness cannot be bypassed by jumping from draft to proposed.
- Gates bind material, target/environment/scope, checker, time and actor; changing
  inputs requires new evidence rather than carrying an old pass forward.
- Cross-cutting readers (`impact`, `match`, `stale`) skip an undecodable record,
  disclose it as a warning and exit partial; named-record readers and `validate`
  stay strict. Relationship evidence holds evidence addresses (`ev:<home>/<stem>`
  or a code locator), not bare slugs.
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
