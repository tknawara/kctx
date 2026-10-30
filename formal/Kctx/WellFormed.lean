import Kctx.Model
set_option autoImplicit false

/-! Well-formedness of single records and whole KBs.

`wellFormed` is the invariant successful admitted mutations preserve (T03)
and decoding must produce (T01). It is a structural predicate — never defined
as "the checker accepted", which would make the soundness theorems
tautological (handover §5). -/

namespace Kctx

def hasDup {α : Type} [BEq α] : List α → Bool
  | [] => false
  | a :: as => as.contains a || hasDup as

def allUnique {α : Type} [BEq α] (l : List α) : Bool := !hasDup l

theorem allUnique_cons_of {α : Type} [BEq α] {a : α} {as : List α}
    (h : allUnique (a :: as) = true) : allUnique as = true := by
  simp [allUnique, hasDup] at h
  simp [allUnique, h.2]

/-- Premises of `r` through derivations concluding `r` (one step). -/
def KbView.premisesOf (v : KbView) (r : ClaimRef) : List ClaimRef :=
  ((v.derivations.filter (fun d => d.conclusion == r)).flatMap
    (fun d => d.premiseGroups)).flatMap (fun g => g)

/-- Bounded transitive premise closure. Fuel = derivation count suffices for
cycle detection in a finite KB. -/
def KbView.reachableIn (v : KbView) : Nat → ClaimRef → List ClaimRef
  | 0, _ => []
  | fuel + 1, r =>
    let ps := v.premisesOf r
    ps ++ (ps.flatMap (fun p => v.reachableIn fuel p))

/-- A derivation witness is acyclic when its conclusion is not reachable from
its own premises. -/
def KbView.acyclicDeriv (v : KbView) (d : Derivation) : Bool :=
  !(v.reachableIn (v.derivations.length + 1) d.conclusion).contains d.conclusion

/-- A rule's declared footprint must contain a `.kbRecord` dependency for each
record identity the rule consults; this is what makes the footprint the reuse
contract (T12). -/
def hasKbRecordDep (d : Derivation) (target : String) : Bool :=
  d.footprint.contains (Dep.mk .kbRecord target "")

def hasDiscoveryDep (d : Derivation) (target : String) : Bool :=
  d.footprint.contains (Dep.mk .discovery target "")

def recordWfDerivation (d : Derivation) : Bool :=
  !d.id.isEmpty
  && !d.conclusion.id.val.isEmpty
  && !d.conclusion.rev.isEmpty
  && d.premiseGroups.all (fun g => g.all (fun r => !r.id.val.isEmpty && !r.rev.isEmpty))
  && (match d.witness with
      | some w => !w.scope.project.isEmpty
      | none => true)

def recordWfObservation (o : Observation) : Bool :=
  !o.id.val.isEmpty && !o.system.isEmpty && !o.locator.isEmpty

def recordWfClaim (c : Claim) : Bool :=
  !c.id.val.isEmpty && !c.rev.isEmpty && !c.scope.project.isEmpty

def recordWfBinding (b : Binding) : Bool :=
  !b.obs.val.isEmpty && !b.ref.id.val.isEmpty && !b.ref.rev.isEmpty

def recordWfCorrection (c : Correction) : Bool :=
  !c.target.id.val.isEmpty && !c.target.rev.isEmpty

/-- Whole-state well-formedness: unique identities, resolving references,
acyclic derivation witnesses, and well-formed single records. -/
def KbView.wellFormed (v : KbView) : Bool :=
  allUnique (v.observations.map (fun o => o.id.val))
  && allUnique (v.claims.map (fun c => (c.id.val, c.rev)))
  && allUnique (v.derivations.map (fun d => d.id))
  && v.observations.all recordWfObservation
  && v.claims.all recordWfClaim
  && v.bindings.all recordWfBinding
  && v.corrections.all recordWfCorrection
  && v.derivations.all recordWfDerivation
  && v.bindings.all (fun b => (v.findObs b.obs).isSome && (v.findClaim b.ref).isSome)
  && v.corrections.all (fun c => (v.findClaim c.target).isSome)
  && v.derivations.all (fun d =>
      (v.findClaim d.conclusion).isSome
      && d.premiseGroups.all (fun g => g.all (fun r => (v.findClaim r).isSome))
      && (match d.evidence with
          | some i => (v.findObs i).isSome
          | none => d.rule != RuleId.obsSupports)
      && v.acyclicDeriv d)
  && v.validations.all (fun p => (v.findClaim p.1).isSome)

def KB.wellFormed (kb : KB) : Bool := kb.view.wellFormed

end Kctx
