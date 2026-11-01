import Kctx.Theorems2

set_option autoImplicit false
set_option maxHeartbeats 1600000
namespace Kctx

/-- A source adapter supplies the concrete source and target revision. The design
revision is the schema-3 design digest, not the historical v2 proposal digest. -/
structure ImplementationBinding where
  designRevision : ProposalRevision
  source : SourceId
  targetRevision : TargetRevision
  actor : ActorId
  observedAt : Nat
  deriving DecidableEq, Repr, Inhabited

structure DesignProposal where
  authored : AuthoredProposal
  targetSource : SourceId
  binding : Option ImplementationBinding
  deriving DecidableEq, Repr, Inhabited

structure DesignBindingCommand where
  expected : DesignProposal
  binding : ImplementationBinding
  deriving DecidableEq, Repr, Inhabited

structure DesignReopenCommand where
  expected : DesignProposal
  actor : ActorId
  reason : String
  deriving DecidableEq, Repr, Inhabited

/-- All checks are on concrete records; source resolution remains an adapter
obligation, never a caller-provided successful-resolution Boolean. -/
def implementationBindingValid (p : DesignProposal) (b : ImplementationBinding) (now : Nat) : Bool :=
  some b.designRevision == p.authored.proposalRevision &&
  some b.designRevision == p.authored.acceptedRevision && b.source == p.targetSource &&
  nonblank b.actor.val && nonblank b.source.val && nonblank b.designRevision.val &&
  nonblank b.targetRevision.val && b.observedAt ≤ now

def implementationBound (p : DesignProposal) (now : Nat) : Bool :=
  match p.binding with
  | none => false
  | some b => implementationBindingValid p b now && some b.targetRevision == p.authored.targetRevision

def designCandidateValid (p : DesignProposal) (target : AuthoredStatus) (now : Nat) : Bool :=
  authoredCandidateValid p.authored target now &&
  (!(target == .accepted || target == .landing || target == .applied || target == .verified) ||
    nonblank p.targetSource.val) &&
  (!(target == .applied || target == .verified) || implementationBound p now)

def designTransition (p : DesignProposal) (target : AuthoredStatus) (now : Nat) : Bool :=
  authoredLegal p.authored.status target && designCandidateValid p target now

/-- Binding never changes design material or gate history. Even an identical
rebind clears landing references: the command does not attest that landing. -/
def designWithBinding (p : DesignProposal) (b : ImplementationBinding) : DesignProposal :=
  { p with
      authored := { p.authored with
        targetRevision := some b.targetRevision
        landedRefs := []
        resolvedLanded := [] }
      binding := some b }

def bindImplementation (current : DesignProposal) (command : DesignBindingCommand)
    (now : Nat) : Option DesignProposal :=
  if current = command.expected ∧
      (current.authored.status = .accepted ∨ current.authored.status = .landing) ∧
      designCandidateValid current current.authored.status now = true ∧
      implementationBindingValid current command.binding now = true then
    some (designWithBinding current command.binding)
  else none

/-- Reopening retains the edited material and historical gate records, but not
acceptance, implementation, execution identity, or landing authority. -/
def designReopened (p : DesignProposal) (actor : ActorId) : DesignProposal :=
  { p with
      authored := { p.authored with
        status := .proposed
        actor := some actor
        acceptedRevision := none
        acceptor := none
        executor := none
        verifier := none
        targetRevision := none
        landedRefs := []
        resolvedLanded := [] }
      binding := none }

def reopenDesign (current : DesignProposal) (command : DesignReopenCommand) : Option DesignProposal :=
  if current = command.expected ∧
      (current.authored.status = .accepted ∨ current.authored.status = .landing) ∧
      nonblank command.actor.val = true ∧ nonblank command.reason = true then
    some (designReopened current command.actor)
  else none

/-- Material represented by the schema-3 digest. Target revisions, acceptance,
landing observations, and gate result history are deliberately not material. -/
def sameDesignMaterial (before after : DesignProposal) : Prop :=
  after.targetSource = before.targetSource ∧
  after.authored.id = before.authored.id ∧
  after.authored.profile = before.authored.profile ∧
  after.authored.researchPresent = before.authored.researchPresent ∧
  after.authored.alternativesCount = before.authored.alternativesCount ∧
  after.authored.proposalRevision = before.authored.proposalRevision ∧
  after.authored.gateDefinitions = before.authored.gateDefinitions ∧
  after.authored.environment = before.authored.environment ∧
  after.authored.scope = before.authored.scope

