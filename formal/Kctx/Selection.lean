import Kctx.Locality

set_option autoImplicit false
namespace Kctx

structure SelectionState where
  kb : KB
  selected : List Ref
  deriving DecidableEq, Repr, Inhabited
structure SelectionPlan where
  id : OperationId
  expectedSnapshot : SnapshotId
  targetSnapshot : SnapshotId
  newSnapshot : SnapshotId
  selected : List Ref
  actor : Option ActorId
  policy : PolicyId
  intendedUse : String
  context : Context
  deriving DecidableEq, Repr, Inhabited
structure VerifiedSelectionApproval where
  plan : SelectionPlan
  deriving DecidableEq, Repr, Inhabited
structure SelectionJournalEntry where
  plan : SelectionPlan
  deriving DecidableEq, Repr, Inhabited
structure SelectionResult where
  state : SelectionState
  journal : List SelectionJournalEntry
  outcome : ApplyOutcome
  deriving DecidableEq, Repr, Inhabited

def selectionStateValid (s : SelectionState) : Bool :=
  s.kb.wellFormed && unique s.selected && s.selected.all (fun r => (claimAt s.kb r).isSome)

def selectedState (s : SelectionState) (p : SelectionPlan) : SelectionState :=
  ⟨{ s.kb with snapshot := p.newSnapshot }, p.selected⟩

def selectionValid (s : SelectionState) (e : Context) (p : SelectionPlan)
    (trusted : List VerifiedSelectionApproval) (retained : List KB) : Bool :=
  selectionStateValid s && contextValid s.kb e && token p.id.val && token p.newSnapshot.val &&
  p.newSnapshot != s.kb.snapshot && !retained.any (fun k => k.snapshot == p.newSnapshot) &&
  unique (retained.map (·.snapshot)) && p.actor.any (fun actor => e.policy.authorizedActors.contains actor) &&
  identPresent p.actor && p.policy == e.policy.id && p.intendedUse == e.intendedUse &&
  p.context == e &&
  trusted.any (fun a => a.plan == p) &&
  match retained.find? (fun k => k.snapshot == p.targetSnapshot) with
  | none => false
  | some target => target.wellFormed && extendsKB target s.kb &&
      p.selected == target.claims.map Claim.ref && unique p.selected &&
      p.selected.all (fun r => (claimAt s.kb r).isSome)

def applySelection (s : SelectionState) (e : Context) (journal : List SelectionJournalEntry)
    (p : SelectionPlan) (trusted : List VerifiedSelectionApproval) (retained : List KB) : SelectionResult :=
  match journal.find? (fun j => j.plan.id == p.id) with
  | some j => ⟨s, journal, if j.plan == p then .alreadyApplied else .inputConflict⟩
  | none => if p.expectedSnapshot != s.kb.snapshot then ⟨s, journal, .predecessorConflict⟩
    else if selectionValid s e p trusted retained then ⟨selectedState s p, ⟨p⟩ :: journal, .applied⟩
    else ⟨s, journal, .rejected⟩

def retrieveSelected (s : SelectionState) (e : Context) (offset limit : Nat) : Retrieval :=
  let relevant := s.kb.claims.filter (fun c => s.selected.contains c.ref && decide (narrower e.target c.statement.scope))
  let page := (relevant.drop offset).take limit
  let next := offset + page.length
  let omitted := relevant.length - next
  ⟨s.kb.snapshot, page.map (fun c => (c, assess s.kb e c.ref)), omitted, omitted == 0,
    if omitted == 0 then none else some next⟩

