import Kctx.Selection
import Kctx.Theorems2

set_option autoImplicit false
namespace Kctx

structure NamedContext where
  id : ContextId
  context : Context
  deriving DecidableEq, Repr, Inhabited
structure ClaimAssignment where
  claim : Ref
  context : ContextId
  witness : Witness
  deriving DecidableEq, Repr, Inhabited
structure PortfolioState where
  kb : KB
  selected : List Ref
  contexts : List NamedContext
  deriving DecidableEq, Repr, Inhabited
structure PortfolioPlan where
  id : OperationId
  expectedSnapshot : SnapshotId
  candidate : KB
  actor : ActorId
  contexts : List NamedContext
  assignments : List ClaimAssignment
  retiredContexts : List ContextId
  deriving DecidableEq, Repr, Inhabited
structure VerifiedPortfolioApproval where
  plan : PortfolioPlan
  deriving DecidableEq, Repr, Inhabited
structure PortfolioJournalEntry where
  plan : PortfolioPlan
  deriving DecidableEq, Repr, Inhabited
structure PortfolioResult where
  state : PortfolioState
  journal : List PortfolioJournalEntry
  outcome : ApplyOutcome
  deriving DecidableEq, Repr, Inhabited
structure PortfolioSelectionPlan where
  id : OperationId
  expectedSnapshot : SnapshotId
  retainedSnapshot : SnapshotId
  newSnapshot : SnapshotId
  actor : ActorId
  contexts : List NamedContext
  selected : List Ref
  deriving DecidableEq, Repr, Inhabited
structure VerifiedPortfolioSelectionApproval where
  plan : PortfolioSelectionPlan
  deriving DecidableEq, Repr, Inhabited
structure PortfolioSelectionJournalEntry where
  plan : PortfolioSelectionPlan
  deriving DecidableEq, Repr, Inhabited
structure PortfolioSelectionResult where
  state : PortfolioState
  journal : List PortfolioSelectionJournalEntry
  outcome : ApplyOutcome
  deriving DecidableEq, Repr, Inhabited

def contextFamilyValid (k : KB) (contexts : List NamedContext) : Bool :=
  unique (contexts.map (·.id)) &&
  contexts.all (fun c => token c.id.val && contextValid k c.context)

def portfolioStateValid (s : PortfolioState) : Bool :=
  selectionStateValid ⟨s.kb, s.selected⟩ && contextFamilyValid s.kb s.contexts &&
  (!s.contexts.isEmpty || s.kb.claims.isEmpty)

def retiredContextIds (before after : List NamedContext) : List ContextId :=
  (before.filter (fun c => !(after.map (·.id)).contains c.id)).map (·.id)

def contextEvolutionValid (before after : List NamedContext) (retired : List ContextId) : Bool :=
  retired == retiredContextIds before after && unique retired &&
  before.all (fun old => match after.find? (fun c => c.id == old.id) with
    | none => true
    | some next => next.context.target == old.context.target &&
        next.context.intendedUse == old.context.intendedUse)

def assignmentValid (candidate : KB) (contexts : List NamedContext) (a : ClaimAssignment) : Bool :=
  match contexts.find? (fun c => c.id == a.context), claimAt candidate a.claim with
  | some named, some claim =>
      match check candidate named.context a.witness with
      | some checked => checked.statement == claim.statement &&
          candidate.derivations.any (fun d => d.claim == a.claim && d.witness == a.witness) &&
          usableFor candidate named.context a.claim
      | none => false
  | _, _ => false

def portfolioAddedRefs (s : PortfolioState) (p : PortfolioPlan) : List Ref :=
  (p.candidate.claims.drop s.kb.claims.length).map Claim.ref

def admittedPortfolio (s : PortfolioState) (p : PortfolioPlan) : PortfolioState :=
  ⟨p.candidate, s.selected ++ portfolioAddedRefs s p, p.contexts⟩