theorem implementationBindingValid_exact {p : DesignProposal} {b : ImplementationBinding} {now : Nat}
    (h : implementationBindingValid p b now = true) :
    some b.designRevision = p.authored.proposalRevision ∧
    some b.designRevision = p.authored.acceptedRevision ∧ b.source = p.targetSource ∧
    nonblank b.actor.val = true ∧ nonblank b.source.val = true ∧
    nonblank b.designRevision.val = true ∧ nonblank b.targetRevision.val = true ∧
    b.observedAt ≤ now := by
  simpa [implementationBindingValid, bool_and, and_assoc] using h

theorem implementationBound_exact {p : DesignProposal} {now : Nat}
    (h : implementationBound p now = true) :
    ∃ b, p.binding = some b ∧
      some b.designRevision = p.authored.proposalRevision ∧
      some b.designRevision = p.authored.acceptedRevision ∧ b.source = p.targetSource ∧
      some b.targetRevision = p.authored.targetRevision ∧
      nonblank b.actor.val = true ∧ nonblank b.source.val = true ∧
      nonblank b.designRevision.val = true ∧ nonblank b.targetRevision.val = true ∧
      b.observedAt ≤ now := by
  cases hb : p.binding with
  | none => simp [implementationBound, hb] at h
  | some b =>
      have hd : implementationBindingValid p b now = true ∧
          some b.targetRevision = p.authored.targetRevision := by
        simpa [implementationBound, hb, bool_and] using h
      rcases implementationBindingValid_exact hd.1 with ⟨hp, ha, hs, hrest⟩
      exact ⟨b, rfl, hp, ha, hs, hd.2, hrest⟩

theorem designCandidate_legacy {p : DesignProposal} {target : AuthoredStatus} {now : Nat}
    (h : designCandidateValid p target now = true) :
    authoredCandidateValid p.authored target now = true :=
  (bool_and.mp (bool_and.mp h).1).1

theorem designTransition_legacy {p : DesignProposal} {target : AuthoredStatus} {now : Nat}
    (h : designTransition p target now = true) : authoredTransition p.authored target now = true :=
  bool_and.mpr ⟨(bool_and.mp h).1, designCandidate_legacy (bool_and.mp h).2⟩

theorem designCandidate_finalized_bound {p : DesignProposal} {target : AuthoredStatus} {now : Nat}
    (h : designCandidateValid p target now = true)
    (finalized : target = .applied ∨ target = .verified) : implementationBound p now = true := by
  rcases finalized with ht | ht <;> subst target <;>
    simp_all [designCandidateValid, bool_and]

theorem designCandidate_acceptance {p : DesignProposal} {target : AuthoredStatus} {now : Nat}
    (h : designCandidateValid p target now = true)
    (active : target = .accepted ∨ target = .landing ∨ target = .applied ∨ target = .verified) :
    p.authored.acceptedRevision = p.authored.proposalRevision := by
  have legacy := designCandidate_legacy h
  rcases active with ht | ht | ht | ht <;> subst target <;>
    simp_all [authoredCandidateValid, bool_and]

theorem designCandidate_material_edit_rejected {p : DesignProposal} {target : AuthoredStatus} {now : Nat}
    (changed : p.authored.acceptedRevision ≠ p.authored.proposalRevision)
    (active : target = .accepted ∨ target = .landing ∨ target = .applied ∨ target = .verified) :
    designCandidateValid p target now = false := by
  cases h : designCandidateValid p target now with
  | false => rfl
  | true => exact False.elim (changed (designCandidate_acceptance h active))

/-- This is exactly the existing gate lookup predicate, not a second gate policy. -/
def designGateResultMatches (p : AuthoredProposal) (now : Nat) (g : GateDefinition)
    (r : GateResult) : Bool :=
  r.definition == g && r.targetRevision == p.targetRevision &&
  r.proposalRevision == p.proposalRevision && r.environment == p.environment && r.scope == p.scope &&
  identPresent r.checker && (g.checker.isNone || r.checker == g.checker) && r.observedAt ≤ now

