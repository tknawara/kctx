import Kctx.Portfolio
import Kctx.DesignWorkflow
import Kctx.WorkflowCodecProofs

set_option autoImplicit false
set_option maxHeartbeats 2400000
set_option maxRecDepth 32768
namespace Kctx
open Lean

/-! Strict workflow-schema-3 value codecs. Core context/witness semantics remain v2.
Roundtrip premises are syntactic validity and recursive wire bounds, never assumed
decoder success or operation authorization. -/

def decWorkflowIdent {kind : IdKind} (j : Json) : Except String (Ident kind) := do
  let value ← decIdent j
  if token value.val then return value else throw "invalid_request"

theorem roundtripWorkflowIdent {kind : IdKind} (v : Ident kind) (h : token v.val = true) :
    decWorkflowIdent (encIdent v) = .ok v := by
  simp [decWorkflowIdent, decIdent_encIdent, h, bind, Except.bind, pure, Except.pure]


def encNamedContext (v : NamedContext) : Json := Json.mkObj [
  ("id", (encIdent) v.id),
  ("context", (encContext) v.context)]

def decNamedContext (j : Json) : Except String NamedContext := do
  fields j ["id", "context"]
  let id : ContextId ← field j "id" >>= (decWorkflowIdent)
  let context : Context ← field j "context" >>= (decContext)
  return ⟨id, context⟩

def WireNamedContext (v : NamedContext) : Prop :=
  (token v.id.val = true) ∧
  (WireContext v.context)

private theorem objectNamedContext (j0 j1 : Json) :
    decNamedContext (Json.mkObj [("id", j0), ("context", j1)]) =
    (do
      let id : ContextId ← (decWorkflowIdent) j0
      let context : Context ← (decContext) j1
      return (⟨id, context⟩ : NamedContext)) := rfl

theorem roundtripNamedContext (v : NamedContext) (h : WireNamedContext v) :
    decNamedContext (encNamedContext v) = .ok v := by
  rcases h with ⟨h0, h1⟩
  have f0 := roundtripWorkflowIdent v.id h0
  have f1 := roundtripContext v.context h1
  simp only [encNamedContext, objectNamedContext]
  rw [f0, f1]
  rfl

theorem canonicalNamedContext {j : Json} {v : NamedContext} (h : WireNamedContext v)
    (decoded : decNamedContext j = .ok v) :
    ((encNamedContext <$> decNamedContext j) >>= decNamedContext) = .ok v := by
  simp [decoded, roundtripNamedContext v h, bind, Except.bind, Functor.map, Except.map]

def encClaimAssignment (v : ClaimAssignment) : Json := Json.mkObj [
  ("claim", (encRef) v.claim),
  ("context", (encIdent) v.context),
  ("witness", (encWitness) v.witness)]

def decClaimAssignment (j : Json) : Except String ClaimAssignment := do
  fields j ["claim", "context", "witness"]
  let claim : Ref ← field j "claim" >>= (decRef)
  let context : ContextId ← field j "context" >>= (decWorkflowIdent)
  let witness : Witness ← field j "witness" >>= (decWitness)
  return ⟨claim, context, witness⟩

def WireClaimAssignment (v : ClaimAssignment) : Prop :=
  (WireRef v.claim) ∧
  (token v.context.val = true) ∧
  (WireWitness v.witness)

private theorem objectClaimAssignment (j0 j1 j2 : Json) :
    decClaimAssignment (Json.mkObj [("claim", j0), ("context", j1), ("witness", j2)]) =
    (do
      let claim : Ref ← (decRef) j0
      let context : ContextId ← (decWorkflowIdent) j1
      let witness : Witness ← (decWitness) j2
      return (⟨claim, context, witness⟩ : ClaimAssignment)) := rfl

theorem roundtripClaimAssignment (v : ClaimAssignment) (h : WireClaimAssignment v) :
    decClaimAssignment (encClaimAssignment v) = .ok v := by
  rcases h with ⟨h0, h1, h2⟩
  have f0 := roundtripRef v.claim h0
  have f1 := roundtripWorkflowIdent v.context h1
  have f2 := roundtripWitness v.witness h2
  simp only [encClaimAssignment, objectClaimAssignment]
  rw [f0, f1, f2]
  rfl

theorem canonicalClaimAssignment {j : Json} {v : ClaimAssignment} (h : WireClaimAssignment v)
    (decoded : decClaimAssignment j = .ok v) :
    ((encClaimAssignment <$> decClaimAssignment j) >>= decClaimAssignment) = .ok v := by
  simp [decoded, roundtripClaimAssignment v h, bind, Except.bind, Functor.map, Except.map]

