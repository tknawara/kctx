import Kctx.Footprint
import Kctx.Theorems2
import Kctx.Selection
import Kctx.NonVacuity

set_option autoImplicit false
set_option maxHeartbeats 2400000
namespace Kctx

/-- Origin integrity is structural, not an assertion that a source tells the truth.
The exact observation value includes its timestamp, source, revision, and content. -/
def OriginSelected (k : KB) (e : Context) (o : Observation) : Prop :=
  observationAt k o.id = some o ∧ sourceSelected e o = true ∧
    o.outcome = .ok ∧ o.observedAt ≤ e.now

private theorem leaf_origin {k : KB} {e : Context} {id : AttestationId} {r : Checked}
    (h : leafEvidence k e id = some r) :
    ∀ o, .observation o ∈ r.dependencies → OriginSelected k e o := by
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
          intro value member
          have noInventory : ∀ x ∈ inventoryDependencies k a, ∀ v, x ≠ .observation v := by
            intro x hx v
            simp only [inventoryDependencies, List.mem_map] at hx
            obtain ⟨z, _, rfl⟩ := hx
            intro impossible; cases impossible
          have valueEq : value = o := by
            simp only [List.mem_append, List.mem_cons, List.not_mem_nil, or_false] at member
            rcases member with member | member
            · simpa [correctionDependency] using member
            · exact False.elim (noInventory _ member value rfl)
          subst value
          have oid : o.id = a.observation := eq_of_beq
            (find_predicate (fun x : Observation => x.id == a.observation) k.observations o ho)
          have hs : sourceSelected e o = true := by
            simp only [leafAllowed, bool_and] at allowed; simp_all
          have hok : o.outcome = .ok := by
            simp only [leafAllowed, bool_and] at allowed; simp_all
          have ht : o.observedAt ≤ e.now := by
            simp only [leafAllowed, bool_and] at allowed; simp_all
          exact ⟨by simpa [oid] using ho, hs, hok, ht⟩
        · contradiction

private theorem enumeration_origin {k : KB} {e : Context} {id : EnumerationId}
    {z : Enumeration} {o : Observation} (h : enumerationEvidence k e id = some (z, o)) :
    OriginSelected k e o := by
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
        have oid : o.id = z.observation := eq_of_beq
          (find_predicate (fun x : Observation => x.id == z.observation) k.observations o ho)
        have hs : sourceSelected e o = true := by
          simp only [enumerationAllowed, bool_and] at allowed; simp_all
        have hok : o.outcome = .ok := by
          simp only [enumerationAllowed, bool_and] at allowed; simp_all
        have ht : o.observedAt ≤ e.now := by
          simp only [enumerationAllowed, bool_and] at allowed; simp_all
        exact ⟨by simpa [oid] using ho, hs, hok, ht⟩
      · contradiction

/-- Every constructor preserves original admitted observations; none renews time. -/
theorem T12_derives_origin_preservation {k : KB} {e : Context} {w : Witness} {r : Checked}
    (h : Derives k e w r) :
    ∀ o, .observation o ∈ r.dependencies → OriginSelected k e o := by
  induction h with
  | attest h => exact leaf_origin h
  | truth s h => simp
  | and ha hb allowed ia ib =>
      intro o ho
      rcases (T12_merge_preserves_dependencies _ _ _).mp ho with ho | ho
      · exact ia o ho
      · exact ib o ho
  | specialize s h narrow ih => exact ih
  | all hz hw allowed ih =>
      intro o ho
      rcases (T12_merge_preserves_dependencies _ _ _).mp ho with ho | ho
      · exact ih o ho
      · simp only [List.mem_cons, List.not_mem_nil, or_false] at ho
        rcases ho with ho | ho
        · cases ho; exact enumeration_origin hz
        · cases ho
  | absent hz hw allowed ih =>
      intro o ho
      rcases (T12_merge_preserves_dependencies _ _ _).mp ho with ho | ho
      · exact ih o ho
      · simp only [List.mem_cons, List.not_mem_nil, or_false] at ho
        rcases ho with ho | ho
        · cases ho; exact enumeration_origin hz
        · cases ho

