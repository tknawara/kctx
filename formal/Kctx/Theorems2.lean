import Kctx.Codec
import Kctx.Locality

set_option autoImplicit false
set_option maxHeartbeats 1600000
namespace Kctx

/-- Full state boundary, including uniqueness, references and supersession acyclicity. -/
theorem T01_admission_wellFormed {k v : KB} (h : admitKB k = some v) :
    v.wellFormed = true := admitKB_sound h

/-- The canonical internal value is retained exactly at the admitted boundary. -/
theorem T02_admitted_identity {k : KB} (h : k.wellFormed = true) :
    admitKB k = some k := admitKB_complete h

private theorem applied_details {k : KB} {e : Context} {js : List JournalEntry}
    {p : Plan} {trusted : List VerifiedApproval}
    (h : (applyPlan k e js p trusted).outcome = .applied) :
    p.expectedSnapshot = k.snapshot ∧ authorized e p trusted = true ∧ planValid k e p = true ∧
      applyPlan k e js p trusted = ⟨p.candidate, ⟨p⟩ :: js, .applied⟩ := by
  cases hf : js.find? (fun j => j.plan.id == p.id) with
  | some j =>
      simp only [applyPlan, hf] at h
      split at h <;> contradiction
  | none =>
      simp only [applyPlan, hf] at h ⊢
      split at h
      · contradiction
      · next predecessor =>
          split at h
          · next valid =>
              have hp : p.expectedSnapshot = k.snapshot := by simpa using predecessor
              have hv := bool_and.mp valid
              simp [hp, hv.1, hv.2]
          · contradiction

theorem T03_operation_preserves_wf {k : KB} {e : Context} {js : List JournalEntry}
    {p : Plan} {trusted : List VerifiedApproval}
    (h : (applyPlan k e js p trusted).outcome = .applied) :
    (applyPlan k e js p trusted).kb.wellFormed = true := by
  have hd := applied_details h
  rw [hd.2.2.2]
  have hv := hd.2.2.1
  simp only [planValid, bool_and] at hv
  simp_all

/-- Computed exact dependency mismatch rejects reuse even if all caller IDs match. -/
theorem T08_dependency_mismatch {k : KB} {e : Context} {r : Ref} {receipt : Receipt}
    (h : ∀ d ∈ k.derivations, d.claim = r → d.witness = receipt.witness →
      ∀ result, checkedDerivation k e d = some result → result.dependencies ≠ receipt.dependencies) :
    reusable k e r receipt = false := by
  apply Bool.eq_false_iff.mpr
  intro accepted
  simp only [reusable, bool_and] at accepted
  obtain ⟨d, hd, good⟩ := List.any_eq_true.mp accepted.2
  have pieces := bool_and.mp good
  have ids := bool_and.mp pieces.1
  cases hc : checkedDerivation k e d with
  | none => simp [hc] at pieces
  | some result =>
      have dep : result.dependencies = receipt.dependencies := by simpa [hc] using pieces.2
      exact h d hd (eq_of_beq ids.1) (eq_of_beq ids.2) result hc dep

theorem T09_alternative_survives {k : KB} {e : Context} {r : Ref} {p : Polarity}
    (hr : supportAlternatives k e r p ≠ []) : supported k e r p = true := by
  simp [supported, List.isEmpty_iff, hr]

theorem T10_no_alternatives {k : KB} {e : Context} {r : Ref} {p : Polarity}
    (hr : supportAlternatives k e r p = []) : supported k e r p = false := by
  simp [supported, hr]

theorem T11_expiry_monotone {o : TtlPolicy} {observed now later : Int}
    (h : assessFresh o observed now = .stale) (hl : now ≤ later) :
    assessFresh o observed later = .stale := assessFresh_stale_mono h hl

/-- Specialization cannot mint observation times or omit any dependency. -/
theorem T12_specialization_preserves_inputs {k : KB} {e : Context} {w : Witness}
    {r out : Checked} {s : Scope} (hr : checkWitness k e w = some r)
    (h : checkWitness k e (.specialize s w) = some out) :
    narrower s r.statement.scope ∧ out.dependencies = r.dependencies ∧
      out.statement.formula = r.statement.formula ∧ out.statement.scope = s := by
  simp only [checkWitness, hr, bind, Option.bind] at h
  split at h
  · cases h; exact ⟨‹_›, rfl, rfl, rfl⟩
  · contradiction

