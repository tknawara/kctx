import Kctx.Theorems

set_option autoImplicit false
set_option maxHeartbeats 1000000

/-! Theorem registry, part 2: obsSupports/allChecked inversions, the main
T04 theorem, T05–T22, and non-vacuity examples. -/

namespace Kctx

/-! ## T04 (continued). -/

theorem not_isNone_eq {a : Type} {o : Option a}
    (h : Not (o.isNone = true)) : o.isNone = false := by
  cases ho : o <;> rw [ho] at h <;> simp_all

theorem verdict_eq_of_beq : ∀ {a b : Verdict}, (a == b) = true → a = b := by
  intro a b h
  cases a <;> cases b <;> simp_all

theorem not_any_true_eq {a : Type} {l : List a} {p : a -> Bool}
    (h : Not (l.any p = true)) : l.any p = false := by
  cases hb : l.any p with
  | true => exact absurd hb h
  | false => rfl

theorem isNone_false_of_not {a : Type} {o : Option a}
    (h : !(o.isNone) = true) : o.isSome = true := by
  cases ho : o <;> rw [ho] at h <;> simp_all

theorem T04_obsSupports {ip : Interp} {v : KbView} {ctx : EvalCtx} {d : Derivation}
    (hr : d.rule = RuleId.obsSupports)
    (h : checkObsSupports v ctx d = Verdict.accepted)
    (hconc : (v.findClaim d.conclusion).isNone = false)
    (hmatch : conclusionMatches v d = true) : Derives ip v ctx d := by
  obtain ⟨c, hcf, hcp⟩ := conclusionMatches_inv hconc hmatch
  unfold checkObsSupports at h
  by_cases c0 : (!d.premiseGroups.isEmpty)
  · rw [if_pos c0] at h; exact absurd h (by intro hh; cases hh)
  · rw [if_neg c0] at h
    have hempty : d.premiseGroups = [] := by
      cases hpg : d.premiseGroups with
      | nil => rfl
      | cons x xs => rw [hpg] at c0; simp at c0
    cases hEv : d.evidence with
    | none => rw [hEv] at h; exact absurd h (by intro hh; cases hh)
    | some i =>
      simp only [hEv] at h
      cases hObs : v.findObs i with
      | none => simp only [hObs] at h; exact absurd h (by intro hh; cases hh)
      | some o =>
        simp only [hObs] at h
        by_cases c1 : (!(v.scopeOf d.conclusion == some d.scope))
        · rw [if_pos c1] at h; exact absurd h (by intro hh; cases hh)
        · rw [if_neg c1] at h
          by_cases c2 : d.conclusionProp.asAtom.isNone
          · rw [if_pos c2] at h; exact absurd h (by intro hh; cases hh)
          · rw [if_neg c2] at h
            by_cases c3 : (o.outcome != ObsOutcome.ok)
            · rw [if_pos c3] at h; exact absurd h (by intro hh; cases hh)
            · rw [if_neg c3] at h
              by_cases c4 : (!v.bindings.contains (Binding.mk i d.conclusion .supports))
              · rw [if_pos c4] at h; exact absurd h (by intro hh; cases hh)
              · rw [if_neg c4] at h
                by_cases c5 : (assessFresh o.ttl o.observedAt ctx.now != Fresh.fresh)
                · rw [if_pos c5] at h; exact absurd h (by intro hh; cases hh)
                · rw [if_neg c5] at h
                  by_cases c6 : (!footprintDeclares v d)
                  · rw [if_pos c6] at h; exact absurd h (by intro hh; cases hh)
                  · rw [if_neg c6] at h
                    have hscope : d.scope = c.scope := by
                      have hs0 : (v.scopeOf d.conclusion == some d.scope) = true :=
                        not_notB_eq c1
                      have hso := opt_scope_beq hs0
                      unfold KbView.scopeOf at hso
                      rw [hcf] at hso
                      simp only [Option.map_some, Option.some.injEq] at hso
                      exact hso.symm
                    have h2 : d.conclusionProp.asAtom.isSome = true :=
                      isNone_false_of_not (by simpa using c2)
                    have hatom : ∃ a : Atom, c.prop = .atom a := by
                      obtain ⟨a, ha⟩ := asAtom_isSome h2
                      exact ⟨a, by rw [hcp, ha]⟩
                    have hok : o.outcome = .ok := obsOutcome_eq_of_beq (not_neqB_eq c3)
                    have hbind : Binding.mk i d.conclusion .supports ∈ v.bindings :=
                      any_supports_binding_inv (not_notB_eq c4)
                    have hfresh : FreshAt o.ttl o.observedAt ctx.now :=
                      assessFresh_fresh_iff.mp (by
                        have hbeq : (assessFresh o.ttl o.observedAt ctx.now
                            == Fresh.fresh) = true := not_neqB_eq c5
                        cases ha : assessFresh o.ttl o.observedAt ctx.now <;>
                          rw [ha] at hbeq <;> simp_all)
                    have hoid : o.id = i := findObs_id hObs
                    rw [← hoid] at hObs
                    rw [← hoid] at hbind
                    exact Derives.obsSupports d o c hr hempty
                      (by simp [hEv, hoid]) hObs hcf
                      ⟨hcp.symm, hscope⟩ hatom hok hbind hfresh

