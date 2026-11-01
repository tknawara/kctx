import Kctx.WorkflowV3Codec

set_option autoImplicit false
set_option maxRecDepth 4096
namespace Kctx.WorkflowV3Reference
open Lean

/-! Workflow schema 3 is an authorization/lifecycle extension, not a new
finite-witness language. Contexts still identify semantic version 2.0.0.
Only the external trusted-environment fixture constructs approval capabilities. -/

def baseFields : List String := ["schema_version", "semantic_version", "id", "op"]
def requestFields (j : Json) (extra : List String) : Except String Unit :=
  fields j (baseFields ++ extra)

def evaluate (j : Json) (trusted : List VerifiedPortfolioApproval := [])
    (selections : List VerifiedPortfolioSelectionApproval := [])
    (retained : List PortfolioState := []) : Except String Json := do
  let schema ← field j "schema_version" >>= decNat
  let version ← field j "semantic_version" >>= decStr
  let id ← field j "id" >>= decStr
  if id.isEmpty || schema != 3 || version != semanticVersion then throw "invalid_request"
  let op ← field j "op" >>= decStr
  if op == "semantic_version" then
    requestFields j []
    return .str semanticVersion
  if op == "workflow_version" then
    requestFields j []
    return encNat 3
  if op == "portfolio_state_valid" then
    requestFields j ["state"]
    return .bool (portfolioStateValid (← field j "state" >>= decPortfolioState))
  if op == "portfolio_valid" then
    requestFields j ["state", "plan"]
    return .bool (portfolioPlanValid (← field j "state" >>= decPortfolioState)
      (← field j "plan" >>= decPortfolioPlan))
  if op == "portfolio_admit" then
    requestFields j ["state", "journal", "plan"]
    return encPortfolioResult (applyPortfolio (← field j "state" >>= decPortfolioState)
      (← field j "journal" >>= decList decPortfolioJournalEntry)
      (← field j "plan" >>= decPortfolioPlan) trusted)
  if op == "portfolio_query_allowed" then
    requestFields j ["state", "context_id", "context"]
    return .bool (queryContextAllowed (← field j "state" >>= decPortfolioState)
      (← field j "context_id" >>= decWorkflowIdent) (← field j "context" >>= decContext))
  if op == "portfolio_assess" then
    requestFields j ["state", "context_id", "context", "claim"]
    return encOpt encAssessment (assessPortfolio (← field j "state" >>= decPortfolioState)
      (← field j "context_id" >>= decWorkflowIdent) (← field j "context" >>= decContext)
      (← field j "claim" >>= decRef))
  if op == "portfolio_selection_valid" then
    requestFields j ["state", "plan"]
    return .bool (portfolioSelectionValid (← field j "state" >>= decPortfolioState)
      (← field j "plan" >>= decPortfolioSelectionPlan) retained)
  if op == "portfolio_select" then
    requestFields j ["state", "journal", "plan"]
    return encPortfolioSelectionResult (applyPortfolioSelection
      (← field j "state" >>= decPortfolioState)
      (← field j "journal" >>= decList decPortfolioSelectionJournalEntry)
      (← field j "plan" >>= decPortfolioSelectionPlan) selections retained)
  if op == "design_valid" || op == "design_transition" then
    requestFields j ["proposal", "target_status", "now"]
    let proposal ← field j "proposal" >>= decDesignProposal
    let target ← field j "target_status" >>= decAuthoredStatus
    let now ← field j "now" >>= decNat
    return .bool (if op == "design_valid" then designCandidateValid proposal target now
      else designTransition proposal target now)
  if op == "design_bind" then
    requestFields j ["proposal", "command", "now"]
    return encOpt encDesignProposal (bindImplementation
      (← field j "proposal" >>= decDesignProposal)
      (← field j "command" >>= decDesignBindingCommand) (← field j "now" >>= decNat))
  if op == "design_reopen" then
    requestFields j ["proposal", "command"]
    return encOpt encDesignProposal (reopenDesign
      (← field j "proposal" >>= decDesignProposal)
      (← field j "command" >>= decDesignReopenCommand))
  throw "invalid_request"

def unwrap (j : Json) : Except String
    (Json × List VerifiedPortfolioApproval × List VerifiedPortfolioSelectionApproval × List PortfolioState) := do
  match field j "request" with
  | .error _ => pure (j, [], [], [])
  | .ok request =>
      fields j ["request", "trusted_environment"]
      let env ← field j "trusted_environment"
      fields env ["approvals", "selections", "retained"]
      let approvals ← field env "approvals" >>= decList decVerifiedPortfolioApproval
      let selections ← field env "selections" >>= decList decVerifiedPortfolioSelectionApproval
      let retained ← field env "retained" >>= decList decPortfolioState
      if !unique (retained.map (fun s => s.kb.snapshot)) then throw "invalid_request"
      return (request, approvals, selections, retained)

def response (j : Json) : Json :=
  match unwrap j with
  | .error _ => Json.mkObj [("id", .str ""), ("ok", .bool false), ("error", .str "invalid_request")]
  | .ok (request, trusted, selections, retained) =>
      let id := (field request "id" >>= decStr).toOption.getD ""
      match evaluate request trusted selections retained with
      | .ok result => Json.mkObj [("id", .str id), ("ok", .bool true), ("result", result)]
      | .error _ => Json.mkObj [("id", .str id), ("ok", .bool false), ("error", .str "invalid_request")]

end Kctx.WorkflowV3Reference
