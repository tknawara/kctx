import Kctx.Theorems

set_option autoImplicit false
set_option maxHeartbeats 1000000

/-! Footprint locality (T07) and historical stability (T15).

T07 answers: *which changes cannot affect a derivation's verdict?* Two forms:

- ``T07_checkDerivationV_agree`` — the verdict is a function of the exact
  observables the checker reads: claim/observation lookups restricted to
  ``consultedIds`` (the footprint construction: premise, conclusion, evidence
  and footprint-target identities — see the ``consultedIds_*`` membership
  lemmas), the evidence-binding test, and the two correction guards. The
  checker queries nothing else, which is exactly what the proof exploits.
- ``T07_checkDerivationV_ext`` — the record-level corollary: appending
  claims/observations whose ids lie outside ``consultedIds``, and corrections
  whose target ids lie outside it, cannot change the verdict.

T15 answers: *is a historical evaluation stable under later additions?*
``T15_supported_ext`` pins the derivation list (the historical context) and
shows that unrelated claims/observations/corrections added afterwards do not
change what the pinned derivations conclude about a reference. -/

namespace Kctx

/-! ## Membership: the checker queries only consulted identities. -/

theorem consultedIds_premise {d : Derivation} {g : List ClaimRef} {r : ClaimRef}
    (hg : g ∈ d.premiseGroups) (hr : r ∈ g) : r.id.val ∈ d.consultedIds := by
  have h1 : r.id.val ∈ d.premiseGroups.flatMap (fun g2 => g2.map (fun x => x.id.val)) :=
    List.mem_flatMap.mpr ⟨g, hg, List.mem_map_of_mem hr⟩
  simp only [Derivation.consultedIds, List.mem_append]
  exact Or.inl (Or.inl (Or.inr h1))

theorem consultedIds_conclusion {d : Derivation} :
    d.conclusion.id.val ∈ d.consultedIds := by
  simp only [Derivation.consultedIds, List.mem_append]
  exact Or.inl (Or.inr (by simp))

theorem consultedIds_evidence {d : Derivation} {i : ObservationId}
    (h : d.evidence = some i) : i.val ∈ d.consultedIds := by
  unfold Derivation.consultedIds
  rw [h]
  simp only [List.mem_append]
  exact Or.inr (by simp)

/-! ## Small congruence helpers. -/

theorem all_congr_mem2 {a : Type} (l : List a) (f g : a → Bool)
    (h : ∀ x ∈ l, f x = g x) : l.all f = l.all g := by
  induction l with
  | nil => rfl
  | cons x xs ih =>
    simp only [List.all_cons, h x (List.mem_cons_self ..),
      ih (fun y hy => h y (List.mem_cons_of_mem _ hy))]

theorem any_congr_mem2 {a : Type} (l : List a) (f g : a → Bool)
    (h : ∀ x ∈ l, f x = g x) : l.any f = l.any g := by
  induction l with
  | nil => rfl
  | cons x xs ih =>
    simp only [List.any_cons, h x (List.mem_cons_self ..),
      ih (fun y hy => h y (List.mem_cons_of_mem _ hy))]

theorem map_congr_mem2 {a b : Type} (l : List a) (f g : a → b)
    (h : ∀ x ∈ l, f x = g x) : l.map f = l.map g := by
  induction l with
  | nil => rfl
  | cons x xs ih =>
    simp only [List.map_cons, h x (List.mem_cons_self ..),
      ih (fun y hy => h y (List.mem_cons_of_mem _ hy))]

/-- ``find?`` ignores an appended segment in which the predicate never holds. -/
theorem find?_append_of_forall {a : Type} (p : a → Bool) (l l2 : List a)
    (h : ∀ x ∈ l2, ¬(p x = true)) : (l ++ l2).find? p = l.find? p := by
  induction l with
  | nil => exact List.find?_eq_none.mpr h
  | cons x xs ih =>
    simp only [List.cons_append, List.find?_cons]
    split
    · rfl
    · exact ih

/-! ## Observable-level agreement (T07, agreement form). -/

section Agree