theorem T04_allChecked {ip : Interp} {v : KbView} {ctx : EvalCtx} {d : Derivation}
    (hr : d.rule = RuleId.allChecked)
    (h : checkAllChecked v d = Verdict.accepted)
    (hprem : PremisesHold ip v d) : Derives ip v ctx d := by
  unfold PremisesHold at hprem
  simp only [hr] at hprem
  unfold checkAllChecked at h
  by_cases c0 : (!d.premiseGroups.isEmpty)
  · rw [if_pos c0] at h; exact absurd h (by intro hh; cases hh)
  · rw [if_neg c0] at h
    have hempty : d.premiseGroups = [] := by
      cases hpg : d.premiseGroups with
      | nil => rfl
      | cons x xs => rw [hpg] at c0; simp at c0
    cases hW : d.witness with
    | none => rw [hW] at h; exact absurd h (by intro hh; cases hh)
    | some w =>
      simp only [hW] at h
      by_cases c1 : (!w.complete)
      · rw [if_pos c1] at h; exact absurd h (by intro hh; cases hh)
      · rw [if_neg c1] at h
        by_cases c2 : w.members.isEmpty
        · rw [if_pos c2] at h; exact absurd h (by intro hh; cases hh)
        · rw [if_neg c2] at h
          cases hP : d.conclusionProp with
          | atom a => simp only [hP] at h; exact absurd h (by intro hh; cases hh)
          | conj ps => simp only [hP] at h; exact absurd h (by intro hh; cases hh)
          | allChecked pred ms =>
            simp only [hP] at h
            by_cases c3 : (ms != w.members)
            · rw [if_pos c3] at h; exact absurd h (by intro hh; cases hh)
            · rw [if_neg c3] at h
              by_cases c4 : (w.scope != d.scope)
              · rw [if_pos c4] at h; exact absurd h (by intro hh; cases hh)
              · rw [if_neg c4] at h
                by_cases c5 : (!footprintDeclares v d)
                · rw [if_pos c5] at h; exact absurd h (by intro hh; cases hh)
                · rw [if_neg c5] at h
                  have hcomp : w.complete = true := not_notB_eq c1
                  have hne : w.members ≠ [] := by
                    intro hcon
                    rw [hcon] at c2
                    simp at c2
                  have hms : ms = w.members := by simpa using (not_neqB_eq c3)
                  have hscope : w.scope = d.scope := scope_beq_true (not_neqB_eq c4)
                  refine Derives.allChecked d w pred hr hempty hW hcomp hne ?_ hscope ?_
                  · rw [hP, hms]
                  · intro m hm
                    have hmp : m ∈ (match d.witness with
                      | some w2 => w2.members
                      | none => []) := by rw [hW]; exact hm
                    have hp := hprem m hmp
                    simp only [hP] at hp
                    exact hp

/-- T04: checker acceptance implies the declarative derivability judgment
(premise truth supplied per rule, never checked). -/

theorem T04_checker_sound {ip : Interp} {v : KbView} {ctx : EvalCtx} {d : Derivation}
    (h : checkDerivationV v ctx d = Verdict.accepted)
    (hprem : PremisesHold ip v d) : Derives ip v ctx d := by
  unfold checkDerivationV at h
  by_cases g0 : (!enabledRules.contains d.rule)
  · rw [if_pos g0] at h; exact absurd h (by intro hh; cases hh)
  · rw [if_neg g0] at h
    by_cases g1 : (!premisesResolve v d)
    · rw [if_pos g1] at h; exact absurd h (by intro hh; cases hh)
    · rw [if_neg g1] at h
      by_cases g2 : (v.findClaim d.conclusion).isNone
      · rw [if_pos g2] at h; exact absurd h (by intro hh; cases hh)
      · rw [if_neg g2] at h
        by_cases g3 : (!conclusionMatches v d)
        · rw [if_pos g3] at h; exact absurd h (by intro hh; cases hh)
        · rw [if_neg g3] at h
          by_cases g4 : v.corrections.any (fun k => k.target == d.conclusion)
          · rw [if_pos g4] at h; exact absurd h (by intro hh; cases hh)
          · rw [if_neg g4] at h
            by_cases g5 : v.corrections.any
                (fun k => d.premiseGroups.any (fun g => g.contains k.target))
            · rw [if_pos g5] at h; exact absurd h (by intro hh; cases hh)
            · rw [if_neg g5] at h
              cases hr : d.rule with
              | andIntro =>
                rw [show d.rule = RuleId.andIntro from hr] at h
                exact T04_andIntro hr h hprem
              | specialize =>
                rw [show d.rule = RuleId.specialize from hr] at h
                exact T04_specialize hr h hprem (not_isNone_eq (by simpa using g2)) (not_notB_eq g3)
              | obsSupports =>
                rw [show d.rule = RuleId.obsSupports from hr] at h
                exact T04_obsSupports hr h (not_isNone_eq (by simpa using g2)) (not_notB_eq g3)
              | allChecked =>
                rw [show d.rule = RuleId.allChecked from hr] at h
                exact T04_allChecked hr h hprem