/-- Provenance of the actual latest matching recorded pass, including the full
context and all freshness/evidence conditions of the historical gate checker. -/
def DesignGateEvidence (p : AuthoredProposal) (now : Nat) (g : GateDefinition) (r : GateResult) : Prop :=
  r ∈ p.gateResults ∧
  p.gateResults.reverse.find? (designGateResultMatches p now g) = some r ∧
  r.definition = g ∧ r.targetRevision = p.targetRevision ∧
  r.proposalRevision = p.proposalRevision ∧ r.environment = p.environment ∧ r.scope = p.scope ∧
  identPresent r.checker = true ∧ (g.checker.isNone = true ∨ r.checker = g.checker) ∧
  r.observedAt ≤ now ∧ r.result = .pass ∧ now ≤ r.expiresAt ∧ identPresent r.actor = true ∧
  r.evidenceRefs ≠ [] ∧ r.evidenceRefs.all nonblank = true

private theorem design_find_mem {α : Type} (f : α → Bool) (xs : List α) (a : α)
    (h : xs.find? f = some a) : a ∈ xs := by
  induction xs with
  | nil => simp at h
  | cons x xs ih =>
      simp only [List.find?] at h
      split at h
      · cases h; simp
      · exact List.mem_cons_of_mem x (ih h)

theorem design_gate_pass_provenance {p : AuthoredProposal} {now : Nat} {g : GateDefinition}
    (h : gatePassed p now g = true) : ∃ r, DesignGateEvidence p now g r := by
  have passed := (bool_and.mp h).2
  change (match p.gateResults.reverse.find? (designGateResultMatches p now g) with
    | some r => r.result == .pass && now ≤ r.expiresAt && identPresent r.actor &&
        !r.evidenceRefs.isEmpty && r.evidenceRefs.all nonblank
    | none => false) = true at passed
  cases hf : p.gateResults.reverse.find? (designGateResultMatches p now g) with
  | none => simp [hf] at passed
  | some r =>
      have hm := find_predicate (designGateResultMatches p now g) p.gateResults.reverse r hf
      have hr : r ∈ p.gateResults := by
        simpa using design_find_mem (designGateResultMatches p now g) p.gateResults.reverse r hf
      simp only [hf] at passed
      refine ⟨r, hr, hf, ?_⟩
      simpa [designGateResultMatches, bool_and, List.isEmpty_iff, and_assoc] using And.intro hm passed

theorem design_gate_evidence_exact_target {p : AuthoredProposal} {now : Nat}
    {g : GateDefinition} {r : GateResult} (h : DesignGateEvidence p now g r) :
    r.targetRevision = p.targetRevision := h.2.2.2.1

theorem design_gate_wrong_target_excluded {p : AuthoredProposal} {now : Nat}
    {g : GateDefinition} {r : GateResult} (wrong : r.targetRevision ≠ p.targetRevision) :
    designGateResultMatches p now g r = false ∧ ¬ DesignGateEvidence p now g r := by
  refine ⟨?_, fun h => wrong (design_gate_evidence_exact_target h)⟩
  simp [designGateResultMatches, wrong]

theorem design_gate_unmatched_history_rejected {p : AuthoredProposal} {now : Nat} {g : GateDefinition}
    (history : ∀ r ∈ p.gateResults, r.targetRevision ≠ p.targetRevision) :
    gatePassed p now g = false := by
  cases hp : gatePassed p now g with
  | false => rfl
  | true =>
      obtain ⟨r, hr⟩ := design_gate_pass_provenance hp
      exact False.elim ((history r hr.1) (design_gate_evidence_exact_target hr))

/-- The exact legacy landing obligation: every reference resolves, and at least
one selected reference resolves to the bound target. It does not assert that
all references have the same target, which v2 never required. -/
def DesignLandingEvidence (p : AuthoredProposal) : Prop :=
  p.landedRefs ≠ [] ∧ p.landedRefs.all nonblank = true ∧
  (∀ reference ∈ p.landedRefs, ∃ resolved ∈ p.resolvedLanded, resolved.reference = reference) ∧
  ∃ resolved ∈ p.resolvedLanded,
    resolved.reference ∈ p.landedRefs ∧ some resolved.targetRevision = p.targetRevision