variable {v v2 : KbView} {ctx : EvalCtx} {d : Derivation}

/-- Hypothesis bundle: the second view answers every checker query exactly as
the first does. This is the precise content of "changes outside the declared
footprint": any two states agreeing on these observables agree on the
verdict, whatever else differs. -/
structure QueryAgree (v v2 : KbView) (d : Derivation) where
  onClaim : ∀ r : ClaimRef, r.id.val ∈ d.consultedIds → v2.findClaim r = v.findClaim r
  onObs : ∀ i : ObservationId, i.val ∈ d.consultedIds → v2.findObs i = v.findObs i
  onBind : ∀ i : ObservationId,
    (v2.bindings.contains (Binding.mk i d.conclusion SupportRole.supports))
      = (v.bindings.contains (Binding.mk i d.conclusion SupportRole.supports))
  onCorrConclusion :
    (v2.corrections.any (fun k => k.target == d.conclusion))
      = (v.corrections.any (fun k => k.target == d.conclusion))
  onCorrPremise :
    (v2.corrections.any (fun k => d.premiseGroups.any (fun g => g.contains k.target)))
      = (v.corrections.any (fun k => d.premiseGroups.any (fun g => g.contains k.target)))

theorem premisesResolve_agree (A : QueryAgree v v2 d) :
    premisesResolve v2 d = premisesResolve v d := by
  have key : ∀ r : ClaimRef, r ∈ d.premiseGroups.flatMap (fun g => g) →
      (v2.findClaim r).isSome = (v.findClaim r).isSome := by
    intro r hr
    obtain ⟨g, hg, hgr⟩ := List.mem_flatMap.mp hr
    rw [A.onClaim r (consultedIds_premise hg hgr)]
  unfold premisesResolve
  refine all_congr_mem2 _ _ _ ?_
  intro g hg
  refine all_congr_mem2 _ _ _ ?_
  intro r hr
  exact key r (List.mem_flatMap.mpr ⟨g, hg, hr⟩)

theorem conclusionMatches_agree (A : QueryAgree v v2 d) :
    conclusionMatches v2 d = conclusionMatches v d := by
  have h1 : v2.findClaim d.conclusion = v.findClaim d.conclusion :=
    A.onClaim d.conclusion consultedIds_conclusion
  unfold conclusionMatches
  rw [h1]

theorem propOf_agree (A : QueryAgree v v2 d) {r : ClaimRef}
    (hr : r.id.val ∈ d.consultedIds) : v2.propOf r = v.propOf r := by
  unfold KbView.propOf
  rw [A.onClaim r hr]

theorem scopeOf_agree (A : QueryAgree v v2 d) {r : ClaimRef}
    (hr : r.id.val ∈ d.consultedIds) : v2.scopeOf r = v.scopeOf r := by
  unfold KbView.scopeOf
  rw [A.onClaim r hr]

theorem checkAndIntro_agree (A : QueryAgree v v2 d) :
    checkAndIntro v2 d = checkAndIntro v d := by
  unfold checkAndIntro
  split
  · next xg g heq =>
    have hg : g ∈ d.premiseGroups := by rw [heq]; exact List.mem_cons_self ..
    by_cases c1 : g.isEmpty
    · rw [if_pos c1, if_pos c1]
    · rw [if_neg c1, if_neg c1]
      have hprop : ∀ r ∈ g, v2.propOf r = v.propOf r :=
        fun r hr => propOf_agree A (consultedIds_premise hg hr)
      rw [all_congr_mem2 _ _ _ (fun r hr => by rw [hprop r hr])]
      by_cases c2 : (!(g.all (fun r => (v.propOf r).asAtom.isSome)))
      · rw [if_pos c2, if_pos c2]
      · rw [if_neg c2, if_neg c2]
        have hscope : ∀ r ∈ g, v2.scopeOf r = v.scopeOf r :=
          fun r hr => scopeOf_agree A (consultedIds_premise hg hr)
        rw [all_congr_mem2 _ _ _ (fun r hr => by rw [hscope r hr])]
        by_cases c3 : (!(g.all (fun r => v.scopeOf r == some d.scope)))
        · rw [if_pos c3, if_pos c3]
        · rw [if_neg c3, if_neg c3]
          have hprop2 : ∀ r ∈ g,
              ((v2.propOf r).asAtom).getD default = ((v.propOf r).asAtom).getD default :=
            fun r hr => by rw [hprop r hr]
          have hatoms : andIntroAtoms v2 g = andIntroAtoms v g :=
            map_congr_mem2 _ _ _ hprop2
          rw [hatoms]
          by_cases c4 : (d.conclusionProp != ClaimProp.conj (andIntroAtoms v g))
          · rw [if_pos c4, if_pos c4]
          · rw [if_neg c4, if_neg c4]
            rfl
  · rfl

