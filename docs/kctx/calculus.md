# The kctx calculus — nouns and verbs

This is the reference card for the proved decision layer of kctx: the small
formal language specified and proved in Lean (`formal/Kctx`, toolchain-pinned,
no mathlib), implemented as a pure Python core (`src/kctx/semantics`), and
cross-checked case-by-case against a Lean reference evaluator
(`formal/.lake/build/bin/kctxref`) by `scripts/conformance_check.py`.

Everything here is semantic version **1.0.0**. The wire format is positional
JSON arrays; field order is the contract. Rejection codes and their order are
a contract. Time is an explicit integer (epoch seconds) — the core never
reads a clock, never does IO, and evaluates deterministically (T22).

## The shape of every decision

Every verb is a **pure function** of explicit inputs:

```
verdict = verb(view, context, subject, …)
```

- **view** — a read-only projection of the knowledge base (`KbView`): the
  observations, claims, bindings, corrections, derivations, and validations
  the checker is allowed to consult. Nothing else. (T07: the checker provably
  queries *only* the identities named in a derivation's footprint.)
- **context** (`EvalCtx`) — an explicit evaluation instant plus the policy
  flags (`require_fresh_evidence`, `require_validated`,
  `require_uncontested`). No ambient "now".
- **subject** — the derivation, claim reference, or proposal under decision.

Because inputs are explicit, the same inputs always give the same verdict —
which is what makes reuse safe: an agent may rely on an assessment while its
recorded context holds, and must re-evaluate the moment anything in the
verdict's declared footprint changes (T06, T08, T11).

## Nouns (the records)

| Noun | Fields (wire order) | Notes |
| --- | --- | --- |
| `Observation` | id, outcome, observedAt, ttl, system, locator | An acquisition *attempt*: `ok / timedOut / partialResult / truncated / denied / unavailable` are all meaningful outcomes. |
| `Claim` | ref(id, rev), prop, scope | Content-addressed by revision; a stable id alone never identifies a historical proposition. |
| `Binding` | obs, ref, role | `supports / contradicts / contextualizes` — a mention is not support. |
| `Derivation` | id, rule, premiseGroups, conclusion, conclusionProp, scope, footprint, evidence, witness | A rule application with its declared dependencies. |
| `Dep` | kind, target, digest | One footprint entry: `sourceContent / kbRecord / policy / checker / correction / discovery`. |
| `CoverageWitness` | scope, members, complete | Proof a required set was enumerated; universal claims are impossible without one (T13). |
| `Correction` | kind, target, recordedAt | `retract / dispute / supersede` against an identified revision. |
| `Scope` | project, extra | Empty `extra` = whole project; specialization narrows, never widens. |
| `ClaimProp` | atom / conj(atoms) / allChecked(pred, members) | v1 conjunctions are over flat atoms. |

## The four derivation rules

The enabled registry is closed — nothing else derives (T14, with a
kernel-decided countermodel for a tempting `contextualizes` inference).

| Rule | Shape it accepts | Declarative meaning |
| --- | --- | --- |
| `obsSupports` | no premises; declared evidence observation; an ok, fresh, `supports`-bound observation; conclusion is an atom in scope | The bound observation vouches for the conclusion *at this evaluation instant* (evidence-veridicality is a declared interpretation clause, not an axiom). |
| `andIntro` | one premise group; every premise an in-scope atom | The conclusion is exactly the conjunction of the premise atoms, in order. |
| `specialize` | exactly one premise | Same proposition, narrower-or-equal scope (checked, never assumed). |
| `allChecked` | a complete, non-empty coverage witness | The predicate held for *every* member of a finite, explicitly witnessed set. No witness, no universal (T13). |

Every rule must also declare its consulted record identities in its
footprint (T12) — a derivation may not silently depend on something it does
not declare.

## Verbs

### Assessment verbs (queries — decide, never mutate)

| Verb | Asks | Answers | Anchors |
| --- | --- | --- | --- |
| `assess_fresh(ttl, observedAt, now)` | Is the recency condition met at `now`? | `fresh / stale / unknown` | T11 — advancing the clock can never revive expired evidence; a missing TTL policy is `unknown`, never fresh; a future observation is `unknown`, never fresh |
| `check_derivation(view, ctx, d)` | Is this derivation admissible right now? | `accepted` or `rejected <code>` | T04 (structure), T05 (per-rule semantics), T12 (footprint declared), T13 (witness required) |
| `supported(view, ctx, ref)` | Does some accepted derivation conclude this claim? | Bool | T09, T10 — alternatives survive independently; removing all support yields unsupported, *not* a proof of the opposite |
| `has_fresh_evidence(view, ctx, ref)` | Is there fresh direct evidence? | Bool | feeds `usable_for` under its flag |
| `contested(view, ref)` | Does any correction target this claim? | Bool | corrections gate but never confer (T16) |
| `validation_current(view, ref)` | Is there a recorded validation for this claim? | Bool | — |
| `usable_for(view, ctx, ref)` | May an agent *act* on this claim under the policy? | Bool | T17 — exactly the conjunction of: supported, and each enabled mandatory condition |
| `reusable(view, ctx, d, observed)` | May a prior verdict be reused? | Bool | T06 — accepted check **and** every declared footprint dependency matched exactly; T08 — one missing dependency kills reuse for that derivation (alternatives unaffected) |

### Planning verbs (commands — pure; persistence executes them conditionally)

| Verb | Decides | Outcomes | Anchors |
| --- | --- | --- | --- |
| `plan_transition(proposal, target, actor, landedRefs, resolvable)` | Is this lifecycle move legal and ready? | `planned` / `refused illegalTransition · notReady · missingActor · gatesNotPassed · landedRefsUnresolved` | T18 — one readiness predicate for *both* filing paths; decided statuses need an actor; `applied` needs land gates + resolved landed refs; `verified` needs deploy/use gates |
| `can_conclude(investigation)` | May this investigation conclude? | Bool | T19 — non-empty checked-against and scope sections, no open *or malformed* hypothesis |
| `commit_op(kb, journal, op)` | Apply this operation against the expected predecessor? | `committed · alreadyCommitted · predecessorConflict · inputConflict · rejectedInvalid` | T20 — rejection leaves state unchanged; T21 — same-input replay is idempotent, different input conflicts; T03 — a commit preserves well-formedness or is refused |

### State actions (what plans are made of)

`addClaim · addObservation · addDerivation · addCorrection · addValidation`
build the change list inside an `Op`. Their safety properties are the
theorems above: well-formedness is preserved (T03), corrections only gate
(T16), and additions whose identities lie outside a derivation's consulted
footprint cannot change that derivation's verdict (T07, both as
query-agreement and as record-extension). Historical evaluation is stable:
`T15_supported_ext` — pin the derivation list (the historical context), and
unrelated later additions neither create nor destroy what it concluded.

