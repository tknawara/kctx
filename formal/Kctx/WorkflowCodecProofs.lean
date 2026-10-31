import Kctx.CodecRecords
import Kctx.AuthoredCodec
import Kctx.SelectionCodec
import Kctx.NonVacuity
import Kctx.WorkflowWireObjects

set_option autoImplicit false
set_option maxHeartbeats 9600000
set_option maxRecDepth 32768
namespace Kctx
open Lean
open WorkflowWireObjects

/- These are value-codec laws for the public codecs, not operation admission or
   authentication claims. Wire predicates state the actual decoder guards and
   recursive field bounds; they never assume decoder success. JSON request frames
   remain the separately validated boundary in Reference.evaluate/unwrap. -/

theorem roundtripAuthoredStatus (v : AuthoredStatus) : decAuthoredStatus (encAuthoredStatus v) = .ok v := by
  cases v <;> rfl

theorem roundtripProfile (v : Profile) : decProfile (encProfile v) = .ok v := by
  cases v <;> rfl

theorem roundtripGatePhase (v : GatePhase) : decGatePhase (encGatePhase v) = .ok v := by
  cases v <;> rfl

theorem roundtripGateOutcome (v : GateOutcome) : decGateOutcome (encGateOutcome v) = .ok v := by
  cases v <;> rfl

def WireAuthority (v : Authority) : Prop :=
  WireRef v.target ∧
  WireStatement v.statement ∧
  WireKB v.approved ∧
  (∀ x ∈ v.approvals, WireClaim x) ∧
  WireContext v.context

private theorem objectAuthority (j0 j1 j2 j3 j4 j5 j6 j7 : Json) :
    decAuthority (Json.mkObj [("actor", j0), ("target", j1), ("intended_use", j2), ("policy", j3), ("statement", j4), ("approved", j5), ("approvals", j6), ("context", j7)]) =
    (do
      let actor ← decIdent j0
      let target ← decRef j1
      let intendedUse ← decStr j2
      let policy ← decIdent j3
      let statement ← decStatement j4
      let approved ← decKB j5
      let approvals ← decList decClaim j6
      let context ← decContext j7
      let v : Authority := ⟨actor, target, intendedUse, policy, statement, approved, approvals, context⟩
      pure v) := rfl

theorem roundtripAuthority (v : Authority) (h : WireAuthority v) :
    decAuthority (encAuthority v) = .ok v := by
  rcases h with ⟨h1, h4, h5, h6, h7⟩
  have f0 := decIdent_encIdent v.actor
  have f1 := roundtripRef v.target h1
  have f2 := decStr_encStr v.intendedUse
  have f3 := decIdent_encIdent v.policy
  have f4 := roundtripStatement v.statement h4
  have f5 := roundtripKB v.approved h5
  have f6 := decList_encList encClaim decClaim v.approvals (fun x hx => roundtripClaim x (h6 x hx))
  have f7 := roundtripContext v.context h7
  simp only [encAuthority, objectAuthority]
  rw [f0, f1, f2, f3, f4, f5, f6, f7]
  rfl

def WirePlan (v : Plan) : Prop :=
  WireKB v.candidate ∧
  WireAuthority v.authority ∧
  WireRef v.claim ∧
  WireWitness v.witness

private theorem objectPlan (j0 j1 j2 j3 j4 j5 : Json) :
    decPlan (Json.mkObj [("id", j0), ("expected_snapshot", j1), ("candidate", j2), ("authority", j3), ("claim", j4), ("witness", j5)]) =
    (do
      let id ← decIdent j0
      let expectedSnapshot ← decIdent j1
      let candidate ← decKB j2
      let authority ← decAuthority j3
      let claim ← decRef j4
      let witness ← decWitness j5
      let v : Plan := ⟨id, expectedSnapshot, candidate, authority, claim, witness⟩
      pure v) := rfl

theorem roundtripPlan (v : Plan) (h : WirePlan v) :
    decPlan (encPlan v) = .ok v := by
  rcases h with ⟨h2, h3, h4, h5⟩
  have f0 := decIdent_encIdent v.id
  have f1 := decIdent_encIdent v.expectedSnapshot
  have f2 := roundtripKB v.candidate h2
  have f3 := roundtripAuthority v.authority h3
  have f4 := roundtripRef v.claim h4
  have f5 := roundtripWitness v.witness h5
  simp only [encPlan, objectPlan]
  rw [f0, f1, f2, f3, f4, f5]
  rfl

def WireJournalEntry (v : JournalEntry) : Prop :=
  WirePlan v.plan

private theorem objectJournalEntry (j0 : Json) :
    decJournalEntry (Json.mkObj [("plan", j0)]) =
    (do
      let plan ← decPlan j0
      let v : JournalEntry := ⟨plan⟩
      pure v) := rfl

theorem roundtripJournalEntry (v : JournalEntry) (h : WireJournalEntry v) :
    decJournalEntry (encJournalEntry v) = .ok v := by
  have h0 : WirePlan v.plan := h
  have f0 := roundtripPlan v.plan h0
  simp only [encJournalEntry, objectJournalEntry]
  rw [f0]
  rfl

def WireVerifiedApproval (v : VerifiedApproval) : Prop :=
  WirePlan v.plan

private theorem objectVerifiedApproval (j0 : Json) :
    decVerifiedApproval (Json.mkObj [("plan", j0)]) =
    (do
      let plan ← decPlan j0
      let v : VerifiedApproval := ⟨plan⟩
      pure v) := rfl

theorem roundtripVerifiedApproval (v : VerifiedApproval) (h : WireVerifiedApproval v) :
    decVerifiedApproval (encVerifiedApproval v) = .ok v := by
  have h0 : WirePlan v.plan := h
  have f0 := roundtripPlan v.plan h0
  simp only [encVerifiedApproval, objectVerifiedApproval]
  rw [f0]
  rfl

def WireProposal (v : Proposal) : Prop :=
  WireRef v.target

private theorem objectProposal (j0 j1 j2 j3 j4 j5 j6 j7 : Json) :
    decProposal (Json.mkObj [("id", j0), ("revision", j1), ("target", j2), ("status", j3), ("actor", j4), ("executor", j5), ("acceptor", j6), ("gates", j7)]) =
    (do
      let id ← decIdent j0
      let revision ← decIdent j1
      let target ← decRef j2
      let status ← decProposalStatus j3
      let actor ← decOptionalIdent j4
      let executor ← decOptionalIdent j5
      let acceptor ← decOptionalIdent j6
      let gates ← decList decIdent j7
      let v : Proposal := ⟨id, revision, target, status, actor, executor, acceptor, gates⟩
      pure v) := rfl