/-! ## T05: every enabled rule preserves its declared proposition semantics. -/

theorem T05_derives_sound {ip : Interp} {v : KbView} {ctx : EvalCtx} {d : Derivation}
    (h : Derives ip v ctx d) : ip.holds d.conclusionProp d.scope := by
  induction h with
  | andIntro g hr hg hatoms hconj hscope hne hprem =>
    rw [hconj]
    refine ip.conj_intro _ _ ?_
    intro a ha
    have hmem : a ∈ andIntroAtoms v g := ha
    simp only [andIntroAtoms, List.mem_map] at hmem
    obtain ⟨r, hrg, haeq⟩ := hmem
    obtain ⟨a', hra'⟩ := hatoms r hrg
    have hget : ((v.propOf r).asAtom).getD default = a' := by
      rw [hra']; rfl
    exact hprem a ha
  | specialize r src tgt hr hg hsrc htgt hprop hspec hp =>
    obtain ⟨hprop1, hprop2⟩ := hprop
    obtain ⟨hspec1, hspec2⟩ := hspec
    rw [hprop1, hprop2, hspec2]
    exact ip.spec_weaken src.prop src.scope tgt.scope hspec1 hp
  | obsSupports o c hr hg hev ho hc hcp hatom hok hbind hfresh =>
    obtain ⟨hcp1, hcp2⟩ := hcp
    rw [hcp1, hcp2]
    exact ip.evidence_veridical o c hok
  | allChecked w pred hr hg hw hcomp hne hprop hscope hprem =>
    rw [hprop]
    exact ip.allc_intro pred w.members d.scope hprem

/-! ## T06/T08: footprint reuse. -/

theorem T06_reusable_iff {v : KbView} {ctx : EvalCtx} {d : Derivation}
    {observed : List Dep} :
    Reusable v ctx d observed = true ↔
      (checkDerivationV v ctx d = Verdict.accepted
        ∧ ∀ dep ∈ d.footprint, (observed.contains dep) = true) := by
  simp [Reusable, depsSatisfied, Bool.and_eq_true, List.all_eq_true]

theorem T08_missing_dep_not_reusable {v : KbView} {ctx : EvalCtx} {d : Derivation}
    {observed : List Dep} {dep : Dep}
    (hreq : dep ∈ d.footprint) (hmiss : (observed.contains dep) = false) :
    Reusable v ctx d observed = false := by
  unfold Reusable
  have h1 : depsSatisfied observed d.footprint = false := by
    refine List.all_eq_false.mpr ?_
    refine ⟨dep, hreq, ?_⟩
    rw [hmiss]
    simp
  cases hc : checkDerivationV v ctx d == Verdict.accepted with
  | true => simp [h1]
  | false => simp [hc]

/-! ## T09/T10: support and alternatives. -/

theorem T09_alternative_survives {v : KbView} {ctx : EvalCtx} {r : ClaimRef}
    {d2 : Derivation} (hmem : d2 ∈ v.derivations) (hcon : d2.conclusion = r)
    (hacc : checkDerivationV v ctx d2 = Verdict.accepted) :
    Supported v ctx r = true :=
  List.any_eq_true.mpr ⟨d2, hmem, by simp [hcon, hacc]⟩

theorem T10_all_support_removed {v : KbView} {ctx : EvalCtx} {r : ClaimRef}
    (h : ∀ d ∈ v.derivations, d.conclusion = r →
      checkDerivationV v ctx d ≠ Verdict.accepted) :
    Supported v ctx r = false := by
  unfold Supported
  refine List.any_eq_false.mpr ?_
  intro d hd
  by_cases hbeq : (d.conclusion == r) = true
  · intro hp
    simp only [Bool.and_eq_true] at hp
    obtain ⟨hbeq2, hacc2⟩ := hp
    exact h d hd (claimRef_eq_of_beq hbeq2) (verdict_eq_of_beq hacc2)
  · simp [hbeq]

/-! ## T12: composition cannot widen scope, renew evidence age, or drop deps. -/

theorem T12_copy_keeps_freshness (o : Observation) (copyId : String) (now : Int) :
    assessFresh o.ttl o.observedAt now
      = assessFresh { o with id := ⟨copyId⟩ }.ttl
          { o with id := ⟨copyId⟩ }.observedAt now := rfl

theorem T12_andIntro_footprint {v : KbView} {d : Derivation}
    (h : checkAndIntro v d = Verdict.accepted) : footprintDeclares v d = true := by
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
          by_cases c4 : (d.conclusionProp != ClaimProp.conj (andIntroAtoms v g))
          · rw [if_pos c4] at h; exact absurd h (by intro hh; cases hh)
          · rw [if_neg c4] at h
            by_cases c5 : (!footprintDeclares v d)
            · rw [if_pos c5] at h; exact absurd h (by intro hh; cases hh)
            · exact not_notB_eq c5
  · exact absurd h (by intro hh; cases hh)

theorem T12_specialize_footprint {v : KbView} {d : Derivation}
    (h : checkSpecialize v d = Verdict.accepted) : footprintDeclares v d = true := by
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
              · exact not_notB_eq c4
  · exact absurd h (by intro hh; cases hh)

theorem T12_obsSupports_footprint {v : KbView} {ctx : EvalCtx} {d : Derivation}
    (h : checkObsSupports v ctx d = Verdict.accepted) : footprintDeclares v d = true := by
  unfold checkObsSupports at h
  by_cases c0 : (!d.premiseGroups.isEmpty)
  · rw [if_pos c0] at h; exact absurd h (by intro hh; cases hh)
  · rw [if_neg c0] at h
    have hempty : d.premiseGroups = [] := by
      cases hpg : d.premiseGroups with
      | nil => rfl
      | cons x xs => rw [hpg] at c0; simp at c0
    cases hEv : d.evidence with
    | none => rw [hEv] at h; exact absurd h (by intro hh; cases hh)
    | some i =>
      simp only [hEv] at h
      cases hObs : v.findObs i with
      | none => rw [hObs] at h; exact absurd h (by intro hh; cases hh)
      | some o =>
        simp only [hObs] at h
        by_cases c1 : (!(v.scopeOf d.conclusion == some d.scope))
        · rw [if_pos c1] at h; exact absurd h (by intro hh; cases hh)
        · rw [if_neg c1] at h
          by_cases c2 : d.conclusionProp.asAtom.isNone
          · rw [if_pos c2] at h; exact absurd h (by intro hh; cases hh)
          · rw [if_neg c2] at h
            by_cases c3 : (o.outcome != ObsOutcome.ok)
            · rw [if_pos c3] at h; exact absurd h (by intro hh; cases hh)
            · rw [if_neg c3] at h
              by_cases c4 : (!v.bindings.contains (Binding.mk i d.conclusion SupportRole.supports))
              · rw [if_pos c4] at h; exact absurd h (by intro hh; cases hh)
              · rw [if_neg c4] at h
                by_cases c5 : (assessFresh o.ttl o.observedAt ctx.now != Fresh.fresh)
                · rw [if_pos c5] at h; exact absurd h (by intro hh; cases hh)
                · rw [if_neg c5] at h
                  by_cases c6 : (!footprintDeclares v d)
                  · rw [if_pos c6] at h; exact absurd h (by intro hh; cases hh)
                  · exact not_notB_eq c6

theorem T12_allChecked_footprint {v : KbView} {d : Derivation}
    (h : checkAllChecked v d = Verdict.accepted) : footprintDeclares v d = true := by
  unfold checkAllChecked at h
  by_cases c0 : (!d.premiseGroups.isEmpty)
  · rw [if_pos c0] at h; exact absurd h (by intro hh; cases hh)
  · rw [if_neg c0] at h
    have hempty : d.premiseGroups = [] := by
      cases hpg : d.premiseGroups with
      | nil => rfl
      | cons x xs => rw [hpg] at c0; simp at c0
    cases hW : d.witness with
    | none => rw [hW] at h; exact absurd h (by intro hh; cases hh)
    | some w =>
      simp only [hW] at h
      by_cases c1 : (!w.complete)
      · rw [if_pos c1] at h; exact absurd h (by intro hh; cases hh)
      · rw [if_neg c1] at h
        by_cases c2 : w.members.isEmpty
        · rw [if_pos c2] at h; exact absurd h (by intro hh; cases hh)
        · rw [if_neg c2] at h
          cases hP : d.conclusionProp with
          | atom a => rw [hP] at h; exact absurd h (by intro hh; cases hh)
          | conj ps => rw [hP] at h; exact absurd h (by intro hh; cases hh)
          | allChecked pred ms =>
            simp only [hP] at h
            by_cases c3 : (ms != w.members)
            · rw [if_pos c3] at h; exact absurd h (by intro hh; cases hh)
            · rw [if_neg c3] at h
              by_cases c4 : (w.scope != d.scope)
              · rw [if_pos c4] at h; exact absurd h (by intro hh; cases hh)
              · rw [if_neg c4] at h
                by_cases c5 : (!footprintDeclares v d)
                · rw [if_pos c5] at h; exact absurd h (by intro hh; cases hh)
                · exact not_notB_eq c5

theorem T12_footprint_declared {v : KbView} {ctx : EvalCtx} {d : Derivation}
    (h : checkDerivationV v ctx d = Verdict.accepted) :
    footprintDeclares v d = true := by
  unfold checkDerivationV at h
  by_cases g0 : (!enabledRules.contains d.rule)
  · rw [if_pos g0] at h; exact absurd h (by intro hh; cases hh)
  · rw [if_neg g0] at h
    by_cases g1 : (!premisesResolve v d)
    · rw [if_pos g1] at h; exact absurd h (by intro hh; cases hh)
    · rw [if_neg g1] at h
      by_cases g2 : (v.findClaim d.conclusion).isNone
      · rw [if_pos g2] at h; exact absurd h (by intro hh; cases hh)
      · rw [if_neg g2] at h
        by_cases g3 : (!conclusionMatches v d)
        · rw [if_pos g3] at h; exact absurd h (by intro hh; cases hh)
        · rw [if_neg g3] at h
          by_cases g4 : v.corrections.any (fun k => k.target == d.conclusion)
          · rw [if_pos g4] at h; exact absurd h (by intro hh; cases hh)
          · rw [if_neg g4] at h
            by_cases g5 : v.corrections.any
                (fun k => d.premiseGroups.any (fun g => g.contains k.target))
            · rw [if_pos g5] at h; exact absurd h (by intro hh; cases hh)
            · rw [if_neg g5] at h
              cases hr : d.rule with
              | andIntro =>
                rw [show d.rule = RuleId.andIntro from hr] at h
                exact T12_andIntro_footprint h
              | specialize =>
                rw [show d.rule = RuleId.specialize from hr] at h
                exact T12_specialize_footprint h
              | obsSupports =>
                rw [show d.rule = RuleId.obsSupports from hr] at h
                exact T12_obsSupports_footprint h
              | allChecked =>
                rw [show d.rule = RuleId.allChecked from hr] at h
                exact T12_allChecked_footprint h


/-! Per-rule footprint guards (last check in each checker). -/

/-! ## T13: no coverage witness, no universal. -/

theorem T13_witness_required {v : KbView} {ctx : EvalCtx} {d : Derivation}
    (h : checkDerivationV v ctx d = Verdict.accepted)
    (hrule : d.rule = RuleId.allChecked) :
    ∃ w : CoverageWitness, d.witness = some w ∧ w.complete = true ∧ w.members ≠ [] := by
  unfold checkDerivationV at h
  simp only [hrule] at h
  by_cases g0 : (!enabledRules.contains RuleId.allChecked)
  · rw [if_pos g0] at h; exact absurd h (by intro hh; cases hh)
  · rw [if_neg g0] at h
    by_cases g1 : (!premisesResolve v d)
    · rw [if_pos g1] at h; exact absurd h (by intro hh; cases hh)
    · rw [if_neg g1] at h
      by_cases g2 : (v.findClaim d.conclusion).isNone
      · rw [if_pos g2] at h; exact absurd h (by intro hh; cases hh)
      · rw [if_neg g2] at h
        by_cases g3 : (!conclusionMatches v d)
        · rw [if_pos g3] at h; exact absurd h (by intro hh; cases hh)
        · rw [if_neg g3] at h
          by_cases g4 : v.corrections.any (fun k => k.target == d.conclusion)
          · rw [if_pos g4] at h; exact absurd h (by intro hh; cases hh)
          · rw [if_neg g4] at h
            by_cases g5 : v.corrections.any
                (fun k => d.premiseGroups.any (fun g => g.contains k.target))
            · rw [if_pos g5] at h; exact absurd h (by intro hh; cases hh)
            · rw [if_neg g5] at h
              unfold checkAllChecked at h
              by_cases c0 : (!d.premiseGroups.isEmpty)
              · rw [if_pos c0] at h; exact absurd h (by intro hh; cases hh)
              · rw [if_neg c0] at h
                have hempty : d.premiseGroups = [] := by
                  cases hpg : d.premiseGroups with
                  | nil => rfl
                  | cons x xs => rw [hpg] at c0; simp at c0
                cases hW : d.witness with
                | none => rw [hW] at h; exact absurd h (by intro hh; cases hh)
                | some w =>
                  simp only [hW] at h
                  by_cases c1 : (!w.complete)
                  · rw [if_pos c1] at h; exact absurd h (by intro hh; cases hh)
                  · rw [if_neg c1] at h
                    by_cases c2 : w.members.isEmpty
                    · rw [if_pos c2] at h; exact absurd h (by intro hh; cases hh)
                    · rw [if_neg c2] at h
                      refine Exists.intro w ⟨rfl, not_notB_eq c1, ?_⟩
                      intro hcon
                      rw [hcon] at c2
                      simp at c2

/-! ## T14: nothing derives outside the enabled registry. -/

theorem T14_derives_only_enabled {ip : Interp} {v : KbView} {ctx : EvalCtx}
    {d : Derivation} (h : Derives ip v ctx d) :
    d.rule ∈ enabledRules := by
  cases h <;> simp_all [enabledRules]

/-! ## T16: corrections never confer support. -/

def addCorrectionV (v : KbView) (c : Correction) : KbView :=
  { v with corrections := v.corrections ++ [c] }

/-- Acceptance survives correction removal: the checker consults corrections
only through negative guards, and the per-rule checkers never consult them. -/

theorem checkDerivationV_drop_correction {v : KbView} {ctx : EvalCtx} {d : Derivation}
    {c : Correction}
    (h : checkDerivationV (addCorrectionV v c) ctx d = Verdict.accepted) :
    checkDerivationV v ctx d = Verdict.accepted := by
  unfold checkDerivationV at h
  unfold checkDerivationV at ⊢
  have hp : premisesResolve (addCorrectionV v c) d = premisesResolve v d := rfl
  have hc2 : (addCorrectionV v c).findClaim d.conclusion = v.findClaim d.conclusion := rfl
  have hc3 : conclusionMatches (addCorrectionV v c) d = conclusionMatches v d := rfl
  rw [hp, hc2, hc3] at h
  by_cases g0 : (!enabledRules.contains d.rule)
  · rw [if_pos g0] at h; exact absurd h (by intro hh; cases hh)
  · rw [if_neg g0] at h ⊢
    by_cases g1 : (!premisesResolve v d)
    · rw [if_pos g1] at h; exact absurd h (by intro hh; cases hh)
    · rw [if_neg g1] at h ⊢
      by_cases g2 : (v.findClaim d.conclusion).isNone
      · rw [if_pos g2] at h; exact absurd h (by intro hh; cases hh)
      · rw [if_neg g2] at h ⊢
        by_cases g3 : (!conclusionMatches v d)
        · rw [if_pos g3] at h; exact absurd h (by intro hh; cases hh)
        · rw [if_neg g3] at h ⊢
          by_cases g4 : (addCorrectionV v c).corrections.any
              (fun k => k.target == d.conclusion)
          · rw [if_pos g4] at h; exact absurd h (by intro hh; cases hh)
          · rw [if_neg g4] at h
            have h4v : v.corrections.any (fun k => k.target == d.conclusion) = false := by
              have h0 : (addCorrectionV v c).corrections.any
                  (fun k => k.target == d.conclusion) = false := not_any_true_eq g4
              simp only [addCorrectionV, List.any_append] at h0
              cases hv : v.corrections.any (fun k => k.target == d.conclusion) with
              | true => rw [hv] at h0; simp at h0
              | false => rfl
            rw [if_neg (show Not ((v.corrections.any (fun k => k.target == d.conclusion)) = true) from by
                intro hcon
                rw [hcon] at h4v
                exact absurd h4v (by simp))] at ⊢
            by_cases g5 : (addCorrectionV v c).corrections.any
                (fun k => d.premiseGroups.any (fun g => g.contains k.target))
            · rw [if_pos g5] at h; exact absurd h (by intro hh; cases hh)
            · rw [if_neg g5] at h
              have h5v : v.corrections.any
                  (fun k => d.premiseGroups.any (fun g => g.contains k.target))
                  = false := by
                have h0 : (addCorrectionV v c).corrections.any
                    (fun k => d.premiseGroups.any (fun g => g.contains k.target))
                    = false := not_any_true_eq g5
                simp only [addCorrectionV, List.any_append] at h0
                cases hv : v.corrections.any
                    (fun k => d.premiseGroups.any (fun g => g.contains k.target)) with
                | true => rw [hv] at h0; simp at h0
                | false => rfl
              rw [if_neg (show Not ((v.corrections.any
                    (fun k => d.premiseGroups.any (fun g => g.contains k.target))) = true) from by
                intro hcon
                rw [hcon] at h5v
                exact absurd h5v (by simp))] at ⊢
              cases hr : d.rule with
              | andIntro => rw [show d.rule = RuleId.andIntro from hr] at h; exact h
              | specialize => rw [show d.rule = RuleId.specialize from hr] at h; exact h
              | obsSupports => rw [show d.rule = RuleId.obsSupports from hr] at h; exact h
              | allChecked => rw [show d.rule = RuleId.allChecked from hr] at h; exact h

theorem T16_add_correction_no_new_support {v : KbView} {ctx : EvalCtx}
    {r : ClaimRef} {c : Correction}
    (h : Supported (addCorrectionV v c) ctx r = true) :
    Supported v ctx r = true := by
  simp only [Supported, addCorrectionV] at h ⊢
  obtain ⟨d, hd, hpd⟩ := List.any_eq_true.mp h
  simp only [Bool.and_eq_true] at hpd
  obtain ⟨hcon, hacc⟩ := hpd
  refine List.any_eq_true.mpr ⟨d, hd, ?_⟩
  simp only [Bool.and_eq_true]
  refine ⟨hcon, ?_⟩
  have hext : checkDerivationV (addCorrectionV v c) ctx d = Verdict.accepted :=
    verdict_eq_of_beq hacc
  rw [checkDerivationV_drop_correction hext]
  rfl

/-! ## T17: UsableFor entails every mandatory condition. -/

theorem T17_usable_conditions {v : KbView} {ctx : EvalCtx} {r : ClaimRef}
    (h : UsableFor v ctx r = true) :
    Supported v ctx r = true
    ∧ (ctx.requireFreshEvidence = false ∨ hasFreshEvidence v ctx r = true)
    ∧ (ctx.requireValidated = false ∨ validationCurrent v r = true)
    ∧ (ctx.requireUncontested = false ∨ Contested v r = false) := by
  simp only [UsableFor, Bool.and_eq_true, Bool.or_eq_true, Bool.not_eq_true'] at h ⊢
  exact ⟨h.1.1.1, h.1.1.2, h.1.2, h.2⟩

/-! ## T18: accepted proposal transitions satisfy their preconditions. -/

theorem T18_transition_conditions {p : Proposal} {target : ProposalStatus}
    {actor : Option String} {landedRefs : List String} {refsResolvable : Bool}
    {p2 : Proposal}
    (h : planTransition p target actor landedRefs refsResolvable = .planned p2) :
    legalTransition p.status target = true
    ∧ (target = .proposed → readyForProposed p = true)
    ∧ (decidedStatus target = true → actor.isSome = true)
    ∧ (target = .applied →
        (p.landGatesPassed = true ∧ refsResolvable = true ∧ landedRefs.length > 0))
    ∧ (target = .verified → p.deployUseGatesPassed = true)
    ∧ p2.status = target := by
  unfold planTransition at h
  by_cases c0 : (!legalTransition p.status target)
  · rw [if_pos c0] at h; exact absurd h (by intro hh; cases hh)
  · rw [if_neg c0] at h
    by_cases c1 : (target == .proposed && !readyForProposed p)
    · rw [if_pos c1] at h; exact absurd h (by intro hh; cases hh)
    · rw [if_neg c1] at h
      by_cases c2 : (decidedStatus target && actor.isNone)
      · rw [if_pos c2] at h; exact absurd h (by intro hh; cases hh)
      · rw [if_neg c2] at h
        by_cases c3 : (target == .applied
            && !(p.landGatesPassed && refsResolvable && !landedRefs.isEmpty))
        · rw [if_pos c3] at h; exact absurd h (by intro hh; cases hh)
        · rw [if_neg c3] at h
          by_cases c4 : (target == .verified && !p.deployUseGatesPassed)
          · rw [if_pos c4] at h; exact absurd h (by intro hh; cases hh)
          · rw [if_neg c4] at h
            refine ⟨not_notB_eq c0, ?_, ?_, ?_, ?_, ?_⟩
            · intro htp
              rw [htp] at c1
              simpa using c1
            · intro hds
              rw [hds] at c2
              simpa [Option.isSome_iff_ne_none] using c2
            · intro hta
              rw [hta] at c3
              have hc3 : (p.landGatesPassed && refsResolvable && !landedRefs.isEmpty) = true := by
                simpa using c3
              simp only [Bool.and_eq_true] at hc3
              refine ⟨hc3.1.1, hc3.1.2, ?_⟩
              cases landedRefs with
              | nil => exact absurd hc3.2 (by simp)
              | cons x xs => simp
            · intro htv
              rw [htv] at c4
              simpa using c4
            · cases PlanOutcome.planned.inj h
              rfl

/-! ## T19: investigation conclusion satisfies its requirements. -/

theorem T19_conclude_conditions {i : Investigation} (h : canConclude i = true) :
    (¬i.checkedAgainst.isEmpty) ∧ (¬i.scopeAndLimits.isEmpty)
    ∧ ∀ hyp ∈ i.hypotheses,
        hyp.status ≠ HypStatus.openH ∧ hyp.status ≠ HypStatus.malformedH := by
  simp only [canConclude, Bool.and_eq_true, Bool.not_eq_true', List.any_eq_false] at h ⊢
  refine ⟨by simpa using h.1.1, by simpa using h.1.2, ?_⟩
  intro hyp hhyp
  have hthis := h.2 hyp hhyp
  constructor
  · intro hopen
    apply hthis
    rw [hopen]
    simp
  · intro hmal
    apply hthis
    rw [hmal]
    simp

/-! ## T20: conditional application; rejection leaves state unchanged. -/

theorem T20_predecessor_conflict {kb : KB} {journal : List JournalEntry} {op : Op}
    (hfresh : ∀ e ∈ journal, e.id ≠ op.id)
    (hhead : kb.head ≠ op.expectedHead) :
    (commitOp kb journal op).1 = kb
    ∧ (commitOp kb journal op).2 = CommitOutcome.predecessorConflict := by
  unfold commitOp
  have hfind : journal.find? (fun e => e.id == op.id) = none :=
    List.find?_eq_none.mpr (fun e he => by
      intro hbeq
      have hid : e.id = op.id := eq_of_beq hbeq
      exact hfresh e he hid)
  simp only [hfind]
  have hcond : (kb.head != op.expectedHead) = true := by simpa using hhead
  simp only [if_pos hcond]
  simp

/-! ## T21: idempotent replay; conflicting replay is a conflict. -/

theorem T21_replay_same {kb : KB} {op : Op} :
    (commitOp kb [JournalEntry.mk op.id op.expectedHead op.inputDigest] op).2
      = CommitOutcome.alreadyCommitted := by
  unfold commitOp
  have hfind : ([JournalEntry.mk op.id op.expectedHead op.inputDigest] : List JournalEntry).find?
      (fun e => e.id == op.id)
      = some (JournalEntry.mk op.id op.expectedHead op.inputDigest) := by
    simp [List.find?]
  simp only [hfind]
  have hcond : ((JournalEntry.mk op.id op.expectedHead op.inputDigest).digest == op.inputDigest
      && (JournalEntry.mk op.id op.expectedHead op.inputDigest).head == op.expectedHead) = true := by
    simp
  simp only [if_pos hcond]

theorem T21_replay_conflict {kb : KB} {op : Op} {e : JournalEntry}
    (hid : e.id = op.id) (hdiff : e.digest ≠ op.inputDigest) :
    (commitOp kb [e] op).2 = CommitOutcome.inputConflict := by
  unfold commitOp
  have hfind : ([e] : List JournalEntry).find? (fun x => x.id == op.id) = some e := by
    simp [List.find?, hid]
  simp only [hfind]
  have hcond : ¬((e.digest == op.inputDigest) && (e.head == op.expectedHead)) := by
    intro hp
    simp only [Bool.and_eq_true] at hp
    exact hdiff (eq_of_beq hp.1)
  simp only [if_neg hcond]

/-! ## T22: determinism for identical explicit inputs. -/

theorem T22_deterministic {v v2 : KbView} {ctx ctx2 : EvalCtx}
    (hv : v = v2) (hc : ctx = ctx2) (d : Derivation) :
    checkDerivationV v ctx d = checkDerivationV v2 ctx2 d := by
  subst hv; subst hc; rfl

theorem T22_commit_deterministic {kb kb2 : KB} {j j2 : List JournalEntry} {op : Op}
    (hkb : kb = kb2) (hj : j = j2) :
    commitOp kb j op = commitOp kb2 j2 op := by
  subst hkb; subst hj; rfl

/-! ## Non-vacuity: concrete positive inhabitants and negative examples.
Everything below is evaluated by `decide` (kernel computation), so these are
machine-checked, not paper claims. -/

namespace NonVacuity

open Kctx

private def demoScope : Kctx.Scope := { project := "payments", extra := "" }

private def demoClaim : Kctx.Claim where
  id := { val := "c1" }
  rev := "r1"
  prop := .atom { subject := "batch-limit", predicate := "is", args := ["500"] }
  scope := demoScope

private def demoObs : Kctx.Observation where
  id := { val := "o1" }
  outcome := .ok
  observedAt := 100
  ttl := .expireAfter 50
  system := "git"
  locator := "repo"

private def demoBinding : Kctx.Binding where
  obs := { val := "o1" }
  ref := { id := { val := "c1" }, rev := "r1" }
  role := .supports

private def demoDeriv : Kctx.Derivation where
  id := "d1"
  rule := .obsSupports
  premiseGroups := []
  conclusion := { id := { val := "c1" }, rev := "r1" }
  conclusionProp := .atom { subject := "batch-limit", predicate := "is", args := ["500"] }
  scope := demoScope
  footprint := [
    { kind := .kbRecord, target := "c1", digest := "" },
    { kind := .kbRecord, target := "o1", digest := "" }
  ]
  evidence := some { val := "o1" }
  witness := none

private def demoView : Kctx.KbView where
  observations := [demoObs]
  claims := [demoClaim]
  bindings := [demoBinding]
  corrections := []
  derivations := [demoDeriv]
  validations := []

private def demoCtx : Kctx.EvalCtx where
  now := 120
  requireFreshEvidence := true
  requireValidated := false
  requireUncontested := true

/-- A nontrivial accepted derivation exists (T04/T08 preconditions inhabited). -/
example : Kctx.checkDerivationV demoView demoCtx demoDeriv = Kctx.Verdict.accepted := by decide

/-- The same derivation is rejected once its evidence goes stale. -/
example : Kctx.checkDerivationV demoView
    { demoCtx with now := 200 } demoDeriv
    = Kctx.Verdict.rejected Kctx.Rejection.evidenceNotFresh := by decide

/-- Supported and UsableFor succeed on the demo view. -/
example : Kctx.Supported demoView demoCtx demoDeriv.conclusion = true := by decide
example : Kctx.UsableFor demoView demoCtx demoDeriv.conclusion = true := by decide

/-- Removing the sole derivation removes support, and does NOT establish the
negated proposition (no derivation for any other ref exists either). -/
example : Kctx.Supported { demoView with derivations := [] } demoCtx
    demoDeriv.conclusion = false := by decide

/-- T14 countermodel flavor: a contextualizes binding does not create support. -/
example : Kctx.checkDerivationV
    { demoView with bindings :=
        [{ obs := { val := "o1" }, ref := demoDeriv.conclusion, role := .contextualizes }] }
    demoCtx demoDeriv
    = Kctx.Verdict.rejected Kctx.Rejection.evidenceNotOk := by decide

/-- T16: adding a supersede correction cannot restore/produce support. -/
example : Kctx.Supported
    (Kctx.addCorrectionV { demoView with derivations := [] }
      { kind := .supersede, target := demoDeriv.conclusion, recordedAt := 300 })
    demoCtx demoDeriv.conclusion = false := by decide

end NonVacuity

end Kctx