theorem designCandidate_landing_evidence {p : DesignProposal} {target : AuthoredStatus} {now : Nat}
    (h : designCandidateValid p target now = true)
    (finalized : target = .applied ∨ target = .verified) : DesignLandingEvidence p.authored := by
  have legacy := designCandidate_legacy h
  have landing : !p.authored.landedRefs.isEmpty && p.authored.landedRefs.all nonblank &&
      p.authored.landedRefs.all (fun ref => p.authored.resolvedLanded.any (fun r => r.reference == ref)) &&
      p.authored.resolvedLanded.any (fun r => p.authored.landedRefs.contains r.reference &&
        some r.targetRevision == p.authored.targetRevision) = true := by
    rcases finalized with ht | ht <;> subst target <;>
      simp_all [authoredCandidateValid, bool_and]
  simpa [DesignLandingEvidence, bool_and, List.isEmpty_iff, List.all_eq_true,
    List.any_eq_true, and_assoc] using landing

theorem designCandidate_applied_evidence {p : DesignProposal} {now : Nat}
    (h : designCandidateValid p .applied now = true) :
    implementationBound p now = true ∧ DesignLandingEvidence p.authored ∧
    hasPhase p.authored .land = true ∧
    ∀ g ∈ p.authored.gateDefinitions, g.when = .land → ∃ r, DesignGateEvidence p.authored now g r := by
  have gates := (T18_authored_candidate_conditions (designCandidate_legacy h)).2.1 rfl
  refine ⟨designCandidate_finalized_bound h (Or.inl rfl),
    designCandidate_landing_evidence h (Or.inl rfl), gates.1, ?_⟩
  intro g hg phase
  apply design_gate_pass_provenance
  apply List.all_eq_true.mp gates.2.1 g
  simp [hg, phase]

theorem designCandidate_verified_evidence {p : DesignProposal} {now : Nat}
    (h : designCandidateValid p .verified now = true) :
    implementationBound p now = true ∧ DesignLandingEvidence p.authored ∧
    hasPhase p.authored .deploy = true ∧ hasPhase p.authored .use = true ∧
    ∀ g ∈ p.authored.gateDefinitions, ∃ r, DesignGateEvidence p.authored now g r := by
  have legacy := designCandidate_legacy h
  have phases : hasPhase p.authored .deploy = true ∧ hasPhase p.authored .use = true := by
    simp_all [authoredCandidateValid, bool_and]
  have gates := ((T18_authored_candidate_conditions legacy).2.2 rfl).1
  refine ⟨designCandidate_finalized_bound h (Or.inr rfl),
    designCandidate_landing_evidence h (Or.inr rfl), phases.1, phases.2, ?_⟩
  intro g hg
  exact design_gate_pass_provenance (List.all_eq_true.mp gates g hg)

/-- Binding, each land pass, and the selected landing witness share the same
concrete target. Exact design/source identity follows from implementationBound_exact. -/
theorem designCandidate_applied_exact_target {p : DesignProposal} {now : Nat}
    (h : designCandidateValid p .applied now = true) :
    ∃ b, p.binding = some b ∧ b.source = p.targetSource ∧
      some b.designRevision = p.authored.proposalRevision ∧
      some b.designRevision = p.authored.acceptedRevision ∧
      (∃ resolved ∈ p.authored.resolvedLanded,
        resolved.reference ∈ p.authored.landedRefs ∧ resolved.targetRevision = b.targetRevision) ∧
      ∀ g ∈ p.authored.gateDefinitions, g.when = .land →
        ∃ r, DesignGateEvidence p.authored now g r ∧ r.targetRevision = some b.targetRevision := by
  rcases designCandidate_applied_evidence h with ⟨bound, landing, _, gates⟩
  rcases implementationBound_exact bound with ⟨b, hb, hd, ha, hs, ht, _⟩
  rcases landing.2.2.2 with ⟨resolved, hr, href, htarget⟩
  refine ⟨b, hb, hs, hd, ha, ⟨resolved, hr, href, ?_⟩, ?_⟩
  · exact Option.some.inj (htarget.trans ht.symm)
  · intro g hg phase
    obtain ⟨r, evidence⟩ := gates g hg phase
    exact ⟨r, evidence, (design_gate_evidence_exact_target evidence).trans ht.symm⟩

