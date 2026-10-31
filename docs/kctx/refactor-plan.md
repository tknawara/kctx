# Typed implementation refactor

## Problem and acceptance contract

The first proposal treated the port as file moves. That does not satisfy
handover §§6–7 or G02: the moved records still contain string IDs, string
state fields, mutable collections, permissive constructor filtering, and
`Any`-shaped service contracts. The current move is unfinished; this plan
supersedes the mechanical-only proposal before further implementation.

The deliverable is a coherent typed Python implementation, not renamed
monster modules. Preserve authored formats, CLI behavior, Lean wire ordering,
and the existing semantic decisions. Reject malformed input before mutation.
No root-module aliases, permissive ID/string equality, unused nominal types,
or type-checker blanket suppressions count as completion.

## Design decisions

| Boundary | Implementation | Rejected alternative |
| --- | --- | --- |
| Entity identity | Frozen, slotted nominal value objects in `domain/ids.py`; constructors validate namespace syntax; `.val`/`str()` only at I/O boundaries | Bare strings, `NewType` alone, equality with strings, an undifferentiated tagged ID |
| Closed vocabulary | Enum classes; decode external strings once and serialize `.value` explicitly | String sets used as the internal model |
| Records | Frozen/slotted dataclasses with nominal IDs, enums and tuples; separate wire records/decoders | Mutable dictionaries as the domain, dataclasses containing mutable lists |
| Mixed references | Closed reference unions parsed at entry; exhaustive variant handling | Repeated prefix slicing in services |
| External data | `object` plus validation/narrowing, explicit wire shapes; schema-version and unknown-field policies | `Any`, unchecked unpacking, silently dropping unknown fields |
| Markdown | A shared span-preserving document codec; targeted patches retain unknown sections, fences and original line endings | Re-rendering a user's whole document to update a field |
| Services | Cohesive use-case modules with concrete input/result contracts; ordinary functions unless state has an owner | Static utility classes, repository frameworks, service locators |
| Assurance | Strict package type checking plus negative ID-mixing examples; runtime malformed-input checks; actual CLI and real adapter smoke | Tests alone, unused types, broad ignore lists |

`config.toml` remains the single configuration surface. `KCTX_CONFIG` only
locates that file; the superseded root/env precedence must not return.

## Implementation slices and interfaces

1. **Foundations and persisted JSON.** Define all identity namespaces used by
   the implementation: `AssetId`, `RelationshipId`, `EvidenceId`,
   `ObservationId`, `ProposalId`, `InvestigationId`, `SignatureId`, `ClaimId`,
   `ClaimRevision`, `CitationId`, `RuleVersion`, `OperationId`, `SnapshotId`,
   `DerivationId`, `RunId`, `GateId`, `TicketId`. Constructors take one `str`,
   expose immutable `.val`, and never accept another ID object. The bounded
   semantic `RuleId` remains the existing closed rule enum. Centralize legacy
   record enums in `domain/vocabulary.py`. Separate record encoding/decoding
   into `codecs/records.py`; migrate inventory, observations and coverage.
2. **Proved semantic host.** Use the same identities in claims, revisions,
   observations, derivations, snapshots and lookup signatures; make tagged
   values exhaustive. Preserve Lean's positional wire format and rejection
   order. Migrate every semantic caller, grid and conformance fixture.
3. **Authored workflows.** Proposal/gate and incident/signature/KTLO/dossier/
   correction records gain explicit types. Move shared Markdown parsing and
   lossless editing to `codecs/documents.py`; keep readiness and durable
   correction ordering unchanged. IDs and states survive through the service
   layer rather than being immediately converted back to strings.
4. **Navigation and refresh.** Split navigation into context, discovery,
   backlinks and freshness responsibilities; split admit into cursor state,
   citation refresh and orchestration. Reuse reference variants and typed
   provider contracts. No old navigation module re-export shim.
5. **Integration.** Finish the CLI package with separate registration,
   dispatch and rendering. Remove stale import bootstraps and file/package
   collisions; migrate storage/config/graph consumers and all test imports.
   Split validation into domain checks plus orchestration. Consume configured
   `dolt_bin` at the actual subprocess boundary.
6. **Executable gates.** Pin quality tools in the container/lock; strict
   checking covers the maintained package, and negative fixtures prove that
   exchanging ClaimId/ProposalId/AssetId (or supplying naked strings to typed
   APIs) fails. Run the existing behavioral suite, real CLI workflows, Lean
   proof audit, cross-host conformance, Dolt smoke and Nagini grids. Update
   gates and port history with observed results; commit and push coherent
   checked checkpoints.

Wire/CLI outputs remain ordinary JSON values; internal identities are not
leaked as `{val: ...}` objects. Search terms and aliases remain prose strings
until resolution produces an entity identity. No fabricated corpus rules:
namespace validation follows the persisted spellings exercised by fixtures.

## Verification requirements

- Wrong ID namespaces are rejected statically; value objects also distinguish
  them at runtime. Invalid enums, unknown versions and malformed nested records
  fail at decoding, before publication.
- Existing user-facing CLI results and authored bytes outside targeted edits
  remain stable, including CRLF, unknown sections and headings inside fences.
- No `Any`-based domain/service APIs, stale flat imports, or dormant type layers.
- All changes are exercised inside Compose. Report citation-skill-dependent
  skips and environment qualifications honestly; do not broaden proof claims
  beyond Lean correspondence and the verified Nagini leaves.

## Built-in citations (requested extension)

The supplied `/mnt/c/Users/tarek/Downloads/cite.py` is the compatibility
source, not a runtime dependency. Integrate its make/check/stale/render
behavior in `kctx.citations`, separated into syntax/models, Git and record
resolution, construction, classification/scanning, rendering and CLI modules.
Use the existing `KctxError`, shared document codec and typed identity model.
No giant copied module, dynamic import, external `cite` executable, or second
citation grammar remains. `kctx cite …` exposes the verbs; services call the
implementation directly instead of shelling out to themselves.

`cite_py` and `cite_bin` leave the config schema. Citation acquisition uses
`cache_dir`, `git_url_template`, `fetch_interval_seconds`, and `github_host`
in the same config file. Root resolution remains the shared KB resolver.
Legacy citation environment variables are not copied into production.
Previously external-skill-dependent tests migrate to the bundled provider
and real temporary Git repositories. Tests that merely assert discovery or
subprocess forwarding are removed with the obsolete integration.

The public token grammar and retained citations remain compatible. Current
classification/refresh does not establish historical resolution or semantic
truth; diagrams and gate reports must expose this distinction. Integration
of the parser is not a repair of the independently identified calculus gaps.