def encPortfolioState (v : PortfolioState) : Json := Json.mkObj [
  ("kb", (encKB) v.kb),
  ("selected", (encList encRef) v.selected),
  ("contexts", (encList encNamedContext) v.contexts)]

def decPortfolioState (j : Json) : Except String PortfolioState := do
  fields j ["kb", "selected", "contexts"]
  let kb : KB ← field j "kb" >>= (decKB)
  let selected : List Ref ← field j "selected" >>= (decList decRef)
  let contexts : List NamedContext ← field j "contexts" >>= (decList decNamedContext)
  return ⟨kb, selected, contexts⟩

def WirePortfolioState (v : PortfolioState) : Prop :=
  (WireKB v.kb) ∧
  (∀ x ∈ v.selected, WireRef x) ∧
  (∀ x ∈ v.contexts, WireNamedContext x)

private theorem objectPortfolioState (j0 j1 j2 : Json) :
    decPortfolioState (Json.mkObj [("kb", j0), ("selected", j1), ("contexts", j2)]) =
    (do
      let kb : KB ← (decKB) j0
      let selected : List Ref ← (decList decRef) j1
      let contexts : List NamedContext ← (decList decNamedContext) j2
      return (⟨kb, selected, contexts⟩ : PortfolioState)) := rfl

theorem roundtripPortfolioState (v : PortfolioState) (h : WirePortfolioState v) :
    decPortfolioState (encPortfolioState v) = .ok v := by
  rcases h with ⟨h0, h1, h2⟩
  have f0 := roundtripKB v.kb h0
  have f1 := decList_encList encRef decRef v.selected (fun x hx => roundtripRef x (h1 x hx))
  have f2 := decList_encList encNamedContext decNamedContext v.contexts (fun x hx => roundtripNamedContext x (h2 x hx))
  simp only [encPortfolioState, objectPortfolioState]
  rw [f0, f1, f2]
  rfl

theorem canonicalPortfolioState {j : Json} {v : PortfolioState} (h : WirePortfolioState v)
    (decoded : decPortfolioState j = .ok v) :
    ((encPortfolioState <$> decPortfolioState j) >>= decPortfolioState) = .ok v := by
  simp [decoded, roundtripPortfolioState v h, bind, Except.bind, Functor.map, Except.map]

def encPortfolioPlan (v : PortfolioPlan) : Json := Json.mkObj [
  ("id", (encIdent) v.id),
  ("expected_snapshot", (encIdent) v.expectedSnapshot),
  ("candidate", (encKB) v.candidate),
  ("actor", (encIdent) v.actor),
  ("contexts", (encList encNamedContext) v.contexts),
  ("assignments", (encList encClaimAssignment) v.assignments),
  ("retired_contexts", (encList encIdent) v.retiredContexts)]

def decPortfolioPlan (j : Json) : Except String PortfolioPlan := do
  fields j ["id", "expected_snapshot", "candidate", "actor", "contexts", "assignments", "retired_contexts"]
  let id : OperationId ← field j "id" >>= (decWorkflowIdent)
  let expectedSnapshot : SnapshotId ← field j "expected_snapshot" >>= (decWorkflowIdent)
  let candidate : KB ← field j "candidate" >>= (decKB)
  let actor : ActorId ← field j "actor" >>= (decIdent)
  let contexts : List NamedContext ← field j "contexts" >>= (decList decNamedContext)
  let assignments : List ClaimAssignment ← field j "assignments" >>= (decList decClaimAssignment)
  let retiredContexts : List ContextId ← field j "retired_contexts" >>= (decList decWorkflowIdent)
  return ⟨id, expectedSnapshot, candidate, actor, contexts, assignments, retiredContexts⟩

def WirePortfolioPlan (v : PortfolioPlan) : Prop :=
  (token v.id.val = true) ∧
  (token v.expectedSnapshot.val = true) ∧
  (WireKB v.candidate) ∧
  (∀ x ∈ v.contexts, WireNamedContext x) ∧
  (∀ x ∈ v.assignments, WireClaimAssignment x) ∧
  (∀ x ∈ v.retiredContexts, token x.val = true)

private theorem objectPortfolioPlan (j0 j1 j2 j3 j4 j5 j6 : Json) :
    decPortfolioPlan (Json.mkObj [("id", j0), ("expected_snapshot", j1), ("candidate", j2), ("actor", j3), ("contexts", j4), ("assignments", j5), ("retired_contexts", j6)]) =
    (do
      let id : OperationId ← (decWorkflowIdent) j0
      let expectedSnapshot : SnapshotId ← (decWorkflowIdent) j1
      let candidate : KB ← (decKB) j2
      let actor : ActorId ← (decIdent) j3
      let contexts : List NamedContext ← (decList decNamedContext) j4
      let assignments : List ClaimAssignment ← (decList decClaimAssignment) j5
      let retiredContexts : List ContextId ← (decList decWorkflowIdent) j6
      return (⟨id, expectedSnapshot, candidate, actor, contexts, assignments, retiredContexts⟩ : PortfolioPlan)) := rfl