theorem roundtripProposal (v : Proposal) (h : WireProposal v) :
    decProposal (encProposal v) = .ok v := by
  have h2 : WireRef v.target := h
  have f0 := decIdent_encIdent v.id
  have f1 := decIdent_encIdent v.revision
  have f2 := roundtripRef v.target h2
  have f3 := roundtripProposalStatus v.status
  have f4 := decOptionalIdent_encOptionalIdent v.actor
  have f5 := decOptionalIdent_encOptionalIdent v.executor
  have f6 := decOptionalIdent_encOptionalIdent v.acceptor
  have f7 := decList_encList encIdent decIdent v.gates (fun x hx => decIdent_encIdent x)
  simp only [encProposal, objectProposal]
  rw [f0, f1, f2, f3, f4, f5, f6, f7]
  rfl

private theorem objectHypothesis (j0 j1 : Json) :
    decHypothesis (Json.mkObj [("text", j0), ("status", j1)]) =
    (do
      let text ← decStr j0
      let status ← decHypothesisStatus j1
      let v : Hypothesis := ⟨text, status⟩
      pure v) := rfl

theorem roundtripHypothesis (v : Hypothesis) :
    decHypothesis (encHypothesis v) = .ok v := by
  have f0 := decStr_encStr v.text
  have f1 := roundtripHypothesisStatus v.status
  simp only [encHypothesis, objectHypothesis]
  rw [f0, f1]
  rfl

private theorem objectInvestigation (j0 j1 j2 : Json) :
    decInvestigation (Json.mkObj [("checked_against", j0), ("scope_and_limits", j1), ("hypotheses", j2)]) =
    (do
      let checkedAgainst ← decStr j0
      let scopeAndLimits ← decStr j1
      let hypotheses ← decList decHypothesis j2
      let v : Investigation := ⟨checkedAgainst, scopeAndLimits, hypotheses⟩
      pure v) := rfl

theorem roundtripInvestigation (v : Investigation) :
    decInvestigation (encInvestigation v) = .ok v := by
  have f0 := decStr_encStr v.checkedAgainst
  have f1 := decStr_encStr v.scopeAndLimits
  have f2 := decList_encList encHypothesis decHypothesis v.hypotheses (fun x hx => roundtripHypothesis x)
  simp only [encInvestigation, objectInvestigation]
  rw [f0, f1, f2]
  rfl

def WireChecked (v : Checked) : Prop :=
  WireStatement v.statement ∧
  ∀ x ∈ v.dependencies, WireDependency x

private theorem objectChecked (j0 j1 : Json) :
    decChecked (Json.mkObj [("statement", j0), ("dependencies", j1)]) =
    (do
      let statement ← decStatement j0
      let dependencies ← decList decDependency j1
      let v : Checked := ⟨statement, dependencies⟩
      pure v) := rfl

theorem roundtripChecked (v : Checked) (h : WireChecked v) :
    decChecked (encChecked v) = .ok v := by
  rcases h with ⟨h0, h1⟩
  have f0 := roundtripStatement v.statement h0
  have f1 := decList_encList encDependency decDependency v.dependencies (fun x hx => roundtripDependency x (h1 x hx))
  simp only [encChecked, objectChecked]
  rw [f0, f1]
  rfl

private theorem objectAssessment (j0 j1 j2 j3 j4 j5 j6 : Json) :
    decAssessment (Json.mkObj [("support", j0), ("applicable", j1), ("freshness", j2), ("validated", j3), ("contested", j4), ("available", j5), ("usable", j6)]) =
    (do
      let support ← decSupport j0
      let applicable ← decBool j1
      let freshness ← decFresh j2
      let validated ← decBool j3
      let contested ← decBool j4
      let available ← decBool j5
      let usable ← decBool j6
      let v : Assessment := ⟨support, applicable, freshness, validated, contested, available, usable⟩
      pure v) := rfl

theorem roundtripAssessment (v : Assessment) :
    decAssessment (encAssessment v) = .ok v := by
  have f0 := roundtripSupport v.support
  have f1 := decBool_encBool v.applicable
  have f2 := roundtripFresh v.freshness
  have f3 := decBool_encBool v.validated
  have f4 := decBool_encBool v.contested
  have f5 := decBool_encBool v.available
  have f6 := decBool_encBool v.usable
  simp only [encAssessment, objectAssessment]
  rw [f0, f1, f2, f3, f4, f5, f6]
  rfl

def WireApplyResult (v : ApplyResult) : Prop :=
  WireKB v.kb ∧
  ∀ x ∈ v.journal, WireJournalEntry x

private theorem objectApplyResult (j0 j1 j2 : Json) :
    decApplyResult (Json.mkObj [("kb", j0), ("journal", j1), ("outcome", j2)]) =
    (do
      let kb ← decKB j0
      let journal ← decList decJournalEntry j1
      let outcome ← decApplyOutcome j2
      let v : ApplyResult := ⟨kb, journal, outcome⟩
      pure v) := rfl

theorem roundtripApplyResult (v : ApplyResult) (h : WireApplyResult v) :
    decApplyResult (encApplyResult v) = .ok v := by
  rcases h with ⟨h0, h1⟩
  have f0 := roundtripKB v.kb h0
  have f1 := decList_encList encJournalEntry decJournalEntry v.journal (fun x hx => roundtripJournalEntry x (h1 x hx))
  have f2 := roundtripApplyOutcome v.outcome
  simp only [encApplyResult, objectApplyResult]
  rw [f0, f1, f2]
  rfl

def WireSequenceResult (v : SequenceResult) : Prop :=
  WireKB v.kb ∧
  ∀ x ∈ v.journal, WireJournalEntry x

private theorem objectSequenceResult (j0 j1 j2 : Json) :
    decSequenceResult (Json.mkObj [("kb", j0), ("journal", j1), ("outcomes", j2)]) =
    (do
      let kb ← decKB j0
      let journal ← decList decJournalEntry j1
      let outcomes ← decList decApplyOutcome j2
      let v : SequenceResult := ⟨kb, journal, outcomes⟩
      pure v) := rfl

theorem roundtripSequenceResult (v : SequenceResult) (h : WireSequenceResult v) :
    decSequenceResult (encSequenceResult v) = .ok v := by
  rcases h with ⟨h0, h1⟩
  have f0 := roundtripKB v.kb h0
  have f1 := decList_encList encJournalEntry decJournalEntry v.journal (fun x hx => roundtripJournalEntry x (h1 x hx))
  have f2 := decList_encList encApplyOutcome decApplyOutcome v.outcomes (fun x hx => roundtripApplyOutcome x)
  simp only [encSequenceResult, objectSequenceResult]
  rw [f0, f1, f2]
  rfl