theorem designCandidate_verified_exact_target {p : DesignProposal} {now : Nat}
    (h : designCandidateValid p .verified now = true) :
    ∃ b, p.binding = some b ∧ b.source = p.targetSource ∧
      some b.designRevision = p.authored.proposalRevision ∧
      some b.designRevision = p.authored.acceptedRevision ∧
      (∃ resolved ∈ p.authored.resolvedLanded,
        resolved.reference ∈ p.authored.landedRefs ∧ resolved.targetRevision = b.targetRevision) ∧
      ∀ g ∈ p.authored.gateDefinitions,
        ∃ r, DesignGateEvidence p.authored now g r ∧ r.targetRevision = some b.targetRevision := by
  rcases designCandidate_verified_evidence h with ⟨bound, landing, _, _, gates⟩
  rcases implementationBound_exact bound with ⟨b, hb, hd, ha, hs, ht, _⟩
  rcases landing.2.2.2 with ⟨resolved, hr, href, htarget⟩
  refine ⟨b, hb, hs, hd, ha, ⟨resolved, hr, href, ?_⟩, ?_⟩
  · exact Option.some.inj (htarget.trans ht.symm)
  · intro g hg
    obtain ⟨r, evidence⟩ := gates g hg
    exact ⟨r, evidence, (design_gate_evidence_exact_target evidence).trans ht.symm⟩

theorem bindImplementation_eq_some_iff {current next : DesignProposal}
    {command : DesignBindingCommand} {now : Nat} :
    bindImplementation current command now = some next ↔
      current = command.expected ∧
      (current.authored.status = .accepted ∨ current.authored.status = .landing) ∧
      designCandidateValid current current.authored.status now = true ∧
      implementationBindingValid current command.binding now = true ∧
      next = designWithBinding current command.binding := by
  unfold bindImplementation
  split
  · rename_i allowed
    constructor
    · intro hn
      exact ⟨allowed.1, allowed.2.1, allowed.2.2.1, allowed.2.2.2, (Option.some.inj hn).symm⟩
    · rintro ⟨_, _, _, _, rfl⟩
      rfl
  · rename_i denied
    constructor
    · intro impossible
      cases impossible
    · rintro ⟨hc, hs, hv, hb, _⟩
      exact False.elim (denied ⟨hc, hs, hv, hb⟩)

theorem bindImplementation_bound {current next : DesignProposal} {command : DesignBindingCommand} {now : Nat}
    (h : bindImplementation current command now = some next) : implementationBound next now = true := by
  rcases bindImplementation_eq_some_iff.mp h with ⟨_, _, _, valid, rfl⟩
  simpa [implementationBound, designWithBinding, implementationBindingValid] using valid

theorem bindImplementation_preserves {current next : DesignProposal}
    {command : DesignBindingCommand} {now : Nat}
    (h : bindImplementation current command now = some next) :
    next.authored.status = current.authored.status ∧
    next.authored.acceptedRevision = current.authored.acceptedRevision ∧
    next.authored.acceptor = current.authored.acceptor ∧ next.authored.actor = current.authored.actor ∧
    next.authored.gateResults = current.authored.gateResults ∧ sameDesignMaterial current next ∧
    next.authored.landedRefs = [] ∧ next.authored.resolvedLanded = [] := by
  rcases bindImplementation_eq_some_iff.mp h with ⟨_, _, _, _, rfl⟩
  simp [designWithBinding, sameDesignMaterial]

theorem bindImplementation_candidate_valid {current next : DesignProposal}
    {command : DesignBindingCommand} {now : Nat}
    (h : bindImplementation current command now = some next) :
    designCandidateValid next next.authored.status now = true := by
  rcases bindImplementation_eq_some_iff.mp h with ⟨_, status, valid, _, rfl⟩
  rcases status with hs | hs <;>
    simpa [designWithBinding, hs, designCandidateValid, authoredCandidateValid] using valid