theorem T12_conjunction_exact_scope {k : KB} {e : Context} {a b : Witness} {r : Checked}
    (h : checkWitness k e (.and a b) = some r) :
    ∃ ra rb, checkWitness k e a = some ra ∧ checkWitness k e b = some rb ∧
      ra.statement.scope = rb.statement.scope ∧ r.statement.scope = ra.statement.scope ∧
      r.dependencies = mergeDependencies ra.dependencies rb.dependencies := by
  have hd := T04_checker_sound h
  cases hd with
  | and ha hb allowed =>
      exact ⟨_, _, finite_witness_complete ha, finite_witness_complete hb,
        eq_of_beq (bool_and.mp (bool_and.mp allowed).1).1, rfl, rfl⟩

theorem T13_coverage_requires_members {k : KB} {e : Context} {id : EnumerationId} {p : String} {w : Witness} {r : Checked}
    (h : checkWitness k e (.all id p w) = some r) :
    ∃ z o a, enumerationEvidence k e id = some (z, o) ∧ Derives k e w a ∧
      a.statement = ⟨.and (.inventory z.id) (memberFormula z.members p), z.scope, .positive⟩ := by
  cases T04_checker_sound h with
  | all hz hw ha => exact ⟨_, _, _, hz, hw, eq_of_beq (bool_and.mp ha).2⟩

theorem T13_absence_requires_empty_inventory {k : KB} {e : Context} {id : EnumerationId} {w : Witness} {r : Checked}
    (h : checkWitness k e (.absent id w) = some r) :
    ∃ z o a, enumerationEvidence k e id = some (z, o) ∧ z.members = [] ∧
      Derives k e w a ∧ a.statement = ⟨.inventory z.id, z.scope, .positive⟩ := by
  cases T04_checker_sound h with
  | absent hz hw ha => exact ⟨_, _, _, hz, eq_of_beq (bool_and.mp ha).1, hw, eq_of_beq (bool_and.mp ha).2⟩

/-- Unsupported arbitrary atoms cannot be fabricated by navigation or rule composition. -/
theorem T14_no_arbitrary_atom {k : KB} {e : Context}
    (h : EvidenceSound falseInterpretation k e) (w : Witness) (r : Checked)
    (a : Atom) (s : Scope) (p : Polarity) (hr : r.statement = ⟨.atom a, s, p⟩) :
    checkWitness k e w ≠ some r := unsupported_atom_impossible h w r a s p hr

theorem T17_usable_policy {k : KB} {e : Context} {r : Ref}
    (h : usableFor k e r = true) :
    (assess k e r).applicable = true ∧
    (e.policy.requireFresh = true → (assess k e r).freshness = .fresh) ∧
    (e.policy.requireValidation = true → (assess k e r).validated = true) ∧
    (e.policy.requireUncontested = true → (assess k e r).contested = false) := by
  simp only [usableFor, assess, bool_and] at h ⊢
  cases hf : e.policy.requireFresh <;> cases hv : e.policy.requireValidation <;> cases hu : e.policy.requireUncontested <;>
    simp_all

theorem T18_transition_conditions {k : KB} {e : Context} {p : Proposal} {target : ProposalStatus}
    (h : transition k e p target = true) :
    legalTransition p.status target = true ∧ identPresent p.actor = true ∧
    usableFor k e p.target = true ∧
    ∀ id ∈ p.gates, ∃ r ∈ k.receipts, r.id = id ∧ reusable k e p.target r = true := by
  simp only [transition, bool_and] at h
  have allGates : p.gates.all (fun id => k.receipts.any (fun r => r.id == id && reusable k e p.target r)) = true := by
    simp_all
  refine ⟨?_, ?_, ?_, ?_⟩
  · simp_all
  · simp_all
  · simp_all
  · intro id hi
    obtain ⟨r, hr, hg⟩ := List.any_eq_true.mp ((List.all_eq_true.mp allGates) id hi)
    exact ⟨r, hr, eq_of_beq (bool_and.mp hg).1, (bool_and.mp hg).2⟩

theorem T18_authored_bound_gates {p : AuthoredProposal} {now : Nat}
    (h : authoredTransition p .verified now = true) :
    hasPhase p .deploy = true ∧ hasPhase p .use = true ∧
    p.gateDefinitions.all (gatePassed p now) = true ∧ p.landedRefs ≠ [] := by
  simp only [authoredTransition, authoredCandidateValid, bool_and] at h
  simp_all [List.isEmpty_iff]

theorem T19_conclusion_conditions {i : Investigation} (h : conclude i = true) :
    nonblank i.checkedAgainst = true ∧ nonblank i.scopeAndLimits = true ∧
    ∀ hypothesis ∈ i.hypotheses, nonblank hypothesis.text = true ∧ hypothesis.status ≠ .open := by
  simpa [conclude, List.all_eq_true, bool_and, and_assoc] using h