def WireSelectionState (v : SelectionState) : Prop :=
  (selectionStateValid v) = true ∧
  WireKB v.kb ∧
  ∀ x ∈ v.selected, WireRef x

private theorem objectSelectionState (j0 j1 : Json) :
    decSelectionState (Json.mkObj [("kb", j0), ("selected", j1)]) =
    (do
      let kb ← decKB j0
      let selected ← decList decRef j1
      let v : SelectionState := ⟨kb, selected⟩
      if selectionStateValid v then pure v else throw "invalid_request") := rfl

theorem roundtripSelectionState (v : SelectionState) (h : WireSelectionState v) :
    decSelectionState (encSelectionState v) = .ok v := by
  rcases h with ⟨hg, h0, h1⟩
  have f0 := roundtripKB v.kb h0
  have f1 := decList_encList encRef decRef v.selected (fun x hx => roundtripRef x (h1 x hx))
  simp only [encSelectionState, objectSelectionState]
  rw [f0, f1]
  simpa only [bind, Except.bind, pure] using
    (show (if selectionStateValid v then Except.ok v else .error "invalid_request") = .ok v from by simp [hg])

def WireSelectionPlan (v : SelectionPlan) : Prop :=
  (token v.id.val && token v.expectedSnapshot.val && token v.targetSnapshot.val && token v.newSnapshot.val && token v.policy.val && v.intendedUse != "") = true ∧
  (∀ x ∈ v.selected, WireRef x) ∧
  WireContext v.context

private theorem objectSelectionPlan (j0 j1 j2 j3 j4 j5 j6 j7 j8 : Json) :
    decSelectionPlan (Json.mkObj [("id", j0), ("expected_snapshot", j1), ("target_snapshot", j2), ("new_snapshot", j3), ("selected", j4), ("actor", j5), ("policy", j6), ("intended_use", j7), ("context", j8)]) =
    (do
      let id ← decIdent j0
      let expectedSnapshot ← decIdent j1
      let targetSnapshot ← decIdent j2
      let newSnapshot ← decIdent j3
      let selected ← decList decRef j4
      let actor ← decOptionalIdent j5
      let policy ← decIdent j6
      let intendedUse ← decStr j7
      let context ← decContext j8
      let v : SelectionPlan := ⟨id, expectedSnapshot, targetSnapshot, newSnapshot, selected, actor, policy, intendedUse, context⟩
      if token v.id.val && token v.expectedSnapshot.val && token v.targetSnapshot.val && token v.newSnapshot.val && token v.policy.val && v.intendedUse != "" then pure v else throw "invalid_request") := rfl

theorem roundtripSelectionPlan (v : SelectionPlan) (h : WireSelectionPlan v) :
    decSelectionPlan (encSelectionPlan v) = .ok v := by
  rcases h with ⟨hg, h4, h8⟩
  have f0 := decIdent_encIdent v.id
  have f1 := decIdent_encIdent v.expectedSnapshot
  have f2 := decIdent_encIdent v.targetSnapshot
  have f3 := decIdent_encIdent v.newSnapshot
  have f4 := decList_encList encRef decRef v.selected (fun x hx => roundtripRef x (h4 x hx))
  have f5 := decOptionalIdent_encOptionalIdent v.actor
  have f6 := decIdent_encIdent v.policy
  have f7 := decStr_encStr v.intendedUse
  have f8 := roundtripContext v.context h8
  simp only [encSelectionPlan, objectSelectionPlan]
  rw [f0, f1, f2, f3, f4, f5, f6, f7, f8]
  simpa only [bind, Except.bind, pure] using
    (show (if token v.id.val && token v.expectedSnapshot.val && token v.targetSnapshot.val && token v.newSnapshot.val && token v.policy.val && v.intendedUse != "" then Except.ok v else .error "invalid_request") = .ok v from by simp [hg])

def WireVerifiedSelectionApproval (v : VerifiedSelectionApproval) : Prop :=
  WireSelectionPlan v.plan

private theorem objectVerifiedSelectionApproval (j0 : Json) :
    decVerifiedSelectionApproval (Json.mkObj [("plan", j0)]) =
    (do
      let plan ← decSelectionPlan j0
      let v : VerifiedSelectionApproval := ⟨plan⟩
      pure v) := rfl

theorem roundtripVerifiedSelectionApproval (v : VerifiedSelectionApproval) (h : WireVerifiedSelectionApproval v) :
    decVerifiedSelectionApproval (encVerifiedSelectionApproval v) = .ok v := by
  have h0 : WireSelectionPlan v.plan := h
  have f0 := roundtripSelectionPlan v.plan h0
  simp only [encVerifiedSelectionApproval, objectVerifiedSelectionApproval]
  rw [f0]
  rfl

def WireSelectionJournalEntry (v : SelectionJournalEntry) : Prop :=
  WireSelectionPlan v.plan

private theorem objectSelectionJournalEntry (j0 : Json) :
    decSelectionJournalEntry (Json.mkObj [("plan", j0)]) =
    (do
      let plan ← decSelectionPlan j0
      let v : SelectionJournalEntry := ⟨plan⟩
      pure v) := rfl

theorem roundtripSelectionJournalEntry (v : SelectionJournalEntry) (h : WireSelectionJournalEntry v) :
    decSelectionJournalEntry (encSelectionJournalEntry v) = .ok v := by
  have h0 : WireSelectionPlan v.plan := h
  have f0 := roundtripSelectionPlan v.plan h0
  simp only [encSelectionJournalEntry, objectSelectionJournalEntry]
  rw [f0]
  rfl

def WireSelectionResult (v : SelectionResult) : Prop :=
  WireSelectionState v.state ∧
  ∀ x ∈ v.journal, WireSelectionJournalEntry x

private theorem objectSelectionResult (j0 j1 j2 : Json) :
    decSelectionResult (Json.mkObj [("state", j0), ("journal", j1), ("outcome", j2)]) =
    (do
      let state ← decSelectionState j0
      let journal ← decList decSelectionJournalEntry j1
      let outcome ← decApplyOutcome j2
      let v : SelectionResult := ⟨state, journal, outcome⟩
      pure v) := rfl

