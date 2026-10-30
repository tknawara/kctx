import Kctx.Codec
import Kctx.Semantics
import Kctx.Workflow

set_option autoImplicit false
set_option maxHeartbeats 1000000

/-! Theorem registry: T01–T22 (see docs/kctx/handover.md §5.1).
`formal/theorems.json` maps IDs to these names. No theorem mentions a
concrete production corpus. -/

open Lean

namespace Kctx

/-! ## Equality helpers for the decide-based BEq instances. -/

theorem ident_eq_of_beq {k : IdKind} : ∀ {a b : Ident k}, (a == b) = true → a = b := by
  intro a b h
  cases a <;> cases b <;> simp_all

theorem scope_beq_true {s t : Scope} (h : (s == t) = true) : s = t := by
  cases s <;> cases t <;> simp_all

theorem claimProp_eq_of_beq : ∀ {a b : ClaimProp}, (a == b) = true → a = b := by
  intro a b h
  cases a <;> cases b <;> simp_all

theorem claimRef_eq_of_beq : ∀ {a b : ClaimRef}, (a == b) = true → a = b := by
  intro a b h
  cases a <;> cases b <;> simp_all

theorem supportRole_eq_of_beq : ∀ {a b : SupportRole}, (a == b) = true → a = b := by
  intro a b h
  cases a <;> cases b <;> simp_all

theorem obsOutcome_eq_of_beq : ∀ {a b : ObsOutcome}, (a == b) = true → a = b := by
  intro a b h
  cases a <;> cases b <;> simp_all

theorem opt_scope_beq {s : Scope} {o : Option Scope} (h : (o == some s) = true) :
    o = some s := by
  cases o with
  | none => simp at h
  | some s' => rw [scope_beq_true h]

theorem asAtom_isSome {p : ClaimProp} (h : p.asAtom.isSome = true) :
    ∃ a : Atom, p = .atom a := by
  cases p with
  | atom a => exact ⟨a, rfl⟩
  | conj ps => simp [ClaimProp.asAtom] at h
  | allChecked pred ms => simp [ClaimProp.asAtom] at h

theorem not_notB_eq {b : Bool} (h : ¬((!b) = true)) : b = true := by
  cases b with
  | true => rfl
  | false => exact absurd rfl h

theorem not_neqB_eq {α : Type} [BEq α] {a b : α}
    (h : ¬((!(a == b)) = true)) : (a == b) = true := by
  cases hb : (a == b) with
  | true => rfl
  | false => rw [hb] at h; exact absurd rfl h

theorem option_isNone_false {α : Type} {o : Option α} (h : o.isNone = false) :
    ∃ x, o = some x := by
  cases o with
  | none => simp at h
  | some x => exact ⟨x, rfl⟩

/-! ## Shared inversions. -/

theorem conclusionMatches_inv {v : KbView} {d : Derivation}
    (hnone : (v.findClaim d.conclusion).isNone = false)
    (hm : conclusionMatches v d = true) :
    ∃ c : Claim, v.findClaim d.conclusion = some c ∧ c.prop = d.conclusionProp := by
  obtain ⟨c, hc⟩ := option_isNone_false hnone
  simp only [conclusionMatches, hc] at hm
  exact ⟨c, hc, claimProp_eq_of_beq hm⟩

theorem any_supports_binding_inv {v : KbView} {i : ObservationId} {r : ClaimRef}
    (h : v.bindings.contains (Binding.mk i r .supports) = true) :
    Binding.mk i r .supports ∈ v.bindings := List.contains_iff_mem.mp h

theorem findObs_id {v : KbView} {i : ObservationId} {o : Observation}
    (h : v.findObs i = some o) : o.id = i := by
  have h1 : List.find? (fun x : Observation => x.id == i) v.observations = some o := h
  have h2 := List.find?_some h1
  exact ident_eq_of_beq h2

/-! ## T01: decoding success admits only well-formed values. -/

theorem T01_observation (j : Json) (o : Observation)
    (h : decObservation j = pure o) : recordWfObservation o = true := by
  simp only [decObservation] at h
  split at h
  · next x _ =>
    split at h
    · next hwf =>
      have hoi : x = o := Except.ok.inj h
      subst hoi
      exact hwf
    · exact absurd h (by intro hh; cases hh)
  · next e _ =>
    exact absurd h (by intro hh; cases hh)

theorem T01_claim (j : Json) (c : Claim)
    (h : decClaim j = pure c) : recordWfClaim c = true := by
  simp only [decClaim] at h
  split at h
  · next x _ =>
    split at h
    · next hwf =>
      have hoi : x = c := Except.ok.inj h
      subst hoi
      exact hwf
    · exact absurd h (by intro hh; cases hh)
  · next e _ =>
    exact absurd h (by intro hh; cases hh)

