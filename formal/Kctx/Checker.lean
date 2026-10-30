import Kctx.Model
import Kctx.Time
import Kctx.WellFormed

set_option autoImplicit false

/-! Executable semantic core: the derivation checker and the judgments
computed from it (support, evidence freshness, usability, dependency reuse).

Pure and total: no IO, no clock, no randomness. Every input the checker
consults is either in the derivation record itself or named in its declared
footprint — this is what the locality theorem (T07) rests on.

Rejection ordering is deterministic (first failing condition wins) and is a
conformance contract: the Python core must reject with the same code in the
same order. -/

namespace Kctx

/-! ## Verdicts. -/

inductive Rejection where
  | ruleNotEnabled
  | missingPremise
  | missingConclusion
  | conclusionPropMismatch
  | contestedConclusion
  | contestedPremise
  | ruleShapeMismatch
  | evidenceNotOk
  | evidenceNotFresh
  | missingCoverage
  | coverageIncomplete
  | footprintIncomplete
deriving DecidableEq, Repr, Inhabited

inductive Verdict where
  | accepted
  | rejected (r : Rejection)
deriving DecidableEq, Repr, Inhabited

instance : BEq Rejection := ⟨fun a b => decide (a = b)⟩
instance : BEq Verdict := ⟨fun a b => decide (a = b)⟩

/-! ## The checker. -/

def premisesResolve (v : KbView) (d : Derivation) : Bool :=
  d.premiseGroups.all (fun g => g.all (fun r => (v.findClaim r).isSome))

def conclusionMatches (v : KbView) (d : Derivation) : Bool :=
  match v.findClaim d.conclusion with
  | some c => c.prop == d.conclusionProp
  | none => false

/-- Every consulted identity must be declared in the footprint (T12: a
derivation may not silently depend on something it does not declare). -/
def footprintDeclares (v : KbView) (d : Derivation) : Bool :=
  let conclusionDep := hasKbRecordDep d d.conclusion.id.val
  match d.rule with
  | .andIntro =>
    conclusionDep
    && (d.premiseGroups.all (fun g =>
          g.all (fun r => hasKbRecordDep d r.id.val)))
  | .specialize =>
    conclusionDep
    && (match d.premiseGroups with
        | [[r]] => hasKbRecordDep d r.id.val
        | _ => false)
  | .obsSupports =>
    conclusionDep
    && (match d.evidence with
        | some i => d.footprint.contains (Dep.mk .kbRecord i.val "")
        | none => false)
  | .allChecked =>
    conclusionDep
    && (match d.witness with
        | some w => hasDiscoveryDep d w.scope.project
        | none => false)

/-- All identities the checker can consult for `d`: footprint targets, premise
ids, the conclusion id, and the declared evidence id. Locality (T07) is
relative to this list. -/
def Derivation.consultedIds (d : Derivation) : List String :=
  d.footprint.map (fun dep => dep.target)
  ++ (d.premiseGroups.flatMap (fun g => g.map (fun r => r.id.val)))
  ++ [d.conclusion.id.val]
  ++ (match d.evidence with
      | some i => [i.val]
      | none => [])

/-- v1 atom set for conjunction introduction: every premise must be an
atomic content claim; the conclusion conjoins those atoms in premise order. -/
def andIntroAtoms (v : KbView) (g : List ClaimRef) : List Atom :=
  g.map (fun r => ((v.propOf r).asAtom).getD default)

def checkAndIntro (v : KbView) (d : Derivation) : Verdict :=
  match d.premiseGroups with
  | [g] =>
    if g.isEmpty then .rejected .ruleShapeMismatch
    else if !(g.all (fun r => (v.propOf r).asAtom.isSome)) then .rejected .ruleShapeMismatch
    else if !(g.all (fun r => v.scopeOf r == some d.scope)) then .rejected .ruleShapeMismatch
    else if d.conclusionProp != .conj (andIntroAtoms v g) then .rejected .ruleShapeMismatch
    else if !footprintDeclares v d then .rejected .footprintIncomplete
    else .accepted
  | _ => .rejected .ruleShapeMismatch

def checkSpecialize (v : KbView) (d : Derivation) : Verdict :=
  match d.premiseGroups with
  | [[r]] =>
    match v.findClaim r, v.findClaim d.conclusion with
    | some src, some tgt =>
      if src.prop != tgt.prop then .rejected .ruleShapeMismatch
      else if !(tgt.scope.specializes src.scope) then .rejected .ruleShapeMismatch
      else if d.scope != tgt.scope then .rejected .ruleShapeMismatch
      else if !footprintDeclares v d then .rejected .footprintIncomplete
      else .accepted
    | _, _ => .rejected .missingPremise
  | _ => .rejected .ruleShapeMismatch

def checkObsSupports (v : KbView) (ctx : EvalCtx) (d : Derivation) : Verdict :=
  if !d.premiseGroups.isEmpty then .rejected .ruleShapeMismatch
  else match d.evidence with
    | none => .rejected .ruleShapeMismatch
    | some i =>
      match v.findObs i with
      | none => .rejected .missingPremise
      | some o =>
        if !(v.scopeOf d.conclusion == some d.scope) then .rejected .ruleShapeMismatch
        else if d.conclusionProp.asAtom.isNone then .rejected .ruleShapeMismatch
        else if o.outcome != .ok then .rejected .evidenceNotOk
        else if !v.bindings.contains (Binding.mk i d.conclusion .supports)
          then .rejected .evidenceNotOk
        else if assessFresh o.ttl o.observedAt ctx.now != .fresh
          then .rejected .evidenceNotFresh
        else if !footprintDeclares v d then .rejected .footprintIncomplete
        else .accepted