theorem roundtripPortfolioPlan (v : PortfolioPlan) (h : WirePortfolioPlan v) :
    decPortfolioPlan (encPortfolioPlan v) = .ok v := by
  rcases h with ⟨h0, h1, h2, h4, h5, h6⟩
  have f0 := roundtripWorkflowIdent v.id h0
  have f1 := roundtripWorkflowIdent v.expectedSnapshot h1
  have f2 := roundtripKB v.candidate h2
  have f3 := decIdent_encIdent v.actor
  have f4 := decList_encList encNamedContext decNamedContext v.contexts (fun x hx => roundtripNamedContext x (h4 x hx))
  have f5 := decList_encList encClaimAssignment decClaimAssignment v.assignments (fun x hx => roundtripClaimAssignment x (h5 x hx))
  have f6 := decList_encList encIdent decWorkflowIdent v.retiredContexts (fun x hx => roundtripWorkflowIdent x (h6 x hx))
  simp only [encPortfolioPlan, objectPortfolioPlan]
  rw [f0, f1, f2, f3, f4, f5, f6]
  rfl

theorem canonicalPortfolioPlan {j : Json} {v : PortfolioPlan} (h : WirePortfolioPlan v)
    (decoded : decPortfolioPlan j = .ok v) :
    ((encPortfolioPlan <$> decPortfolioPlan j) >>= decPortfolioPlan) = .ok v := by
  simp [decoded, roundtripPortfolioPlan v h, bind, Except.bind, Functor.map, Except.map]

def encVerifiedPortfolioApproval (v : VerifiedPortfolioApproval) : Json := Json.mkObj [
  ("plan", (encPortfolioPlan) v.plan)]

def decVerifiedPortfolioApproval (j : Json) : Except String VerifiedPortfolioApproval := do
  fields j ["plan"]
  let plan : PortfolioPlan ← field j "plan" >>= (decPortfolioPlan)
  return ⟨plan⟩

def WireVerifiedPortfolioApproval (v : VerifiedPortfolioApproval) : Prop :=
  (WirePortfolioPlan v.plan)

private theorem objectVerifiedPortfolioApproval (j0 : Json) :
    decVerifiedPortfolioApproval (Json.mkObj [("plan", j0)]) =
    (do
      let plan : PortfolioPlan ← (decPortfolioPlan) j0
      return (⟨plan⟩ : VerifiedPortfolioApproval)) := rfl

theorem roundtripVerifiedPortfolioApproval (v : VerifiedPortfolioApproval) (h : WireVerifiedPortfolioApproval v) :
    decVerifiedPortfolioApproval (encVerifiedPortfolioApproval v) = .ok v := by
  have h0 : WirePortfolioPlan v.plan := h
  have f0 := roundtripPortfolioPlan v.plan h0
  simp only [encVerifiedPortfolioApproval, objectVerifiedPortfolioApproval]
  rw [f0]
  rfl

theorem canonicalVerifiedPortfolioApproval {j : Json} {v : VerifiedPortfolioApproval} (h : WireVerifiedPortfolioApproval v)
    (decoded : decVerifiedPortfolioApproval j = .ok v) :
    ((encVerifiedPortfolioApproval <$> decVerifiedPortfolioApproval j) >>= decVerifiedPortfolioApproval) = .ok v := by
  simp [decoded, roundtripVerifiedPortfolioApproval v h, bind, Except.bind, Functor.map, Except.map]

def encPortfolioJournalEntry (v : PortfolioJournalEntry) : Json := Json.mkObj [
  ("plan", (encPortfolioPlan) v.plan)]

def decPortfolioJournalEntry (j : Json) : Except String PortfolioJournalEntry := do
  fields j ["plan"]
  let plan : PortfolioPlan ← field j "plan" >>= (decPortfolioPlan)
  return ⟨plan⟩

def WirePortfolioJournalEntry (v : PortfolioJournalEntry) : Prop :=
  (WirePortfolioPlan v.plan)

private theorem objectPortfolioJournalEntry (j0 : Json) :
    decPortfolioJournalEntry (Json.mkObj [("plan", j0)]) =
    (do
      let plan : PortfolioPlan ← (decPortfolioPlan) j0
      return (⟨plan⟩ : PortfolioJournalEntry)) := rfl

