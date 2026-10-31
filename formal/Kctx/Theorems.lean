import Kctx.Workflow

set_option autoImplicit false
set_option maxHeartbeats 1200000
namespace Kctx

theorem bool_and {a b : Bool} : (a && b) = true ↔ a = true ∧ b = true := by
  cases a <;> cases b <;> decide

/-- Completeness is for EVERY finite tree in the declared syntax, not a test grid. -/
theorem finite_witness_complete {k : KB} {e : Context} {w : Witness} {r : Checked}
    (h : Derives k e w r) : checkWitness k e w = some r := by
  induction h with
  | attest h => exact h
  | truth s h => simp [checkWitness, h]
  | and _ _ h ia ib => simp [checkWitness, ia, ib, h]
  | specialize s _ h ih => simp [checkWitness, ih, h]
  | all h _ ha ih => simp [checkWitness, h, ih, ha]
  | absent h _ ha ih => simp [checkWitness, h, ih, ha]

theorem T04_checker_sound {k : KB} {e : Context} {w : Witness} {r : Checked}
    (h : checkWitness k e w = some r) : Derives k e w r := by
  induction w generalizing r with
  | attest id => exact .attest h
  | truth s =>
      simp only [checkWitness] at h
      split at h
      · cases h; exact .truth s ‹_›
      · contradiction
  | and wa wb ia ib =>
      cases ha : checkWitness k e wa with
      | none => simp [checkWitness, ha] at h
      | some a =>
          cases hb : checkWitness k e wb with
          | none => simp [checkWitness, ha, hb] at h
          | some b =>
              simp only [checkWitness, ha, hb, bind, Option.bind] at h
              split at h
              · cases h; exact .and (ia ha) (ib hb) ‹_›
              · contradiction
  | specialize s w ih =>
      cases hw : checkWitness k e w with
      | none => simp [checkWitness, hw] at h
      | some a =>
          simp only [checkWitness, hw, bind, Option.bind] at h
          split at h
          · cases h; exact .specialize s (ih hw) ‹_›
          · contradiction
  | all id p w ih =>
      cases hz : enumerationEvidence k e id with
      | none => simp [checkWitness, hz] at h
      | some pair =>
          rcases pair with ⟨z, o⟩
          cases hw : checkWitness k e w with
          | none => simp [checkWitness, hz, hw] at h
          | some a =>
              simp only [checkWitness, hz, hw, bind, Option.bind] at h
              split at h
              · cases h; exact .all hz (ih hw) ‹_›
              · contradiction
  | absent id w ih =>
      cases hz : enumerationEvidence k e id with
      | none => simp [checkWitness, hz] at h
      | some pair =>
          rcases pair with ⟨z, o⟩
          cases hw : checkWitness k e w with
          | none => simp [checkWitness, hz, hw] at h
          | some a =>
              simp only [checkWitness, hz, hw, bind, Option.bind] at h
              split at h
              · cases h; exact .absent hz (ih hw) ‹_›
              · contradiction

theorem checkWitness_iff {k : KB} {e : Context} {w : Witness} {r : Checked} :
    checkWitness k e w = some r ↔ Derives k e w r :=
  ⟨T04_checker_sound, finite_witness_complete⟩

