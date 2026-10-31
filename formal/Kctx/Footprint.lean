import Kctx.Locality

set_option autoImplicit false
set_option maxHeartbeats 2400000
namespace Kctx

def DependencyMatches (k : KB) (e : Context) : Dependency → Prop
  | .observation o => observationAt k o.id = some o
  | .claim c => claimAt k c.ref = some c
  | .attestation a => attestationAt k a.id = some a
  | .enumeration z => enumerationAt k z.id = some z
  | .corrections r events => correctionDependency k e r = .corrections r events
  | .context value => contextDependency e = .context value

def FootprintMatches (k : KB) (e : Context) (ds : List Dependency) : Prop :=
  ∀ d ∈ ds, DependencyMatches k e d

private theorem any_filtered (xs : List Correction) (r : Ref) (now : Nat) :
    (xs.filter (fun c => c.target == r && c.recordedAt ≤ now)).any (fun c => c.kind == .retract) =
      xs.any (fun c => c.kind == .retract && c.target == r && c.recordedAt ≤ now) := by
  induction xs with
  | nil => rfl
  | cons c cs ih =>
      cases hk : c.kind == .retract <;> cases ht : c.target == r <;>
        cases hn : decide (c.recordedAt ≤ now) <;>
        simp_all [List.filter_cons, List.any_cons] <;> omega