theorem bindImplementation_not_finalized {current next : DesignProposal}
    {command : DesignBindingCommand} {now : Nat}
    (h : bindImplementation current command now = some next) :
    next.authored.status ≠ .applied ∧ next.authored.status ≠ .verified := by
  have hs := (bindImplementation_preserves h).1
  rcases (bindImplementation_eq_some_iff.mp h).2.1 with status | status <;> simp [hs, status]

theorem bindImplementation_no_landing_authority {current next : DesignProposal}
    {command : DesignBindingCommand} {now : Nat}
    (h : bindImplementation current command now = some next) :
    designCandidateValid next .applied now = false ∧ designCandidateValid next .verified now = false := by
  rcases bindImplementation_eq_some_iff.mp h with ⟨_, _, _, _, rfl⟩
  simp [designCandidateValid, authoredCandidateValid, designWithBinding]

theorem bindImplementation_old_result_excluded {current next : DesignProposal}
    {command : DesignBindingCommand} {now : Nat} {r : GateResult}
    (h : bindImplementation current command now = some next)
    (old : r.targetRevision ≠ some command.binding.targetRevision) :
    ∀ g, designGateResultMatches next.authored now g r = false ∧
      ¬ DesignGateEvidence next.authored now g r := by
  rcases bindImplementation_eq_some_iff.mp h with ⟨_, _, _, _, rfl⟩
  intro g
  exact design_gate_wrong_target_excluded old

theorem bindImplementation_retarget_old_history {current next : DesignProposal}
    {command : DesignBindingCommand} {now : Nat} {oldTarget : Option TargetRevision}
    (h : bindImplementation current command now = some next)
    (changed : oldTarget ≠ some command.binding.targetRevision)
    (history : ∀ r ∈ current.authored.gateResults, r.targetRevision = oldTarget) :
    ∀ g, gatePassed next.authored now g = false := by
  rcases bindImplementation_eq_some_iff.mp h with ⟨_, _, _, _, rfl⟩
  intro g
  apply design_gate_unmatched_history_rejected
  intro r hr
  have old := history r hr
  simpa [designWithBinding, old] using changed

theorem bindImplementation_stale_rejected {current : DesignProposal} {command : DesignBindingCommand} {now : Nat}
    (stale : current ≠ command.expected) : bindImplementation current command now = none := by
  simp [bindImplementation, stale]

theorem bindImplementation_invalid_binding_rejected {current : DesignProposal}
    {command : DesignBindingCommand} {now : Nat}
    (invalid : implementationBindingValid current command.binding now = false) :
    bindImplementation current command now = none := by
  simp [bindImplementation, invalid]

theorem bindImplementation_wrong_design_rejected {current : DesignProposal}
    {command : DesignBindingCommand} {now : Nat}
    (wrong : some command.binding.designRevision ≠ current.authored.proposalRevision) :
    bindImplementation current command now = none := by
  apply bindImplementation_invalid_binding_rejected
  simp [implementationBindingValid, wrong]

theorem bindImplementation_wrong_acceptance_rejected {current : DesignProposal}
    {command : DesignBindingCommand} {now : Nat}
    (wrong : some command.binding.designRevision ≠ current.authored.acceptedRevision) :
    bindImplementation current command now = none := by
  apply bindImplementation_invalid_binding_rejected
  simp [implementationBindingValid, wrong]

theorem bindImplementation_wrong_source_rejected {current : DesignProposal}
    {command : DesignBindingCommand} {now : Nat}
    (wrong : command.binding.source ≠ current.targetSource) :
    bindImplementation current command now = none := by
  apply bindImplementation_invalid_binding_rejected
  simp [implementationBindingValid, wrong]

theorem bindImplementation_future_rejected {current : DesignProposal}
    {command : DesignBindingCommand} {now : Nat}
    (future : now < command.binding.observedAt) : bindImplementation current command now = none := by
  apply bindImplementation_invalid_binding_rejected
  simp [implementationBindingValid, Nat.not_le_of_lt future]

theorem bindImplementation_blank_actor_rejected {current : DesignProposal}
    {command : DesignBindingCommand} {now : Nat}
    (blank : nonblank command.binding.actor.val = false) : bindImplementation current command now = none := by
  apply bindImplementation_invalid_binding_rejected
  simp [implementationBindingValid, blank]

