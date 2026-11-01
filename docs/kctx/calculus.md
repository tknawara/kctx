# Calculus card: inference v2, workflow schema 3

**Core semantic version `2.0.0`; core wire schema `2`; workflow schema `3`.**
The finite-witness language is unchanged. Workflow 3 extends authorization and
authored lifecycle judgments, not inference. The historical v1 in the original
[handover](handover.md) remains superseded; [calculus-revision.md](calculus-revision.md)
states the controlling guarantees. Qualification evidence belongs in
[gates.md](gates.md); definitions alone are not gate-pass claims.

## Language and scope

A claim has a nominal `ClaimId`, immutable `ClaimRevision`, and a statement:
formula, scope, polarity. A scope is `(project, selector)`. Narrowing requires the
same project and either an empty source selector or equal selectors. It is not
string-prefix, path-prefix, or arbitrary set containment.

| Formula | Meaning and witness |
| --- | --- |
| `Atomic(Atom(subject, predicate, args))` | Exact structured proposition. `AttestWitness` names an attestation binding this claim revision/statement to an observation and actor. |
| `Truth` | Logical truth in a named scope, constructed by `TruthWitness`; not evidence for arbitrary atoms. |
| `Conjunction(left, right)` | `AndWitness` recursively checks both positive premises in the same scope. |
| `Inventory(enumeration)` | Attested finite discovery inventory, not a free completeness boolean. |
| `All(enumeration, predicate)` | `AllWitness` checks inventory plus the recursively constructed conjunction of every member's predicate. |
| `Absent(enumeration)` | `AbsentWitness` checks an inventory premise and an empty, successfully enumerated declared domain. |

`SpecializeWitness` preserves the premise formula and polarity while explicitly
narrowing its scope. Witnesses are finite recursive trees, not graph navigation
edges. Alternative derivations remain separate; every accepted witness must
match the exact recorded conclusion, scope and polarity.

An observation records source, revision, retained content identity, time and
`ok | timeout | partial | truncated | denied | unavailable`. Successful capture
alone establishes no atomic truth. An attestation is an explicit interpretation
of that capture, not automatic prose extraction. Enumeration checking binds
source/revision, query, scope, method, successful observation and inventory
content; members must equal the declared universe without duplicates. Its
`inventory:` identity is a length-delimited UTF-8 member encoding. Soundness is
relative to that declared finite domain, not an assertion that every possible
real-world object was discovered.

## Assessment is not a status string

`assess(kb, context, ref)` returns:

- `support`: `none`, `positive`, `negative`, or `both`;
- `applicable`: exact context and target scope compatibility;
- `freshness`: `fresh`, `stale`, or `unknown`;
- `validated`, `contested`, `available`, and policy-dependent `usable`.

Positive and negative interpretations are independent. Lack of support is not
negation. A dispute preserves evidence and marks contestation; contrary support
also contests. Retraction suppresses the targeted revision's current evidence;
supersession does not transfer support or validation. Historical evaluation
selects a retained snapshot: changing a timestamp on the current database is
not historical replay. Correction times are interpreted within that selected KB.

Support checking does not erase old evidence merely because its TTL expired.
Freshness examines actual observation dependencies: a composed witness is stale
if any observation is stale, unknown if no observations or an unknown remains,
otherwise fresh. Across alternatives a fresh witness wins; all-stale alternatives
are stale; otherwise freshness is unknown. `now == observed_at + ttl` is fresh;
future observations and missing TTL are unknown. The selected statement's
polarity, applicability and policy requirements determine usability.

## Explicit context, receipts and operations

`Context` binds snapshot, semantic version, ruleset, checker, complete policy,
explicit time, target scope, intended use, and exact source selections
`(source, revision, content)`. The checker constructs dependencies from actual
observations, claims, attestations, enumerations, relevant corrections and
context. It does not trust an unrelated caller-supplied digest as a footprint.
A passing receipt names claim, context, witness, exact dependencies and inclusive
expiry. Reuse checks these bindings and the accepted witness again.

