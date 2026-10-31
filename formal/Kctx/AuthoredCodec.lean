import Kctx.Codec

set_option autoImplicit false
namespace Kctx
open Lean

def encAuthoredStatus : AuthoredStatus → Json
  | .draft => .str "draft"
  | .proposed => .str "proposed"
  | .accepted => .str "accepted"
  | .rejected => .str "rejected"
  | .landing => .str "landing"
  | .applied => .str "applied"
  | .verified => .str "verified"
  | .regressed => .str "regressed"
  | .deferred => .str "deferred"
  | .superseded => .str "superseded"
def decAuthoredStatus (j : Json) : Except String AuthoredStatus := do
  match ← decStr j with
  | "draft" => pure .draft
  | "proposed" => pure .proposed
  | "accepted" => pure .accepted
  | "rejected" => pure .rejected
  | "landing" => pure .landing
  | "applied" => pure .applied
  | "verified" => pure .verified
  | "regressed" => pure .regressed
  | "deferred" => pure .deferred
  | "superseded" => pure .superseded
  | _ => throw "invalid_request"

def encProfile : Profile → Json
  | .modern => .str "modern"
  | .legacyLimited => .str "legacy_limited"
def decProfile (j : Json) : Except String Profile := do
  match ← decStr j with
  | "modern" => pure .modern
  | "legacy_limited" => pure .legacyLimited
  | _ => throw "invalid_request"

def encGatePhase : GatePhase → Json
  | .land => .str "land"
  | .deploy => .str "deploy"
  | .use => .str "use"
def decGatePhase (j : Json) : Except String GatePhase := do
  match ← decStr j with
  | "land" => pure .land
  | "deploy" => pure .deploy
  | "use" => pure .use
  | _ => throw "invalid_request"

def encGateOutcome : GateOutcome → Json
  | .pass => .str "pass"
  | .fail => .str "fail"
  | .unk => .str "unk"
def decGateOutcome (j : Json) : Except String GateOutcome := do
  match ← decStr j with
  | "pass" => pure .pass
  | "fail" => pure .fail
  | "unk" => pure .unk
  | _ => throw "invalid_request"

def encGateDefinition (v : GateDefinition) : Json := Json.mkObj [
  ("id", encIdent v.id),
  ("claim", encStr v.claim),
  ("check", encStr v.check),
  ("when", encGatePhase v.when),
  ("by", encOptionalIdent v.byActor),
  ("checker", encOptionalIdent v.checker)]
def decGateDefinition (j : Json) : Except String GateDefinition := do
  fields j ["id", "claim", "check", "when", "by", "checker"]
  let id ← field j "id" >>= decIdent
  let claim ← field j "claim" >>= decStr
  let check ← field j "check" >>= decStr
  let when ← field j "when" >>= decGatePhase
  let byActor ← field j "by" >>= decOptionalIdent
  let checker ← field j "checker" >>= decOptionalIdent
  let v : GateDefinition := ⟨id, claim, check, when, byActor, checker⟩
  if token v.id.val then pure v else throw "invalid_request"

def encGateResult (v : GateResult) : Json := Json.mkObj [
  ("definition", encGateDefinition v.definition),
  ("target_revision", encOptionalIdent v.targetRevision),
  ("checker", encOptionalIdent v.checker),
  ("result", encGateOutcome v.result),
  ("observed_at", encNat v.observedAt),
  ("expires_at", encNat v.expiresAt), ("proposal_revision", encOptionalIdent v.proposalRevision),
  ("environment", encStr v.environment), ("scope", encStr v.scope),
  ("evidence_refs", encList encStr v.evidenceRefs), ("actor", encOptionalIdent v.actor)]
def decGateResult (j : Json) : Except String GateResult := do
  fields j ["definition", "target_revision", "checker", "result", "observed_at", "expires_at", "proposal_revision", "environment", "scope", "evidence_refs", "actor"]
  let definition ← field j "definition" >>= decGateDefinition
  let targetRevision ← field j "target_revision" >>= decOptionalIdent
  let checker ← field j "checker" >>= decOptionalIdent
  let result ← field j "result" >>= decGateOutcome
  let observedAt ← field j "observed_at" >>= decNat
  let expiresAt ← field j "expires_at" >>= decNat
  let proposalRevision ← field j "proposal_revision" >>= decOptionalIdent
  let environment ← field j "environment" >>= decStr
  let scope ← field j "scope" >>= decStr
  let evidenceRefs ← field j "evidence_refs" >>= decList decStr
  let actor ← field j "actor" >>= decOptionalIdent
  let v : GateResult := ⟨definition, targetRevision, checker, result, observedAt, expiresAt, proposalRevision, environment, scope, evidenceRefs, actor⟩
  pure v