def checkAllChecked (v : KbView) (d : Derivation) : Verdict :=
  if !d.premiseGroups.isEmpty then .rejected .ruleShapeMismatch
  else match d.witness with
    | none => .rejected .missingCoverage
    | some w =>
      if !w.complete then .rejected .coverageIncomplete
      else if w.members.isEmpty then .rejected .coverageIncomplete
      else match d.conclusionProp with
        | .allChecked _ ms =>
          if ms != w.members then .rejected .ruleShapeMismatch
          else if w.scope != d.scope then .rejected .ruleShapeMismatch
          else if !footprintDeclares v d then .rejected .footprintIncomplete
          else .accepted
        | _ => .rejected .ruleShapeMismatch

/-- The executable derivation checker. Common checks first (deterministic
rejection order), then the per-rule shape checks. -/

def checkDerivationV (v : KbView) (ctx : EvalCtx) (d : Derivation) : Verdict :=
  if !enabledRules.contains d.rule then .rejected .ruleNotEnabled
  else if !premisesResolve v d then .rejected .missingPremise
  else if (v.findClaim d.conclusion).isNone then .rejected .missingConclusion
  else if !conclusionMatches v d then .rejected .conclusionPropMismatch
  else if v.corrections.any (fun c => c.target == d.conclusion)
    then .rejected .contestedConclusion
  else if v.corrections.any (fun c =>
      d.premiseGroups.any (fun g => g.contains c.target))
    then .rejected .contestedPremise
  else match d.rule with
    | .andIntro => checkAndIntro v d
    | .specialize => checkSpecialize v d
    | .obsSupports => checkObsSupports v ctx d
    | .allChecked => checkAllChecked v d

def KB.checkDerivation (kb : KB) (ctx : EvalCtx) (d : Derivation) : Verdict :=
  checkDerivationV kb.view ctx d

/-! ## Judgments computed from the checker. -/

/-- Positive support: some derivation concluding `r` is accepted. -/

def Supported (v : KbView) (ctx : EvalCtx) (r : ClaimRef) : Bool :=
  v.derivations.any (fun d => d.conclusion == r && checkDerivationV v ctx d == .accepted)

/-- Direct fresh evidence: an accepted `obsSupports` derivation concluding
`r` (acceptance already entails the freshness check). -/

def hasFreshEvidence (v : KbView) (ctx : EvalCtx) (r : ClaimRef) : Bool :=
  v.derivations.any (fun d =>
    d.conclusion == r && d.rule == .obsSupports && checkDerivationV v ctx d == .accepted)

/-- Contested: any correction targets `r`. -/

def Contested (v : KbView) (r : ClaimRef) : Bool :=
  v.corrections.any (fun c => c.target == r)

def validationCurrent (v : KbView) (r : ClaimRef) : Bool :=
  v.validations.any (fun p => p.1 == r)

/-- T17: `UsableFor` is exactly the conjunction of the policy's mandatory
conditions. -/

def UsableFor (v : KbView) (ctx : EvalCtx) (r : ClaimRef) : Bool :=
  Supported v ctx r
  && (!ctx.requireFreshEvidence || hasFreshEvidence v ctx r)
  && (!ctx.requireValidated || validationCurrent v r)
  && (!ctx.requireUncontested || !Contested v r)

/-! ## Dependency footprint reuse. -/

/-- Every required dependency is observed at exactly its required version. -/

def depsSatisfied (observed required : List Dep) : Bool :=
  required.all (fun dep => observed.contains dep)

/-- T06: a derivation is reusable when its check is accepted and its complete
declared footprint is matched by the observed dependency state. -/

def Reusable (v : KbView) (ctx : EvalCtx) (d : Derivation) (observed : List Dep) : Bool :=
  checkDerivationV v ctx d == .accepted && depsSatisfied observed d.footprint

/-! ## Membership congruence helper for locality. -/

theorem bool_ne_true_eq_false {b : Bool} (h : ¬ (b = true)) : b = false := by
  cases b with
  | true => exact absurd rfl h
  | false => rfl

theorem List.any_congr_mem {α : Type} (p : α → Bool) (l l' : List α)
    (h : ∀ a, p a = true → (a ∈ l ↔ a ∈ l')) : l.any p = l'.any p := by
  by_cases h1 : l.any p = true
  · obtain ⟨a, ha, hpa⟩ := List.any_eq_true.mp h1
    have hmem : a ∈ l' := (h a hpa).mp ha
    rw [h1, List.any_eq_true.mpr ⟨a, hmem, hpa⟩]
  · have hl : ∀ a ∈ l, ¬ (p a = true) := fun a ha =>
      List.any_eq_false.mp (bool_ne_true_eq_false h1) a ha
    have h2 : l'.any p = false := by
      rw [List.any_eq_false]
      intro a ha
      by_cases hp : p a = true
      · exact absurd hp (hl a ((h a hp).mpr ha))
      · simpa using hp
    rw [bool_ne_true_eq_false h1, h2]

end Kctx