The TTL is a policy parameter of the signed evaluation context, not a property
of an observation or a claim. Retrieval uses the selected named context's
approved policy. A later signed change to that context's TTL can reassess
unchanged, never re-observed claims without a source delta. This is authorization
of a policy event (D37), not renewed observation evidence. A query cannot replace
that policy with an unsigned earlier or more permissive one. Different explicitly
authorized contexts may have different policies; their assessments stay labeled.

The retained v2 `Plan`/`VerifiedApproval` interpretation remains for authenticating
old signed releases. New operations use `PortfolioPlan` and exact
`VerifiedPortfolioApproval` capabilities. A Python constructor is not proof that
an adapter authenticated a signer. Production admission verifies Ed25519,
canonical full-plan identity, trusted policy, every intended use and predecessor
before publishing. Replays distinguish already-applied, changed-input,
predecessor-conflict and rejection. The pure semantic journal records applied
operations; storage additionally has durable
**prepared/candidate/manifest/published** recovery phases. A prepared storage
journal is not an admitted semantic journal entry.

## Workflow 3: named-context authorization

`PortfolioState` contains an immutable KB, active selected claim refs and a finite
collection of `NamedContext(id, context)` records. Nonempty claim states require
contexts; an empty bootstrap is distinct. Each context retains one target and
the unchanged `narrower` relation.

`PortfolioPlan` binds expected snapshot, complete candidate, actor, resulting
contexts, added-claim assignments and explicit retired context IDs. Each added
claim appears exactly once, in candidate order, with its `ContextId` and witness.
The witness must derive its exact statement and the claim must be usable in that
same complete context. No conjunction pools premises checked under different
contexts. Context-only changes are also explicit signed operations.

Retained context IDs keep their target and intended-use identity. Removing one
requires the exact retirement list; adding another target does not implicitly
erase prior access. Policies, sources and time remain signed inputs, not cached
verdicts. Carrying a context forward does not promise its old claims stay usable.

Queries identify one named context, keep its policy/sources/versions/use, may
narrow its target, and cannot predate its approved time. `assessPortfolio` returns
exactly the existing `assess` result for an authorized selected claim. Adding
unrelated authorization entries cannot change a fixed-context assessment when
the KB, selection and chosen context lookup are unchanged. Receipts bind the
complete core context and snapshot; context names are selectors, not alternative
proof premises. Continuations also bind the named query and release.

Forward retained selection uses a new snapshot, preserves the current ledger and
corrections, keeps current context configurations apart from snapshot and
nondecreasing declared times, and selects exactly the retained release's active
refs. It does not reactivate every claim stored in a prior selection's KB.
Historical retrieval of that release is a separate operation.

Owners: `formal/Kctx/Portfolio.lean`, `PortfolioExamples.lean`,
`WorkflowV3Codec.lean`; Python `semantics/portfolio.py`, `workflow_models.py`,
`workflow_wire.py`. `assignment_core_derivation` and
`assignment_interpretation_sound` connect assignments to the original `Derives`
and local `EvidenceSound` contract. Singleton legacy embedding explicitly rebases
the snapshot and states its compatibility premises; it is not permission to
reinterpret v2 signatures or infer assignments for old multi-claim writes.

## Workflow 3: design acceptance and implementation binding

`DesignProposal` pairs the authored structural model with an intended source and
an optional `ImplementationBinding(design_revision, source, target_revision,
actor, observed_at)`. Acceptance binds design material, including gate definitions,
scope, environment and intended source; a concrete implementing revision need
not exist yet. Source resolution and recomputing the design digest are adapter
obligations, not caller-supplied successful-resolution flags.

Binding requires an exact expected state, valid accepted/landing design, matching
accepted revision/source and a nonfuture recorded actor observation. It preserves
design acceptance and gate history, updates the target and clears landing refs.
An old-target pass cannot authorize a new target. Identical-target/context
evidence may still be reusable under the existing gate expiry rules; binding
itself never attests landing.