theorem roundtripPortfolioJournalEntry (v : PortfolioJournalEntry) (h : WirePortfolioJournalEntry v) :
    decPortfolioJournalEntry (encPortfolioJournalEntry v) = .ok v := by
  have h0 : WirePortfolioPlan v.plan := h
  have f0 := roundtripPortfolioPlan v.plan h0
  simp only [encPortfolioJournalEntry, objectPortfolioJournalEntry]
  rw [f0]
  rfl

theorem canonicalPortfolioJournalEntry {j : Json} {v : PortfolioJournalEntry} (h : WirePortfolioJournalEntry v)
    (decoded : decPortfolioJournalEntry j = .ok v) :
    ((encPortfolioJournalEntry <$> decPortfolioJournalEntry j) >>= decPortfolioJournalEntry) = .ok v := by
  simp [decoded, roundtripPortfolioJournalEntry v h, bind, Except.bind, Functor.map, Except.map]

def encPortfolioResult (v : PortfolioResult) : Json := Json.mkObj [
  ("state", (encPortfolioState) v.state),
  ("journal", (encList encPortfolioJournalEntry) v.journal),
  ("outcome", (encApplyOutcome) v.outcome)]

def decPortfolioResult (j : Json) : Except String PortfolioResult := do
  fields j ["state", "journal", "outcome"]
  let state : PortfolioState ← field j "state" >>= (decPortfolioState)
  let journal : List PortfolioJournalEntry ← field j "journal" >>= (decList decPortfolioJournalEntry)
  let outcome : ApplyOutcome ← field j "outcome" >>= (decApplyOutcome)
  return ⟨state, journal, outcome⟩

def WirePortfolioResult (v : PortfolioResult) : Prop :=
  (WirePortfolioState v.state) ∧
  (∀ x ∈ v.journal, WirePortfolioJournalEntry x)

private theorem objectPortfolioResult (j0 j1 j2 : Json) :
    decPortfolioResult (Json.mkObj [("state", j0), ("journal", j1), ("outcome", j2)]) =
    (do
      let state : PortfolioState ← (decPortfolioState) j0
      let journal : List PortfolioJournalEntry ← (decList decPortfolioJournalEntry) j1
      let outcome : ApplyOutcome ← (decApplyOutcome) j2
      return (⟨state, journal, outcome⟩ : PortfolioResult)) := rfl

theorem roundtripPortfolioResult (v : PortfolioResult) (h : WirePortfolioResult v) :
    decPortfolioResult (encPortfolioResult v) = .ok v := by
  rcases h with ⟨h0, h1⟩
  have f0 := roundtripPortfolioState v.state h0
  have f1 := decList_encList encPortfolioJournalEntry decPortfolioJournalEntry v.journal (fun x hx => roundtripPortfolioJournalEntry x (h1 x hx))
  have f2 := roundtripApplyOutcome v.outcome
  simp only [encPortfolioResult, objectPortfolioResult]
  rw [f0, f1, f2]
  rfl

theorem canonicalPortfolioResult {j : Json} {v : PortfolioResult} (h : WirePortfolioResult v)
    (decoded : decPortfolioResult j = .ok v) :
    ((encPortfolioResult <$> decPortfolioResult j) >>= decPortfolioResult) = .ok v := by
  simp [decoded, roundtripPortfolioResult v h, bind, Except.bind, Functor.map, Except.map]

def encPortfolioSelectionPlan (v : PortfolioSelectionPlan) : Json := Json.mkObj [
  ("id", (encIdent) v.id),
  ("expected_snapshot", (encIdent) v.expectedSnapshot),
  ("retained_snapshot", (encIdent) v.retainedSnapshot),
  ("new_snapshot", (encIdent) v.newSnapshot),
  ("actor", (encIdent) v.actor),
  ("contexts", (encList encNamedContext) v.contexts),
  ("selected", (encList encRef) v.selected)]

def decPortfolioSelectionPlan (j : Json) : Except String PortfolioSelectionPlan := do
  fields j ["id", "expected_snapshot", "retained_snapshot", "new_snapshot", "actor", "contexts", "selected"]
  let id : OperationId ← field j "id" >>= (decWorkflowIdent)
  let expectedSnapshot : SnapshotId ← field j "expected_snapshot" >>= (decWorkflowIdent)
  let retainedSnapshot : SnapshotId ← field j "retained_snapshot" >>= (decWorkflowIdent)
  let newSnapshot : SnapshotId ← field j "new_snapshot" >>= (decWorkflowIdent)
  let actor : ActorId ← field j "actor" >>= (decIdent)
  let contexts : List NamedContext ← field j "contexts" >>= (decList decNamedContext)
  let selected : List Ref ← field j "selected" >>= (decList decRef)
  return ⟨id, expectedSnapshot, retainedSnapshot, newSnapshot, actor, contexts, selected⟩