theorem T01_binding (j : Json) (b : Binding)
    (h : decBinding j = pure b) : recordWfBinding b = true := by
  simp only [decBinding] at h
  split at h
  · next x _ =>
    split at h
    · next hwf =>
      have hoi : x = b := Except.ok.inj h
      subst hoi
      exact hwf
    · exact absurd h (by intro hh; cases hh)
  · next e _ =>
    exact absurd h (by intro hh; cases hh)

theorem T01_correction (j : Json) (c : Correction)
    (h : decCorrection j = pure c) : recordWfCorrection c = true := by
  simp only [decCorrection] at h
  split at h
  · next x _ =>
    split at h
    · next hwf =>
      have hoi : x = c := Except.ok.inj h
      subst hoi
      exact hwf
    · exact absurd h (by intro hh; cases hh)
  · next e _ =>
    exact absurd h (by intro hh; cases hh)

theorem T01_derivation (j : Json) (d : Derivation)
    (h : decDerivation j = pure d) : recordWfDerivation d = true := by
  simp only [decDerivation] at h
  split at h
  · next x _ =>
    split at h
    · next hwf =>
      have hoi : x = d := Except.ok.inj h
      subst hoi
      exact hwf
    · exact absurd h (by intro hh; cases hh)
  · next e _ =>
    exact absurd h (by intro hh; cases hh)

/-! ## T02: encode/decode round-trips on well-formed protocol values. -/

theorem T02_observation (o : Observation) (h : recordWfObservation o = true) :
    decObservation (encObservation o) = pure o := decObservation_encObservation o h

theorem T02_claim (c : Claim) (h : recordWfClaim c = true) :
    decClaim (encClaim c) = pure c := decClaim_encClaim c h

theorem T02_binding (b : Binding) (h : recordWfBinding b = true) :
    decBinding (encBinding b) = pure b := decBinding_encBinding b h

theorem T02_correction (c : Correction) (h : recordWfCorrection c = true) :
    decCorrection (encCorrection c) = pure c := decCorrection_encCorrection c h

theorem T02_derivation (d : Derivation) (h : recordWfDerivation d = true) :
    decDerivation (encDerivation d) = pure d := decDerivation_encDerivation d h

theorem T02_evalCtx (c : EvalCtx) : decEvalCtx (encEvalCtx c) = pure c :=
  decEvalCtx_encEvalCtx c

/-! ## T03: committed operations preserve well-formedness. -/

theorem T03_commit_wf (kb : KB) (journal : List JournalEntry) (op : Op)
    (h : (commitOp kb journal op).2 = CommitOutcome.committed) :
    ((commitOp kb journal op).1).wellFormed = true := by
  unfold commitOp at h
  split at h
  · next e he =>
    split at h <;> exact absurd h (by intro hh; cases hh)
  · next he =>
    split at h
    · exact absurd h (by intro hh; cases hh)
    · next hne =>
      split at h
      · next hwf =>
        simp only [commitOp, he, if_neg hne, if_pos hwf]
        exact hwf
      · exact absurd h (by intro hh; cases hh)

/-! ## Premise truth supplied to T04 (never checked by the checker). -/

def PremisesHold (ip : Interp) (v : KbView) (d : Derivation) : Prop :=
  match d.rule with
  | .andIntro =>
    ∀ r ∈ d.premiseGroups.flatMap (fun g => g),
      match (v.propOf r).asAtom with
      | some a => ip.holds (.atom a) d.scope
      | none => True
  | .specialize =>
    ∀ r ∈ d.premiseGroups.flatMap (fun g => g),
      ∀ s, v.scopeOf r = some s → ip.holds (v.propOf r) s
  | .obsSupports => True
  | .allChecked =>
    ∀ m ∈ (match d.witness with
      | some w => w.members
      | none => []),
      match d.conclusionProp with
      | .allChecked pred _ => ip.holds (memberProp pred m) d.scope
      | _ => True

/-! ## T04: checker acceptance (+ supplied premises) implies derivability. -/