theorem bindImplementation_finalized_rejected {current : DesignProposal}
    {command : DesignBindingCommand} {now : Nat}
    (finalized : current.authored.status = .applied ∨ current.authored.status = .verified) :
    bindImplementation current command now = none := by
  rcases finalized with hs | hs <;> simp [bindImplementation, hs]

theorem reopenDesign_eq_some_iff {current next : DesignProposal} {command : DesignReopenCommand} :
    reopenDesign current command = some next ↔
      current = command.expected ∧
      (current.authored.status = .accepted ∨ current.authored.status = .landing) ∧
      nonblank command.actor.val = true ∧ nonblank command.reason = true ∧
      next = designReopened current command.actor := by
  unfold reopenDesign
  split
  · rename_i allowed
    constructor
    · intro hn
      exact ⟨allowed.1, allowed.2.1, allowed.2.2.1, allowed.2.2.2, (Option.some.inj hn).symm⟩
    · rintro ⟨_, _, _, _, rfl⟩
      rfl
  · rename_i denied
    constructor
    · intro impossible
      cases impossible
    · rintro ⟨hc, hs, ha, hr, _⟩
      exact False.elim (denied ⟨hc, hs, ha, hr⟩)

theorem reopenDesign_clears_authority {current next : DesignProposal} {command : DesignReopenCommand}
    (h : reopenDesign current command = some next) :
    next.authored.status = .proposed ∧ next.authored.actor = some command.actor ∧
    next.authored.acceptedRevision = none ∧ next.authored.acceptor = none ∧
    next.authored.executor = none ∧ next.authored.verifier = none ∧
    next.authored.targetRevision = none ∧ next.authored.landedRefs = [] ∧
    next.authored.resolvedLanded = [] ∧ next.binding = none := by
  rcases reopenDesign_eq_some_iff.mp h with ⟨_, _, _, _, rfl⟩
  simp [designReopened]

theorem reopenDesign_preserves_material_history {current next : DesignProposal} {command : DesignReopenCommand}
    (h : reopenDesign current command = some next) :
    sameDesignMaterial current next ∧ next.authored.gateResults = current.authored.gateResults := by
  rcases reopenDesign_eq_some_iff.mp h with ⟨_, _, _, _, rfl⟩
  simp [designReopened, sameDesignMaterial]

theorem reopenDesign_not_applied {current next : DesignProposal} {command : DesignReopenCommand}
    (h : reopenDesign current command = some next) (now : Nat) :
    next.authored.status ≠ .applied ∧ next.authored.status ≠ .verified ∧
    designCandidateValid next .applied now = false ∧ designCandidateValid next .verified now = false := by
  rcases reopenDesign_eq_some_iff.mp h with ⟨_, _, _, _, rfl⟩
  simp [designReopened, designCandidateValid, authoredCandidateValid, identPresent]

theorem reopenDesign_stale_rejected {current : DesignProposal} {command : DesignReopenCommand}
    (stale : current ≠ command.expected) : reopenDesign current command = none := by
  simp [reopenDesign, stale]

theorem reopenDesign_blank_actor_rejected {current : DesignProposal} {command : DesignReopenCommand}
    (blank : nonblank command.actor.val = false) : reopenDesign current command = none := by
  simp [reopenDesign, blank]

theorem reopenDesign_blank_reason_rejected {current : DesignProposal} {command : DesignReopenCommand}
    (blank : nonblank command.reason = false) : reopenDesign current command = none := by
  simp [reopenDesign, blank]

theorem reopenDesign_finalized_rejected {current : DesignProposal} {command : DesignReopenCommand}
    (finalized : current.authored.status = .applied ∨ current.authored.status = .verified) :
    reopenDesign current command = none := by
  rcases finalized with hs | hs <;> simp [reopenDesign, hs]

/-- Ordinary transitions do not acquire the explicit reopening edge. -/
theorem designTransition_no_implicit_reopen {p : DesignProposal} {now : Nat}
    (status : p.authored.status = .accepted ∨ p.authored.status = .landing) :
    designTransition p .proposed now = false := by
  rcases status with hs | hs <;> simp [designTransition, authoredLegal, hs]

end Kctx