def portfolioPlanValid (s : PortfolioState) (p : PortfolioPlan) : Bool :=
  portfolioStateValid s &&
  p.candidate.snapshot != s.kb.snapshot && extendsKB s.kb p.candidate &&
  nonblank p.actor.val && token p.id.val && !p.contexts.isEmpty &&
  p.contexts.all (fun c => c.context.policy.authorizedActors.contains p.actor) &&
  contextEvolutionValid s.contexts p.contexts p.retiredContexts &&
  p.assignments.map (·.claim) == portfolioAddedRefs s p &&
  p.assignments.all (assignmentValid p.candidate p.contexts) &&
  portfolioStateValid (admittedPortfolio s p)

def applyPortfolio (s : PortfolioState) (journal : List PortfolioJournalEntry)
    (p : PortfolioPlan) (trusted : List VerifiedPortfolioApproval := []) : PortfolioResult :=
  match journal.find? (fun j => j.plan.id == p.id) with
  | some j => ⟨s, journal, if j.plan == p then .alreadyApplied else .inputConflict⟩
  | none => if p.expectedSnapshot != s.kb.snapshot then ⟨s, journal, .predecessorConflict⟩
    else if trusted.any (fun a => a.plan == p) && portfolioPlanValid s p then
      ⟨admittedPortfolio s p, ⟨p⟩ :: journal, .applied⟩
    else ⟨s, journal, .rejected⟩

def queryContextAllowed (s : PortfolioState) (id : ContextId) (query : Context) : Bool :=
  contextFamilyValid s.kb s.contexts && contextValid s.kb query &&
  match s.contexts.find? (fun c => c.id == id) with
  | none => false
  | some approved => query == { approved.context with target := query.target, now := query.now } &&
      decide (narrower query.target approved.context.target) && decide (approved.context.now ≤ query.now)

def assessPortfolio (s : PortfolioState) (id : ContextId) (query : Context) (ref : Ref) : Option Assessment :=
  if queryContextAllowed s id query && s.selected.contains ref then some (assess s.kb query ref)
  else none

def selectedPortfolio (s : PortfolioState) (p : PortfolioSelectionPlan) : PortfolioState :=
  ⟨{ s.kb with snapshot := p.newSnapshot }, p.selected, p.contexts⟩

/-- Equality of full records, modulo only the newly signed clock and snapshot. -/
def selectionContextsValid (before after : List NamedContext) (snapshot : SnapshotId) : Bool :=
  before.map (·.id) == after.map (·.id) && after.all (fun next =>
    match before.find? (fun old => old.id == next.id) with
    | none => false
    | some old => next.context == { old.context with snapshot := snapshot, now := next.context.now } &&
        decide (old.context.now ≤ next.context.now))

def portfolioSelectionValid (s : PortfolioState) (p : PortfolioSelectionPlan)
    (retained : List PortfolioState) : Bool :=
  portfolioStateValid s && token p.id.val && token p.newSnapshot.val &&
  nonblank p.actor.val && p.newSnapshot != s.kb.snapshot &&
  !retained.any (fun old => old.kb.snapshot == p.newSnapshot) &&
  unique (retained.map (fun old => old.kb.snapshot)) &&
  !p.contexts.isEmpty && selectionContextsValid s.contexts p.contexts p.newSnapshot &&
  p.contexts.all (fun c => c.context.policy.authorizedActors.contains p.actor) &&
  portfolioStateValid (selectedPortfolio s p) &&
  match retained.find? (fun old => old.kb.snapshot == p.retainedSnapshot) with
  | none => false
  | some old => portfolioStateValid old && extendsKB old.kb s.kb && p.selected == old.selected

