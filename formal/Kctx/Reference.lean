import Kctx.AuthoredCodec
import Kctx.Theorems2
import Kctx.SelectionCodec

set_option autoImplicit false
set_option maxRecDepth 4096
namespace Kctx.Reference
open Lean

def baseFields : List String := ["schema_version", "semantic_version", "id", "op"]
def requestFields (j : Json) (extra : List String) : Except String Unit := fields j (baseFields ++ extra)

def evaluate (j : Json) (trusted : List VerifiedApproval := [])
    (selections : List VerifiedSelectionApproval := []) (retained : List KB := []) : Except String Json := do
  let schema ← field j "schema_version" >>= decNat
  let version ← field j "semantic_version" >>= decStr
  let _ ← field j "id" >>= decStr
  if schema != 2 || version != semanticVersion then throw "invalid_request"
  let op ← field j "op" >>= decStr
  if op == "semantic_version" then
    requestFields j []
    return .str semanticVersion
  if op == "fresh" then
    requestFields j ["now", "observed_at", "ttl"]
    let now ← field j "now" >>= decNat
    let observed ← field j "observed_at" >>= decNat
    let ttl ← field j "ttl" >>= decTtlPolicy
    return encFresh (assessFresh ttl observed now)
  if op == "validate" then
    requestFields j ["kb"]
    let _ ← field j "kb" >>= decKB
    return .bool true
  if op == "conclude" then
    requestFields j ["investigation"]
    return .bool (conclude (← field j "investigation" >>= decInvestigation))
  if op == "authored_transition" then
    requestFields j ["proposal", "target_status", "now"]
    return .bool (authoredTransition (← field j "proposal" >>= decAuthoredProposal)
      (← field j "target_status" >>= decAuthoredStatus) (← field j "now" >>= decNat))
  if op == "authored_candidate_valid" then
    requestFields j ["proposal", "target_status", "now"]
    return .bool (authoredCandidateValid (← field j "proposal" >>= decAuthoredProposal)
      (← field j "target_status" >>= decAuthoredStatus) (← field j "now" >>= decNat))
  if op == "select" then
    requestFields j ["state", "context", "journal", "plan"]
    let state ← field j "state" >>= decSelectionState
    let context ← field j "context" >>= decContext
    let journal ← field j "journal" >>= decList decSelectionJournalEntry
    let plan ← field j "plan" >>= decSelectionPlan
    return encSelectionResult (applySelection state context journal plan selections retained)
  if op == "retrieve_selected" then
    requestFields j ["state", "context", "offset", "limit"]
    let state ← field j "state" >>= decSelectionState
    let context ← field j "context" >>= decContext
    if !contextValid state.kb context then throw "invalid_request"
    return encRetrieval (retrieveSelected state context (← field j "offset" >>= decNat) (← field j "limit" >>= decNat))
  let k ← field j "kb" >>= decKB
  let e ← field j "context" >>= decContext
  match op with
  | "check" =>
      requestFields j ["kb", "context", "witness"]
      return encOpt encChecked (check k e (← field j "witness" >>= decWitness))
  | "supported" =>
      requestFields j ["kb", "context", "claim", "polarity"]
      return .bool (supported k e (← field j "claim" >>= decRef) (← field j "polarity" >>= decPolarity))
  | "assess" =>
      requestFields j ["kb", "context", "claim"]
      return encAssessment (assess k e (← field j "claim" >>= decRef))
  | "usable" =>
      requestFields j ["kb", "context", "claim"]
      return .bool (usableFor k e (← field j "claim" >>= decRef))
  | "reuse" =>
      requestFields j ["kb", "context", "claim", "receipt"]
      return .bool (reusable k e (← field j "claim" >>= decRef) (← field j "receipt" >>= decReceipt))
  | "retrieve" =>
      requestFields j ["kb", "context", "offset", "limit"]
      if !contextValid k e then throw "invalid_request"
      return encRetrieval (retrieve k e (← field j "offset" >>= decNat) (← field j "limit" >>= decNat))
  | "admit" =>
      requestFields j ["kb", "context", "plan"]
      return encApplyResult (applyPlan k e [] (← field j "plan" >>= decPlan) trusted)
  | "sequence" =>
      requestFields j ["kb", "context", "journal", "plans"]
      if !contextValid k e then throw "invalid_request"
      return encSequenceResult (applySequence k e (← field j "journal" >>= decList decJournalEntry)
        trusted (← field j "plans" >>= decList decPlan))
  | "transition" =>
      requestFields j ["kb", "context", "proposal", "target_status"]
      return .bool (transition k e (← field j "proposal" >>= decProposal) (← field j "target_status" >>= decProposalStatus))
  | _ => throw "invalid_request"