def encAuthoredReplacement (v : AuthoredReplacement) : Json := Json.mkObj [
  ("id", encIdent v.id),
  ("superseded_by", (encOpt encIdent) v.supersededBy)]
def decAuthoredReplacement (j : Json) : Except String AuthoredReplacement := do
  fields j ["id", "superseded_by"]
  let id ← field j "id" >>= decIdent
  let supersededBy ← field j "superseded_by" >>= (decOpt decIdent)
  let v : AuthoredReplacement := ⟨id, supersededBy⟩
  pure v

def encAuthoredLanded (v : AuthoredLanded) : Json := Json.mkObj [
  ("reference", encStr v.reference), ("target_revision", encIdent v.targetRevision)]
def decAuthoredLanded (j : Json) : Except String AuthoredLanded := do
  fields j ["reference", "target_revision"]
  return ⟨← field j "reference" >>= decStr, ← field j "target_revision" >>= decIdent⟩

def encAuthoredProposal (v : AuthoredProposal) : Json := Json.mkObj [
  ("status", encAuthoredStatus v.status),
  ("profile", encProfile v.profile),
  ("research_present", encBool v.researchPresent),
  ("alternatives_count", encNat v.alternativesCount),
  ("target_revision", encOptionalIdent v.targetRevision),
  ("gate_definitions", (encList encGateDefinition) v.gateDefinitions),
  ("gate_results", (encList encGateResult) v.gateResults),
  ("actor", encOptionalIdent v.actor),
  ("acceptor", encOptionalIdent v.acceptor),
  ("executor", encOptionalIdent v.executor),
  ("verifier", encOptionalIdent v.verifier),
  ("landed_refs", (encList encStr) v.landedRefs),
  ("regression_note", encStr v.regressionNote),
  ("id", encIdent v.id),
  ("superseded_by", (encOpt encIdent) v.supersededBy),
  ("proposals", (encList encAuthoredReplacement) v.proposals),
  ("accepted_revision", encOptionalIdent v.acceptedRevision),
  ("proposal_revision", encOptionalIdent v.proposalRevision), ("environment", encStr v.environment), ("scope", encStr v.scope),
  ("resolved_landed", encList encAuthoredLanded v.resolvedLanded)]
def decAuthoredProposal (j : Json) : Except String AuthoredProposal := do
  fields j ["status", "profile", "research_present", "alternatives_count", "target_revision", "gate_definitions", "gate_results", "actor", "acceptor", "executor", "verifier", "landed_refs", "regression_note", "id", "superseded_by", "proposals", "accepted_revision", "proposal_revision", "environment", "scope", "resolved_landed"]
  let status ← field j "status" >>= decAuthoredStatus
  let profile ← field j "profile" >>= decProfile
  let researchPresent ← field j "research_present" >>= decBool
  let alternativesCount ← field j "alternatives_count" >>= decNat
  let targetRevision ← field j "target_revision" >>= decOptionalIdent
  let gateDefinitions ← field j "gate_definitions" >>= (decList decGateDefinition)
  let gateResults ← field j "gate_results" >>= (decList decGateResult)
  let actor ← field j "actor" >>= decOptionalIdent
  let acceptor ← field j "acceptor" >>= decOptionalIdent
  let executor ← field j "executor" >>= decOptionalIdent
  let verifier ← field j "verifier" >>= decOptionalIdent
  let landedRefs ← field j "landed_refs" >>= (decList decStr)
  let regressionNote ← field j "regression_note" >>= decStr
  let id ← field j "id" >>= decIdent
  let supersededBy ← field j "superseded_by" >>= (decOpt decIdent)
  let proposals ← field j "proposals" >>= (decList decAuthoredReplacement)
  let acceptedRevision ← field j "accepted_revision" >>= decOptionalIdent
  let proposalRevision ← field j "proposal_revision" >>= decOptionalIdent
  let environment ← field j "environment" >>= decStr
  let scope ← field j "scope" >>= decStr
  let resolvedLanded ← field j "resolved_landed" >>= decList decAuthoredLanded
  let v : AuthoredProposal := ⟨status, profile, researchPresent, alternativesCount, targetRevision, gateDefinitions, gateResults, actor, acceptor, executor, verifier, landedRefs, regressionNote, id, supersededBy, proposals, acceptedRevision, proposalRevision, environment, scope, resolvedLanded⟩
  if unique (v.gateDefinitions.map (·.id)) then pure v else throw "invalid_request"

end Kctx