## The rejection vocabulary

`check_derivation` refuses, in this exact order (a wire contract mirrored on
both hosts):

```
ruleNotEnabled → missingPremise → missingConclusion → conclusionPropMismatch
→ contestedConclusion → contestedPremise → ruleShapeMismatch → evidenceNotOk
→ evidenceNotFresh → missingCoverage → coverageIncomplete → footprintIncomplete
```

Failure is always named, never a boolean. An unknown is an unknown —
`assess_fresh` says `unknown` rather than guessing fresh; a truncated search
can never establish absence (T13); losing all support is not negation (T10).

## Calling it

**Python (production):** `from kctx.semantics import check_derivation_v,
usable_for, assess_fresh …` — pure functions, stdlib-only, no clock, no IO.

**Any language (reference protocol):** JSONL over stdin/stdout against the
Lean-built reference evaluator — one request per line, one response per line:

```json
{"id":"1","op":"assess_fresh","ttl":["expireAfter",50],"observedAt":100,"now":120}
{"id":"2","op":"check_derivation","kb":[…],"ctx":[120,true,false,true],"derivation":[…]}
{"id":"3","op":"usable","kb":[…],"ctx":[200,true,false,true],"ref":["c1","r1"]}
```

```json
{"id":"1","ok":true,"result":"fresh"}
{"id":"2","ok":true,"result":["accepted"]}
{"id":"3","ok":true,"result":false}
```

(The third case: same claim, evidence gone stale — `usable_for` says no,
even though `supported` alone would say yes. Freshness is an assessment,
not a stored property.)

## Where the proofs live

`formal/theorems.json` maps every T-number above to its theorem names,
assumptions, and executable entry point; `formal/proof-report.json` records
the axiom audit (standard Lean logical axioms only — `propext`,
`Classical.choice`, `Quot.sound`); `conformance-report.json` records the
Lean↔Python case agreement. Assurance label, honestly stated: **model proved,
Python conformance checked.**