def applyPortfolioSelection (s : PortfolioState) (journal : List PortfolioSelectionJournalEntry)
    (p : PortfolioSelectionPlan) (trusted : List VerifiedPortfolioSelectionApproval := [])
    (retained : List PortfolioState := []) : PortfolioSelectionResult :=
  match journal.find? (fun j => j.plan.id == p.id) with
  | some j => ⟨s, journal, if j.plan == p then .alreadyApplied else .inputConflict⟩
  | none => if p.expectedSnapshot != s.kb.snapshot then ⟨s, journal, .predecessorConflict⟩
    else if trusted.any (fun a => a.plan == p) && portfolioSelectionValid s p retained then
      ⟨selectedPortfolio s p, ⟨p⟩ :: journal, .applied⟩
    else ⟨s, journal, .rejected⟩

 theorem portfolio_applied_details {s : PortfolioState} {js : List PortfolioJournalEntry}
    {p : PortfolioPlan} {trusted : List VerifiedPortfolioApproval}
    (h : (applyPortfolio s js p trusted).outcome = .applied) :
    p.expectedSnapshot = s.kb.snapshot ∧
    trusted.any (fun a => a.plan == p) = true ∧ portfolioPlanValid s p = true ∧
    applyPortfolio s js p trusted = ⟨admittedPortfolio s p, ⟨p⟩ :: js, .applied⟩ := by
  cases hf : js.find? (fun j => j.plan.id == p.id) with
  | some j =>
      simp only [applyPortfolio, hf] at h
      split at h <;> contradiction
  | none =>
      simp only [applyPortfolio, hf] at h ⊢
      split at h
      · contradiction
      · next predecessor =>
          split at h
          · next valid =>
              have hp : p.expectedSnapshot = s.kb.snapshot := by simpa using predecessor
              have hv := bool_and.mp valid
              simp [hp, hv.1, hv.2]
          · contradiction

theorem portfolio_applied_preserves {s : PortfolioState} {js : List PortfolioJournalEntry}
    {p : PortfolioPlan} {trusted : List VerifiedPortfolioApproval}
    (h : (applyPortfolio s js p trusted).outcome = .applied) :
    portfolioStateValid (applyPortfolio s js p trusted).state = true ∧
    extendsKB s.kb (applyPortfolio s js p trusted).state.kb = true := by
  have hd := portfolio_applied_details h
  rw [hd.2.2.2]
  have hv := hd.2.2.1
  simp only [portfolioPlanValid, bool_and] at hv
  simp_all [admittedPortfolio]

theorem portfolio_exact_capability {s : PortfolioState} {js : List PortfolioJournalEntry}
    {p : PortfolioPlan} {trusted : List VerifiedPortfolioApproval}
    (h : (applyPortfolio s js p trusted).outcome = .applied) :
    ∃ a ∈ trusted, a.plan = p := by
  have ht := (portfolio_applied_details h).2.1
  obtain ⟨a, member, exactPlan⟩ := List.any_eq_true.mp ht
  exact ⟨a, member, eq_of_beq exactPlan⟩

theorem portfolio_no_self_approval (s : PortfolioState) (js : List PortfolioJournalEntry) (p : PortfolioPlan) :
    (applyPortfolio s js p []).outcome ≠ .applied := by
  intro h
  have ht := (portfolio_applied_details h).2.1
  simp at ht

theorem assignment_named_witness {k : KB} {cs : List NamedContext} {a : ClaimAssignment}
    (h : assignmentValid k cs a = true) :
    ∃ named claim checked,
      cs.find? (fun c => c.id == a.context) = some named ∧
      claimAt k a.claim = some claim ∧ check k named.context a.witness = some checked ∧
      checked.statement = claim.statement ∧
      k.derivations.any (fun d => d.claim == a.claim && d.witness == a.witness) = true ∧
      usableFor k named.context a.claim = true := by
  cases hn : cs.find? (fun c => c.id == a.context) with
  | none => simp [assignmentValid, hn] at h
  | some named =>
    cases hc : claimAt k a.claim with
    | none => simp [assignmentValid, hn, hc] at h
    | some claim =>
      cases hw : check k named.context a.witness with
      | none => simp [assignmentValid, hn, hc, hw] at h
      | some checked =>
        simp only [assignmentValid, hn, hc, hw, bool_and] at h
        exact ⟨named, claim, checked, by simp [hn], by simp [hc], hw,
          eq_of_beq h.1.1, h.1.2, h.2⟩

