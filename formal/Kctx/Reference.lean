import Kctx.Codec
import Kctx.Theorems2

set_option autoImplicit false
set_option maxHeartbeats 1000000

/-! Reference evaluator (CI conformance oracle).

Reads JSONL on stdin: one request object per line, each of the shape
`{"id": "...", "op": "...", "kb": <kb>, "ctx": <ctx>, ...op fields...}`.
Writes one response line per request:
`{"id": "...", "ok": true, "result": <json>}` or
`{"id": "...", "ok": false, "error": "..."}`.

The wire format is the positional-array codec from `Kctx.Codec` (field order
is the contract; see `kctx/semantics/wire.py` for the Python mirror). Both
sides carry `SEMANTIC_VERSION`. -/

namespace Kctx.Reference

open Lean

def field (j : Json) (k : String) : Except String Json := do
  match j with
  | .obj _ => j.getObjVal? k
  | _ => throw "expected object request"

def reqId (j : Json) : String :=
  match field j "id" with
  | .ok (.str s) => s
  | _ => ""

def getKB (j : Json) : Except String KB := do
  let kbj ← field j "kb"
  decKB kbj

def getCtx (j : Json) : Except String EvalCtx := do
  let cj ← field j "ctx"
  decEvalCtx cj

def getDerivation (j : Json) : Except String Derivation := do
  let dj ← field j "derivation"
  decDerivation dj

def getClaimRef (j : Json) : Except String ClaimRef := do
  let rj ← field j "ref"
  decClaimRef rj

def getObserved (j : Json) : Except String (List Dep) := do
  let oj ← field j "observed"
  decList decDep oj

def freshToJson (f : Fresh) : Json :=
  match f with
  | .fresh => .str "fresh"
  | .stale => .str "stale"
  | .unknown => .str "unknown"

def verdictToJson (v : Verdict) : Json :=
  match v with
  | .accepted => .arr #[.str "accepted"]
  | .rejected r => .arr #[.str "rejected", rejectionToJson r]
where rejectionToJson (r : Rejection) : Json :=
  match r with
  | .ruleNotEnabled => .str "ruleNotEnabled"
  | .missingPremise => .str "missingPremise"
  | .missingConclusion => .str "missingConclusion"
  | .conclusionPropMismatch => .str "conclusionPropMismatch"
  | .contestedConclusion => .str "contestedConclusion"
  | .contestedPremise => .str "contestedPremise"
  | .ruleShapeMismatch => .str "ruleShapeMismatch"
  | .evidenceNotOk => .str "evidenceNotOk"
  | .evidenceNotFresh => .str "evidenceNotFresh"
  | .missingCoverage => .str "missingCoverage"
  | .coverageIncomplete => .str "coverageIncomplete"
  | .footprintIncomplete => .str "footprintIncomplete"

def commitOutcomeToJson (o : CommitOutcome) : Json :=
  match o with
  | .committed => .str "committed"
  | .alreadyCommitted => .str "alreadyCommitted"
  | .predecessorConflict => .str "predecessorConflict"
  | .inputConflict => .str "inputConflict"
  | .rejectedInvalid => .str "rejectedInvalid"

def planOutcomeToJson (o : PlanOutcome) : Json :=
  match o with
  | .planned _ => .arr #[.str "planned"]
  | .refused e =>
    .arr #[.str "refused", .str (match e with
      | .illegalTransition => "illegalTransition"
      | .notReady => "notReady"
      | .missingActor => "missingActor"
      | .gatesNotPassed => "gatesNotPassed"
      | .landedRefsUnresolved => "landedRefsUnresolved")]