/-- Reference-only authenticated environment fixture. Ordinary requests cannot
manufacture VerifiedApproval; production adapters obtain these after verification. -/
def unwrap (j : Json) : Except String (Json × List VerifiedApproval × List VerifiedSelectionApproval × List KB) := do
  match field j "request" with
  | .error _ => pure (j, [], [], [])
  | .ok request =>
      fields j ["request", "trusted_environment"]
      let env ← field j "trusted_environment"
      fields env ["approvals", "selections", "retained"]
      let approvals ← field env "approvals" >>= decList decVerifiedApproval
      let selections ← field env "selections" >>= decList decVerifiedSelectionApproval
      let retained ← field env "retained" >>= decList decKB
      if !unique (retained.map (·.snapshot)) then throw "invalid_request"
      return (request, approvals, selections, retained)

def response (j : Json) : Json :=
  match unwrap j with
  | .error _ => Json.mkObj [("id", .str ""), ("ok", .bool false), ("error", .str "invalid_request")]
  | .ok (request, trusted, selections, retained) =>
      let id := (field request "id" >>= decStr).toOption.getD ""
      match evaluate request trusted selections retained with
      | .ok result => Json.mkObj [("id", .str id), ("ok", .bool true), ("result", result)]
      | .error _ => Json.mkObj [("id", .str id), ("ok", .bool false), ("error", .str "invalid_request")]

structure ObjectFrame where
  object : Bool
  keys : List String
  expectsKey : Bool

/-- JSON escape syntax may contain UTF-16 pairs, but never lone surrogates.
Lean's parser replaces lone surrogates; the wire contract rejects them instead. -/
private def scalarEscapes : List Char → Bool
  | '\\' :: 'u' :: a :: b :: _c :: _d :: rest =>
      if (a == 'd' || a == 'D') && ['8', '9', 'a', 'A', 'b', 'B'].contains b then
        match rest with
        | '\\' :: 'u' :: e :: f :: _g :: _h :: following =>
            (e == 'd' || e == 'D') && ['c', 'C', 'd', 'D', 'e', 'E', 'f', 'F'].contains f &&
              scalarEscapes following
        | _ => false
      else if (a == 'd' || a == 'D') && ['c', 'C', 'd', 'D', 'e', 'E', 'f', 'F'].contains b then false
      else scalarEscapes rest
  | '\\' :: _ :: rest => scalarEscapes rest
  | _ :: rest => scalarEscapes rest
  | [] => true

/-- Preserve duplicate-key rejection before Json.parse normalizes object maps.
Keys are decoded before comparison, so escaped aliases are duplicates too. -/
def quoted : List Char → Bool → List Char → Option (String × List Char)
  | [], _, _ => none
  | c :: cs, escaped, acc =>
      if escaped then quoted cs false (c :: acc)
      else if c == '\\' then quoted cs true (c :: acc)
      else if c == '"' then some (String.mk ((c :: acc).reverse), cs)
      else quoted cs false (c :: acc)

def uniqueKeys : Nat → List Char → List ObjectFrame → Bool
  | 0, _, _ => false
  | _ + 1, [], _ => true
  | n + 1, c :: cs, stack =>
      if c == '"' then
        match quoted cs false ['"'] with
        | none => false
        | some (raw, rest) =>
            if !scalarEscapes raw.toList then false else
            match stack with
            | f :: fs =>
                if f.object && f.expectsKey then
                  match Json.parse raw >>= decStr with
                  | .error _ => false
                  | .ok key => !f.keys.contains key && uniqueKeys n rest ({ f with keys := key :: f.keys, expectsKey := false } :: fs)
                else uniqueKeys n rest stack
            | [] => uniqueKeys n rest stack
      else if c == '{' then uniqueKeys n cs (⟨true, [], true⟩ :: stack)
      else if c == '[' then uniqueKeys n cs (⟨false, [], false⟩ :: stack)
      else if c == '}' || c == ']' then uniqueKeys n cs stack.tail
      else if c == ',' then
        match stack with
        | f :: fs => uniqueKeys n cs ({ f with expectsKey := f.object } :: fs)
        | [] => false
      else uniqueKeys n cs stack

def processLine (line : String) : Json :=
  let parsed := Json.parse line
  if uniqueKeys (line.length + 1) line.toList [] then
    match parsed with
    | .ok j => response j
    | .error _ => Json.mkObj [("id", .str ""), ("ok", .bool false), ("error", .str "invalid_request")]
  else Json.mkObj [("id", .str ""), ("ok", .bool false), ("error", .str "invalid_request")]

end Kctx.Reference

def main : IO Unit := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    if !line.trim.isEmpty then
      output.putStrLn ((Kctx.Reference.processLine line).compress)