/-- A portfolio assignment introduces no new derivation constructor. Its exact
claim is derived by the unchanged finite-witness judgment in one named context. -/
theorem assignment_core_derivation {k : KB} {cs : List NamedContext} {a : ClaimAssignment}
    (h : assignmentValid k cs a = true) :
    ∃ named claim raw,
      cs.find? (fun c => c.id == a.context) = some named ∧
      claimAt k a.claim = some claim ∧ Derives k named.context a.witness raw ∧
      raw.statement = claim.statement := by
  obtain ⟨named, claim, checked, hn, hc, hw, exactStatement, _, _⟩ := assignment_named_witness h
  obtain ⟨raw, derived, projected⟩ := (T04_public_check_sound hw).2
  exact ⟨named, claim, raw, hn, hc, derived, projected.symm.trans exactStatement⟩

/-- External evidence soundness is required only for the selected context's
actual admitted leaves, exactly as in the v2 interpretation theorem. -/
theorem assignment_interpretation_sound {i : Interpretation} {k : KB}
    {cs : List NamedContext} {a : ClaimAssignment}
    (h : assignmentValid k cs a = true)
    (evidence : ∀ named, cs.find? (fun c => c.id == a.context) = some named →
      EvidenceSound i k named.context) :
    ∃ claim, claimAt k a.claim = some claim ∧ Holds i k claim.statement := by
  obtain ⟨named, claim, raw, hn, hc, derived, exactStatement⟩ := assignment_core_derivation h
  have sound := T05_derives_sound (evidence named hn) derived
  exact ⟨claim, hc, by simpa [exactStatement] using sound⟩

theorem portfolio_added_claim_assignment {s : PortfolioState} {p : PortfolioPlan}
    (h : portfolioPlanValid s p = true) {r : Ref} (hr : r ∈ portfolioAddedRefs s p) :
    ∃ a ∈ p.assignments, a.claim = r ∧ assignmentValid p.candidate p.contexts a = true := by
  have hm : p.assignments.map (·.claim) = portfolioAddedRefs s p := by
    simp only [portfolioPlanValid, bool_and] at h
    apply eq_of_beq
    simp_all
  have ha : p.assignments.all (assignmentValid p.candidate p.contexts) = true := by
    simp only [portfolioPlanValid, bool_and] at h
    simp_all
  rw [← hm] at hr
  obtain ⟨a, hin, heq⟩ := List.mem_map.mp hr
  exact ⟨a, hin, heq, List.all_eq_true.mp ha a hin⟩

theorem portfolio_retirement_exact {s : PortfolioState} {p : PortfolioPlan}
    (h : portfolioPlanValid s p = true) :
    p.retiredContexts = retiredContextIds s.contexts p.contexts := by
  simp only [portfolioPlanValid, contextEvolutionValid, bool_and] at h
  apply eq_of_beq
  simp_all

theorem portfolio_query_projection {s : PortfolioState} {id : ContextId} {q : Context} {r : Ref}
    {a : Assessment} (h : assessPortfolio s id q r = some a) : a = assess s.kb q r := by
  unfold assessPortfolio at h
  split at h
  · exact (Option.some.inj h).symm
  · contradiction

theorem portfolio_allowed_query (s : PortfolioState) (id : ContextId) (q : Context) (r : Ref)
    (allowed : queryContextAllowed s id q = true) (selected : s.selected.contains r = true) :
    assessPortfolio s id q r = some (assess s.kb q r) := by
  have member : r ∈ s.selected := by simpa using selected
  simp [assessPortfolio, allowed, member]

/-- Unrelated authorization is not an inference premise. Both scopes must remain allowed. -/
theorem portfolio_authorization_locality {s t : PortfolioState} {id : ContextId} {q : Context} {r : Ref}
    (kb : s.kb = t.kb) (hs : queryContextAllowed s id q = true)
    (ht : queryContextAllowed t id q = true)
    (ss : s.selected.contains r = true) (st : t.selected.contains r = true) :
    assessPortfolio s id q r = assessPortfolio t id q r := by
  rw [portfolio_allowed_query s id q r hs ss, portfolio_allowed_query t id q r ht st, kb]

