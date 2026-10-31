# Calculus revision and production qualification

## Decision

Replace the inadequate v1 assurance model rather than certify its narrower
lemmas as the handover obligations. The executable counterexamples are retained
in `reports/semantic-audit-cases.jsonl`. Semantic version 2 is an intentional
contract change; the authored Markdown/JSON formats and ordinary CLI spellings
remain compatible. The reference protocol becomes explicitly versioned.

## Required semantic contract

1. **Nontrivial interpretations.** Atomic positive and negative evidence are
   independently interpreted; conjunction and finite coverage have compositional
   meanings. Acquisition success is not truth. Evidence soundness is a local
   premise about the particular admitted observation, claim revision, polarity,
   scope and retained content identity. No hypothesis may imply every claim
   from any successful observation. Exhibit a model with a false unsupported
   atom and prove it cannot acquire support without an admissible witness.
2. **Recursive witnesses.** Support comes from a finite acyclic proof witness
   rooted in exact evidence bindings. Every premise has its own checked
   supporting witness in the selected snapshot. Alternative derivations remain
   independent. Rule acceptance supplies its premise obligations; no externally
   supplied `PremisesHold` substitutes for this check. Prove checker soundness
   against an independently defined derivability relation, and finite-witness
   completeness for the supported language.
3. **Exact conclusion and scope.** A derivation matches both the conclusion
   proposition and its recorded scope. Specialization is an explicit rule with
   the declared scope-order condition; no other rule widens scope.
4. **Coverage.** Universal/absence conclusions name a finite discovery domain
   at an exact source/index revision, query/scope identity, and complete
   enumeration receipt. Every required member has checked evidence. A caller's
   `complete=true` plus an arbitrary list is not such a witness. Empty,
   truncated, denied and unavailable acquisition remain distinguishable; absence
   can only be scoped to a successfully enumerated declared finite domain.
5. **Independent state dimensions.** Assessment reports none/positive/negative/
   both support, applicability, freshness, validation, contestation and availability.
   A dispute does not erase contrary evidence. Retraction removes only its exact
   current support; supersession transfers neither support nor validation.
   Historical selection excludes later events rather than filtering by display
   dates. Observation age survives composition and summaries.
6. **Complete explicit context.** Evaluation identifies the immutable snapshot,
   target scope/intended use, semantic/ruleset/checker/policy versions and time.
   Witness evaluation constructs the transitive dependency footprint, including
   discovery membership and relevant corrections. Reuse compares these actual
   inputs, not unconstrained triples supplied by a caller. Validation receipts
   bind exact inputs, checker, result, scope and expiry.
7. **Admission and operations.** Raw source capture, candidate statements,
   admitted revisions and assessed results are distinct types/states. A plan
   binds base snapshot, exact proposed delta, material inputs and applicable
   authority evidence. The engine computes the canonical input identity; replay
   does not trust a caller-provided digest unrelated to its changes. Applying a
   plan validates the complete candidate and expected predecessor, preserves
   admitted invariants, and atomically publishes or leaves the previous state.
   Journal entries are produced only for applied operations. Approval of one
   revision/target never authorizes another.
8. **Bounded retrieval, not inference by SQL.** Retrieval pins a completed
   generation and returns relevant records, positive/negative evidence,
   assessment, explicit omissions/completeness and continuation at the same
   snapshot. Navigation edges do not become proof premises. PRs and documents
   are source kinds entering the same capture/candidate/admission path, not
   special inference rules or implicit authority.

## Implementation boundaries

- Lean owns the language, declarative judgments, executable decision functions,
  operation laws and registry T01–T22. Time's already-valid inclusive-boundary
  semantics is reused. No `sorry`, unapproved axiom, assumed global rule
  soundness, impossible-wellformedness premise or vacuous all-true model.
- Python mirrors the checked definitions with nominal values, validated codecs
  and no hidden clock/IO inside semantics. Every changed consumer migrates;
  obsolete unsafe semantic APIs are removed rather than wrapped.
- Services collect source bytes and acquisition metadata; they never infer that
  arbitrary prose is true. Explicit proposed structured claims require the
  applicable authority and checked evidence before admission.
- Git retains authored assets and release manifests; Dolt stores normalized
  structured records and query projections. Candidate data is isolated, committed
  natively, validated and retained before a conditional completed-pointer update.
  Local concurrency/recovery and remote transport are exercised with actual
  independent processes. No whole-KB JSON blob replaces relational storage.
- Citation syntax/resolution is built in. Historical exact resolution and current
  advisory classification are distinct operations, with retained evidence and
  explicit missing-object outcomes.

## Qualification work

The v1 counterexamples become failing-before/passing-after regressions, not
examples that pin bad behavior. Conformance includes reviewed examples,
generated finite cases, stateful sequences and deliberate semantic mutations.
Proof reports enumerate every registry symbol and assumption, reject missing
proofs/unapproved axioms, and record source/reference/toolchain identity.

Storage qualification exercises crashes around each publication boundary,
competing writers, pinned readers, replay/conflict, unknown revisions, exact
binding parity, same-KB ownership, retained rebuilds, migration dry-run/apply/
repeat/rollback, independent local-remote clients and clean restore. Evaluation
uses a frozen, predeclared task set with correctness and cost measurements.
Actual enterprise transport, policy protections and credentials must be exercised
on that endpoint; a local remote is not substituted for that result.

README and flow documentation describe the final executed paths, not intended
architecture. Each gate receives evidence from its actual implementation; an
unmet requirement remains work to do, never a renamed pass.