def WirePortfolioSelectionPlan (v : PortfolioSelectionPlan) : Prop :=
  (token v.id.val = true) ∧
  (token v.expectedSnapshot.val = true) ∧
  (token v.retainedSnapshot.val = true) ∧
  (token v.newSnapshot.val = true) ∧
  (∀ x ∈ v.contexts, WireNamedContext x) ∧
  (∀ x ∈ v.selected, WireRef x)

private theorem objectPortfolioSelectionPlan (j0 j1 j2 j3 j4 j5 j6 : Json) :
    decPortfolioSelectionPlan (Json.mkObj [("id", j0), ("expected_snapshot", j1), ("retained_snapshot", j2), ("new_snapshot", j3), ("actor", j4), ("contexts", j5), ("selected", j6)]) =
    (do
      let id : OperationId ← (decWorkflowIdent) j0
      let expectedSnapshot : SnapshotId ← (decWorkflowIdent) j1
      let retainedSnapshot : SnapshotId ← (decWorkflowIdent) j2
      let newSnapshot : SnapshotId ← (decWorkflowIdent) j3
      let actor : ActorId ← (decIdent) j4
      let contexts : List NamedContext ← (decList decNamedContext) j5
      let selected : List Ref ← (decList decRef) j6
      return (⟨id, expectedSnapshot, retainedSnapshot, newSnapshot, actor, contexts, selected⟩ : PortfolioSelectionPlan)) := rfl

theorem roundtripPortfolioSelectionPlan (v : PortfolioSelectionPlan) (h : WirePortfolioSelectionPlan v) :
    decPortfolioSelectionPlan (encPortfolioSelectionPlan v) = .ok v := by
  rcases h with ⟨h0, h1, h2, h3, h5, h6⟩
  have f0 := roundtripWorkflowIdent v.id h0
  have f1 := roundtripWorkflowIdent v.expectedSnapshot h1
  have f2 := roundtripWorkflowIdent v.retainedSnapshot h2
  have f3 := roundtripWorkflowIdent v.newSnapshot h3
  have f4 := decIdent_encIdent v.actor
  have f5 := decList_encList encNamedContext decNamedContext v.contexts (fun x hx => roundtripNamedContext x (h5 x hx))
  have f6 := decList_encList encRef decRef v.selected (fun x hx => roundtripRef x (h6 x hx))
  simp only [encPortfolioSelectionPlan, objectPortfolioSelectionPlan]
  rw [f0, f1, f2, f3, f4, f5, f6]
  rfl

theorem canonicalPortfolioSelectionPlan {j : Json} {v : PortfolioSelectionPlan} (h : WirePortfolioSelectionPlan v)
    (decoded : decPortfolioSelectionPlan j = .ok v) :
    ((encPortfolioSelectionPlan <$> decPortfolioSelectionPlan j) >>= decPortfolioSelectionPlan) = .ok v := by
  simp [decoded, roundtripPortfolioSelectionPlan v h, bind, Except.bind, Functor.map, Except.map]

def encVerifiedPortfolioSelectionApproval (v : VerifiedPortfolioSelectionApproval) : Json := Json.mkObj [
  ("plan", (encPortfolioSelectionPlan) v.plan)]

def decVerifiedPortfolioSelectionApproval (j : Json) : Except String VerifiedPortfolioSelectionApproval := do
  fields j ["plan"]
  let plan : PortfolioSelectionPlan ← field j "plan" >>= (decPortfolioSelectionPlan)
  return ⟨plan⟩

def WireVerifiedPortfolioSelectionApproval (v : VerifiedPortfolioSelectionApproval) : Prop :=
  (WirePortfolioSelectionPlan v.plan)

private theorem objectVerifiedPortfolioSelectionApproval (j0 : Json) :
    decVerifiedPortfolioSelectionApproval (Json.mkObj [("plan", j0)]) =
    (do
      let plan : PortfolioSelectionPlan ← (decPortfolioSelectionPlan) j0
      return (⟨plan⟩ : VerifiedPortfolioSelectionApproval)) := rfl

theorem roundtripVerifiedPortfolioSelectionApproval (v : VerifiedPortfolioSelectionApproval) (h : WireVerifiedPortfolioSelectionApproval v) :
    decVerifiedPortfolioSelectionApproval (encVerifiedPortfolioSelectionApproval v) = .ok v := by
  have h0 : WirePortfolioSelectionPlan v.plan := h
  have f0 := roundtripPortfolioSelectionPlan v.plan h0
  simp only [encVerifiedPortfolioSelectionApproval, objectVerifiedPortfolioSelectionApproval]
  rw [f0]
  rfl