theorem portfolio_query_named_context {s : PortfolioState} {id : ContextId} {q : Context}
    (h : queryContextAllowed s id q = true) :
    ∃ c, s.contexts.find? (fun c => c.id == id) = some c ∧
      q = { c.context with target := q.target, now := q.now } ∧
      narrower q.target c.context.target ∧ c.context.now ≤ q.now := by
  cases hc : s.contexts.find? (fun c => c.id == id) with
  | none => simp [queryContextAllowed, hc] at h
  | some c =>
      simp only [queryContextAllowed, hc, bool_and] at h
      exact ⟨c, by simp [hc], eq_of_beq h.2.1.1,
        of_decide_eq_true h.2.1.2, of_decide_eq_true h.2.2⟩

theorem portfolio_rejection_unchanged {s : PortfolioState} {js : List PortfolioJournalEntry}
    {p : PortfolioPlan} {trusted : List VerifiedPortfolioApproval}
    (h : (applyPortfolio s js p trusted).outcome ≠ .applied) :
    (applyPortfolio s js p trusted).state = s ∧ (applyPortfolio s js p trusted).journal = js := by
  unfold applyPortfolio at *
  split
  · exact ⟨rfl, rfl⟩
  · split
    · exact ⟨rfl, rfl⟩
    · split
      · simp_all
      · exact ⟨rfl, rfl⟩

theorem portfolio_replay {s : PortfolioState} {js : List PortfolioJournalEntry}
    {p : PortfolioPlan} {trusted : List VerifiedPortfolioApproval}
    (h : (applyPortfolio s js p trusted).outcome = .applied) :
    let result := applyPortfolio s js p trusted
    applyPortfolio result.state result.journal p [] = ⟨result.state, result.journal, .alreadyApplied⟩ := by
  have hd := (portfolio_applied_details h).2.2.2
  dsimp only
  rw [hd]
  simp [applyPortfolio, List.find?]

theorem portfolio_changed_input_conflicts {s : PortfolioState} {js : List PortfolioJournalEntry}
    {p q : PortfolioPlan} {trusted : List VerifiedPortfolioApproval}
    (h : (applyPortfolio s js p trusted).outcome = .applied)
    (hid : q.id = p.id) (changed : p ≠ q) :
    let result := applyPortfolio s js p trusted
    applyPortfolio result.state result.journal q [] = ⟨result.state, result.journal, .inputConflict⟩ := by
  have hd := (portfolio_applied_details h).2.2.2
  dsimp only
  rw [hd]
  simp [applyPortfolio, List.find?, hid, changed]

theorem portfolio_selection_applied_details {s : PortfolioState}
    {js : List PortfolioSelectionJournalEntry} {p : PortfolioSelectionPlan}
    {trusted : List VerifiedPortfolioSelectionApproval} {retained : List PortfolioState}
    (h : (applyPortfolioSelection s js p trusted retained).outcome = .applied) :
    p.expectedSnapshot = s.kb.snapshot ∧ trusted.any (fun a => a.plan == p) = true ∧
    portfolioSelectionValid s p retained = true ∧
    applyPortfolioSelection s js p trusted retained = ⟨selectedPortfolio s p, ⟨p⟩ :: js, .applied⟩ := by
  cases hf : js.find? (fun j => j.plan.id == p.id) with
  | some j =>
      simp only [applyPortfolioSelection, hf] at h
      split at h <;> contradiction
  | none =>
      simp only [applyPortfolioSelection, hf] at h ⊢
      split at h
      · contradiction
      · next predecessor =>
          split at h
          · next valid =>
              have hp : p.expectedSnapshot = s.kb.snapshot := by simpa using predecessor
              have hv := bool_and.mp valid
              simp [hp, hv.1, hv.2]
          · contradiction

theorem portfolio_selection_preserves {s : PortfolioState} {p : PortfolioSelectionPlan}
    {retained : List PortfolioState} (h : portfolioSelectionValid s p retained = true) :
    portfolioStateValid (selectedPortfolio s p) = true := by
  simp only [portfolioSelectionValid, bool_and] at h
  simp_all

theorem portfolio_selection_exact_capability {s : PortfolioState}
    {js : List PortfolioSelectionJournalEntry} {p : PortfolioSelectionPlan}
    {trusted : List VerifiedPortfolioSelectionApproval} {retained : List PortfolioState}
    (h : (applyPortfolioSelection s js p trusted retained).outcome = .applied) :
    ∃ a ∈ trusted, a.plan = p := by
  have ht := (portfolio_selection_applied_details h).2.1
  obtain ⟨a, member, exactPlan⟩ := List.any_eq_true.mp ht
  exact ⟨a, member, eq_of_beq exactPlan⟩