theorem selection_applied_details {s : SelectionState} {e : Context} {js : List SelectionJournalEntry}
    {p : SelectionPlan} {trusted : List VerifiedSelectionApproval} {retained : List KB}
    (h : (applySelection s e js p trusted retained).outcome = .applied) :
    p.expectedSnapshot = s.kb.snapshot ∧ selectionValid s e p trusted retained = true ∧
    applySelection s e js p trusted retained = ⟨selectedState s p, ⟨p⟩ :: js, .applied⟩ := by
  cases hf : js.find? (fun j => j.plan.id == p.id) with
  | some j =>
      simp only [applySelection, hf] at h
      split at h <;> contradiction
  | none =>
      simp only [applySelection, hf] at h ⊢
      split at h
      · contradiction
      · next predecessor =>
          split at h
          · next valid =>
              have hp : p.expectedSnapshot = s.kb.snapshot := by simpa using predecessor
              simp [hp, valid]
          · contradiction

theorem selection_preserves_ledger (s : SelectionState) (p : SelectionPlan) :
    (selectedState s p).kb.observations = s.kb.observations ∧
    (selectedState s p).kb.claims = s.kb.claims ∧
    (selectedState s p).kb.attestations = s.kb.attestations ∧
    (selectedState s p).kb.enumerations = s.kb.enumerations ∧
    (selectedState s p).kb.derivations = s.kb.derivations ∧
    (selectedState s p).kb.corrections = s.kb.corrections ∧
    (selectedState s p).kb.receipts = s.kb.receipts := ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl⟩

theorem selection_exact_retained_refs {s : SelectionState} {e : Context} {p : SelectionPlan}
    {trusted : List VerifiedSelectionApproval} {retained : List KB}
    (h : selectionValid s e p trusted retained = true) :
    ∃ target, retained.find? (fun k => k.snapshot == p.targetSnapshot) = some target ∧
      p.selected = target.claims.map Claim.ref ∧ extendsKB target s.kb = true := by
  simp only [selectionValid, bool_and] at h
  cases ht : retained.find? (fun k => k.snapshot == p.targetSnapshot) with
  | none => simp [ht] at h
  | some target =>
      have hh := h.2
      simp only [ht, bool_and] at hh
      exact ⟨target, rfl, eq_of_beq hh.1.1.2, hh.1.1.1.2⟩

theorem selection_replay {s : SelectionState} {e : Context} {js : List SelectionJournalEntry}
    {p : SelectionPlan} {trusted : List VerifiedSelectionApproval} {retained : List KB}
    (h : (applySelection s e js p trusted retained).outcome = .applied) :
    let result := applySelection s e js p trusted retained
    applySelection result.state e result.journal p [] retained =
      ⟨result.state, result.journal, .alreadyApplied⟩ := by
  have hd := (selection_applied_details h).2.2
  dsimp only
  rw [hd]
  simp [applySelection, List.find?]

theorem selection_rejects_self_approval (s : SelectionState) (e : Context) (p : SelectionPlan) (retained : List KB) :
    (applySelection s e [] p [] retained).outcome ≠ .applied := by
  have hv : selectionValid s e p [] retained = false := by simp [selectionValid]
  simp only [applySelection, List.find?, hv, Bool.false_eq_true, ↓reduceIte]
  split <;> simp

/-- Selection does not change support witnesses or observation age; current corrections
remain selected by current time. Snapshot-bound validation is not transferred. -/
theorem selection_witness_unchanged (s : SelectionState) (p : SelectionPlan) (e : Context) (w : Witness) :
    checkWitness (selectedState s p).kb e w = checkWitness s.kb e w := by
  apply T07_check_locality
  induction w with
  | attest id => exact ⟨rfl, fun _ _ => ⟨rfl, rfl, rfl, rfl, rfl⟩⟩
  | truth scope => trivial
  | and a b ia ib => exact ⟨ia, ib⟩
  | specialize scope w ih => exact ih
  | all id pred w ih => exact ⟨rfl, (fun _ _ => rfl), ih⟩
  | absent id w ih => exact ⟨rfl, (fun _ _ => rfl), ih⟩