theorem canonicalVerifiedPortfolioSelectionApproval {j : Json} {v : VerifiedPortfolioSelectionApproval} (h : WireVerifiedPortfolioSelectionApproval v)
    (decoded : decVerifiedPortfolioSelectionApproval j = .ok v) :
    ((encVerifiedPortfolioSelectionApproval <$> decVerifiedPortfolioSelectionApproval j) >>= decVerifiedPortfolioSelectionApproval) = .ok v := by
  simp [decoded, roundtripVerifiedPortfolioSelectionApproval v h, bind, Except.bind, Functor.map, Except.map]

def encPortfolioSelectionJournalEntry (v : PortfolioSelectionJournalEntry) : Json := Json.mkObj [
  ("plan", (encPortfolioSelectionPlan) v.plan)]

def decPortfolioSelectionJournalEntry (j : Json) : Except String PortfolioSelectionJournalEntry := do
  fields j ["plan"]
  let plan : PortfolioSelectionPlan ← field j "plan" >>= (decPortfolioSelectionPlan)
  return ⟨plan⟩

def WirePortfolioSelectionJournalEntry (v : PortfolioSelectionJournalEntry) : Prop :=
  (WirePortfolioSelectionPlan v.plan)

private theorem objectPortfolioSelectionJournalEntry (j0 : Json) :
    decPortfolioSelectionJournalEntry (Json.mkObj [("plan", j0)]) =
    (do
      let plan : PortfolioSelectionPlan ← (decPortfolioSelectionPlan) j0
      return (⟨plan⟩ : PortfolioSelectionJournalEntry)) := rfl

theorem roundtripPortfolioSelectionJournalEntry (v : PortfolioSelectionJournalEntry) (h : WirePortfolioSelectionJournalEntry v) :
    decPortfolioSelectionJournalEntry (encPortfolioSelectionJournalEntry v) = .ok v := by
  have h0 : WirePortfolioSelectionPlan v.plan := h
  have f0 := roundtripPortfolioSelectionPlan v.plan h0
  simp only [encPortfolioSelectionJournalEntry, objectPortfolioSelectionJournalEntry]
  rw [f0]
  rfl

theorem canonicalPortfolioSelectionJournalEntry {j : Json} {v : PortfolioSelectionJournalEntry} (h : WirePortfolioSelectionJournalEntry v)
    (decoded : decPortfolioSelectionJournalEntry j = .ok v) :
    ((encPortfolioSelectionJournalEntry <$> decPortfolioSelectionJournalEntry j) >>= decPortfolioSelectionJournalEntry) = .ok v := by
  simp [decoded, roundtripPortfolioSelectionJournalEntry v h, bind, Except.bind, Functor.map, Except.map]

def encPortfolioSelectionResult (v : PortfolioSelectionResult) : Json := Json.mkObj [
  ("state", (encPortfolioState) v.state),
  ("journal", (encList encPortfolioSelectionJournalEntry) v.journal),
  ("outcome", (encApplyOutcome) v.outcome)]

def decPortfolioSelectionResult (j : Json) : Except String PortfolioSelectionResult := do
  fields j ["state", "journal", "outcome"]
  let state : PortfolioState ← field j "state" >>= (decPortfolioState)
  let journal : List PortfolioSelectionJournalEntry ← field j "journal" >>= (decList decPortfolioSelectionJournalEntry)
  let outcome : ApplyOutcome ← field j "outcome" >>= (decApplyOutcome)
  return ⟨state, journal, outcome⟩

def WirePortfolioSelectionResult (v : PortfolioSelectionResult) : Prop :=
  (WirePortfolioState v.state) ∧
  (∀ x ∈ v.journal, WirePortfolioSelectionJournalEntry x)

private theorem objectPortfolioSelectionResult (j0 j1 j2 : Json) :
    decPortfolioSelectionResult (Json.mkObj [("state", j0), ("journal", j1), ("outcome", j2)]) =
    (do
      let state : PortfolioState ← (decPortfolioState) j0
      let journal : List PortfolioSelectionJournalEntry ← (decList decPortfolioSelectionJournalEntry) j1
      let outcome : ApplyOutcome ← (decApplyOutcome) j2
      return (⟨state, journal, outcome⟩ : PortfolioSelectionResult)) := rfl

theorem roundtripPortfolioSelectionResult (v : PortfolioSelectionResult) (h : WirePortfolioSelectionResult v) :
    decPortfolioSelectionResult (encPortfolioSelectionResult v) = .ok v := by
  rcases h with ⟨h0, h1⟩
  have f0 := roundtripPortfolioState v.state h0
  have f1 := decList_encList encPortfolioSelectionJournalEntry decPortfolioSelectionJournalEntry v.journal (fun x hx => roundtripPortfolioSelectionJournalEntry x (h1 x hx))
  have f2 := roundtripApplyOutcome v.outcome
  simp only [encPortfolioSelectionResult, objectPortfolioSelectionResult]
  rw [f0, f1, f2]
  rfl

