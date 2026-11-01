import Kctx.Portfolio

set_option autoImplicit false
set_option maxRecDepth 100000
set_option maxHeartbeats 0
namespace Kctx.PortfolioExamples

def actor : ActorId := ⟨"reviewer", by decide⟩
def firstScope : Scope := ⟨⟨"project-a", by decide⟩, "staging"⟩
def secondScope : Scope := ⟨⟨"project-a", by decide⟩, "production"⟩
def thirdScope : Scope := ⟨⟨"project-b", by decide⟩, ""⟩
def first : Claim := ⟨⟨"first", by decide⟩, ⟨"r1", by decide⟩, ⟨.truth, firstScope, .positive⟩⟩
def second : Claim := ⟨⟨"second", by decide⟩, ⟨"r1", by decide⟩, ⟨.truth, secondScope, .positive⟩⟩
def third : Claim := ⟨⟨"third", by decide⟩, ⟨"r1", by decide⟩, ⟨.truth, thirdScope, .positive⟩⟩
def firstId : ContextId := ⟨"staging", by decide⟩
def secondId : ContextId := ⟨"production", by decide⟩
def thirdId : ContextId := ⟨"other-project", by decide⟩
def base : KB := ⟨⟨"base", by decide⟩, [], [first], [], [],
  [⟨⟨"first-proof", by decide⟩, first.ref, .truth firstScope⟩], [], []⟩
def candidate : KB :=
  { base with
      snapshot := ⟨"next", by decide⟩
      claims := [first, second, third]
      derivations := base.derivations ++
        [⟨⟨"second-proof", by decide⟩, second.ref, .truth secondScope⟩,
         ⟨⟨"third-proof", by decide⟩, third.ref, .truth thirdScope⟩] }
def context (snapshot : SnapshotId) (scope : Scope) : Context :=
  ⟨snapshot, "2.0.0", ⟨"core-2", by decide⟩, ⟨"kctx-2", by decide⟩,
    ⟨⟨"release", by decide⟩, false, false, true, .noExpiry, [actor]⟩,
    20, scope, "release", []⟩
def initial : PortfolioState := ⟨base, [first.ref], [⟨firstId, context base.snapshot firstScope⟩]⟩
def plan : PortfolioPlan := ⟨⟨"release-batch", by decide⟩, base.snapshot, candidate, actor,
  [⟨firstId, context candidate.snapshot firstScope⟩,
   ⟨secondId, context candidate.snapshot secondScope⟩,
   ⟨thirdId, context candidate.snapshot thirdScope⟩],
  [⟨second.ref, secondId, .truth secondScope⟩, ⟨third.ref, thirdId, .truth thirdScope⟩], []⟩
def admitted : PortfolioState := admittedPortfolio initial plan

theorem initial_valid : portfolioStateValid initial = true := by decide
theorem mixed_selectors_and_projects_admitted : portfolioPlanValid initial plan = true := by decide
theorem authenticated_batch_applied :
    (applyPortfolio initial [] plan [⟨plan⟩]).outcome = .applied := by decide
theorem unauthenticated_batch_rejected :
    (applyPortfolio initial [] plan []).outcome = .rejected := by decide

theorem old_context_still_readable :
    (assessPortfolio admitted firstId (context candidate.snapshot firstScope) first.ref).isSome = true := by decide
theorem old_context_still_usable : usableFor candidate (context candidate.snapshot firstScope) first.ref = true := by decide

def unsupportedCandidate : KB := { candidate with derivations := base.derivations ++
  [⟨⟨"second-proof", by decide⟩, second.ref, .truth secondScope⟩] }
def unsupportedPlan : PortfolioPlan := { plan with candidate := unsupportedCandidate }
theorem unsupported_second_added_claim_rejected : portfolioPlanValid initial unsupportedPlan = false := by decide

def missingContextPlan : PortfolioPlan := { plan with assignments :=
  [⟨second.ref, ⟨"missing", by decide⟩, .truth secondScope⟩, ⟨third.ref, thirdId, .truth thirdScope⟩] }
def mismatchedContextPlan : PortfolioPlan := { plan with assignments :=
  [⟨second.ref, thirdId, .truth secondScope⟩, ⟨third.ref, thirdId, .truth thirdScope⟩] }