theorem narrower_refl (s : Scope) : narrower s s := ⟨rfl, Or.inl rfl⟩
theorem narrower_trans {a b c : Scope} (ab : narrower a b) (bc : narrower b c) : narrower a c := by
  rcases ab with ⟨hp, hs⟩
  rcases bc with ⟨hp', hs'⟩
  constructor
  · exact hp.trans hp'
  · rcases hs with hs | hs <;> rcases hs' with hs' | hs'
    · exact Or.inl (hs.trans hs')
    · exact Or.inr hs'
    · exact Or.inr (hs'.symm.trans hs)
    · exact Or.inr hs'

theorem holds_specialize (i : Interpretation) (k : KB) (f : Formula) (p : Polarity)
    {s t : Scope} (hst : narrower t s) (h : holdsFormula i k s p f) :
    holdsFormula i k t p f := by
  induction f generalizing p with
  | atom a => exact fun u hu => h u (narrower_trans hu hst)
  | truth => exact h
  | and a b ia ib => exact ⟨h.1, ia .positive h.2.1, ib .positive h.2.2⟩
  | all id predicate =>
      rcases h with ⟨hp, z, hz, hm⟩
      exact ⟨hp, z, hz, fun member hmem u hu => hm member hmem u (narrower_trans hu hst)⟩
  | absent id => exact h
  | inventory id => exact h

theorem memberFormula_sound (i : Interpretation) (k : KB) (s : Scope)
    (members : List String) (p : String)
    (h : holdsFormula i k s .positive (memberFormula members p)) :
    ∀ m ∈ members, atomHolds i ⟨m, p, []⟩ s .positive := by
  induction members with
  | nil => simp
  | cons a rest ih =>
      simp only [memberFormula, List.foldr_cons, holdsFormula] at h
      intro m hm
      cases hm with
      | head => exact h.2.1
      | tail _ ht => exact ih h.2.2 m ht

theorem find_predicate {α : Type} (p : α → Bool) (xs : List α) (a : α)
    (h : xs.find? p = some a) : p a = true := by
  induction xs with
  | nil => simp at h
  | cons x xs ih =>
      simp only [List.find?] at h
      split at h
      · cases h; assumption
      · exact ih h

theorem enumerationEvidence_lookup {k : KB} {e : Context} {id : EnumerationId}
    {z : Enumeration} {o : Observation} (h : enumerationEvidence k e id = some (z, o)) :
    enumerationAt k z.id = some z := by
  cases hz : enumerationAt k id with
  | none => simp [enumerationEvidence, hz] at h
  | some z' =>
      cases ho : observationAt k z'.observation with
      | none => simp [enumerationEvidence, hz, ho] at h
      | some o' =>
          simp only [enumerationEvidence, hz, ho, bind, Option.bind] at h
          split at h
          · cases h
            have hid : z.id = id := eq_of_beq (find_predicate (fun x : Enumeration => x.id == id) k.enumerations z hz)
            simpa [hid] using hz
          · contradiction

/-- Per-rule preservation, with only exact admitted attestation leaves trusted. -/
theorem T05_derives_sound {i : Interpretation} {k : KB} {e : Context}
    (evidence : EvidenceSound i k e) {w : Witness} {r : Checked}
    (h : Derives k e w r) : Holds i k r.statement := by
  induction h with
  | @attest id r h =>
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
                  · cases h; exact evidence id a o ha ho ‹_›
                  · contradiction
  | truth s _ => rfl
  | @and wa wb a b _ _ allowed ia ib =>
      have hh := bool_and.mp allowed
      have hh' := bool_and.mp hh.1
      have hs : a.statement.scope = b.statement.scope := eq_of_beq hh'.1
      have hp : a.statement.polarity = .positive := eq_of_beq hh'.2
      have hq : b.statement.polarity = .positive := eq_of_beq hh.2
      exact ⟨rfl, by simpa [Holds, andResult, hp] using ia, by simpa [Holds, andResult, hs, hq] using ib⟩
  | @specialize w a s _ narrow ih =>
      exact holds_specialize i k a.statement.formula a.statement.polarity narrow ih
  | @all w a id p z o hz _ allowed ih =>
      have hs : a.statement = ⟨.and (.inventory z.id) (memberFormula z.members p), z.scope, .positive⟩ :=
        eq_of_beq (bool_and.mp allowed).2
      have hi : holdsFormula i k z.scope .positive (.and (.inventory z.id) (memberFormula z.members p)) := by
        simpa [Holds, hs] using ih
      obtain ⟨_, cert, hc, complete⟩ := hi.2.1
      have ceq : cert = z := Option.some.inj (hc.symm.trans (enumerationEvidence_lookup hz))
      subst cert
      refine ⟨rfl, z, enumerationEvidence_lookup hz, ?_⟩
      rw [complete]
      exact memberFormula_sound i k z.scope z.members p hi.2.2
  | @absent id w a z o hz _ allowed ih =>
      have hs : a.statement = ⟨.inventory z.id, z.scope, .positive⟩ := eq_of_beq (bool_and.mp allowed).2
      have hi : holdsFormula i k z.scope .positive (.inventory z.id) := by simpa [Holds, hs] using ih
      obtain ⟨_, cert, hc, complete⟩ := hi
      have ceq : cert = z := Option.some.inj (hc.symm.trans (enumerationEvidence_lookup hz))
      subst cert
      exact ⟨rfl, z, enumerationEvidence_lookup hz, complete.trans (eq_of_beq (bool_and.mp allowed).1)⟩

/-- Atomic falsity is inhabited; there is no interpretation-collapse axiom. -/
def falseInterpretation : Interpretation := ⟨fun _ _ _ => False, fun _ _ _ _ _ => []⟩

theorem false_atom (k : KB) (a : Atom) (s : Scope) (p : Polarity) :
    ¬ Holds falseInterpretation k ⟨.atom a, s, p⟩ := by
  intro h
  exact h s (narrower_refl s)

theorem unsupported_atom_impossible {k : KB} {e : Context}
    (h : EvidenceSound falseInterpretation k e) (w : Witness) (r : Checked)
    (a : Atom) (s : Scope) (p : Polarity) (hr : r.statement = ⟨.atom a, s, p⟩) :
    checkWitness k e w ≠ some r := by
  intro accepted
  have truth := T05_derives_sound h (T04_checker_sound accepted)
  rw [hr] at truth
  exact false_atom k a s p truth

theorem checkedDerivation_exact {k : KB} {e : Context} {d : Derivation} {out : Checked}
    (h : checkedDerivation k e d = some out) :
    ∃ c raw, claimAt k d.claim = some c ∧ Derives k e d.witness raw ∧
      out.statement = c.statement ∧ raw.statement = c.statement := by
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
                  · next hs =>
                      cases h
                      exact ⟨c, raw, rfl, T04_checker_sound hw, eq_of_beq hs, eq_of_beq hs⟩
                  · contradiction

theorem T05_admitted_derivation_sound {i : Interpretation} {k : KB} {e : Context}
    (evidence : EvidenceSound i k e) {d : Derivation} {out : Checked}
    (h : checkedDerivation k e d = some out) : Holds i k out.statement := by
  obtain ⟨c, raw, _, hd, ho, hr⟩ := checkedDerivation_exact h
  rw [ho, ← hr]
  exact T05_derives_sound evidence hd

theorem T04_public_check_sound {k : KB} {e : Context} {w : Witness} {out : Checked}
    (h : check k e w = some out) :
    contextValid k e = true ∧ ∃ raw, Derives k e w raw ∧ out.statement = raw.statement := by
  cases he : contextValid k e with
  | false => simp [check, he] at h
  | true =>
      cases hw : checkWitness k e w with
      | none => simp [check, he, hw] at h
      | some raw =>
          simp only [check, he, hw, ↓reduceIte, Option.map_some] at h
          cases h
          exact ⟨rfl, raw, T04_checker_sound hw, rfl⟩

theorem mem_dedupDependencies (seen xs : List Dependency) (d : Dependency) :
    d ∈ dedupDependencies seen xs ↔ d ∈ xs ∧ d ∉ seen := by
  induction xs generalizing seen with
  | nil => simp [dedupDependencies]
  | cons x xs ih =>
      by_cases hx : x ∈ seen
      · simp [dedupDependencies, hx, ih]
        intro hd
        exact fun hdx => False.elim (hd (hdx ▸ hx))
      · by_cases hd : d = x
        · subst d; simp [dedupDependencies, hx, ih]
        · simp [dedupDependencies, hx, ih, hd]

theorem T12_merge_preserves_dependencies (a b : List Dependency) (d : Dependency) :
    d ∈ mergeDependencies a b ↔ d ∈ a ∨ d ∈ b := by
  simp [mergeDependencies, mem_dedupDependencies]

end Kctx