theorem T12_recursive_origin_preservation {k : KB} {e : Context} {w : Witness} {r : Checked}
    (h : checkWitness k e w = some r) (o : Observation)
    (ho : .observation o ∈ r.dependencies) : OriginSelected k e o :=
  T12_derives_origin_preservation (T04_checker_sound h) o ho

theorem T12_public_origin_preservation {k : KB} {e : Context} {w : Witness} {r : Checked}
    (h : check k e w = some r) (o : Observation)
    (ho : .observation o ∈ r.dependencies) : OriginSelected k e o := by
  cases he : contextValid k e with
  | false => simp [check, he] at h
  | true =>
    cases hw : checkWitness k e w with
    | none => simp [check, he, hw] at h
    | some raw =>
      simp only [check, he, hw, ↓reduceIte, Option.map_some] at h
      cases h
      rcases (T12_merge_preserves_dependencies _ _ _).mp ho with ho | ho
      · exact T12_recursive_origin_preservation hw o ho
      · simp [contextDependency] at ho

/-- A recursive child relation includes either conjunction branch and every unary rule. -/
inductive WitnessChild : Witness → Witness → Prop where
  | left (a b : Witness) : WitnessChild a (.and a b)
  | right (a b : Witness) : WitnessChild b (.and a b)
  | specialize (s : Scope) (w : Witness) : WitnessChild w (.specialize s w)
  | all (id : EnumerationId) (p : String) (w : Witness) : WitnessChild w (.all id p w)
  | absent (id : EnumerationId) (w : Witness) : WitnessChild w (.absent id w)

/-- Reflexive transitive child relation, not a second evaluator. -/
inductive WitnessDescendant : Witness → Witness → Prop where
  | self (w : Witness) : WitnessDescendant w w
  | step {a b c : Witness} : WitnessChild a b → WitnessDescendant b c → WitnessDescendant a c

theorem T12_child_dependencies_and_scope {k : KB} {e : Context} {child parent : Witness}
    {out : Checked} (hc : WitnessChild child parent) (h : Derives k e parent out) :
    ∃ r, Derives k e child r ∧ narrower out.statement.scope r.statement.scope ∧
      ∀ d ∈ r.dependencies, d ∈ out.dependencies := by
  cases hc with
  | left a b =>
    cases h with
    | and ha hb allowed =>
      exact ⟨_, ha, narrower_refl _, fun d hd =>
        (T12_merge_preserves_dependencies _ _ _).mpr (Or.inl hd)⟩
  | right a b =>
    cases h with
    | and ha hb allowed =>
      have hs := eq_of_beq (bool_and.mp (bool_and.mp allowed).1).1
      refine ⟨_, hb, ?_, fun d hd => (T12_merge_preserves_dependencies _ _ _).mpr (Or.inr hd)⟩
      simpa only [andResult, hs] using narrower_refl _
  | specialize s w =>
    cases h with
    | specialize _ hw narrow => exact ⟨_, hw, narrow, fun _ hd => hd⟩
  | all id p w =>
    cases h with
    | all hz hw allowed =>
      have hs := eq_of_beq (bool_and.mp allowed).2
      refine ⟨_, hw, ?_, fun d hd => (T12_merge_preserves_dependencies _ _ _).mpr (Or.inl hd)⟩
      simp only [allResult, hs]; exact narrower_refl _
  | absent id w =>
    cases h with
    | absent hz hw allowed =>
      have hs := eq_of_beq (bool_and.mp allowed).2
      refine ⟨_, hw, ?_, fun d hd => (T12_merge_preserves_dependencies _ _ _).mpr (Or.inl hd)⟩
      simp only [absenceResult, hs]; exact narrower_refl _

/-- Arbitrarily deep children retain every dependency and cannot have their scope widened. -/
theorem T12_recursive_dependencies_and_scope {k : KB} {e : Context} {child parent : Witness}
    {out : Checked} (hc : WitnessDescendant child parent) (h : checkWitness k e parent = some out) :
    ∃ r, checkWitness k e child = some r ∧ narrower out.statement.scope r.statement.scope ∧
      ∀ d ∈ r.dependencies, d ∈ out.dependencies := by
  induction hc generalizing out with
  | self w => exact ⟨out, h, narrower_refl _, fun _ hd => hd⟩
  | step child descendant ih =>
    obtain ⟨middle, hm, scope, deps⟩ := ih h
    obtain ⟨r, hr, scope', deps'⟩ := T12_child_dependencies_and_scope child (T04_checker_sound hm)
    exact ⟨r, finite_witness_complete hr, narrower_trans scope scope', fun d hd => deps d (deps' d hd)⟩