theorem portfolio_selection_no_self_approval (s : PortfolioState)
    (js : List PortfolioSelectionJournalEntry) (p : PortfolioSelectionPlan) (retained : List PortfolioState) :
    (applyPortfolioSelection s js p [] retained).outcome ≠ .applied := by
  intro h
  have ht := (portfolio_selection_applied_details h).2.1
  simp at ht

theorem portfolio_selection_exact_retained {s : PortfolioState} {p : PortfolioSelectionPlan}
    {retained : List PortfolioState} (h : portfolioSelectionValid s p retained = true) :
    ∃ old, retained.find? (fun old => old.kb.snapshot == p.retainedSnapshot) = some old ∧
      p.selected = old.selected ∧ extendsKB old.kb s.kb = true := by
  cases ht : retained.find? (fun old => old.kb.snapshot == p.retainedSnapshot) with
  | none => simp [portfolioSelectionValid, ht] at h
  | some old =>
      simp only [portfolioSelectionValid, ht, bool_and] at h
      exact ⟨old, by simp [ht], eq_of_beq h.2.2, h.2.1.2⟩

theorem portfolio_selection_context_configuration {s : PortfolioState} {p : PortfolioSelectionPlan}
    {retained : List PortfolioState} (h : portfolioSelectionValid s p retained = true)
    {next : NamedContext} (hn : next ∈ p.contexts) :
    ∃ old, s.contexts.find? (fun old => old.id == next.id) = some old ∧
      next.context = { old.context with snapshot := p.newSnapshot, now := next.context.now } ∧
      old.context.now ≤ next.context.now := by
  have hc : selectionContextsValid s.contexts p.contexts p.newSnapshot = true := by
    simp only [portfolioSelectionValid, bool_and] at h
    simp_all
  have ha := List.all_eq_true.mp (bool_and.mp hc).2 next hn
  cases ho : s.contexts.find? (fun old => old.id == next.id) with
  | none => simp [ho] at ha
  | some old =>
      simp only [ho, bool_and] at ha
      exact ⟨old, by simp [ho], eq_of_beq ha.1, of_decide_eq_true ha.2⟩

theorem portfolio_selection_preserves_ledger (s : PortfolioState) (p : PortfolioSelectionPlan) :
    (selectedPortfolio s p).kb.observations = s.kb.observations ∧
    (selectedPortfolio s p).kb.claims = s.kb.claims ∧
    (selectedPortfolio s p).kb.attestations = s.kb.attestations ∧
    (selectedPortfolio s p).kb.enumerations = s.kb.enumerations ∧
    (selectedPortfolio s p).kb.derivations = s.kb.derivations ∧
    (selectedPortfolio s p).kb.corrections = s.kb.corrections ∧
    (selectedPortfolio s p).kb.receipts = s.kb.receipts := ⟨rfl, rfl, rfl, rfl, rfl, rfl, rfl⟩

theorem portfolio_selection_rejection_unchanged {s : PortfolioState}
    {js : List PortfolioSelectionJournalEntry} {p : PortfolioSelectionPlan}
    {trusted : List VerifiedPortfolioSelectionApproval} {retained : List PortfolioState}
    (h : (applyPortfolioSelection s js p trusted retained).outcome ≠ .applied) :
    (applyPortfolioSelection s js p trusted retained).state = s ∧
    (applyPortfolioSelection s js p trusted retained).journal = js := by
  unfold applyPortfolioSelection at *
  split
  · exact ⟨rfl, rfl⟩
  · split
    · exact ⟨rfl, rfl⟩
    · split
      · simp_all
      · exact ⟨rfl, rfl⟩