theorem roundtripSelectionResult (v : SelectionResult) (h : WireSelectionResult v) :
    decSelectionResult (encSelectionResult v) = .ok v := by
  rcases h with ⟨h0, h1⟩
  have f0 := roundtripSelectionState v.state h0
  have f1 := decList_encList encSelectionJournalEntry decSelectionJournalEntry v.journal (fun x hx => roundtripSelectionJournalEntry x (h1 x hx))
  have f2 := roundtripApplyOutcome v.outcome
  simp only [encSelectionResult, objectSelectionResult]
  rw [f0, f1, f2]
  rfl

def WireGateDefinition (v : GateDefinition) : Prop :=
  (token v.id.val) = true

private theorem objectGateDefinition (j0 j1 j2 j3 j4 j5 : Json) :
    decGateDefinition (Json.mkObj [("id", j0), ("claim", j1), ("check", j2), ("when", j3), ("by", j4), ("checker", j5)]) =
    (do
      let id ← decIdent j0
      let claim ← decStr j1
      let check ← decStr j2
      let when ← decGatePhase j3
      let byActor ← decOptionalIdent j4
      let checker ← decOptionalIdent j5
      let v : GateDefinition := ⟨id, claim, check, when, byActor, checker⟩
      if token v.id.val then pure v else throw "invalid_request") := rfl

theorem roundtripGateDefinition (v : GateDefinition) (h : WireGateDefinition v) :
    decGateDefinition (encGateDefinition v) = .ok v := by
  have hg : (token v.id.val) = true := h
  have f0 := decIdent_encIdent v.id
  have f1 := decStr_encStr v.claim
  have f2 := decStr_encStr v.check
  have f3 := roundtripGatePhase v.when
  have f4 := decOptionalIdent_encOptionalIdent v.byActor
  have f5 := decOptionalIdent_encOptionalIdent v.checker
  simp only [encGateDefinition, objectGateDefinition]
  rw [f0, f1, f2, f3, f4, f5]
  simpa only [bind, Except.bind, pure] using
    (show (if token v.id.val then Except.ok v else .error "invalid_request") = .ok v from by simp [hg])

def WireGateResult (v : GateResult) : Prop :=
  WireGateDefinition v.definition


theorem roundtripGateResult (v : GateResult) (h : WireGateResult v) :
    decGateResult (encGateResult v) = .ok v := by
  have h0 : WireGateDefinition v.definition := h
  have f0 := roundtripGateDefinition v.definition h0
  have f1 := decOptionalIdent_encOptionalIdent v.targetRevision
  have f2 := decOptionalIdent_encOptionalIdent v.checker
  have f3 := roundtripGateOutcome v.result
  have f4 := decNat_encNat v.observedAt
  have f5 := decNat_encNat v.expiresAt
  have f6 := decOptionalIdent_encOptionalIdent v.proposalRevision
  have f7 := decStr_encStr v.environment
  have f8 := decStr_encStr v.scope
  have f9 := decList_encList encStr decStr v.evidenceRefs (fun x hx => decStr_encStr x)
  have f10 := decOptionalIdent_encOptionalIdent v.actor
  simp only [encGateResult, objectGateResult]
  rw [f0, f1, f2, f3, f4, f5, f6, f7, f8, f9, f10]
  rfl

private theorem objectAuthoredReplacement (j0 j1 : Json) :
    decAuthoredReplacement (Json.mkObj [("id", j0), ("superseded_by", j1)]) =
    (do
      let id ← decIdent j0
      let supersededBy ← decOpt decIdent j1
      let v : AuthoredReplacement := ⟨id, supersededBy⟩
      pure v) := rfl

theorem roundtripAuthoredReplacement (v : AuthoredReplacement) :
    decAuthoredReplacement (encAuthoredReplacement v) = .ok v := by
  have f0 := decIdent_encIdent v.id
  have f1 := decOpt_encOpt encIdent decIdent v.supersededBy (fun x _ => decIdent_encIdent x) (fun _ => by intro h; cases h)
  simp only [encAuthoredReplacement, objectAuthoredReplacement]
  rw [f0, f1]
  rfl

private theorem objectAuthoredLanded (j0 j1 : Json) :
    decAuthoredLanded (Json.mkObj [("reference", j0), ("target_revision", j1)]) =
    (do
      let reference ← decStr j0
      let targetRevision ← decIdent j1
      let v : AuthoredLanded := ⟨reference, targetRevision⟩
      pure v) := rfl

theorem roundtripAuthoredLanded (v : AuthoredLanded) :
    decAuthoredLanded (encAuthoredLanded v) = .ok v := by
  have f0 := decStr_encStr v.reference
  have f1 := decIdent_encIdent v.targetRevision
  simp only [encAuthoredLanded, objectAuthoredLanded]
  rw [f0, f1]
  rfl

def WireAuthoredProposal (v : AuthoredProposal) : Prop :=
  (unique (v.gateDefinitions.map (·.id))) = true ∧
  (∀ x ∈ v.gateDefinitions, WireGateDefinition x) ∧
  ∀ x ∈ v.gateResults, WireGateResult x


theorem roundtripAuthoredProposal (v : AuthoredProposal) (h : WireAuthoredProposal v) :
    decAuthoredProposal (encAuthoredProposal v) = .ok v := by
  rcases h with ⟨hg, h5, h6⟩
  have f0 := roundtripAuthoredStatus v.status
  have f1 := roundtripProfile v.profile
  have f2 := decBool_encBool v.researchPresent
  have f3 := decNat_encNat v.alternativesCount
  have f4 := decOptionalIdent_encOptionalIdent v.targetRevision
  have f5 := decList_encList encGateDefinition decGateDefinition v.gateDefinitions (fun x hx => roundtripGateDefinition x (h5 x hx))
  have f6 := decList_encList encGateResult decGateResult v.gateResults (fun x hx => roundtripGateResult x (h6 x hx))
  have f7 := decOptionalIdent_encOptionalIdent v.actor
  have f8 := decOptionalIdent_encOptionalIdent v.acceptor
  have f9 := decOptionalIdent_encOptionalIdent v.executor
  have f10 := decOptionalIdent_encOptionalIdent v.verifier
  have f11 := decList_encList encStr decStr v.landedRefs (fun x hx => decStr_encStr x)
  have f12 := decStr_encStr v.regressionNote
  have f13 := decIdent_encIdent v.id
  have f14 := decOpt_encOpt encIdent decIdent v.supersededBy (fun x _ => decIdent_encIdent x) (fun _ => by intro h; cases h)
  have f15 := decList_encList encAuthoredReplacement decAuthoredReplacement v.proposals (fun x hx => roundtripAuthoredReplacement x)
  have f16 := decOptionalIdent_encOptionalIdent v.acceptedRevision
  have f17 := decOptionalIdent_encOptionalIdent v.proposalRevision
  have f18 := decStr_encStr v.environment
  have f19 := decStr_encStr v.scope
  have f20 := decList_encList encAuthoredLanded decAuthoredLanded v.resolvedLanded (fun x hx => roundtripAuthoredLanded x)
  simp only [encAuthoredProposal, objectAuthoredProposal]
  rw [f0, f1, f2, f3, f4, f5, f6, f7, f8, f9, f10, f11, f12, f13, f14, f15, f16, f17, f18, f19, f20]
  simpa only [bind, Except.bind, pure] using
    (show (if unique (v.gateDefinitions.map (·.id)) then Except.ok v else .error "invalid_request") = .ok v from by simp [hg])