Applied/verified candidates additionally require the exact current binding,
resolved landing evidence and all gates for the relevant phases. The landing
rule remains precise: every selected reference resolves and at least one
matches the bound target; it does not claim all references share that target.
Explicit reopening of accepted/landing clears acceptance, execution roles,
binding, target and landing refs while retaining design material and gate history.
Applied/verified records cannot be reopened or rebound.

Owners: `formal/Kctx/DesignWorkflow.lean`, `DesignWorkflowExamples.lean`;
Python `semantics/design_workflow.py` and proposal adapters. These prove workflow
eligibility and binding, not that arbitrary implementation prose is true, and
not authority to publish signed knowledge. See [workflows](workflows.md).


## Exact wire examples

These JSONL records are copied from `tests/conformance/cases.jsonl`:

```jsonl
{"schema_version":2,"semantic_version":"2.0.0","id":"version-v2","op":"semantic_version","expected":"2.0.0"}
{"schema_version":2,"semantic_version":"2.0.0","id":"ttl-inclusive-boundary","op":"fresh","now":110,"observed_at":100,"ttl":10,"expected":"fresh"}
```

The development reference protocol is versioned, object-shaped JSONL, not a
positional production IPC API. Production Python imports the semantic functions.
The public engine is separately JSON-RPC 2.0 over JSONL (`kctx serve`, initialize
with `protocol_version: "2"`); its protocol version is not the calculus version.

The following exact component shapes come from
`KnowledgeAdmissionTests.candidate` in `tests/test_knowledge.py`:

```json
{
  "claim": {"id": "reviewed", "revision": "r1"},
  "context": "review",
  "witness": {"tag": "attest", "attestation": "attestation-1"}
}
```

```json
{
  "formula": {"tag": "atom", "atom": {"subject": "service", "predicate": "reviewed", "args": []}},
  "scope": {"project": "test-kb", "selector": ""},
  "polarity": "positive"
}
```

These are components, not a complete admission request. The first object is one
entry in `assignments`. The fixture constructs `schema_version: 3`,
`expected_snapshot`, `kb`, `capture_ids`, `contexts`, `assignments`,
`retired_contexts`, and `authority_key` using **returned** retained capture IDs and
content identities. Core context/witness/KB values keep their v2 grammar. Never
paste a made-up capture hash into a real candidate.
[Workflows](workflows.md) describes the service lifecycle.

## Assurance boundaries and ownership

| Boundary | Owner | What it does not establish |
| --- | --- | --- |
| Model proofs | `formal/Kctx/Model.lean`, `Semantics.lean`, `Checker.lean`, `Theorems.lean`, `Theorems2.lean`, `NonVacuity.lean`, `Selection.lean`, `Workflow.lean`, `Portfolio.lean`, `DesignWorkflow.lean` | Truth of arbitrary observations, filesystem safety, network trust or Python refinement. |
| Python conformance | `src/kctx/semantics/`, `tests/semantics/`, `tests/conformance/cases.jsonl` | Universal equivalence from finite examples alone. |
| Nominal types/codecs | `domain/ids.py`, `semantics/wire.py`, `workflow_wire.py`, Lean `Ids.lean` and codec modules | Authenticity of external data just because it decoded. |
| Adapter trust | `services/knowledge.py`, Git/Dolt/files adapters | A theorem about every possible external implementation. |
| Authored workflow decisions | `semantics/workflow.py`, `design_workflow.py`, proposal/investigation/run services | Natural-language truth inferred from structural readiness. |

The model uses local evidence-soundness premises and recursive derivability,
not a global hypothesis that successful acquisition proves everything. Nagini
qualification is restricted to named Boolean/time leaves and their runtime
bridges, not a whole-core refinement proof. Reject the older shortcut of
conflating fresh support, validation, admission and contestation. Named regression
pointers include `tests/test_knowledge.py`, `tests/test_gates_rev.py`,
`tests/test_observation_quality.py`, and `tests/test_storage_publication.py`.