theorem snapshot_wellFormed (k : KB) (id : SnapshotId)
    (hw : k.wellFormed = true) (hi : token id.val = true) :
    ({ k with snapshot := id }).wellFormed = true := by
  have formulas : ∀ f, formulaRefs { k with snapshot := id } f = formulaRefs k f := by
    intro f; induction f <;> simp_all [formulaRefs, enumerationAt]
  have witnesses : ∀ w, witnessRefs { k with snapshot := id } w = witnessRefs k w := by
    intro w; induction w <;> simp_all [witnessRefs, attestationAt, enumerationAt]
  have dependencies : ∀ d, dependencyWf { k with snapshot := id } d = dependencyWf k d := by
    intro d; cases d <;> simp [dependencyWf, claimAt]
  have oldToken : token k.snapshot.val = true := by
    have copy := hw
    simp only [KB.wellFormed, bool_and] at copy
    simp_all only [bool_and]
  have dependencyFunction : dependencyWf { k with snapshot := id } = dependencyWf k := funext dependencies
  simpa only [KB.wellFormed, formulas, witnesses, dependencyFunction, claimAt, observationAt,
    enumerationAt, supersessionEdges, hi, oldToken] using hw

theorem selection_preserves_wellFormed {s : SelectionState} {e : Context} {p : SelectionPlan}
    {trusted : List VerifiedSelectionApproval} {retained : List KB}
    (h : selectionValid s e p trusted retained = true) :
    selectionStateValid (selectedState s p) = true := by
  simp only [selectionValid, bool_and] at h
  have hs : selectionStateValid s = true := by simp_all
  have hn : token p.newSnapshot.val = true := by simp_all
  have hw : s.kb.wellFormed = true := (bool_and.mp (bool_and.mp hs).1).1
  have newWf := snapshot_wellFormed s.kb p.newSnapshot hw hn
  cases ht : retained.find? (fun k => k.snapshot == p.targetSnapshot) with
  | none => simp [ht] at h
  | some target =>
      have tail := h.2
      simp only [ht, bool_and] at tail
      have hu : unique p.selected = true := tail.1.2
      have hr := tail.2
      simpa [selectionStateValid, selectedState, newWf, hu, claimAt] using hr

theorem T03_selection_applied_wellFormed {s : SelectionState} {e : Context} {js : List SelectionJournalEntry}
    {p : SelectionPlan} {trusted : List VerifiedSelectionApproval} {retained : List KB}
    (h : (applySelection s e js p trusted retained).outcome = .applied) :
    selectionStateValid (applySelection s e js p trusted retained).state = true := by
  have details := selection_applied_details h
  rw [details.2.2]
  exact selection_preserves_wellFormed details.2.1

theorem selection_rejection_unchanged {s : SelectionState} {e : Context} {js : List SelectionJournalEntry}
    {p : SelectionPlan} {trusted : List VerifiedSelectionApproval} {retained : List KB}
    (h : (applySelection s e js p trusted retained).outcome ≠ .applied) :
    (applySelection s e js p trusted retained).state = s ∧
      (applySelection s e js p trusted retained).journal = js := by
  unfold applySelection at *
  split
  · exact ⟨rfl, rfl⟩
  · split
    · exact ⟨rfl, rfl⟩
    · split
      · simp_all
      · exact ⟨rfl, rfl⟩

theorem selection_changed_input_conflicts {s : SelectionState} {e : Context} {js : List SelectionJournalEntry}
    {p q : SelectionPlan} {trusted : List VerifiedSelectionApproval} {retained : List KB}
    (h : (applySelection s e js p trusted retained).outcome = .applied)
    (hid : q.id = p.id) (changed : p ≠ q) :
    let result := applySelection s e js p trusted retained
    applySelection result.state e result.journal q [] retained =
      ⟨result.state, result.journal, .inputConflict⟩ := by
  have details := (selection_applied_details h).2.2
  dsimp only
  rw [details]
  simp [applySelection, List.find?, hid, changed]

end Kctx