private theorem corrections_retraction {k k' : KB} {e : Context} {r : Ref}
    (h : correctionDependency k' e r = correctionDependency k e r) :
    activeRetracted k' e r = activeRetracted k e r := by
  have selected : k'.corrections.filter (fun c => c.target == r && c.recordedAt ≤ e.now) =
      k.corrections.filter (fun c => c.target == r && c.recordedAt ≤ e.now) := by
    exact Dependency.corrections.inj h |>.2
  unfold activeRetracted
  rw [← any_filtered, ← any_filtered, selected]

private theorem leaf_footprint_transfer {k k' : KB} {e : Context} {id : AttestationId} {r : Checked}
    (h : leafEvidence k e id = some r) (hm : FootprintMatches k' e r.dependencies) :
    leafEvidence k' e id = some r := by
  cases ha : attestationAt k id with
  | none => simp [leafEvidence, ha] at h
  | some a =>
      cases ho : observationAt k a.observation with
      | none => simp [leafEvidence, ha, ho] at h
      | some o =>
          cases hc : claimAt k a.claim with
          | none => simp [leafEvidence, ha, ho, hc] at h
          | some c =>
              simp only [leafEvidence, ha, ho, hc, bind, Option.bind] at h
              split at h
              · next allowed =>
                  cases h
                  have aid : a.id = id := eq_of_beq (find_predicate (fun x : Attestation => x.id == id) k.attestations a ha)
                  have oid : o.id = a.observation := eq_of_beq (find_predicate (fun x : Observation => x.id == a.observation) k.observations o ho)
                  have cref : c.ref = a.claim := eq_of_beq (find_predicate (fun x : Claim => x.ref == a.claim) k.claims c hc)
                  have ha' : attestationAt k' id = some a := by
                    simpa [DependencyMatches, aid] using hm (.attestation a) (by simp)
                  have ho' : observationAt k' a.observation = some o := by
                    simpa [DependencyMatches, oid] using hm (.observation o) (by simp)
                  have hc' : claimAt k' a.claim = some c := by
                    simpa [DependencyMatches, cref] using hm (.claim c) (by simp)
                  have corr : correctionDependency k' e a.claim = correctionDependency k e a.claim :=
                    hm (correctionDependency k e a.claim) (by simp)
                  have retract := corrections_retraction corr
                  have inv : inventoryAttestation k' a = inventoryAttestation k a := by
                    cases hf : a.statement.formula <;> try simp only [inventoryAttestation, hf]
                    case inventory eid =>
                      cases hz : enumerationAt k eid with
                      | none => simp [leafAllowed, inventoryAttestation, hf, hz] at allowed
                      | some z =>
                          have zid : z.id = eid := eq_of_beq (find_predicate (fun x : Enumeration => x.id == eid) k.enumerations z hz)
                          have mz := hm (.enumeration z) (by simp [inventoryDependencies, inventoryAttestation, hf, hz])
                          simpa [DependencyMatches, inventoryAttestation, hf, hz, zid] using mz
                  have allowed' : leafAllowed k' e a o = true := by
                    simpa [leafAllowed, hc, hc', inv, retract] using allowed
                  simp [leafEvidence, ha', ho', hc', allowed', corr, inventoryDependencies, inv]
              · contradiction

private theorem enumeration_footprint_transfer {k k' : KB} {e : Context} {id : EnumerationId}
    {z : Enumeration} {o : Observation} (h : enumerationEvidence k e id = some (z, o))
    (hmz : DependencyMatches k' e (.enumeration z)) (hmo : DependencyMatches k' e (.observation o)) :
    enumerationEvidence k' e id = some (z, o) := by
  cases hz : enumerationAt k id with
  | none => simp [enumerationEvidence, hz] at h
  | some z' =>
      cases ho : observationAt k z'.observation with
      | none => simp [enumerationEvidence, hz, ho] at h
      | some o' =>
          simp only [enumerationEvidence, hz, ho, bind, Option.bind] at h
          split at h
          · next allowed =>
              cases h
              have zid : z.id = id := eq_of_beq (find_predicate (fun x : Enumeration => x.id == id) k.enumerations z hz)
              have oid : o.id = z.observation := eq_of_beq (find_predicate (fun x : Observation => x.id == z.observation) k.observations o ho)
              have hz' : enumerationAt k' id = some z := by simpa [DependencyMatches, zid] using hmz
              have ho' : observationAt k' z.observation = some o := by simpa [DependencyMatches, oid] using hmo
              simp [enumerationEvidence, hz', ho', allowed]
          · contradiction

/-- Equality of the ACTUALLY COMPUTED transitive footprint transfers the independent
judgment at fixed explicit context/time. No externally supplied premise truth. -/
theorem T06_computed_footprint_transfer {k k' : KB} {e : Context} {w : Witness} {r : Checked}
    (h : Derives k e w r) (hm : FootprintMatches k' e r.dependencies) : Derives k' e w r := by
  induction h with
  | attest h => exact .attest (leaf_footprint_transfer h hm)
  | truth s h => exact .truth s h
  | @and wa wb a b ha hb allowed ia ib =>
      apply Derives.and (ia ?_) (ib ?_) allowed
      · intro d hd
        exact hm d ((T12_merge_preserves_dependencies _ _ _).mpr (Or.inl hd))
      · intro d hd
        exact hm d ((T12_merge_preserves_dependencies _ _ _).mpr (Or.inr hd))
  | specialize s h narrow ih => exact .specialize s (ih hm) narrow
  | @all w a id p z o hz hw allowed ih =>
      have mz : DependencyMatches k' e (.enumeration z) := hm _
        ((T12_merge_preserves_dependencies _ _ _).mpr (Or.inr (by simp)))
      have mo : DependencyMatches k' e (.observation o) := hm _
        ((T12_merge_preserves_dependencies _ _ _).mpr (Or.inr (by simp)))
      apply Derives.all (enumeration_footprint_transfer hz mz mo) (ih ?_) allowed
      intro d hd
      exact hm d ((T12_merge_preserves_dependencies _ _ _).mpr (Or.inl hd))
  | @absent id w a z o hz hw allowed ih =>
      have mz : DependencyMatches k' e (.enumeration z) := hm _
        ((T12_merge_preserves_dependencies _ _ _).mpr (Or.inr (by simp)))
      have mo : DependencyMatches k' e (.observation o) := hm _
        ((T12_merge_preserves_dependencies _ _ _).mpr (Or.inr (by simp)))
      apply Derives.absent (enumeration_footprint_transfer hz mz mo) (ih ?_) allowed
      intro d hd
      exact hm d ((T12_merge_preserves_dependencies _ _ _).mpr (Or.inl hd))

theorem T07_computed_footprint_locality {k k' : KB} {e : Context} {w : Witness} {r : Checked}
    (h : checkWitness k e w = some r) (hm : FootprintMatches k' e r.dependencies) :
    checkWitness k' e w = some r :=
  finite_witness_complete (T06_computed_footprint_transfer (T04_checker_sound h) hm)

end Kctx