theorem T04_andIntro {ip : Interp} {v : KbView} {ctx : EvalCtx} {d : Derivation}
    (hr : d.rule = RuleId.andIntro)
    (h : checkAndIntro v d = Verdict.accepted)
    (hprem : PremisesHold ip v d) : Derives ip v ctx d := by
  unfold PremisesHold at hprem
  simp only [hr] at hprem
  unfold checkAndIntro at h
  split at h
  · next xg g heq =>
    by_cases c1 : g.isEmpty
    · rw [if_pos c1] at h; exact absurd h (by intro hh; cases hh)
    · rw [if_neg c1] at h
      by_cases c2 : (!g.all (fun r => (v.propOf r).asAtom.isSome))
      · rw [if_pos c2] at h; exact absurd h (by intro hh; cases hh)
      · rw [if_neg c2] at h
        by_cases c3 : (!g.all (fun r => v.scopeOf r == some d.scope))
        · rw [if_pos c3] at h; exact absurd h (by intro hh; cases hh)
        · rw [if_neg c3] at h
          by_cases c4 : (d.conclusionProp != .conj (andIntroAtoms v g))
          · rw [if_pos c4] at h; exact absurd h (by intro hh; cases hh)
          · rw [if_neg c4] at h
            by_cases c5 : (!footprintDeclares v d)
            · rw [if_pos c5] at h; exact absurd h (by intro hh; cases hh)
            · rw [if_neg c5] at h
              have hne : 0 < g.length := by
                cases g with
                | nil => simp at c1
                | cons x xs => simp
              have hall2 : (g.all (fun r => (v.propOf r).asAtom.isSome)) = true := not_notB_eq c2
              have hall3 : (g.all (fun r => v.scopeOf r == some d.scope)) = true := not_notB_eq c3
              have hatoms : ∀ r ∈ g, ∃ a : Atom, v.propOf r = .atom a := by
                intro r hrg
                exact asAtom_isSome ((List.all_eq_true.mp hall2) r hrg)
              have hscope : ∀ r ∈ g, v.scopeOf r = some d.scope := by
                intro r hrg
                exact opt_scope_beq ((List.all_eq_true.mp hall3) r hrg)
              have hconj : d.conclusionProp = .conj (andIntroAtoms v g) :=
                claimProp_eq_of_beq (not_neqB_eq c4)
              refine Derives.andIntro d g hr heq hatoms hconj hscope hne ?_
              intro a ha
              simp only [andIntroAtoms, List.mem_map] at ha
              obtain ⟨r, hrg, haeq⟩ := ha
              obtain ⟨a', hra'⟩ := hatoms r hrg
              have hs : ip.holds (.atom a') d.scope := by
                have hp := hprem r (by simp [heq, hrg])
                rw [hra'] at hp
                simpa using hp
              have hget : ((v.propOf r).asAtom).getD default = a' := by
                rw [hra']; rfl
              rw [← haeq, hget]
              exact hs
  · exact absurd h (by intro hh; cases hh)

theorem T04_specialize {ip : Interp} {v : KbView} {ctx : EvalCtx} {d : Derivation}
    (hr : d.rule = RuleId.specialize)
    (h : checkSpecialize v d = Verdict.accepted)
    (hprem : PremisesHold ip v d)
    (hconc : (v.findClaim d.conclusion).isNone = false)
    (hmatch : conclusionMatches v d = true) : Derives ip v ctx d := by
  unfold PremisesHold at hprem
  simp only [hr] at hprem
  unfold checkSpecialize at h
  split at h
  · next xr r heq =>
    cases hsrc : v.findClaim r with
    | none => rw [hsrc] at h; exact absurd h (by intro hh; cases hh)
    | some src =>
      cases htar : v.findClaim d.conclusion with
      | none => rw [hsrc, htar] at h; exact absurd h (by intro hh; cases hh)
      | some tgt =>
        simp only [hsrc, htar] at h
        by_cases c1 : (src.prop != tgt.prop)
        · rw [if_pos c1] at h; exact absurd h (by intro hh; cases hh)
        · rw [if_neg c1] at h
          by_cases c2 : (!tgt.scope.specializes src.scope)
          · rw [if_pos c2] at h; exact absurd h (by intro hh; cases hh)
          · rw [if_neg c2] at h
            by_cases c3 : (d.scope != tgt.scope)
            · rw [if_pos c3] at h; exact absurd h (by intro hh; cases hh)
            · rw [if_neg c3] at h
              by_cases c4 : (!footprintDeclares v d)
              · rw [if_pos c4] at h; exact absurd h (by intro hh; cases hh)
              · rw [if_neg c4] at h
                have hps : src.prop = tgt.prop := claimProp_eq_of_beq (not_neqB_eq c1)
                have hsp : tgt.scope.specializes src.scope = true := by simpa using c2
                have hsc : d.scope = tgt.scope := scope_beq_true (not_neqB_eq c3)
                have hp : ip.holds src.prop src.scope := by
                  have hso : v.scopeOf r = some src.scope := by
                    unfold KbView.scopeOf
                    rw [hsrc]
                    rfl
                  have hpo : v.propOf r = src.prop := by
                    unfold KbView.propOf
                    rw [hsrc]
                  have hmem : r ∈ d.premiseGroups.flatMap (fun g => g) := by
                    rw [heq]
                    exact List.Mem.head _
                  have hp0 := hprem r hmem src.scope hso
                  rw [hpo] at hp0
                  exact hp0
                have hc0 : v.findClaim d.conclusion = some tgt := htar
                have hcp0 : d.conclusionProp = tgt.prop := by
                  obtain ⟨c', hcf, hcp⟩ := conclusionMatches_inv hconc hmatch
                  have hct : c' = tgt := Option.some.inj (hcf.symm.trans hc0)
                  subst hct
                  exact hcp.symm
                exact Derives.specialize d r src tgt hr heq hsrc htar
                  ⟨hcp0, hps.symm⟩ ⟨hsp, hsc⟩ hp
  · exact absurd h (by intro hh; cases hh)

end Kctx