theorem canonicalPortfolioSelectionResult {j : Json} {v : PortfolioSelectionResult} (h : WirePortfolioSelectionResult v)
    (decoded : decPortfolioSelectionResult j = .ok v) :
    ((encPortfolioSelectionResult <$> decPortfolioSelectionResult j) >>= decPortfolioSelectionResult) = .ok v := by
  simp [decoded, roundtripPortfolioSelectionResult v h, bind, Except.bind, Functor.map, Except.map]

def encImplementationBinding (v : ImplementationBinding) : Json := Json.mkObj [
  ("design_revision", (encIdent) v.designRevision),
  ("source", (encIdent) v.source),
  ("target_revision", (encIdent) v.targetRevision),
  ("actor", (encIdent) v.actor),
  ("observed_at", (encNat) v.observedAt)]

def decImplementationBinding (j : Json) : Except String ImplementationBinding := do
  fields j ["design_revision", "source", "target_revision", "actor", "observed_at"]
  let designRevision : ProposalRevision ← field j "design_revision" >>= (decIdent)
  let source : SourceId ← field j "source" >>= (decIdent)
  let targetRevision : TargetRevision ← field j "target_revision" >>= (decIdent)
  let actor : ActorId ← field j "actor" >>= (decIdent)
  let observedAt : Nat ← field j "observed_at" >>= (decNat)
  return ⟨designRevision, source, targetRevision, actor, observedAt⟩

private theorem objectImplementationBinding (j0 j1 j2 j3 j4 : Json) :
    decImplementationBinding (Json.mkObj [("design_revision", j0), ("source", j1), ("target_revision", j2), ("actor", j3), ("observed_at", j4)]) =
    (do
      let designRevision : ProposalRevision ← (decIdent) j0
      let source : SourceId ← (decIdent) j1
      let targetRevision : TargetRevision ← (decIdent) j2
      let actor : ActorId ← (decIdent) j3
      let observedAt : Nat ← (decNat) j4
      return (⟨designRevision, source, targetRevision, actor, observedAt⟩ : ImplementationBinding)) := rfl

theorem roundtripImplementationBinding (v : ImplementationBinding) :
    decImplementationBinding (encImplementationBinding v) = .ok v := by
  have f0 := decIdent_encIdent v.designRevision
  have f1 := decIdent_encIdent v.source
  have f2 := decIdent_encIdent v.targetRevision
  have f3 := decIdent_encIdent v.actor
  have f4 := decNat_encNat v.observedAt
  simp only [encImplementationBinding, objectImplementationBinding]
  rw [f0, f1, f2, f3, f4]
  rfl

theorem canonicalImplementationBinding {j : Json} {v : ImplementationBinding}
    (decoded : decImplementationBinding j = .ok v) :
    ((encImplementationBinding <$> decImplementationBinding j) >>= decImplementationBinding) = .ok v := by
  simp [decoded, roundtripImplementationBinding v, bind, Except.bind, Functor.map, Except.map]

def encDesignProposal (v : DesignProposal) : Json := Json.mkObj [
  ("authored", (encAuthoredProposal) v.authored),
  ("target_source", (encIdent) v.targetSource),
  ("binding", (encOpt encImplementationBinding) v.binding)]

def decDesignProposal (j : Json) : Except String DesignProposal := do
  fields j ["authored", "target_source", "binding"]
  let authored : AuthoredProposal ← field j "authored" >>= (decAuthoredProposal)
  let targetSource : SourceId ← field j "target_source" >>= (decIdent)
  let binding : Option ImplementationBinding ← field j "binding" >>= (decOpt decImplementationBinding)
  return ⟨authored, targetSource, binding⟩

def WireDesignProposal (v : DesignProposal) : Prop :=
  (WireAuthoredProposal v.authored)

private theorem objectDesignProposal (j0 j1 j2 : Json) :
    decDesignProposal (Json.mkObj [("authored", j0), ("target_source", j1), ("binding", j2)]) =
    (do
      let authored : AuthoredProposal ← (decAuthoredProposal) j0
      let targetSource : SourceId ← (decIdent) j1
      let binding : Option ImplementationBinding ← (decOpt decImplementationBinding) j2
      return (⟨authored, targetSource, binding⟩ : DesignProposal)) := rfl

theorem roundtripDesignProposal (v : DesignProposal) (h : WireDesignProposal v) :
    decDesignProposal (encDesignProposal v) = .ok v := by
  have h0 : WireAuthoredProposal v.authored := h
  have f0 := roundtripAuthoredProposal v.authored h0
  have f1 := decIdent_encIdent v.targetSource
  have f2 := decOpt_encOpt encImplementationBinding decImplementationBinding v.binding (fun x _ => roundtripImplementationBinding x) (by intro x; simp [encImplementationBinding, Json.mkObj])
  simp only [encDesignProposal, objectDesignProposal]
  rw [f0, f1, f2]
  rfl

