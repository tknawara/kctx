# Calculus card: version 2

**Semantic version `2.0.0`; wire schema `2`.** This is the current finite-witness
calculus, not the historical v1 described in the original
[handover](handover.md). The reason for replacement and required guarantees are
in [calculus-revision.md](calculus-revision.md). Qualification evidence belongs
in [gates.md](gates.md); this card makes no current gate-pass claim.

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
of an observation or a claim. Every retrieval is assessed under its release's
approved policy, so admitting a later release whose signed context carries a
different TTL re-assesses every claim of that release — including unchanged,
never re-observed ones — without any source delta. The operator authorizes
both the TTL and the release signature; a policy change is itself the event
being certified (D37), and readers cannot ask "fresh under an earlier policy?"
at the later release because query contexts are pinned to it.

A semantic `Plan` binds expected snapshot, full candidate KB, authority, claim
and witness. `VerifiedApproval` is an adapter capability, not proof that an
arbitrary Python constructor authenticated a signer. Production admission
verifies the operator's Ed25519 signature, canonical plan identity, trusted
policy, intended use and predecessor before publishing. Replays distinguish
already-applied, changed-input, predecessor-conflict and rejection. The pure
semantic journal records applied operations; the storage adapter additionally
has durable **prepared/candidate/manifest/published** recovery phases. A prepared
storage journal is not an admitted semantic journal entry.

Retained-release selection is a new authorized forward operation with a new
snapshot. It changes selected claims without deleting accumulated records or
later corrections. Historical query of the old release is a different operation.
See [storage and retrieval flows](flows.md).

## Exact wire examples

These JSONL records are copied from `tests/conformance/cases.jsonl`:

```jsonl
{"schema_version":2,"semantic_version":"2.0.0","id":"version-v2","op":"semantic_version","expected":"2.0.0"}
{"schema_version":2,"semantic_version":"2.0.0","id":"ttl-inclusive-boundary","op":"fresh","now":110,"observed_at":100,"ttl":10,"expected":"fresh"}
```

The development reference protocol is versioned, object-shaped JSONL, not a
positional production IPC API. Production Python imports the semantic functions.
The public engine is separately JSON-RPC 2.0 over JSONL (`kctx serve`, initialize
with `protocol_version: 1`); its protocol version is not the calculus version.

The following exact component shapes come from
`KnowledgeAdmissionTests.candidate` in `tests/test_knowledge.py`:

```json
{
  "claim": {"id": "reviewed", "revision": "r1"},
  "witness": {"tag": "attest", "attestation": "attestation-1"},
  "authority_key": "reviewer-key"
}
```

```json
{
  "formula": {"tag": "atom", "atom": {"subject": "service", "predicate": "reviewed", "args": []}},
  "scope": {"project": "test-kb", "selector": ""},
  "polarity": "positive"
}
```

These are components, not a complete admission request. The fixture constructs
`kb`, `capture_ids`, `context`, `claim`, `witness`, `authority_key` together using
the **returned** retained capture IDs and content identities. Never paste a
made-up capture hash into a real candidate. [Workflows](workflows.md) describes
the service request lifecycle.

## Assurance boundaries and ownership

| Boundary | Owner | What it does not establish |
| --- | --- | --- |
| Model proofs | `formal/Kctx/Model.lean`, `Semantics.lean`, `Checker.lean`, `Theorems.lean`, `Theorems2.lean`, `NonVacuity.lean`, `Selection.lean`, `Workflow.lean` | Truth of arbitrary observations, filesystem safety, network trust or Python refinement. |
| Python conformance | `src/kctx/semantics/`, `tests/semantics/`, `tests/conformance/cases.jsonl` | Universal equivalence from finite examples alone. |
| Nominal types/codecs | `domain/ids.py`, `semantics/wire.py`, Lean `Ids.lean` and codec modules | Authenticity of external data just because it decoded. |
| Adapter trust | `services/knowledge.py`, Git/Dolt/files adapters | A theorem about every possible external implementation. |
| Authored workflow decisions | `semantics/workflow.py`, proposal/investigation/run services | Natural-language truth inferred from structural readiness. |

The model uses local evidence-soundness premises and recursive derivability,
not a global hypothesis that successful acquisition proves everything. Nagini
qualification is restricted to named Boolean/time leaves and their runtime
bridges, not a whole-core refinement proof. Reject the older shortcut of
conflating fresh support, validation, admission and contestation. Named regression
pointers include `tests/test_knowledge.py`, `tests/test_gates_rev.py`,
`tests/test_observation_quality.py`, and `tests/test_storage_publication.py`.