def handle (j : Json) : Except String Json := do
  let op ← field j "op" >>= fun o => o.getStr?
  match op with
  | "semantic_version" => pure (.str SEMANTIC_VERSION)
  | "assess_fresh" =>
    let tj ← field j "ttl"
    let oj ← field j "observedAt"
    let nj ← field j "now"
    let t ← decTtl tj
    let o ← decInt oj
    let n ← decInt nj
    pure (freshToJson (assessFresh t o n))
  | "check_derivation" =>
    let kb ← getKB j
    let ctx ← getCtx j
    let d ← getDerivation j
    pure (verdictToJson (checkDerivationV kb.view ctx d))
  | "supported" =>
    let kb ← getKB j
    let ctx ← getCtx j
    let r ← getClaimRef j
    pure (Json.bool (Supported kb.view ctx r))
  | "usable" =>
    let kb ← getKB j
    let ctx ← getCtx j
    let r ← getClaimRef j
    pure (Json.bool (UsableFor kb.view ctx r))
  | "reusable" =>
    let kb ← getKB j
    let ctx ← getCtx j
    let d ← getDerivation j
    let observed ← getObserved j
    pure (Json.bool (Reusable kb.view ctx d observed))
  | "plan_transition" =>
    let pj ← field j "proposal"
    let target ← field pj "status" >>= fun x => decProposalStatus x
    let researchPresent ← field pj "researchPresent" >>= fun x => decBool x
    let researchJustifiedSkip ← field pj "researchJustifiedSkip" >>= fun x => decBool x
    let alternativesCount ← field pj "alternativesCount" >>= fun x => decInt x
    let gatesTablePresent ← field pj "gatesTablePresent" >>= fun x => decBool x
    let legacyProfile ← field pj "legacyProfile" >>= fun x => decBool x
    let landGatesPassed ← field pj "landGatesPassed" >>= fun x => decBool x
    let deployUseGatesPassed ← field pj "deployUseGatesPassed" >>= fun x => decBool x
    let actor ← field pj "actor" >>= fun x =>
      decOpt decStr x
    let landedRefs ← field pj "landedRefs" >>= fun x => decList decStr x
    let refsResolvable ← field pj "refsResolvable" >>= fun x => decBool x
    let pid ← field pj "id" >>= fun x => decStr x
    let p : Proposal :=
      { id := ⟨pid⟩, status := .draft, researchPresent, researchJustifiedSkip,
        alternativesCount, gatesTablePresent, legacyProfile, decidedBy := none,
        landedRefs, landGatesPassed, deployUseGatesPassed }
    pure (planOutcomeToJson (planTransition p target actor landedRefs refsResolvable))
  | "conclude_investigation" =>
    let ij ← field j "investigation"
    let checkedAgainst ← field ij "checkedAgainst" >>= fun x => decStr x
    let scopeAndLimits ← field ij "scopeAndLimits" >>= fun x => decStr x
    let hyps ← field ij "hypotheses" >>= fun x =>
      decList (fun h => do
        let text ← field h "text" >>= fun y => decStr y
        let st ← field h "status" >>= fun y => decHypStatus y
        pure ({ text, status := st } : Hypothesis)) x
    let i : Investigation := { id := ⟨"inv"⟩, checkedAgainst, scopeAndLimits, hypotheses := hyps }
    pure (Json.bool (canConclude i))
  | _ => throw ("unknown op: " ++ op)

def handleLine (line : String) : String :=
  let j := Json.parse line.trim
  match j with
  | .error e =>
    toString (Json.mkObj [("id", .str ""), ("ok", Json.bool False), ("error", .str ("parse: " ++ e))])
  | .ok req =>
    match handle req with
    | .error e =>
      toString (Json.mkObj [("id", .str (reqId req)), ("ok", Json.bool False), ("error", .str e)])
    | .ok res =>
      toString (Json.mkObj [("id", .str (reqId req)), ("ok", Json.bool True), ("result", res)])

end Kctx.Reference

def main : IO Unit := do
  let stdin ← IO.getStdin
  let mut line ← stdin.getLine
  while !line.isEmpty do
    if !line.trim.isEmpty then
      IO.println (Kctx.Reference.handleLine line)
    line ← stdin.getLine