theorem canonicalDesignProposal {j : Json} {v : DesignProposal} (h : WireDesignProposal v)
    (decoded : decDesignProposal j = .ok v) :
    ((encDesignProposal <$> decDesignProposal j) >>= decDesignProposal) = .ok v := by
  simp [decoded, roundtripDesignProposal v h, bind, Except.bind, Functor.map, Except.map]

def encDesignBindingCommand (v : DesignBindingCommand) : Json := Json.mkObj [
  ("expected", (encDesignProposal) v.expected),
  ("binding", (encImplementationBinding) v.binding)]

def decDesignBindingCommand (j : Json) : Except String DesignBindingCommand := do
  fields j ["expected", "binding"]
  let expected : DesignProposal ← field j "expected" >>= (decDesignProposal)
  let binding : ImplementationBinding ← field j "binding" >>= (decImplementationBinding)
  return ⟨expected, binding⟩

def WireDesignBindingCommand (v : DesignBindingCommand) : Prop :=
  (WireDesignProposal v.expected)

private theorem objectDesignBindingCommand (j0 j1 : Json) :
    decDesignBindingCommand (Json.mkObj [("expected", j0), ("binding", j1)]) =
    (do
      let expected : DesignProposal ← (decDesignProposal) j0
      let binding : ImplementationBinding ← (decImplementationBinding) j1
      return (⟨expected, binding⟩ : DesignBindingCommand)) := rfl

theorem roundtripDesignBindingCommand (v : DesignBindingCommand) (h : WireDesignBindingCommand v) :
    decDesignBindingCommand (encDesignBindingCommand v) = .ok v := by
  have h0 : WireDesignProposal v.expected := h
  have f0 := roundtripDesignProposal v.expected h0
  have f1 := roundtripImplementationBinding v.binding
  simp only [encDesignBindingCommand, objectDesignBindingCommand]
  rw [f0, f1]
  rfl

theorem canonicalDesignBindingCommand {j : Json} {v : DesignBindingCommand} (h : WireDesignBindingCommand v)
    (decoded : decDesignBindingCommand j = .ok v) :
    ((encDesignBindingCommand <$> decDesignBindingCommand j) >>= decDesignBindingCommand) = .ok v := by
  simp [decoded, roundtripDesignBindingCommand v h, bind, Except.bind, Functor.map, Except.map]

def encDesignReopenCommand (v : DesignReopenCommand) : Json := Json.mkObj [
  ("expected", (encDesignProposal) v.expected),
  ("actor", (encIdent) v.actor),
  ("reason", (encStr) v.reason)]

def decDesignReopenCommand (j : Json) : Except String DesignReopenCommand := do
  fields j ["expected", "actor", "reason"]
  let expected : DesignProposal ← field j "expected" >>= (decDesignProposal)
  let actor : ActorId ← field j "actor" >>= (decIdent)
  let reason : String ← field j "reason" >>= (decStr)
  return ⟨expected, actor, reason⟩

def WireDesignReopenCommand (v : DesignReopenCommand) : Prop :=
  (WireDesignProposal v.expected)

private theorem objectDesignReopenCommand (j0 j1 j2 : Json) :
    decDesignReopenCommand (Json.mkObj [("expected", j0), ("actor", j1), ("reason", j2)]) =
    (do
      let expected : DesignProposal ← (decDesignProposal) j0
      let actor : ActorId ← (decIdent) j1
      let reason : String ← (decStr) j2
      return (⟨expected, actor, reason⟩ : DesignReopenCommand)) := rfl

theorem roundtripDesignReopenCommand (v : DesignReopenCommand) (h : WireDesignReopenCommand v) :
    decDesignReopenCommand (encDesignReopenCommand v) = .ok v := by
  have h0 : WireDesignProposal v.expected := h
  have f0 := roundtripDesignProposal v.expected h0
  have f1 := decIdent_encIdent v.actor
  have f2 := decStr_encStr v.reason
  simp only [encDesignReopenCommand, objectDesignReopenCommand]
  rw [f0, f1, f2]
  rfl

theorem canonicalDesignReopenCommand {j : Json} {v : DesignReopenCommand} (h : WireDesignReopenCommand v)
    (decoded : decDesignReopenCommand j = .ok v) :
    ((encDesignReopenCommand <$> decDesignReopenCommand j) >>= decDesignReopenCommand) = .ok v := by
  simp [decoded, roundtripDesignReopenCommand v h, bind, Except.bind, Functor.map, Except.map]

end Kctx
