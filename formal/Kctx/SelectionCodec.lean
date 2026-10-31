import Kctx.Codec
import Kctx.Selection

set_option autoImplicit false
namespace Kctx
open Lean

def encSelectionState (v : SelectionState) : Json := Json.mkObj [
  ("kb", encKB v.kb),
  ("selected", (encList encRef) v.selected)]
def decSelectionState (j : Json) : Except String SelectionState := do
  fields j ["kb", "selected"]
  let kb ← field j "kb" >>= decKB
  let selected ← field j "selected" >>= (decList decRef)
  let v : SelectionState := ⟨kb, selected⟩
  if selectionStateValid v then pure v else throw "invalid_request"

def encSelectionPlan (v : SelectionPlan) : Json := Json.mkObj [
  ("id", encIdent v.id),
  ("expected_snapshot", encIdent v.expectedSnapshot),
  ("target_snapshot", encIdent v.targetSnapshot),
  ("new_snapshot", encIdent v.newSnapshot),
  ("selected", (encList encRef) v.selected),
  ("actor", encOptionalIdent v.actor),
  ("policy", encIdent v.policy),
  ("intended_use", encStr v.intendedUse),
  ("context", encContext v.context)]
def decSelectionPlan (j : Json) : Except String SelectionPlan := do
  fields j ["id", "expected_snapshot", "target_snapshot", "new_snapshot", "selected", "actor", "policy", "intended_use", "context"]
  let id ← field j "id" >>= decIdent
  let expectedSnapshot ← field j "expected_snapshot" >>= decIdent
  let targetSnapshot ← field j "target_snapshot" >>= decIdent
  let newSnapshot ← field j "new_snapshot" >>= decIdent
  let selected ← field j "selected" >>= (decList decRef)
  let actor ← field j "actor" >>= decOptionalIdent
  let policy ← field j "policy" >>= decIdent
  let intendedUse ← field j "intended_use" >>= decStr
  let context ← field j "context" >>= decContext
  let v : SelectionPlan := ⟨id, expectedSnapshot, targetSnapshot, newSnapshot, selected, actor, policy, intendedUse, context⟩
  if token v.id.val && token v.expectedSnapshot.val && token v.targetSnapshot.val && token v.newSnapshot.val && token v.policy.val && v.intendedUse != "" then pure v else throw "invalid_request"

def encVerifiedSelectionApproval (v : VerifiedSelectionApproval) : Json := Json.mkObj [
  ("plan", encSelectionPlan v.plan)]
def decVerifiedSelectionApproval (j : Json) : Except String VerifiedSelectionApproval := do
  fields j ["plan"]
  let plan ← field j "plan" >>= decSelectionPlan
  let v : VerifiedSelectionApproval := ⟨plan⟩
  pure v

def encSelectionJournalEntry (v : SelectionJournalEntry) : Json := Json.mkObj [
  ("plan", encSelectionPlan v.plan)]
def decSelectionJournalEntry (j : Json) : Except String SelectionJournalEntry := do
  fields j ["plan"]
  let plan ← field j "plan" >>= decSelectionPlan
  let v : SelectionJournalEntry := ⟨plan⟩
  pure v

def encSelectionResult (v : SelectionResult) : Json := Json.mkObj [
  ("state", encSelectionState v.state),
  ("journal", (encList encSelectionJournalEntry) v.journal),
  ("outcome", encApplyOutcome v.outcome)]
def decSelectionResult (j : Json) : Except String SelectionResult := do
  fields j ["state", "journal", "outcome"]
  let state ← field j "state" >>= decSelectionState
  let journal ← field j "journal" >>= (decList decSelectionJournalEntry)
  let outcome ← field j "outcome" >>= decApplyOutcome
  let v : SelectionResult := ⟨state, journal, outcome⟩
  pure v

end Kctx