theorem checkSpecialize_agree (A : QueryAgree v v2 d) :
    checkSpecialize v2 d = checkSpecialize v d := by
  unfold checkSpecialize
  split
  · next xr r heq =>
    have hr : r.id.val ∈ d.consultedIds :=
      consultedIds_premise (by rw [heq]; exact List.mem_cons_self ..)
        (by simp)
    rw [A.onClaim r hr, A.onClaim d.conclusion consultedIds_conclusion]
    cases hs : v.findClaim r with
    | none => rfl
    | some src =>
      cases ht : v.findClaim d.conclusion with
      | none => rfl
      | some tgt =>
        simp only [hs, ht]
        by_cases c1 : (src.prop != tgt.prop)
        · rw [if_pos c1, if_pos c1]
        · rw [if_neg c1, if_neg c1]
          by_cases c2 : (!tgt.scope.specializes src.scope)
          · rw [if_pos c2, if_pos c2]
          · rw [if_neg c2, if_neg c2]
            by_cases c3 : (d.scope != tgt.scope)
            · rw [if_pos c3, if_pos c3]
            · rw [if_neg c3, if_neg c3]
              rfl
  · rfl

theorem checkObsSupports_agree (A : QueryAgree v v2 d) :
    checkObsSupports v2 ctx d = checkObsSupports v ctx d := by
  unfold checkObsSupports
  by_cases c0 : (!d.premiseGroups.isEmpty)
  · rw [if_pos c0, if_pos c0]
  · rw [if_neg c0, if_neg c0]
    cases hEv : d.evidence with
    | none => rfl
    | some i =>
      simp only [hEv]
      rw [A.onObs i (consultedIds_evidence hEv)]
      cases ho : v.findObs i with
      | none => rfl
      | some o =>
        simp only [ho]
        rw [scopeOf_agree A consultedIds_conclusion]
        by_cases c1 : (!(v.scopeOf d.conclusion == some d.scope))
        · rw [if_pos c1, if_pos c1]
        · rw [if_neg c1, if_neg c1]
          by_cases c2 : d.conclusionProp.asAtom.isNone
          · rw [if_pos c2, if_pos c2]
          · rw [if_neg c2, if_neg c2]
            by_cases c3 : (o.outcome != ObsOutcome.ok)
            · rw [if_pos c3, if_pos c3]
            · rw [if_neg c3, if_neg c3]
              rw [A.onBind i]
              by_cases c4 : (!v.bindings.contains
                  (Binding.mk i d.conclusion SupportRole.supports))
              · rw [if_pos c4, if_pos c4]
              · rw [if_neg c4, if_neg c4]
                by_cases c5 : (assessFresh o.ttl o.observedAt ctx.now != Fresh.fresh)
                · rw [if_pos c5, if_pos c5]
                · rw [if_neg c5, if_neg c5]
                  rfl

theorem checkAllChecked_agree :
    checkAllChecked v2 d = checkAllChecked v d := rfl