theorem portfolio_selection_replay {s : PortfolioState}
    {js : List PortfolioSelectionJournalEntry} {p : PortfolioSelectionPlan}
    {trusted : List VerifiedPortfolioSelectionApproval} {retained : List PortfolioState}
    (h : (applyPortfolioSelection s js p trusted retained).outcome = .applied) :
    let result := applyPortfolioSelection s js p trusted retained
    applyPortfolioSelection result.state result.journal p [] retained =
      ⟨result.state, result.journal, .alreadyApplied⟩ := by
  have hd := (portfolio_selection_applied_details h).2.2.2
  dsimp only
  rw [hd]
  simp [applyPortfolioSelection, List.find?]

theorem portfolio_selection_changed_input_conflicts {s : PortfolioState}
    {js : List PortfolioSelectionJournalEntry} {p q : PortfolioSelectionPlan}
    {trusted : List VerifiedPortfolioSelectionApproval} {retained : List PortfolioState}
    (h : (applyPortfolioSelection s js p trusted retained).outcome = .applied)
    (hid : q.id = p.id) (changed : p ≠ q) :
    let result := applyPortfolioSelection s js p trusted retained
    applyPortfolioSelection result.state result.journal q [] retained =
      ⟨result.state, result.journal, .inputConflict⟩ := by
  have hd := (portfolio_selection_applied_details h).2.2.2
  dsimp only
  rw [hd]
  simp [applyPortfolioSelection, List.find?, hid, changed]

/-- The legacy frame is the predecessor; the portfolio frame is the candidate.
Only the snapshot is rebased, never the policy, selector, target or clock. -/
def singletonPortfolioPlan (id : ContextId) (e : Context) (p : Plan) : PortfolioPlan :=
  ⟨p.id, p.expectedSnapshot, p.candidate, p.authority.actor,
    [⟨id, { e with snapshot := p.candidate.snapshot }⟩],
    [⟨p.claim, id, p.witness⟩], []⟩

theorem legacy_plan_named_assignment {k : KB} {e : Context} {p : Plan}
    (id : ContextId) (h : planValid k e p = true) :
    assignmentValid p.candidate
      [⟨id, { e with snapshot := p.candidate.snapshot }⟩]
      ⟨p.claim, id, p.witness⟩ = true := by
  simp only [planValid, bool_and] at h
  cases hc : claimAt p.candidate p.claim with
  | none => simp [hc] at h
  | some claim =>
    cases hw : check p.candidate { e with snapshot := p.candidate.snapshot } p.witness with
    | none => simp [hc, hw] at h
    | some checked =>
      simp only [hc, hw, bool_and] at h
      simp_all [assignmentValid, List.find?]

/-- A single newly added claim admits the legacy witness assignment. The explicit
compatibility assumptions are valid input/output selections, one stable context
identity, exact one-claim delta, and the separately authenticated actor policy.
No equivalence is asserted for old multi-claim plans lacking per-claim witnesses. -/
theorem singleton_legacy_embedding {s : PortfolioState} {e : Context} {p : Plan}
    (id : ContextId) (legacy : planValid s.kb e p = true)
    (state : portfolioStateValid s = true)
    (contexts : s.contexts = [⟨id, e⟩])
    (output : portfolioStateValid (admittedPortfolio s (singletonPortfolioPlan id e p)) = true)
    (delta : portfolioAddedRefs s (singletonPortfolioPlan id e p) = [p.claim])
    (actor : e.policy.authorizedActors.contains p.authority.actor = true) :
    portfolioPlanValid s (singletonPortfolioPlan id e p) = true := by
  have assignment := legacy_plan_named_assignment id legacy
  have operation : token p.id.val = true := by
    simp only [planValid, bool_and] at legacy
    simp_all
  have changed : (p.candidate.snapshot != s.kb.snapshot) = true := by
    simp only [planValid, bool_and] at legacy
    simp_all
  have prefixPreserved : extendsKB s.kb p.candidate = true := by
    simp only [planValid, bool_and] at legacy
    simp_all
  have present : nonblank p.authority.actor.val = true := by
    simp only [planValid, bool_and] at legacy
    simp_all
  have authorized : p.authority.actor ∈ e.policy.authorizedActors := by simpa using actor
  simp only [portfolioPlanValid, state, output, delta]
  simp [singletonPortfolioPlan, operation, changed, prefixPreserved, present, authorized,
    assignment, contexts, contextEvolutionValid, retiredContextIds, unique, List.find?]

