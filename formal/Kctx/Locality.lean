import Kctx.Theorems

set_option autoImplicit false
namespace Kctx

/-- Query-local agreement, over actual lookups rather than caller dependency hashes.
It deliberately includes empty correction selections and discovery records. -/
def LookupAgree (k k' : KB) (e : Context) : Witness → Prop
  | .attest id => attestationAt k id = attestationAt k' id ∧
      ∀ a, attestationAt k id = some a →
        observationAt k a.observation = observationAt k' a.observation ∧
        claimAt k a.claim = claimAt k' a.claim ∧
        activeRetracted k e a.claim = activeRetracted k' e a.claim ∧
        correctionDependency k e a.claim = correctionDependency k' e a.claim ∧
        inventoryAttestation k a = inventoryAttestation k' a
  | .truth _ => True
  | .and a b => LookupAgree k k' e a ∧ LookupAgree k k' e b
  | .specialize _ w => LookupAgree k k' e w
  | .all id _ w => enumerationAt k id = enumerationAt k' id ∧
      (∀ z, enumerationAt k id = some z → observationAt k z.observation = observationAt k' z.observation) ∧
      LookupAgree k k' e w
  | .absent id w => enumerationAt k id = enumerationAt k' id ∧
      (∀ z, enumerationAt k id = some z → observationAt k z.observation = observationAt k' z.observation) ∧
      LookupAgree k k' e w

private theorem leaf_agree {k k' : KB} {e : Context} {id : AttestationId}
    (h : LookupAgree k k' e (.attest id)) : leafEvidence k e id = leafEvidence k' e id := by
  rcases h with ⟨ha, hr⟩
  cases hx : attestationAt k id with
  | none => simp [leafEvidence, ← ha, hx]
  | some a =>
      rcases hr a hx with ⟨ho, hc, ht, hd, hi⟩
      simp [leafEvidence, ← ha, hx, ← ho, ← hc, leafAllowed, ← ht, ← hd, inventoryDependencies, ← hi]

private theorem enumeration_agree {k k' : KB} {e : Context} {id : EnumerationId}
    (h : enumerationAt k id = enumerationAt k' id)
    (ho : ∀ z, enumerationAt k id = some z → observationAt k z.observation = observationAt k' z.observation) :
    enumerationEvidence k e id = enumerationEvidence k' e id := by
  cases hz : enumerationAt k id with
  | none => simp [enumerationEvidence, ← h, hz]
  | some z => simp [enumerationEvidence, ← h, hz, ← ho z hz]

theorem T07_check_locality {k k' : KB} {e : Context} (w : Witness)
    (h : LookupAgree k k' e w) : checkWitness k e w = checkWitness k' e w := by
  induction w with
  | attest id => exact leaf_agree h
  | truth s => rfl
  | and a b ia ib => simp only [checkWitness, ia h.1, ib h.2]
  | specialize s w ih => simp only [checkWitness, ih h]
  | all id p w ih => simp only [checkWitness, enumeration_agree h.1 h.2.1, ih h.2.2]
  | absent id w ih => simp only [checkWitness, enumeration_agree h.1 h.2.1, ih h.2.2]

theorem T06_derivability_transfer {k k' : KB} {e : Context} {w : Witness} {r : Checked}
    (agree : LookupAgree k k' e w) (h : Derives k e w r) : Derives k' e w r := by
  apply T04_checker_sound
  rw [← T07_check_locality w agree]
  exact finite_witness_complete h

/-- Immutable snapshot selection ignores subsequent history, rather than guessing
historical acquisition/correction visibility from a civil display date. -/
structure Snapshot where
  id : SnapshotId
  state : KB
  deriving DecidableEq, BEq, Repr, Inhabited

def selectSnapshot (history : List Snapshot) (id : SnapshotId) : Option KB :=
  (history.find? (fun s => s.id == id)).map (·.state)

theorem T15_pinned_history {history later : List Snapshot} {id : SnapshotId} {state : KB}
    (h : selectSnapshot history id = some state) :
    selectSnapshot (history ++ later) id = some state := by
  unfold selectSnapshot at *
  cases hf : history.find? (fun s => s.id == id) with
  | none => simp [hf] at h
  | some s => simpa [List.find?_append, hf] using h

/-- Explicit supersession adds no evidence, no derivation and no receipt. -/
theorem T16_supersession_no_transfer (k : KB) (c : Correction) :
    ({ k with corrections := k.corrections ++ [c] }).attestations = k.attestations ∧
    ({ k with corrections := k.corrections ++ [c] }).derivations = k.derivations ∧
    ({ k with corrections := k.corrections ++ [c] }).receipts = k.receipts := ⟨rfl, rfl, rfl⟩

private theorem filterMap_none {α β : Type} (xs : List α) (f : α → Option β)
    (h : ∀ x ∈ xs, f x = none) : xs.filterMap f = [] := by
  induction xs with
  | nil => rfl
  | cons x xs ih =>
      simp [List.filterMap_cons, h x (by simp), ih (fun y hy => h y (by simp [hy]))]

theorem exactAlternatives_empty {k : KB} {e : Context} {r : Ref}
    (h : ∀ d ∈ k.derivations, d.claim ≠ r) : exactAlternatives k e r = [] := by
  apply filterMap_none
  intro d hd
  simp [h d hd]

theorem T16_identical_statement_no_revision_transfer {k : KB} {e : Context} {r : Ref} {c : Claim}
    (hc : claimAt k r = some c)
    (h : ∀ d ∈ k.derivations, d.claim ≠ r) :
    supported k e r c.statement.polarity = false := by
  simp [supported, supportAlternatives, hc, exactAlternatives_empty h]

theorem T16_no_validation_transfer {k : KB} {e : Context} {r : Ref}
    (h : ∀ receipt ∈ k.receipts, receipt.claim ≠ r) :
    validationCurrent k e r = false := by
  apply List.any_eq_false.mpr
  intro receipt hr
  simp [reusable, h receipt hr]

end Kctx