/-- T07 (agreement form): views answering the checker's queries identically
give identical verdicts. The queries are exactly the footprint construction
(premise/conclusion/evidence lookups), the evidence binding test, and the
correction guards. -/
theorem T07_checkDerivationV_agree (A : QueryAgree v v2 d) :
    checkDerivationV v2 ctx d = checkDerivationV v ctx d := by
  have h1 : (!premisesResolve v2 d) = (!premisesResolve v d) := by
    rw [premisesResolve_agree A]
  have h2 : (v2.findClaim d.conclusion).isNone
      = (v.findClaim d.conclusion).isNone := by
    rw [A.onClaim d.conclusion consultedIds_conclusion]
  have h3 : (!conclusionMatches v2 d) = (!conclusionMatches v d) := by
    rw [conclusionMatches_agree A]
  unfold checkDerivationV
  rw [h1, h2, h3, A.onCorrConclusion, A.onCorrPremise]
  split
  · rfl
  split
  · rfl
  split
  · rfl
  split
  · rfl
  split
  · rfl
  split
  · rfl
  split
  · exact checkAndIntro_agree A
  · exact checkSpecialize_agree A
  · exact checkObsSupports_agree A
  · exact checkAllChecked_agree

end Agree

/-! ## T07, record-extension corollary. -/

section Ext

variable {v : KbView} {ctx : EvalCtx} {d : Derivation}

def extView (v : KbView) (newObs : List Observation)
    (newClaims : List Claim) (newCorr : List Correction) : KbView :=
  { v with observations := v.observations ++ newObs,
           claims := v.claims ++ newClaims,
           corrections := v.corrections ++ newCorr }

theorem findClaim_append_fresh {newClaims : List Claim} {r : ClaimRef}
    (hin : r.id.val ∈ d.consultedIds)
    (hfresh : ∀ c ∈ newClaims, c.id.val ∉ d.consultedIds) :
    (v.claims ++ newClaims).find? (fun c => c.id == r.id && c.rev == r.rev)
      = v.claims.find? (fun c => c.id == r.id && c.rev == r.rev) := by
  refine find?_append_of_forall _ _ _ ?_
  intro c hc
  intro hp
  rw [Bool.and_eq_true] at hp
  have hcid : c.id = r.id := ident_eq_of_beq hp.1
  exact hfresh c hc (by rw [hcid]; exact hin)

theorem findObs_append_fresh {newObs : List Observation} {i : ObservationId}
    (hin : i.val ∈ d.consultedIds)
    (hfresh : ∀ o ∈ newObs, o.id.val ∉ d.consultedIds) :
    (v.observations ++ newObs).find? (fun o => o.id == i)
      = v.observations.find? (fun o => o.id == i) := by
  refine find?_append_of_forall _ _ _ ?_
  intro o ho
  intro hp
  have hoid : o.id = i := ident_eq_of_beq hp
  exact hfresh o ho (by rw [hoid]; exact hin)

/-- T07 (extension form): appending claims/observations whose ids lie outside
the derivation's consulted footprint, and corrections whose target ids lie
outside it, cannot change the verdict. Bindings are deliberately not extended
here — a new binding can legitimately create support (that is acquisition,
not noise). -/
theorem T07_checkDerivationV_ext {newObs : List Observation}
    {newClaims : List Claim} {newCorr : List Correction}
    (hObs : ∀ o ∈ newObs, o.id.val ∉ d.consultedIds)
    (hCl : ∀ c ∈ newClaims, c.id.val ∉ d.consultedIds)
    (hCorr : ∀ k ∈ newCorr, k.target.id.val ∉ d.consultedIds) :
    checkDerivationV (extView v newObs newClaims newCorr) ctx d
      = checkDerivationV v ctx d := by
  have hcorrC : (newCorr.any (fun k => k.target == d.conclusion)) = false := by
    refine List.any_eq_false.mpr ?_
    intro k hk
    intro hp
    exact hCorr k hk (by
      rw [claimRef_eq_of_beq hp]
      exact consultedIds_conclusion)
  have hcorrP : (newCorr.any
      (fun k => d.premiseGroups.any (fun g => g.contains k.target))) = false := by
    refine List.any_eq_false.mpr ?_
    intro k hk
    intro hp
    obtain ⟨g, hg, hgm⟩ := List.any_eq_true.mp hp
    obtain ⟨m, hmg, hmbeq⟩ := List.contains_iff_exists_mem_beq.mp hgm
    exact hCorr k hk (by
      rw [show k.target = m from claimRef_eq_of_beq hmbeq]
      exact consultedIds_premise hg hmg)
  refine T07_checkDerivationV_agree {
    onClaim := fun r hr => findClaim_append_fresh (d := d) hr hCl
    onObs := fun i hi => findObs_append_fresh (d := d) hi hObs
    onBind := fun _ => rfl
    onCorrConclusion := by
      show ((v.corrections ++ newCorr).any
        (fun k => k.target == d.conclusion))
        = (v.corrections.any (fun k => k.target == d.conclusion))
      rw [List.any_append, hcorrC, Bool.or_false]
    onCorrPremise := by
      show ((v.corrections ++ newCorr).any
        (fun k => d.premiseGroups.any (fun g => g.contains k.target)))
        = (v.corrections.any
            (fun k => d.premiseGroups.any (fun g => g.contains k.target)))
      rw [List.any_append, hcorrP, Bool.or_false] }