/- Decode first: unknown/malformed frames are not turned into valid values.
   On successful decoding, re-encoding and decoding preserves the entire value,
   including nominal identities, option constructors, contexts and bounded trees. -/

theorem T02_scope_canonicalization {j : Json} {v : Scope}
    (decoded : decScope j = .ok v) (valid : WireScope v) :
    ((encScope <$> decScope j) >>= decScope) = .ok v := by
  simp [decoded, roundtripScope v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_formula_canonicalization {j : Json} {v : Formula}
    (decoded : decFormula j = .ok v) (valid : WireFormula v) :
    ((encFormula <$> decFormula j) >>= decFormula) = .ok v := by
  simp [decoded, roundtripFormula v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_witness_canonicalization {j : Json} {v : Witness}
    (decoded : decWitness j = .ok v) (valid : WireWitness v) :
    ((encWitness <$> decWitness j) >>= decWitness) = .ok v := by
  simp [decoded, roundtripWitness v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_statement_canonicalization {j : Json} {v : Statement}
    (decoded : decStatement j = .ok v) (valid : WireStatement v) :
    ((encStatement <$> decStatement j) >>= decStatement) = .ok v := by
  simp [decoded, roundtripStatement v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_ref_canonicalization {j : Json} {v : Ref}
    (decoded : decRef j = .ok v) (valid : WireRef v) :
    ((encRef <$> decRef j) >>= decRef) = .ok v := by
  simp [decoded, roundtripRef v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_claim_canonicalization {j : Json} {v : Claim}
    (decoded : decClaim j = .ok v) (valid : WireClaim v) :
    ((encClaim <$> decClaim j) >>= decClaim) = .ok v := by
  simp [decoded, roundtripClaim v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_observation_canonicalization {j : Json} {v : Observation}
    (decoded : decObservation j = .ok v) (valid : WireObservation v) :
    ((encObservation <$> decObservation j) >>= decObservation) = .ok v := by
  simp [decoded, roundtripObservation v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_attestation_canonicalization {j : Json} {v : Attestation}
    (decoded : decAttestation j = .ok v) (valid : WireAttestation v) :
    ((encAttestation <$> decAttestation j) >>= decAttestation) = .ok v := by
  simp [decoded, roundtripAttestation v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_enumeration_canonicalization {j : Json} {v : Enumeration}
    (decoded : decEnumeration j = .ok v) (valid : WireEnumeration v) :
    ((encEnumeration <$> decEnumeration j) >>= decEnumeration) = .ok v := by
  simp [decoded, roundtripEnumeration v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_derivation_canonicalization {j : Json} {v : Derivation}
    (decoded : decDerivation j = .ok v) (valid : WireDerivation v) :
    ((encDerivation <$> decDerivation j) >>= decDerivation) = .ok v := by
  simp [decoded, roundtripDerivation v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_correction_canonicalization {j : Json} {v : Correction}
    (decoded : decCorrection j = .ok v) (valid : WireCorrection v) :
    ((encCorrection <$> decCorrection j) >>= decCorrection) = .ok v := by
  simp [decoded, roundtripCorrection v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_policy_canonicalization {j : Json} {v : Policy}
    (decoded : decPolicy j = .ok v) (valid : WirePolicy v) :
    ((encPolicy <$> decPolicy j) >>= decPolicy) = .ok v := by
  simp [decoded, roundtripPolicy v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_context_canonicalization {j : Json} {v : Context}
    (decoded : decContext j = .ok v) (valid : WireContext v) :
    ((encContext <$> decContext j) >>= decContext) = .ok v := by
  simp [decoded, roundtripContext v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_dependency_canonicalization {j : Json} {v : Dependency}
    (decoded : decDependency j = .ok v) (valid : WireDependency v) :
    ((encDependency <$> decDependency j) >>= decDependency) = .ok v := by
  simp [decoded, roundtripDependency v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_receipt_canonicalization {j : Json} {v : Receipt}
    (decoded : decReceipt j = .ok v) (valid : WireReceipt v) :
    ((encReceipt <$> decReceipt j) >>= decReceipt) = .ok v := by
  simp [decoded, roundtripReceipt v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_kb_canonicalization {j : Json} {v : KB}
    (decoded : decKB j = .ok v) (valid : WireKB v) :
    ((encKB <$> decKB j) >>= decKB) = .ok v := by
  simp [decoded, roundtripKB v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_source_selection_canonicalization {j : Json} {v : SourceSelection}
    (decoded : decSourceSelection j = .ok v) :
    ((encSourceSelection <$> decSourceSelection j) >>= decSourceSelection) = .ok v := by
  simp [decoded, roundtripSourceSelection v, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_polarity_canonicalization {j : Json} {v : Polarity}
    (decoded : decPolarity j = .ok v) :
    ((encPolarity <$> decPolarity j) >>= decPolarity) = .ok v := by
  simp [decoded, roundtripPolarity v, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_outcome_canonicalization {j : Json} {v : Outcome}
    (decoded : decOutcome j = .ok v) :
    ((encOutcome <$> decOutcome j) >>= decOutcome) = .ok v := by
  simp [decoded, roundtripOutcome v, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_correction_kind_canonicalization {j : Json} {v : CorrectionKind}
    (decoded : decCorrectionKind j = .ok v) :
    ((encCorrectionKind <$> decCorrectionKind j) >>= decCorrectionKind) = .ok v := by
  simp [decoded, roundtripCorrectionKind v, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_proposal_status_canonicalization {j : Json} {v : ProposalStatus}
    (decoded : decProposalStatus j = .ok v) :
    ((encProposalStatus <$> decProposalStatus j) >>= decProposalStatus) = .ok v := by
  simp [decoded, roundtripProposalStatus v, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_hypothesis_status_canonicalization {j : Json} {v : HypothesisStatus}
    (decoded : decHypothesisStatus j = .ok v) :
    ((encHypothesisStatus <$> decHypothesisStatus j) >>= decHypothesisStatus) = .ok v := by
  simp [decoded, roundtripHypothesisStatus v, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_fresh_canonicalization {j : Json} {v : Fresh}
    (decoded : decFresh j = .ok v) :
    ((encFresh <$> decFresh j) >>= decFresh) = .ok v := by
  simp [decoded, roundtripFresh v, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_support_canonicalization {j : Json} {v : Support}
    (decoded : decSupport j = .ok v) :
    ((encSupport <$> decSupport j) >>= decSupport) = .ok v := by
  simp [decoded, roundtripSupport v, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_apply_outcome_canonicalization {j : Json} {v : ApplyOutcome}
    (decoded : decApplyOutcome j = .ok v) :
    ((encApplyOutcome <$> decApplyOutcome j) >>= decApplyOutcome) = .ok v := by
  simp [decoded, roundtripApplyOutcome v, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_ttl_policy_canonicalization {j : Json} {v : TtlPolicy}
    (decoded : decTtlPolicy j = .ok v) (valid : WireTtlPolicy v) :
    ((encTtlPolicy <$> decTtlPolicy j) >>= decTtlPolicy) = .ok v := by
  simp [decoded, roundtripTtlPolicy v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_authored_status_canonicalization {j : Json} {v : AuthoredStatus}
    (decoded : decAuthoredStatus j = .ok v) :
    ((encAuthoredStatus <$> decAuthoredStatus j) >>= decAuthoredStatus) = .ok v := by
  simp [decoded, roundtripAuthoredStatus v, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_profile_canonicalization {j : Json} {v : Profile}
    (decoded : decProfile j = .ok v) :
    ((encProfile <$> decProfile j) >>= decProfile) = .ok v := by
  simp [decoded, roundtripProfile v, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_gate_phase_canonicalization {j : Json} {v : GatePhase}
    (decoded : decGatePhase j = .ok v) :
    ((encGatePhase <$> decGatePhase j) >>= decGatePhase) = .ok v := by
  simp [decoded, roundtripGatePhase v, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_gate_outcome_canonicalization {j : Json} {v : GateOutcome}
    (decoded : decGateOutcome j = .ok v) :
    ((encGateOutcome <$> decGateOutcome j) >>= decGateOutcome) = .ok v := by
  simp [decoded, roundtripGateOutcome v, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_authority_canonicalization {j : Json} {v : Authority}
    (decoded : decAuthority j = .ok v) (valid : WireAuthority v) :
    ((encAuthority <$> decAuthority j) >>= decAuthority) = .ok v := by
  simp [decoded, roundtripAuthority v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_plan_canonicalization {j : Json} {v : Plan}
    (decoded : decPlan j = .ok v) (valid : WirePlan v) :
    ((encPlan <$> decPlan j) >>= decPlan) = .ok v := by
  simp [decoded, roundtripPlan v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_journal_entry_canonicalization {j : Json} {v : JournalEntry}
    (decoded : decJournalEntry j = .ok v) (valid : WireJournalEntry v) :
    ((encJournalEntry <$> decJournalEntry j) >>= decJournalEntry) = .ok v := by
  simp [decoded, roundtripJournalEntry v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_verified_approval_canonicalization {j : Json} {v : VerifiedApproval}
    (decoded : decVerifiedApproval j = .ok v) (valid : WireVerifiedApproval v) :
    ((encVerifiedApproval <$> decVerifiedApproval j) >>= decVerifiedApproval) = .ok v := by
  simp [decoded, roundtripVerifiedApproval v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_proposal_canonicalization {j : Json} {v : Proposal}
    (decoded : decProposal j = .ok v) (valid : WireProposal v) :
    ((encProposal <$> decProposal j) >>= decProposal) = .ok v := by
  simp [decoded, roundtripProposal v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_hypothesis_canonicalization {j : Json} {v : Hypothesis}
    (decoded : decHypothesis j = .ok v) :
    ((encHypothesis <$> decHypothesis j) >>= decHypothesis) = .ok v := by
  simp [decoded, roundtripHypothesis v, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_investigation_canonicalization {j : Json} {v : Investigation}
    (decoded : decInvestigation j = .ok v) :
    ((encInvestigation <$> decInvestigation j) >>= decInvestigation) = .ok v := by
  simp [decoded, roundtripInvestigation v, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_checked_canonicalization {j : Json} {v : Checked}
    (decoded : decChecked j = .ok v) (valid : WireChecked v) :
    ((encChecked <$> decChecked j) >>= decChecked) = .ok v := by
  simp [decoded, roundtripChecked v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_assessment_canonicalization {j : Json} {v : Assessment}
    (decoded : decAssessment j = .ok v) :
    ((encAssessment <$> decAssessment j) >>= decAssessment) = .ok v := by
  simp [decoded, roundtripAssessment v, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_apply_result_canonicalization {j : Json} {v : ApplyResult}
    (decoded : decApplyResult j = .ok v) (valid : WireApplyResult v) :
    ((encApplyResult <$> decApplyResult j) >>= decApplyResult) = .ok v := by
  simp [decoded, roundtripApplyResult v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_sequence_result_canonicalization {j : Json} {v : SequenceResult}
    (decoded : decSequenceResult j = .ok v) (valid : WireSequenceResult v) :
    ((encSequenceResult <$> decSequenceResult j) >>= decSequenceResult) = .ok v := by
  simp [decoded, roundtripSequenceResult v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_selection_state_canonicalization {j : Json} {v : SelectionState}
    (decoded : decSelectionState j = .ok v) (valid : WireSelectionState v) :
    ((encSelectionState <$> decSelectionState j) >>= decSelectionState) = .ok v := by
  simp [decoded, roundtripSelectionState v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_selection_plan_canonicalization {j : Json} {v : SelectionPlan}
    (decoded : decSelectionPlan j = .ok v) (valid : WireSelectionPlan v) :
    ((encSelectionPlan <$> decSelectionPlan j) >>= decSelectionPlan) = .ok v := by
  simp [decoded, roundtripSelectionPlan v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_verified_selection_approval_canonicalization {j : Json} {v : VerifiedSelectionApproval}
    (decoded : decVerifiedSelectionApproval j = .ok v) (valid : WireVerifiedSelectionApproval v) :
    ((encVerifiedSelectionApproval <$> decVerifiedSelectionApproval j) >>= decVerifiedSelectionApproval) = .ok v := by
  simp [decoded, roundtripVerifiedSelectionApproval v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_selection_journal_entry_canonicalization {j : Json} {v : SelectionJournalEntry}
    (decoded : decSelectionJournalEntry j = .ok v) (valid : WireSelectionJournalEntry v) :
    ((encSelectionJournalEntry <$> decSelectionJournalEntry j) >>= decSelectionJournalEntry) = .ok v := by
  simp [decoded, roundtripSelectionJournalEntry v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_selection_result_canonicalization {j : Json} {v : SelectionResult}
    (decoded : decSelectionResult j = .ok v) (valid : WireSelectionResult v) :
    ((encSelectionResult <$> decSelectionResult j) >>= decSelectionResult) = .ok v := by
  simp [decoded, roundtripSelectionResult v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_gate_definition_canonicalization {j : Json} {v : GateDefinition}
    (decoded : decGateDefinition j = .ok v) (valid : WireGateDefinition v) :
    ((encGateDefinition <$> decGateDefinition j) >>= decGateDefinition) = .ok v := by
  simp [decoded, roundtripGateDefinition v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_gate_result_canonicalization {j : Json} {v : GateResult}
    (decoded : decGateResult j = .ok v) (valid : WireGateResult v) :
    ((encGateResult <$> decGateResult j) >>= decGateResult) = .ok v := by
  simp [decoded, roundtripGateResult v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_authored_replacement_canonicalization {j : Json} {v : AuthoredReplacement}
    (decoded : decAuthoredReplacement j = .ok v) :
    ((encAuthoredReplacement <$> decAuthoredReplacement j) >>= decAuthoredReplacement) = .ok v := by
  simp [decoded, roundtripAuthoredReplacement v, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_authored_landed_canonicalization {j : Json} {v : AuthoredLanded}
    (decoded : decAuthoredLanded j = .ok v) :
    ((encAuthoredLanded <$> decAuthoredLanded j) >>= decAuthoredLanded) = .ok v := by
  simp [decoded, roundtripAuthoredLanded v, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_authored_proposal_canonicalization {j : Json} {v : AuthoredProposal}
    (decoded : decAuthoredProposal j = .ok v) (valid : WireAuthoredProposal v) :
    ((encAuthoredProposal <$> decAuthoredProposal j) >>= decAuthoredProposal) = .ok v := by
  simp [decoded, roundtripAuthoredProposal v valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_plan_list_roundtrip (vs : List Plan)
    (valid : ∀ v ∈ vs, WirePlan v) :
    decList decPlan (encList encPlan vs) = .ok vs :=
  decList_encList encPlan decPlan vs (fun v hv => roundtripPlan v (valid v hv))

theorem T02_plan_list_canonicalization {j : Json} {vs : List Plan}
    (decoded : decList decPlan j = .ok vs) (valid : ∀ v ∈ vs, WirePlan v) :
    ((encList encPlan <$> decList decPlan j) >>= decList decPlan) = .ok vs := by
  simp [decoded, T02_plan_list_roundtrip vs valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_journal_entry_list_roundtrip (vs : List JournalEntry)
    (valid : ∀ v ∈ vs, WireJournalEntry v) :
    decList decJournalEntry (encList encJournalEntry vs) = .ok vs :=
  decList_encList encJournalEntry decJournalEntry vs (fun v hv => roundtripJournalEntry v (valid v hv))

theorem T02_journal_entry_list_canonicalization {j : Json} {vs : List JournalEntry}
    (decoded : decList decJournalEntry j = .ok vs) (valid : ∀ v ∈ vs, WireJournalEntry v) :
    ((encList encJournalEntry <$> decList decJournalEntry j) >>= decList decJournalEntry) = .ok vs := by
  simp [decoded, T02_journal_entry_list_roundtrip vs valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_verified_approval_list_roundtrip (vs : List VerifiedApproval)
    (valid : ∀ v ∈ vs, WireVerifiedApproval v) :
    decList decVerifiedApproval (encList encVerifiedApproval vs) = .ok vs :=
  decList_encList encVerifiedApproval decVerifiedApproval vs (fun v hv => roundtripVerifiedApproval v (valid v hv))

theorem T02_verified_approval_list_canonicalization {j : Json} {vs : List VerifiedApproval}
    (decoded : decList decVerifiedApproval j = .ok vs) (valid : ∀ v ∈ vs, WireVerifiedApproval v) :
    ((encList encVerifiedApproval <$> decList decVerifiedApproval j) >>= decList decVerifiedApproval) = .ok vs := by
  simp [decoded, T02_verified_approval_list_roundtrip vs valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_verified_selection_approval_list_roundtrip (vs : List VerifiedSelectionApproval)
    (valid : ∀ v ∈ vs, WireVerifiedSelectionApproval v) :
    decList decVerifiedSelectionApproval (encList encVerifiedSelectionApproval vs) = .ok vs :=
  decList_encList encVerifiedSelectionApproval decVerifiedSelectionApproval vs (fun v hv => roundtripVerifiedSelectionApproval v (valid v hv))

theorem T02_verified_selection_approval_list_canonicalization {j : Json} {vs : List VerifiedSelectionApproval}
    (decoded : decList decVerifiedSelectionApproval j = .ok vs) (valid : ∀ v ∈ vs, WireVerifiedSelectionApproval v) :
    ((encList encVerifiedSelectionApproval <$> decList decVerifiedSelectionApproval j) >>= decList decVerifiedSelectionApproval) = .ok vs := by
  simp [decoded, T02_verified_selection_approval_list_roundtrip vs valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_selection_journal_entry_list_roundtrip (vs : List SelectionJournalEntry)
    (valid : ∀ v ∈ vs, WireSelectionJournalEntry v) :
    decList decSelectionJournalEntry (encList encSelectionJournalEntry vs) = .ok vs :=
  decList_encList encSelectionJournalEntry decSelectionJournalEntry vs (fun v hv => roundtripSelectionJournalEntry v (valid v hv))

theorem T02_selection_journal_entry_list_canonicalization {j : Json} {vs : List SelectionJournalEntry}
    (decoded : decList decSelectionJournalEntry j = .ok vs) (valid : ∀ v ∈ vs, WireSelectionJournalEntry v) :
    ((encList encSelectionJournalEntry <$> decList decSelectionJournalEntry j) >>= decList decSelectionJournalEntry) = .ok vs := by
  simp [decoded, T02_selection_journal_entry_list_roundtrip vs valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_kb_list_roundtrip (vs : List KB)
    (valid : ∀ v ∈ vs, WireKB v) :
    decList decKB (encList encKB vs) = .ok vs :=
  decList_encList encKB decKB vs (fun v hv => roundtripKB v (valid v hv))

theorem T02_kb_list_canonicalization {j : Json} {vs : List KB}
    (decoded : decList decKB j = .ok vs) (valid : ∀ v ∈ vs, WireKB v) :
    ((encList encKB <$> decList decKB j) >>= decList decKB) = .ok vs := by
  simp [decoded, T02_kb_list_roundtrip vs valid, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_atom_canonicalization {j : Json} {v : Atom}
    (decoded : decAtom j = .ok v) (valid : atomWf v = true) :
    ((encAtom <$> decAtom j) >>= decAtom) = .ok v := by
  simp [decoded, decAtom_encAtom v valid, bind, Except.bind, Functor.map, Except.map]

theorem T02_ident_canonicalization {kind : IdKind} {j : Json} {v : Ident kind}
    (decoded : decIdent j = .ok v) :
    ((encIdent <$> decIdent (kind := kind) j) >>= decIdent) = .ok v := by
  simp [decoded, decIdent_encIdent, bind, Except.bind, Functor.map, Except.map]

theorem T02_optional_ident_canonicalization {kind : IdKind} {j : Json}
    {v : Option (Ident kind)} (decoded : decOptionalIdent j = .ok v) :
    ((encOptionalIdent <$> decOptionalIdent (kind := kind) j) >>= decOptionalIdent) = .ok v := by
  simp [decoded, decOptionalIdent_encOptionalIdent, bind, Except.bind,
    Functor.map, Except.map]

theorem T02_optional_checked_roundtrip (v : Option Checked)
    (valid : ∀ x, v = some x → WireChecked x) :
    decOpt decChecked (encOpt encChecked v) = .ok v :=
  decOpt_encOpt encChecked decChecked v (fun x hx => roundtripChecked x (valid x hx))
    (fun _ => by intro h; cases h)

theorem T02_optional_checked_canonicalization {j : Json} {v : Option Checked}
    (decoded : decOpt decChecked j = .ok v) (valid : ∀ x, v = some x → WireChecked x) :
    ((encOpt encChecked <$> decOpt decChecked j) >>= decOpt decChecked) = .ok v := by
  simp [decoded, T02_optional_checked_roundtrip v valid, bind, Except.bind,
    Functor.map, Except.map]

namespace WorkflowCodecExamples
open NonVacuity

/-- Nonempty full-state fixture with observations, claims, witnesses and sources. -/
theorem kb_valid : WireKB kb := by
  simp [WireKB, NonVacuity.kb, WireObservation, WireClaim, WireStatement,
    WireFormula, WireScope, WireAttestation, WireRef, WireEnumeration,
    WireDerivation, WireWitness] <;> decide

def authority : Authority :=
  ⟨⟨"reviewer", by decide⟩, claim.ref, "review", context.policy.id,
    statement, kb, [claim], context⟩
def plan : Plan :=
  ⟨⟨"operation", by decide⟩, kb.snapshot, kb, authority, claim.ref,
    .and (.attest attestation.id) (.truth scope)⟩
def selectionState : SelectionState := ⟨kb, [claim.ref]⟩
def selectionPlan : SelectionPlan :=
  ⟨⟨"selection", by decide⟩, kb.snapshot, kb.snapshot, ⟨"next", by decide⟩,
    [claim.ref], some ⟨"reviewer", by decide⟩, context.policy.id, "review", context⟩
def gate : GateDefinition :=
  ⟨⟨"gate", by decide⟩, "checked claim", "run check", .land,
    some ⟨"reviewer", by decide⟩, none⟩
def gateResult : GateResult :=
  ⟨gate, some ⟨"target-r1", by decide⟩, some ⟨"checker", by decide⟩,
    .pass, 10, 30, some ⟨"proposal-r1", by decide⟩, "staging", "project",
    ["retained-evidence"], some ⟨"reviewer", by decide⟩⟩
def authoredProposal : AuthoredProposal :=
  ⟨.accepted, .modern, true, 2, some ⟨"target-r1", by decide⟩,
    [gate], [gateResult], some ⟨"author", by decide⟩,
    some ⟨"reviewer", by decide⟩, none, none, ["landed-reference"], "",
    ⟨"proposal", by decide⟩, none,
    [⟨⟨"previous", by decide⟩, some ⟨"proposal", by decide⟩⟩],
    some ⟨"proposal-r1", by decide⟩, some ⟨"proposal-r1", by decide⟩,
    "staging", "project", [⟨"landed-reference", ⟨"target-r1", by decide⟩⟩]⟩
def investigation : Investigation :=
  ⟨"retained observations", "project at r1", [⟨"supported finding", .supported⟩,
    ⟨"unknown finding", .unk⟩]⟩

theorem plan_valid : WirePlan plan := by
  simp [WirePlan, WireAuthority, plan, authority, kb_valid, WireRef,
    WireStatement, WireFormula, WireScope, WireClaim, WireContext, WirePolicy,
    WireTtlPolicy, WireWitness] <;> decide
theorem selection_state_valid : WireSelectionState selectionState := by
  simp [WireSelectionState, selectionState, kb_valid, WireRef] <;> decide
theorem selection_plan_valid : WireSelectionPlan selectionPlan := by
  simp [WireSelectionPlan, selectionPlan, WireRef, WireContext, WirePolicy,
    WireTtlPolicy, WireScope] <;> decide
theorem authored_valid : WireAuthoredProposal authoredProposal := by
  simp [WireAuthoredProposal, WireGateResult, WireGateDefinition, authoredProposal] <;> decide

theorem T02_workflow_nonvacuous :
    decPlan (encPlan plan) = .ok plan := roundtripPlan plan plan_valid

theorem T02_selection_nonvacuous :
    decSelectionState (encSelectionState selectionState) = .ok selectionState ∧
    decSelectionPlan (encSelectionPlan selectionPlan) = .ok selectionPlan :=
  ⟨roundtripSelectionState selectionState selection_state_valid,
    roundtripSelectionPlan selectionPlan selection_plan_valid⟩

theorem T02_authored_nonvacuous :
    decAuthoredProposal (encAuthoredProposal authoredProposal) = .ok authoredProposal :=
  roundtripAuthoredProposal authoredProposal authored_valid

theorem T02_investigation_nonvacuous :
    decInvestigation (encInvestigation investigation) = .ok investigation :=
  roundtripInvestigation investigation

end WorkflowCodecExamples

end Kctx