theorem missing_context_rejected : portfolioPlanValid initial missingContextPlan = false := by decide
theorem mismatched_context_rejected : portfolioPlanValid initial mismatchedContextPlan = false := by decide

def changedContextPlan : PortfolioPlan := { plan with contexts :=
  [⟨firstId, { context candidate.snapshot firstScope with now := 21 }⟩,
   ⟨secondId, context candidate.snapshot secondScope⟩,
   ⟨thirdId, context candidate.snapshot thirdScope⟩] }
theorem changed_context_same_operation_conflicts :
    (applyPortfolio admitted [⟨plan⟩] changedContextPlan [⟨changedContextPlan⟩]).outcome = .inputConflict := by decide
theorem no_authorizing_query_by_another_context :
    queryContextAllowed admitted firstId (context candidate.snapshot secondScope) = false := by decide
theorem selected_other_context_allows_own_query :
    queryContextAllowed admitted secondId (context candidate.snapshot secondScope) = true := by decide

def retirement : PortfolioPlan := ⟨⟨"retire-staging", by decide⟩, candidate.snapshot,
  { candidate with snapshot := ⟨"retired", by decide⟩ }, actor,
  [⟨secondId, context ⟨"retired", by decide⟩ secondScope⟩,
   ⟨thirdId, context ⟨"retired", by decide⟩ thirdScope⟩], [], [firstId]⟩
theorem explicit_retirement_with_carried_claim_allowed : portfolioPlanValid admitted retirement = true := by decide
theorem implicit_retirement_rejected :
    portfolioPlanValid admitted { retirement with retiredContexts := [] } = false := by decide

def rollback : PortfolioSelectionPlan := ⟨⟨"select-old", by decide⟩, candidate.snapshot,
  base.snapshot, ⟨"selected-old", by decide⟩, actor,
  [⟨firstId, context ⟨"selected-old", by decide⟩ firstScope⟩,
   ⟨secondId, context ⟨"selected-old", by decide⟩ secondScope⟩,
   ⟨thirdId, context ⟨"selected-old", by decide⟩ thirdScope⟩], initial.selected⟩
theorem rollback_nonvacuous : portfolioSelectionValid admitted rollback [initial] = true := by decide
theorem rollback_applied :
    (applyPortfolioSelection admitted [] rollback [⟨rollback⟩] [initial]).outcome = .applied := by decide
theorem rollback_retains_ledger : (selectedPortfolio admitted rollback).kb.claims = candidate.claims := rfl
theorem rollback_unselects_later_claim :
    assessPortfolio (selectedPortfolio admitted rollback) secondId
      (context rollback.newSnapshot secondScope) second.ref = none := by decide
theorem rollback_cannot_revert_clock :
    portfolioSelectionValid admitted { rollback with contexts :=
      [⟨firstId, { context rollback.newSnapshot firstScope with now := 19 }⟩,
       ⟨secondId, context rollback.newSnapshot secondScope⟩,
       ⟨thirdId, context rollback.newSnapshot thirdScope⟩] } [initial] = false := by decide

/-- Two real attestation leaves share a source but select incompatible revisions.
Their conjunction is never constructed by pooling portfolio authorizations. -/
def pClaim : Claim := ⟨⟨"p", by decide⟩, ⟨"r1", by decide⟩,
  ⟨.atom ⟨"item", "P", []⟩, firstScope, .positive⟩⟩
def qClaim : Claim := ⟨⟨"q", by decide⟩, ⟨"r1", by decide⟩,
  ⟨.atom ⟨"item", "Q", []⟩, firstScope, .positive⟩⟩
def pObservation : Observation := ⟨⟨"p-observation", by decide⟩, ⟨"source", by decide⟩,
  ⟨"rev1", by decide⟩, ⟨"bytes1", by decide⟩, 10, .ok⟩
def qObservation : Observation := ⟨⟨"q-observation", by decide⟩, ⟨"source", by decide⟩,
  ⟨"rev2", by decide⟩, ⟨"bytes2", by decide⟩, 10, .ok⟩