end Ext

/-! ## T15: historical stability of support under unrelated additions. -/

section Historical

variable {v : KbView} {ctx : EvalCtx} {r : ClaimRef}

/-- Union of the consulted footprints of every derivation concluding ``r``:
the identities a historical evaluation of ``r`` depends on. -/
def supportFootprint (v : KbView) (r : ClaimRef) : List String :=
  (v.derivations.filter (fun d => d.conclusion == r)).flatMap
    Derivation.consultedIds

theorem supportFootprint_mem {d : Derivation}
    (hd : d ∈ v.derivations) (hc : d.conclusion = r) :
    ∀ t ∈ d.consultedIds, t ∈ supportFootprint v r :=
  fun t ht => List.mem_flatMap_of_mem (List.mem_filter.mpr
    (And.intro hd (by rw [hc]; simp))) ht

/-- T15: pin the derivation list (the historical context). Adding
claims/observations/corrections whose relevant identities lie outside the
support footprint cannot change what those derivations conclude about ``r``:
a later addition neither creates nor destroys historical support. New
derivations may of course add support — they are new history, not extensions
of the pinned one. -/
theorem T15_supported_ext {newObs : List Observation}
    {newClaims : List Claim} {newCorr : List Correction}
    (hObs : ∀ o ∈ newObs, o.id.val ∉ supportFootprint v r)
    (hCl : ∀ c ∈ newClaims, c.id.val ∉ supportFootprint v r)
    (hCorr : ∀ k ∈ newCorr, k.target.id.val ∉ supportFootprint v r) :
    Supported (extView v newObs newClaims newCorr) ctx r = Supported v ctx r := by
  have key : ∀ d ∈ v.derivations,
      ((d.conclusion == r) && (checkDerivationV
          (extView v newObs newClaims newCorr) ctx d == Verdict.accepted))
      = ((d.conclusion == r) && (checkDerivationV v ctx d == Verdict.accepted)) := by
    intro d hd
    by_cases hc : (d.conclusion == r) = true
    · have hcr : d.conclusion = r := claimRef_eq_of_beq hc
      have hagree : checkDerivationV (extView v newObs newClaims newCorr) ctx d
          = checkDerivationV v ctx d := by
        refine T07_checkDerivationV_ext (d := d) ?_ ?_ ?_
        · intro o ho hmem
          exact hObs o ho (supportFootprint_mem hd hcr o.id.val hmem)
        · intro c hc2 hmem
          exact hCl c hc2 (supportFootprint_mem hd hcr c.id.val hmem)
        · intro k hk hmem
          exact hCorr k hk (supportFootprint_mem hd hcr k.target.id.val hmem)
      rw [hc, hagree]
    · have hf : (d.conclusion == r) = false := by simpa using hc
      rw [hf, Bool.false_and, Bool.false_and]
  have hder : (extView v newObs newClaims newCorr).derivations
      = v.derivations := rfl
  unfold Supported
  rw [hder]
  exact any_congr_mem2 _ _ _ (fun d hd => key d hd)

end Historical

end Kctx