/-- This is a direct output-shape check, independent of the inference projection
and exact-capability laws above. -/
theorem portfolio_plan_output_valid {s : PortfolioState} {p : PortfolioPlan}
    (h : portfolioPlanValid s p = true) :
    portfolioStateValid (admittedPortfolio s p) = true :=
  (bool_and.mp h).2

theorem portfolio_selection_applied_preserves {s : PortfolioState}
    {js : List PortfolioSelectionJournalEntry} {p : PortfolioSelectionPlan}
    {trusted : List VerifiedPortfolioSelectionApproval} {retained : List PortfolioState}
    (h : (applyPortfolioSelection s js p trusted retained).outcome = .applied) :
    portfolioStateValid (applyPortfolioSelection s js p trusted retained).state = true := by
  have hd := portfolio_selection_applied_details h
  rw [hd.2.2.2]
  exact portfolio_selection_preserves hd.2.2.1

/-- Changing other authorization entries does not change this lookup's permission
or assessment, provided both families remain valid and the KB/selection are fixed. -/
theorem portfolio_unrelated_context_noninterference {s t : PortfolioState}
    (id : ContextId) (q : Context) (r : Ref)
    (kb : s.kb = t.kb) (selected : s.selected = t.selected)
    (sf : contextFamilyValid s.kb s.contexts = true)
    (tf : contextFamilyValid t.kb t.contexts = true)
    (lookup : s.contexts.find? (fun c => c.id == id) =
      t.contexts.find? (fun c => c.id == id)) :
    queryContextAllowed s id q = queryContextAllowed t id q ∧
    assessPortfolio s id q r = assessPortfolio t id q r := by
  have allowed : queryContextAllowed s id q = queryContextAllowed t id q := by
    have sameFamily : contextFamilyValid t.kb s.contexts = true := by simpa [kb] using sf
    simp only [queryContextAllowed, kb, sameFamily, tf, lookup]
  exact ⟨allowed, by simp only [assessPortfolio, allowed, kb, selected]⟩

theorem portfolio_retained_context_identity {before after : List NamedContext}
    {retired : List ContextId} (h : contextEvolutionValid before after retired = true)
    {old next : NamedContext} (member : old ∈ before)
    (found : after.find? (fun c => c.id == old.id) = some next) :
    next.context.target = old.context.target ∧
    next.context.intendedUse = old.context.intendedUse := by
  have ha := List.all_eq_true.mp (bool_and.mp h).2 old member
  simp only [found, bool_and] at ha
  exact ⟨eq_of_beq ha.1, eq_of_beq ha.2⟩

theorem portfolio_selection_extends_ledger (s : PortfolioState) (p : PortfolioSelectionPlan) :
    extendsKB s.kb (selectedPortfolio s p).kb = true := by
  simp [extendsKB, selectedPortfolio, isPrefix]

theorem portfolio_wrong_predecessor {s : PortfolioState} {js : List PortfolioJournalEntry}
    {p : PortfolioPlan} (trusted : List VerifiedPortfolioApproval)
    (fresh : js.find? (fun j => j.plan.id == p.id) = none)
    (wrong : p.expectedSnapshot ≠ s.kb.snapshot) :
    applyPortfolio s js p trusted = ⟨s, js, .predecessorConflict⟩ := by
  simp [applyPortfolio, fresh, wrong]

theorem portfolio_selection_wrong_predecessor {s : PortfolioState}
    {js : List PortfolioSelectionJournalEntry} {p : PortfolioSelectionPlan}
    (trusted : List VerifiedPortfolioSelectionApproval) (retained : List PortfolioState)
    (fresh : js.find? (fun j => j.plan.id == p.id) = none)
    (wrong : p.expectedSnapshot ≠ s.kb.snapshot) :
    applyPortfolioSelection s js p trusted retained = ⟨s, js, .predecessorConflict⟩ := by
  simp [applyPortfolioSelection, fresh, wrong]

end Kctx