theorem T20_expected_predecessor {k : KB} {e : Context} {js : List JournalEntry}
    {p : Plan} {trusted : List VerifiedApproval}
    (h : (applyPlan k e js p trusted).outcome = .applied) :
    p.expectedSnapshot = k.snapshot := (applied_details h).1

theorem T20_rejection_unchanged {k : KB} {e : Context} {js : List JournalEntry}
    {p : Plan} {trusted : List VerifiedApproval}
    (h : (applyPlan k e js p trusted).outcome ≠ .applied) :
    (applyPlan k e js p trusted).kb = k ∧ (applyPlan k e js p trusted).journal = js := by
  unfold applyPlan at *
  split <;> rename_i branch
  · exact ⟨rfl, rfl⟩
  · split
    · exact ⟨rfl, rfl⟩
    · split
      · simp_all
      · exact ⟨rfl, rfl⟩

theorem T21_applied_replay {k : KB} {e : Context} {js : List JournalEntry}
    {p : Plan} {trusted : List VerifiedApproval}
    (h : (applyPlan k e js p trusted).outcome = .applied) :
    let applied := applyPlan k e js p trusted
    applyPlan applied.kb e applied.journal p [] = ⟨applied.kb, applied.journal, .alreadyApplied⟩ := by
  have hd := (applied_details h).2.2.2
  dsimp only
  rw [hd]
  simp [applyPlan, List.find?]

theorem T21_changed_input_conflicts {k : KB} {e : Context} {js : List JournalEntry}
    {p q : Plan} {trusted : List VerifiedApproval}
    (h : (applyPlan k e js p trusted).outcome = .applied)
    (hid : q.id = p.id) (changed : p ≠ q) :
    let applied := applyPlan k e js p trusted
    applyPlan applied.kb e applied.journal q [] = ⟨applied.kb, applied.journal, .inputConflict⟩ := by
  have hd := (applied_details h).2.2.2
  dsimp only
  rw [hd]
  simp [applyPlan, List.find?, hid, changed]

theorem no_self_issued_authority (k : KB) (e : Context) (p : Plan) :
    (applyPlan k e [] p []).outcome ≠ .applied := by
  simp only [applyPlan, List.find?, authorized, List.any_nil, Bool.and_false]
  split <;> simp

theorem applied_authority_exact {k : KB} {e : Context} {js : List JournalEntry}
    {p : Plan} {trusted : List VerifiedApproval}
    (h : (applyPlan k e js p trusted).outcome = .applied) :
    ∃ approval ∈ trusted, approval.plan = p := by
  have ha := (bool_and.mp (applied_details h).2.1).2
  obtain ⟨a, ha, he⟩ := List.any_eq_true.mp ha
  exact ⟨a, ha, eq_of_beq he⟩

theorem T18_exact_signed_context {k : KB} {e : Context} {p : Plan}
    (h : planValid k e p = true) :
    p.authority.context = e ∧ p.authority.approved = p.candidate ∧
    p.authority.approvals = p.candidate.claims.drop k.claims.length := by
  simp only [planValid, bool_and] at h
  simp_all

theorem T18_authored_candidate_conditions {p : AuthoredProposal} {target : AuthoredStatus} {now : Nat}
    (h : authoredCandidateValid p target now = true) :
    (target = .superseded → replacementValid p = true) ∧
    (target = .applied → hasPhase p .land = true ∧
      (p.gateDefinitions.filter (fun g => g.when == .land)).all (gatePassed p now) = true ∧ p.landedRefs ≠ []) ∧
    (target = .verified → p.gateDefinitions.all (gatePassed p now) = true ∧
      p.acceptedRevision = p.proposalRevision ∧ identPresent p.acceptedRevision = true) := by
  cases target <;> simp_all [authoredCandidateValid, bool_and, List.isEmpty_iff]
  rcases h with ⟨⟨⟨⟨⟨⟨hn, he⟩, _⟩, _⟩, _⟩, _⟩, _⟩
  simpa [← he] using hn

theorem T18_factual_execution_conditions {k : KB} {e : Context} {p : Proposal} {target : ProposalStatus}
    (h : transition k e p target = true) :
    (target = .applied → identPresent p.executor = true ∧ p.gates ≠ []) ∧
    (target = .verified → identPresent p.executor = true ∧ identPresent p.acceptor = true ∧
      p.executor ≠ p.acceptor ∧ p.gates ≠ []) := by
  cases target <;> simp_all [transition, bool_and, List.isEmpty_iff]

theorem T22_deterministic (k : KB) (e : Context) (w : Witness) :
    check k e w = check k e w := rfl

end Kctx