private theorem leaf_footprint {k : KB} {e : Context} {id : AttestationId} {r : Checked}
    (h : leafEvidence k e id = some r) : FootprintMatches k e r.dependencies := by
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
        · cases h
          have aid : a.id = id := eq_of_beq (find_predicate (fun x : Attestation => x.id == id) k.attestations a ha)
          have oid : o.id = a.observation := eq_of_beq (find_predicate (fun x : Observation => x.id == a.observation) k.observations o ho)
          have cid : c.ref = a.claim := eq_of_beq (find_predicate (fun x : Claim => x.ref == a.claim) k.claims c hc)
          intro d hd
          simp only [List.mem_append, List.mem_cons, List.not_mem_nil, or_false] at hd
          rcases hd with (rfl | rfl | rfl | rfl) | hd
          · simpa [DependencyMatches, oid] using ho
          · simpa [DependencyMatches, cid] using hc
          · simpa [DependencyMatches, aid] using ha
          · rfl
          · simp only [inventoryDependencies, List.mem_map] at hd
            obtain ⟨z, hz, rfl⟩ := hd
            have hz' : inventoryAttestation k a = some z := by simpa using hz
            cases hf : a.statement.formula <;> simp only [inventoryAttestation, hf] at hz' <;> try contradiction
            case inventory eid =>
              have zid : z.id = eid := eq_of_beq (find_predicate (fun x : Enumeration => x.id == eid) k.enumerations z hz')
              simpa [DependencyMatches, zid] using hz'
        · contradiction

/-- Every computed dependency is its exact lookup, including complete correction buckets. -/
theorem derives_footprint_matches {k : KB} {e : Context} {w : Witness} {r : Checked}
    (h : Derives k e w r) : FootprintMatches k e r.dependencies := by
  induction h with
  | attest h => exact leaf_footprint h
  | truth s h => intro d hd; cases hd
  | and ha hb allowed ia ib =>
    intro d hd
    rcases (T12_merge_preserves_dependencies _ _ _).mp hd with hd | hd
    · exact ia d hd
    · exact ib d hd
  | specialize s h narrow ih => exact ih
  | all hz hw allowed ih =>
    intro d hd
    rcases (T12_merge_preserves_dependencies _ _ _).mp hd with hd | hd
    · exact ih d hd
    · simp only [List.mem_cons, List.not_mem_nil, or_false] at hd
      rcases hd with rfl | rfl
      · exact (enumeration_origin hz).1
      · exact enumerationEvidence_lookup hz
  | absent hz hw allowed ih =>
    intro d hd
    rcases (T12_merge_preserves_dependencies _ _ _).mp hd with hd | hd
    · exact ih d hd
    · simp only [List.mem_cons, List.not_mem_nil, or_false] at hd
      rcases hd with rfl | rfl
      · exact (enumeration_origin hz).1
      · exact enumerationEvidence_lookup hz

private theorem checked_footprint {k : KB} {e : Context} {d : Derivation} {r : Checked}
    (h : checkedDerivation k e d = some r) : FootprintMatches k e r.dependencies := by
  cases hc : claimAt k d.claim with
  | none => simp [checkedDerivation, hc] at h
  | some c =>
    cases ht : activeRetracted k e d.claim with
    | true => simp [checkedDerivation, hc, ht] at h
    | false =>
      cases he : contextValid k e with
      | false => simp [checkedDerivation, hc, ht, he] at h
      | true =>
        cases hw : checkWitness k e d.witness with
        | none => simp [checkedDerivation, hc, ht, he, hw] at h
        | some raw =>
          simp only [checkedDerivation, hc, ht, he, hw, bind, Option.bind, Bool.not_true,
            Bool.false_eq_true, ↓reduceIte] at h
          split at h
          · cases h
            intro dep hd
            rcases (T12_merge_preserves_dependencies _ _ _).mp hd with hd | hd
            · exact derives_footprint_matches (T04_checker_sound hw) dep hd
            · simp only [List.mem_cons, List.not_mem_nil, or_false] at hd
              rcases hd with rfl | rfl | rfl
              · have cid : c.ref = d.claim := eq_of_beq (find_predicate (fun x : Claim => x.ref == d.claim) k.claims c hc)
                simpa [DependencyMatches, cid] using hc
              · rfl
              · rfl
          · contradiction

/-- Only the correction ledger changes; this is the immutable append operation
already used by T16_supersession_no_transfer, not a new state machine. -/
private theorem append_retraction (k : KB) (e : Context) (c : Correction)
    (kind : c.kind = .supersede) (r : Ref) :
    activeRetracted { k with corrections := k.corrections ++ [c] } e r =
      activeRetracted k e r := by
  simp [activeRetracted, List.any_append, kind]

private theorem derives_statement_transfer {k k' : KB} {e : Context}
    (leaves : ∀ id r, leafEvidence k e id = some r →
      ∃ r', leafEvidence k' e id = some r' ∧ r'.statement = r.statement)
    (enums : ∀ id, enumerationEvidence k' e id = enumerationEvidence k e id)
    {w : Witness} {r : Checked} (h : Derives k e w r) :
    ∃ r', Derives k' e w r' ∧ r'.statement = r.statement := by
  induction h with
  | @attest id r h =>
    obtain ⟨r', hr', hs⟩ := leaves id r h
    exact ⟨r', .attest hr', hs⟩
  | truth s h => exact ⟨_, .truth s h, rfl⟩
  | and ha hb allowed ia ib =>
    obtain ⟨a', ha', sa⟩ := ia
    obtain ⟨b', hb', sb⟩ := ib
    refine ⟨_, .and ha' hb' ?_, ?_⟩
    · simpa [andAllowed, sa, sb] using allowed
    · simp [andResult, sa, sb]
  | specialize s h narrow ih =>
    obtain ⟨a', ha', sa⟩ := ih
    refine ⟨_, .specialize s ha' ?_, ?_⟩
    · simpa [sa] using narrow
    · simp [sa]
  | all hz hw allowed ih =>
    obtain ⟨a', ha', sa⟩ := ih
    exact ⟨_, .all (by rw [enums]; exact hz) ha'
      (by simpa [allAllowed, sa] using allowed), rfl⟩
  | absent hz hw allowed ih =>
    obtain ⟨a', ha', sa⟩ := ih
    exact ⟨_, .absent (by rw [enums]; exact hz) ha'
      (by simpa [absenceAllowed, sa] using allowed), rfl⟩

private theorem leaf_statement_transfer {k k' : KB} {e : Context}
    (claims : k'.claims = k.claims) (observations : k'.observations = k.observations)
    (attestations : k'.attestations = k.attestations) (enumerations : k'.enumerations = k.enumerations)
    (retractions : ∀ r, activeRetracted k' e r = activeRetracted k e r)
    {id : AttestationId} {r : Checked} (h : leafEvidence k e id = some r) :
    ∃ r', leafEvidence k' e id = some r' ∧ r'.statement = r.statement := by
  have aa : ∀ id, attestationAt k' id = attestationAt k id := by intro id; simp [attestationAt, attestations]
  have oo : ∀ id, observationAt k' id = observationAt k id := by intro id; simp [observationAt, observations]
  have cc : ∀ ref, claimAt k' ref = claimAt k ref := by intro ref; simp [claimAt, claims]
  have ii : ∀ a, inventoryAttestation k' a = inventoryAttestation k a := by
    intro a; cases a.statement.formula <;> simp [inventoryAttestation, enumerationAt, enumerations]
  have allowed : ∀ a o, leafAllowed k' e a o = leafAllowed k e a o := by
    intro a o; simp [leafAllowed, retractions, cc, ii]
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
        · next good =>
          cases h
          refine ⟨⟨a.statement, [.observation o, .claim c, .attestation a,
            correctionDependency k' e a.claim] ++ inventoryDependencies k' a⟩, ?_, rfl⟩
          simp [leafEvidence, aa, oo, cc, allowed, ha, ho, hc, good]
        · contradiction

private theorem witness_statement_eq {k k' : KB} {e : Context}
    (claims : k'.claims = k.claims) (observations : k'.observations = k.observations)
    (attestations : k'.attestations = k.attestations) (enumerations : k'.enumerations = k.enumerations)
    (retractions : ∀ r, activeRetracted k' e r = activeRetracted k e r) (w : Witness) :
    (checkWitness k' e w).map Checked.statement = (checkWitness k e w).map Checked.statement := by
  have forward : ∀ r, checkWitness k e w = some r →
      ∃ r', checkWitness k' e w = some r' ∧ r'.statement = r.statement := by
    intro r hr
    obtain ⟨r', hd, hs⟩ := derives_statement_transfer
      (fun _ _ h => leaf_statement_transfer claims observations attestations enumerations retractions h)
      (by intro id; simp [enumerationEvidence, enumerationAt, observationAt, observations, enumerations])
      (T04_checker_sound hr)
    exact ⟨r', finite_witness_complete hd, hs⟩
  have backward : ∀ r', checkWitness k' e w = some r' →
      ∃ r, checkWitness k e w = some r ∧ r.statement = r'.statement := by
    intro r hr
    obtain ⟨r', hd, hs⟩ := derives_statement_transfer
      (fun _ _ h => leaf_statement_transfer claims.symm observations.symm attestations.symm
        enumerations.symm (fun r => (retractions r).symm) h)
      (by intro id; simp [enumerationEvidence, enumerationAt, observationAt, observations, enumerations])
      (T04_checker_sound hr)
    exact ⟨r', finite_witness_complete hd, hs⟩
  cases h : checkWitness k e w with
  | none =>
    cases h' : checkWitness k' e w with
    | none => rfl
    | some r' =>
      obtain ⟨r, hr, _⟩ := backward r' h'
      simp [h] at hr
  | some r =>
    obtain ⟨r', hr', hs⟩ := forward r h
    simp [hr', hs]

theorem T16_supersession_witness_statement (k : KB) (e : Context) (c : Correction)
    (kind : c.kind = .supersede) (w : Witness) :
    (checkWitness { k with corrections := k.corrections ++ [c] } e w).map Checked.statement =
      (checkWitness k e w).map Checked.statement :=
  witness_statement_eq (k := k) (k' := { k with corrections := k.corrections ++ [c] })
    rfl rfl rfl rfl (append_retraction k e c kind) w

private theorem append_checked_statement (k : KB) (e : Context) (c : Correction)
    (kind : c.kind = .supersede) (d : Derivation) :
    (checkedDerivation { k with corrections := k.corrections ++ [c] } e d).map Checked.statement =
      (checkedDerivation k e d).map Checked.statement := by
  let k' := { k with corrections := k.corrections ++ [c] }
  have hw := T16_supersession_witness_statement k e c kind d.witness
  change (checkWitness k' e d.witness).map Checked.statement =
    (checkWitness k e d.witness).map Checked.statement at hw
  have ht := append_retraction k e c kind d.claim
  have hc' : claimAt k' d.claim = claimAt k d.claim := rfl
  have he' : contextValid k' e = contextValid k e := rfl
  change (checkedDerivation k' e d).map Checked.statement =
    (checkedDerivation k e d).map Checked.statement
  unfold checkedDerivation
  rw [hc', ht, he']
  cases hc : claimAt k d.claim with
  | none => rfl
  | some claim =>
    cases hr : activeRetracted k e d.claim with
    | true => simp
    | false =>
      cases he : contextValid k e with
      | false => simp
      | true =>
        cases ha : checkWitness k e d.witness <;>
          cases hb : checkWitness k' e d.witness <;>
          simp only [ha, hb, Option.map_none, Option.map_some, Option.some.injEq] at hw <;>
          try contradiction
        all_goals simp_all

private theorem filterMap_empty_eq {α : Type} (xs : List α) (f g : α → Option Checked)
    (h : ∀ x, (f x).map Checked.statement = (g x).map Checked.statement) :
    (xs.filterMap f).isEmpty = (xs.filterMap g).isEmpty := by
  induction xs with
  | nil => rfl
  | cons x xs ih =>
    have hx := h x
    cases hf : f x <;> cases hg : g x <;>
      simp_all [List.filterMap_cons]

/-- Superseding is neither evidence nor retraction. At a fixed context and snapshot,
both own and contrary support are unchanged, even for arbitrary raw states. -/
theorem T16_supersession_support_unchanged (k : KB) (e : Context) (c : Correction)
    (kind : c.kind = .supersede) (r : Ref) (p : Polarity) :
    supported { k with corrections := k.corrections ++ [c] } e r p = supported k e r p := by
  let k' := { k with corrections := k.corrections ++ [c] }
  have checked : ∀ d, (checkedDerivation k' e d).map Checked.statement =
      (checkedDerivation k e d).map Checked.statement := append_checked_statement k e c kind
  have lookupEq : claimAt k' r = claimAt k r := rfl
  change supported k' e r p = supported k e r p
  unfold supported supportAlternatives
  rw [lookupEq]
  cases hc : claimAt k r with
  | none => rfl
  | some claim =>
    dsimp only
    split
    · apply congrArg Bool.not
      apply filterMap_empty_eq k.derivations
      intro d
      cases hd : d.claim == r <;> simp [hd, checked]
    · apply congrArg Bool.not
      apply filterMap_empty_eq k.derivations
      intro d
      have hh := checked d
      cases ha : checkedDerivation k' e d <;> cases hb : checkedDerivation k e d <;>
        simp only [ha, hb, Option.map_none, Option.map_some, Option.some.injEq] at hh <;>
        try contradiction
      all_goals simp [hh]

/-- Exact claim references prevent a source receipt from validating its replacement,
independently of timestamps or even the well-formedness of the raw state. -/
theorem T16_source_receipt_not_replacement (k : KB) (e : Context) (c : Correction)
    (receipt : Receipt) (target : Ref) (source : receipt.claim = c.target)
    (distinct : c.target ≠ target) :
    reusable { k with corrections := k.corrections ++ [c] } e target receipt = false := by
  simp [reusable, source, distinct]

private theorem append_footprint_back {k : KB} {e : Context} {c : Correction}
    (fresh : c ∉ k.corrections) {ds : List Dependency}
    (hm : FootprintMatches { k with corrections := k.corrections ++ [c] } e ds)
    (admitted : ds.all (dependencyWf k) = true) : FootprintMatches k e ds := by
  intro dep hd
  have matchNew := hm dep hd
  have wf := List.all_eq_true.mp admitted dep hd
  cases dep with
  | observation o => exact matchNew
  | claim claim => exact matchNew
  | attestation a => exact matchNew
  | enumeration z => exact matchNew
  | context context => exact matchNew
  | corrections r events =>
    have eventsEq : (k.corrections ++ [c]).filter (fun x => x.target == r && x.recordedAt ≤ e.now) = events :=
      (Dependency.corrections.inj matchNew).2
    have noNew : c ∉ events := by
      intro member
      have allEvents : events.all (fun x => x.target == r && k.corrections.contains x) = true :=
        (bool_and.mp wf).2
      have old := (bool_and.mp (List.all_eq_true.mp allEvents c member)).2
      exact fresh (by simpa using old)
    have inactive : (c.target == r && decide (c.recordedAt ≤ e.now)) = false := by
      cases selected : (c.target == r && decide (c.recordedAt ≤ e.now)) with
      | false => rfl
      | true =>
        apply False.elim
        apply noNew
        rw [← eventsEq]
        simp [List.filter_append, selected]
    change correctionDependency k e r = .corrections r events
    unfold correctionDependency
    congr 1
    simpa [List.filter_append, inactive] using eventsEq

private theorem checked_append_back {k : KB} {e : Context} {c : Correction}
    (kind : c.kind = .supersede) (fresh : c ∉ k.corrections)
    {d : Derivation} {r : Checked}
    (h : checkedDerivation { k with corrections := k.corrections ++ [c] } e d = some r)
    (admitted : r.dependencies.all (dependencyWf k) = true) :
    checkedDerivation k e d = some r := by
  let k' := { k with corrections := k.corrections ++ [c] }
  have footprint := append_footprint_back fresh (checked_footprint h) admitted
  have ht := append_retraction k e c kind d.claim
  change checkedDerivation k' e d = some r at h
  change activeRetracted k' e d.claim = activeRetracted k e d.claim at ht
  cases hc : claimAt k d.claim with
  | none =>
    have hc' : claimAt k' d.claim = none := hc
    simp [checkedDerivation, hc'] at h
  | some claim =>
    have hc' : claimAt k' d.claim = some claim := hc
    cases hr : activeRetracted k e d.claim with
    | true => simp [checkedDerivation, hc', ht, hr] at h
    | false =>
      cases he : contextValid k e with
      | false =>
        have he' : contextValid k' e = false := he
        simp [checkedDerivation, hc', ht, hr, he'] at h
      | true =>
        have he' : contextValid k' e = true := he
        cases hw : checkWitness k' e d.witness with
        | none => simp [checkedDerivation, hc', ht, hr, he', hw] at h
        | some raw =>
          simp only [checkedDerivation, hc', ht, hr, he', hw, bind, Option.bind,
            Bool.not_true, Bool.false_eq_true, ↓reduceIte] at h
          split at h
          · next statement =>
            cases h
            have rawFootprint : FootprintMatches k e raw.dependencies := by
              intro dep hd
              exact footprint dep ((T12_merge_preserves_dependencies _ _ _).mpr (Or.inl hd))
            have oldWitness := T07_computed_footprint_locality hw rawFootprint
            have corr := footprint (correctionDependency k' e d.claim)
              ((T12_merge_preserves_dependencies _ _ _).mpr (Or.inr (by simp)))
            have corrEq : correctionDependency k e d.claim = correctionDependency k' e d.claim := corr
            have statementEq : raw.statement = claim.statement := eq_of_beq statement
            simp [checkedDerivation, hc, hr, he, oldWitness, statementEq, corrEq]
          · contradiction

/-- Admission forbids receipts anticipating events not yet in the old ledger.
Under precisely that invariant, appending a fresh supersede can only lose validation. -/
theorem T16_supersession_reusable_monotone {k : KB} {e : Context} {c : Correction}
    (kind : c.kind = .supersede) (fresh : c ∉ k.corrections)
    (receipt : Receipt) (r : Ref)
    (admitted : receipt.dependencies.all (dependencyWf k) = true)
    (accepted : reusable { k with corrections := k.corrections ++ [c] } e r receipt = true) :
    reusable k e r receipt = true := by
  simp only [reusable, bool_and] at accepted ⊢
  refine ⟨accepted.1, ?_⟩
  obtain ⟨d, hd, good⟩ := List.any_eq_true.mp accepted.2
  have ids := (bool_and.mp good).1
  have deps := (bool_and.mp good).2
  cases checked : checkedDerivation { k with corrections := k.corrections ++ [c] } e d with
  | none => simp [checked] at deps
  | some result =>
    have eqDeps : result.dependencies = receipt.dependencies := by simpa [checked] using deps
    have before := checked_append_back kind fresh checked (by simpa [eqDeps] using admitted)
    apply List.any_eq_true.mpr
    exact ⟨d, hd, by simp [before, eqDeps, ids]⟩

theorem T16_supersession_validation_monotone {k : KB} {e : Context} {c : Correction}
    (kind : c.kind = .supersede) (fresh : c ∉ k.corrections)
    (admitted : k.wellFormed = true) (r : Ref)
    (accepted : validationCurrent { k with corrections := k.corrections ++ [c] } e r = true) :
    validationCurrent k e r = true := by
  have receipts : k.receipts.all (fun receipt => token receipt.id.val &&
      (claimAt k receipt.claim).isSome && contextWf receipt.context &&
      witnessRefs k receipt.witness && receipt.dependencies.all (dependencyWf k)) = true := by
    unfold KB.wellFormed at admitted
    exact (bool_and.mp admitted).2
  obtain ⟨receipt, member, good⟩ := List.any_eq_true.mp accepted
  have wf := (bool_and.mp (List.all_eq_true.mp receipts receipt member)).2
  exact List.any_eq_true.mpr ⟨receipt, member, T16_supersession_reusable_monotone kind fresh receipt r wf good⟩

/-- Direct two-state law for a valid immutable supersession append. Structural
admission of the successor is supplied by the operation boundary; the stronger
support equality itself does not require admission. Context/snapshot are fixed:
source truth, authenticated publication and durable storage are adapter premises. -/
theorem T16_valid_supersession_no_transfer {before after : KB} {e : Context}
    {c : Correction} {replacement : Ref}
    (operation : after = { before with corrections := before.corrections ++ [c] })
    (kind : c.kind = .supersede) (_target : c.replacement = some replacement)
    (distinct : c.target ≠ replacement) (fresh : c ∉ before.corrections)
    (oldAdmitted : before.wellFormed = true) (newAdmitted : after.wellFormed = true) :
    after.observations = before.observations ∧ after.claims = before.claims ∧
    after.attestations = before.attestations ∧ after.enumerations = before.enumerations ∧
    after.derivations = before.derivations ∧ after.receipts = before.receipts ∧
    (∀ r p, supported after e r p = supported before e r p) ∧
    (∀ r, validationCurrent after e r = true → validationCurrent before e r = true) ∧
    (∀ receipt, receipt.claim = c.target → reusable after e replacement receipt = false) := by
  subst after
  exact ⟨rfl, rfl, rfl, rfl, rfl, rfl,
    T16_supersession_support_unchanged before e c kind,
    fun r h => T16_supersession_validation_monotone kind fresh oldAdmitted r h,
    fun receipt h => T16_source_receipt_not_replacement before e c receipt replacement h distinct⟩

namespace CompositionExamples
open NonVacuity

def supersede : Correction :=
  ⟨⟨"supersede", by decide⟩, .supersede, claim.ref, some unsupported.ref, 15⟩

def after : KB := { kb with corrections := [supersede] }

def anticipatedReceipt : Receipt :=
  ⟨⟨"anticipated", by decide⟩, claim.ref, context, .attest attestation.id,
    [.observation observation, .claim claim, .attestation attestation,
      .corrections claim.ref [supersede], contextDependency context], true, 40⟩

def rawBefore : KB := { kb with receipts := [anticipatedReceipt] }
def rawAfter : KB := { rawBefore with corrections := [supersede] }

/-- Concrete counterexample to monotonic validation over arbitrary raw states. -/
theorem raw_validation_increases :
    validationCurrent rawBefore context claim.ref = false ∧
    validationCurrent rawAfter context claim.ref = true := by decide

theorem anticipated_receipt_not_admitted :
    anticipatedReceipt.dependencies.all (dependencyWf rawBefore) = false := by decide

/-- Both ends of a genuine supersede append are admitted and its ID/event is fresh. -/
theorem supersession_premises_inhabited :
    kb.wellFormed = true ∧ after.wellFormed = true ∧ supersede ∉ kb.corrections ∧
    supersede.kind = .supersede ∧ supersede.replacement = some unsupported.ref := by decide

theorem supported_source_does_not_support_replacement :
    supported after context claim.ref .positive = true ∧
    supported after context unsupported.ref .positive = false := by decide

def admittedReceipt : Receipt :=
  ⟨⟨"admitted", by decide⟩, claim.ref, context, .attest attestation.id,
    [.observation observation, .claim claim, .attestation attestation,
      .corrections claim.ref [], contextDependency context], true, 40⟩

def admittedBefore : KB := { kb with receipts := [admittedReceipt] }
def admittedAfter : KB := { admittedBefore with corrections := [supersede] }

/-- A genuinely reusable old receipt can lose validation without losing support. -/
theorem admitted_validation_decreases :
    admittedBefore.wellFormed = true ∧ admittedAfter.wellFormed = true ∧
    validationCurrent admittedBefore context claim.ref = true ∧
    validationCurrent admittedAfter context claim.ref = false ∧
    supported admittedAfter context claim.ref .positive = true := by decide

end CompositionExamples
end Kctx
