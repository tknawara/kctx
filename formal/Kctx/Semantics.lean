import Kctx.Model
import Kctx.Time
import Kctx.Checker

set_option autoImplicit false

/-! Declarative semantics: interpretations and the derivability judgment.

Deliberately independent of `Kctx.Checker`: nothing in this file refers to
the executable checker, so soundness (T04/T05) can never be a tautology
(handover §5: never define `Sound x` as "the checker returned pass").

An `Interp` assigns truth to atomic propositions and is *required* to satisfy
the declared base-attestation clauses: conjunction introduction, scope
weakening, universal-over-witness introduction, and evidence veridicality
(an OK observation bound to a claim makes the claim's content proposition
hold). Rules are sound relative to interpretations satisfying these clauses —
no axiom claims all rules or all configured registries are sound. -/

namespace Kctx

structure Interp where
  holds : ClaimProp → Scope → Prop
  conj_intro : ∀ (ps : List Atom) (s : Scope),
    (∀ a ∈ ps, holds (.atom a) s) → holds (.conj ps) s
  spec_weaken : ∀ (p : ClaimProp) (s s' : Scope),
    s'.specializes s = true → holds p s → holds p s'
  allc_intro : ∀ (pred : String) (ms : List String) (s : Scope),
    (∀ m ∈ ms, holds (.atom { subject := pred, predicate := "member", args := [m] }) s) →
    holds (.allChecked pred ms) s
  evidence_veridical : ∀ (o : Observation) (c : Claim),
    o.outcome = ObsOutcome.ok → holds c.prop c.scope

/-- Per-member proposition used by `allChecked`. -/
def memberProp (pred : String) (m : String) : ClaimProp :=
  .atom { subject := pred, predicate := "member", args := [m] }

/-- The declarative derivability judgment. Each constructor carries the
structural facts its rule requires; truth-transfer premises (`ip.holds ...`)
appear only where the rule genuinely concludes interpreted content. -/

inductive Derives (ip : Interp) (v : KbView) (ctx : EvalCtx) : Derivation → Prop
  | andIntro (d : Derivation) (g : List ClaimRef)
      (hr : d.rule = RuleId.andIntro)
      (hg : d.premiseGroups = [g])
      (hatoms : ∀ r ∈ g, ∃ a : Atom, v.propOf r = .atom a)
      (hconj : d.conclusionProp = .conj (andIntroAtoms v g))
      (hscope : ∀ r ∈ g, v.scopeOf r = some d.scope)
      (hne : 0 < g.length)
      (hprem : ∀ a ∈ andIntroAtoms v g, ip.holds (.atom a) d.scope) :
      Derives ip v ctx d
  | specialize (d : Derivation) (r : ClaimRef) (src tgt : Claim)
      (hr : d.rule = RuleId.specialize)
      (hg : d.premiseGroups = [[r]])
      (hsrc : v.findClaim r = some src)
      (htgt : v.findClaim d.conclusion = some tgt)
      (hprop : d.conclusionProp = tgt.prop ∧ tgt.prop = src.prop)
      (hspec : tgt.scope.specializes src.scope = true ∧ d.scope = tgt.scope)
      (hp : ip.holds src.prop src.scope) :
      Derives ip v ctx d
  | obsSupports (d : Derivation) (o : Observation) (c : Claim)
      (hr : d.rule = RuleId.obsSupports)
      (hg : d.premiseGroups = [])
      (hev : d.evidence = some o.id)
      (ho : v.findObs o.id = some o)
      (hc : v.findClaim d.conclusion = some c)
      (hcp : d.conclusionProp = c.prop ∧ d.scope = c.scope)
      (hatom : ∃ a : Atom, c.prop = .atom a)
      (hok : o.outcome = ObsOutcome.ok)
      (hbind : Binding.mk o.id d.conclusion SupportRole.supports ∈ v.bindings)
      (hfresh : FreshAt o.ttl o.observedAt ctx.now) :
      Derives ip v ctx d
  | allChecked (d : Derivation) (w : CoverageWitness) (pred : String)
      (hr : d.rule = RuleId.allChecked)
      (hg : d.premiseGroups = [])
      (hw : d.witness = some w)
      (hcomp : w.complete = true)
      (hne : w.members ≠ [])
      (hprop : d.conclusionProp = .allChecked pred w.members)
      (hscope : w.scope = d.scope)
      (hprem : ∀ m ∈ w.members, ip.holds (memberProp pred m) d.scope) :
      Derives ip v ctx d

end Kctx