def pAttestation : Attestation := ⟨⟨"p-attestation", by decide⟩, pClaim.ref,
  pObservation.id, pClaim.statement, actor⟩
def qAttestation : Attestation := ⟨⟨"q-attestation", by decide⟩, qClaim.ref,
  qObservation.id, qClaim.statement, actor⟩
def isolatedKB : KB := ⟨⟨"isolated", by decide⟩, [pObservation, qObservation], [pClaim, qClaim],
  [pAttestation, qAttestation], [],
  [⟨⟨"p-proof", by decide⟩, pClaim.ref, .attest pAttestation.id⟩,
   ⟨⟨"q-proof", by decide⟩, qClaim.ref, .attest qAttestation.id⟩], [], []⟩
def pContext : Context := { context isolatedKB.snapshot firstScope with
  sources := [⟨pObservation.source, pObservation.revision, pObservation.content⟩] }
def qContext : Context := { context isolatedKB.snapshot firstScope with
  sources := [⟨qObservation.source, qObservation.revision, qObservation.content⟩] }
def isolatedState : PortfolioState := ⟨isolatedKB, [pClaim.ref, qClaim.ref],
  [⟨firstId, pContext⟩, ⟨secondId, qContext⟩]⟩
theorem isolation_state_valid : portfolioStateValid isolatedState = true := by decide
theorem p_only_under_rev1 : usableFor isolatedKB pContext pClaim.ref = true ∧
    usableFor isolatedKB qContext pClaim.ref = false := by decide
theorem q_only_under_rev2 : usableFor isolatedKB qContext qClaim.ref = true ∧
    usableFor isolatedKB pContext qClaim.ref = false := by decide
theorem conjunction_not_pooled :
    check isolatedKB pContext (.and (.attest pAttestation.id) (.attest qAttestation.id)) = none ∧
    check isolatedKB qContext (.and (.attest pAttestation.id) (.attest qAttestation.id)) = none := by decide
theorem source_authorization_not_borrowed : queryContextAllowed isolatedState firstId qContext = false := by decide

/-- The old plan and singleton portfolio use distinct snapshot frames explicitly. -/
def singletonCandidate : KB :=
  { base with
      snapshot := ⟨"singleton", by decide⟩
      claims := [first, second]
      derivations := base.derivations ++
        [⟨⟨"second-proof", by decide⟩, second.ref, .truth secondScope⟩] }
def legacyContext : Context := context base.snapshot secondScope
def legacy : Plan := ⟨⟨"legacy", by decide⟩, base.snapshot, singletonCandidate,
  ⟨actor, second.ref, "release", legacyContext.policy.id, second.statement, singletonCandidate,
    [second], legacyContext⟩, second.ref, .truth secondScope⟩
def singletonInitial : PortfolioState := ⟨base, [first.ref], [⟨secondId, legacyContext⟩]⟩
theorem legacy_valid : planValid base legacyContext legacy = true := by decide
theorem singleton_embedded_valid :
    portfolioPlanValid singletonInitial (singletonPortfolioPlan secondId legacyContext legacy) = true := by decide

def retainedSubset : PortfolioState := { admitted with selected := [first.ref] }
def selectSubset : PortfolioSelectionPlan := { rollback with retainedSnapshot := candidate.snapshot }
theorem retained_selection_not_all_stored_claims :
    portfolioSelectionValid admitted selectSubset [retainedSubset] = true ∧
    portfolioSelectionValid admitted
      { selectSubset with selected := candidate.claims.map Claim.ref } [retainedSubset] = false := by decide

def contextOnly : PortfolioPlan := { plan with
  candidate := { base with snapshot := candidate.snapshot }, assignments := [] }
theorem adding_contexts_without_claims_allowed : portfolioPlanValid initial contextOnly = true := by decide

theorem empty_context_family_not_a_release :
    contextFamilyValid base [] = true ∧
    portfolioStateValid { initial with contexts := [] } = false := by decide

def bootstrap : PortfolioState :=
  ⟨{ base with claims := [], derivations := [] }, [], []⟩
theorem empty_bootstrap_valid : portfolioStateValid bootstrap = true := by decide

end Kctx.PortfolioExamples
