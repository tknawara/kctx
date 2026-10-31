import Lean.Data.Json
import Kctx.Workflow

set_option autoImplicit false
set_option maxRecDepth 4096
namespace Kctx
open Lean

def encList {α : Type} (f : α → Json) (xs : List α) : Json := .arr (xs.map f).toArray
def decJsonList {α : Type} (f : Json → Except String α) : List Json → Except String (List α)
  | [] => pure []
  | j :: js => do
      let x ← f j
      let xs ← decJsonList f js
      pure (x :: xs)
def decList {α : Type} (f : Json → Except String α) (j : Json) : Except String (List α) := do
  let xs ← j.getArr?
  decJsonList f xs.toList
def encOpt {α : Type} (f : α → Json) : Option α → Json
  | none => .null
  | some x => f x
def decOpt {α : Type} (f : Json → Except String α) : Json → Except String (Option α)
  | .null => pure none
  | j => some <$> f j
def encNat (n : Nat) : Json := toJson n
def decNat : Json → Except String Nat := Json.getNat?
def encStr : String → Json := Json.str
def decStr : Json → Except String String := Json.getStr?

/-- Encode nominal identifiers without normalizing their original wire spelling. -/
def encIdent {kind : IdKind} (id : Ident kind) : Json := encStr id.val
/-- Parse required identifiers; record-specific validation remains at its boundary. -/
def decIdent {kind : IdKind} (j : Json) : Except String (Ident kind) := do
  let raw ← decStr j
  if h : raw = "" then throw "invalid_request" else return ⟨raw, h⟩

/-- Legacy optional identifier fields use the empty string, never JSON null. -/
def encOptionalIdent {kind : IdKind} : Option (Ident kind) → Json
  | none => encStr ""
  | some id => encIdent id
def decOptionalIdent {kind : IdKind} (j : Json) : Except String (Option (Ident kind)) := do
  let raw ← decStr j
  if h : raw = "" then return none else return some ⟨raw, h⟩
def encBool : Bool → Json := Json.bool
def decBool : Json → Except String Bool := Json.getBool?
def field (j : Json) (name : String) : Except String Json := j.getObjVal? name

def fields (j : Json) (names : List String) : Except String Unit := do
  let obj ← j.getObj?
  let actual := obj.fold (fun keys key _ => key :: keys) []
  if actual.length == names.length && names.all (fun n => actual.contains n) then pure ()
  else throw "invalid_request"

/-- Three distinct policies; existing numeric/null spellings remain unchanged. -/
def encTtlPolicy : TtlPolicy → Json
  | .expireAfter seconds => .num (JsonNumber.fromInt seconds)
  | .noExpiry => Json.mkObj [("tag", .str "noExpiry")]
  | .missing => .null

def decTtlPolicy : Json → Except String TtlPolicy
  | .null => pure .missing
  | j@(.num _) => do
      let seconds ← decNat j
      pure (.expireAfter seconds)
  | j@(.obj _) => do
      fields j ["tag"]
      let tag ← field j "tag" >>= decStr
      if tag == "noExpiry" then pure .noExpiry else throw "invalid_request"
  | _ => throw "invalid_request"


def encPolarity : Polarity → Json
  | .positive => .str "positive"
  | .negative => .str "negative"
def decPolarity (j : Json) : Except String Polarity := do
  match ← decStr j with
  | "positive" => pure .positive
  | "negative" => pure .negative
  | _ => throw "invalid_request"

def encOutcome : Outcome → Json
  | .ok => .str "ok"
  | .timeout => .str "timeout"
  | .partial => .str "partial"
  | .truncated => .str "truncated"
  | .denied => .str "denied"
  | .unavailable => .str "unavailable"
def decOutcome (j : Json) : Except String Outcome := do
  match ← decStr j with
  | "ok" => pure .ok
  | "timeout" => pure .timeout
  | "partial" => pure .partial
  | "truncated" => pure .truncated
  | "denied" => pure .denied
  | "unavailable" => pure .unavailable
  | _ => throw "invalid_request"

def encCorrectionKind : CorrectionKind → Json
  | .retract => .str "retract"
  | .dispute => .str "dispute"
  | .supersede => .str "supersede"
def decCorrectionKind (j : Json) : Except String CorrectionKind := do
  match ← decStr j with
  | "retract" => pure .retract
  | "dispute" => pure .dispute
  | "supersede" => pure .supersede
  | _ => throw "invalid_request"

def encProposalStatus : ProposalStatus → Json
  | .draft => .str "draft"
  | .proposed => .str "proposed"
  | .approved => .str "approved"
  | .applied => .str "applied"
  | .verified => .str "verified"
  | .rejected => .str "rejected"
def decProposalStatus (j : Json) : Except String ProposalStatus := do
  match ← decStr j with
  | "draft" => pure .draft
  | "proposed" => pure .proposed
  | "approved" => pure .approved
  | "applied" => pure .applied
  | "verified" => pure .verified
  | "rejected" => pure .rejected
  | _ => throw "invalid_request"

def encHypothesisStatus : HypothesisStatus → Json
  | .supported => .str "supported"
  | .refuted => .str "refuted"
  | .unk => .str "unk"
  | .open => .str "open"
def decHypothesisStatus (j : Json) : Except String HypothesisStatus := do
  match ← decStr j with
  | "supported" => pure .supported
  | "refuted" => pure .refuted
  | "unk" => pure .unk
  | "open" => pure .open
  | _ => throw "invalid_request"

def encFresh : Fresh → Json
  | .fresh => .str "fresh"
  | .stale => .str "stale"
  | .unknown => .str "unknown"
def decFresh (j : Json) : Except String Fresh := do
  match ← decStr j with
  | "fresh" => pure .fresh
  | "stale" => pure .stale
  | "unknown" => pure .unknown
  | _ => throw "invalid_request"

def encSupport : Support → Json
  | .none => .str "none"
  | .positive => .str "positive"
  | .negative => .str "negative"
  | .both => .str "both"
def decSupport (j : Json) : Except String Support := do
  match ← decStr j with
  | "none" => pure .none
  | "positive" => pure .positive
  | "negative" => pure .negative
  | "both" => pure .both
  | _ => throw "invalid_request"

def encApplyOutcome : ApplyOutcome → Json
  | .applied => .str "applied"
  | .alreadyApplied => .str "already_applied"
  | .inputConflict => .str "input_conflict"
  | .predecessorConflict => .str "predecessor_conflict"
  | .rejected => .str "rejected"
def decApplyOutcome (j : Json) : Except String ApplyOutcome := do
  match ← decStr j with
  | "applied" => pure .applied
  | "already_applied" => pure .alreadyApplied
  | "input_conflict" => pure .inputConflict
  | "predecessor_conflict" => pure .predecessorConflict
  | "rejected" => pure .rejected
  | _ => throw "invalid_request"

def encScope (v : Scope) : Json := Json.mkObj [
  ("project", encIdent v.project),
  ("selector", encStr v.selector)]
def decScope (j : Json) : Except String Scope := do
  fields j ["project", "selector"]
  let project ← field j "project" >>= decIdent
  let selector ← field j "selector" >>= decStr
  let v : Scope := ⟨project, selector⟩
  if scopeWf v then pure v else throw "invalid_request"

def encAtom (v : Atom) : Json := Json.mkObj [
  ("subject", encStr v.subject),
  ("predicate", encStr v.predicate),
  ("args", (encList encStr) v.args)]
def decAtom (j : Json) : Except String Atom := do
  fields j ["subject", "predicate", "args"]
  let subject ← field j "subject" >>= decStr
  let predicate ← field j "predicate" >>= decStr
  let args ← field j "args" >>= (decList decStr)
  let v : Atom := ⟨subject, predicate, args⟩
  if atomWf v then pure v else throw "invalid_request"

def encFormula : Formula → Json
  | .atom a => Json.mkObj [("tag", .str "atom"), ("atom", encAtom a)]
  | .truth => Json.mkObj [("tag", .str "truth")]
  | .and a b => Json.mkObj [("tag", .str "and"), ("left", encFormula a), ("right", encFormula b)]
  | .all e p => Json.mkObj [("tag", .str "all"), ("enumeration", encIdent e), ("predicate", .str p)]
  | .absent e => Json.mkObj [("tag", .str "absent"), ("enumeration", encIdent e)]
  | .inventory e => Json.mkObj [("tag", .str "inventory"), ("enumeration", encIdent e)]
def decFormulaFuel : Nat → Json → Except String Formula
  | 0, _ => throw "invalid_request"
  | n+1, j => do
      match ← field j "tag" >>= decStr with
      | "atom" => fields j ["tag", "atom"]; return .atom (← field j "atom" >>= decAtom)
      | "truth" => fields j ["tag"]; return .truth
      | "and" =>
          fields j ["tag", "left", "right"]
          return .and (← field j "left" >>= decFormulaFuel n) (← field j "right" >>= decFormulaFuel n)
      | "all" =>
          fields j ["tag", "enumeration", "predicate"]
          return .all (← field j "enumeration" >>= decIdent) (← field j "predicate" >>= decStr)
      | "absent" => fields j ["tag", "enumeration"]; return .absent (← field j "enumeration" >>= decIdent)
      | "inventory" => fields j ["tag", "enumeration"]; return .inventory (← field j "enumeration" >>= decIdent)
      | _ => throw "invalid_request"
def decFormula (j : Json) : Except String Formula := do
  let f ← decFormulaFuel 256 j
  if formulaWf f then pure f else throw "invalid_request"

def encStatement (v : Statement) : Json := Json.mkObj [
  ("formula", encFormula v.formula),
  ("scope", encScope v.scope),
  ("polarity", encPolarity v.polarity)]
def decStatement (j : Json) : Except String Statement := do
  fields j ["formula", "scope", "polarity"]
  let formula ← field j "formula" >>= decFormula
  let scope ← field j "scope" >>= decScope
  let polarity ← field j "polarity" >>= decPolarity
  let v : Statement := ⟨formula, scope, polarity⟩
  if statementWf v then pure v else throw "invalid_request"

def encRef (v : Ref) : Json := Json.mkObj [
  ("id", encIdent v.id),
  ("revision", encIdent v.revision)]
def decRef (j : Json) : Except String Ref := do
  fields j ["id", "revision"]
  let id ← field j "id" >>= decIdent
  let revision ← field j "revision" >>= decIdent
  let v : Ref := ⟨id, revision⟩
  if refWf v then pure v else throw "invalid_request"

def encClaim (v : Claim) : Json := Json.mkObj [
  ("id", encIdent v.id),
  ("revision", encIdent v.revision),
  ("statement", encStatement v.statement)]
def decClaim (j : Json) : Except String Claim := do
  fields j ["id", "revision", "statement"]
  let id ← field j "id" >>= decIdent
  let revision ← field j "revision" >>= decIdent
  let statement ← field j "statement" >>= decStatement
  let v : Claim := ⟨id, revision, statement⟩
  if refWf v.ref then pure v else throw "invalid_request"

def encObservation (v : Observation) : Json := Json.mkObj [
  ("id", encIdent v.id),
  ("source", encIdent v.source),
  ("revision", encIdent v.revision),
  ("content", encIdent v.content),
  ("observed_at", encNat v.observedAt),
  ("outcome", encOutcome v.outcome)]
def decObservation (j : Json) : Except String Observation := do
  fields j ["id", "source", "revision", "content", "observed_at", "outcome"]
  let id ← field j "id" >>= decIdent
  let source ← field j "source" >>= decIdent
  let revision ← field j "revision" >>= decIdent
  let content ← field j "content" >>= decIdent
  let observedAt ← field j "observed_at" >>= decNat
  let outcome ← field j "outcome" >>= decOutcome
  let v : Observation := ⟨id, source, revision, content, observedAt, outcome⟩
  if observationWf v then pure v else throw "invalid_request"

def encAttestation (v : Attestation) : Json := Json.mkObj [
  ("id", encIdent v.id),
  ("claim", encRef v.claim),
  ("observation", encIdent v.observation),
  ("statement", encStatement v.statement),
  ("authority", encIdent v.authority)]
def decAttestation (j : Json) : Except String Attestation := do
  fields j ["id", "claim", "observation", "statement", "authority"]
  let id ← field j "id" >>= decIdent
  let claim ← field j "claim" >>= decRef
  let observation ← field j "observation" >>= decIdent
  let statement ← field j "statement" >>= decStatement
  let authority ← field j "authority" >>= decIdent
  let v : Attestation := ⟨id, claim, observation, statement, authority⟩
  pure v

def encEnumeration (v : Enumeration) : Json := Json.mkObj [
  ("id", encIdent v.id),
  ("source", encIdent v.source),
  ("revision", encIdent v.revision),
  ("query", encStr v.query),
  ("scope", encScope v.scope),
  ("observation", encIdent v.observation),
  ("members", (encList encStr) v.members),
  ("universe", (encList encStr) v.universe),
  ("method", encStr v.method)]
def decEnumeration (j : Json) : Except String Enumeration := do
  fields j ["id", "source", "revision", "query", "scope", "observation", "members", "universe", "method"]
  let id ← field j "id" >>= decIdent
  let source ← field j "source" >>= decIdent
  let revision ← field j "revision" >>= decIdent
  let query ← field j "query" >>= decStr
  let scope ← field j "scope" >>= decScope
  let observation ← field j "observation" >>= decIdent
  let members ← field j "members" >>= (decList decStr)
  let inventory ← field j "universe" >>= (decList decStr)
  let method ← field j "method" >>= decStr
  let v : Enumeration := ⟨id, source, revision, query, scope, observation, members, inventory, method⟩
  pure v

def encWitness : Witness → Json
  | .attest a => Json.mkObj [("tag", .str "attest"), ("attestation", encIdent a)]
  | .truth s => Json.mkObj [("tag", .str "truth"), ("scope", encScope s)]
  | .and a b => Json.mkObj [("tag", .str "and"), ("left", encWitness a), ("right", encWitness b)]
  | .specialize s w => Json.mkObj [("tag", .str "specialize"), ("scope", encScope s), ("premise", encWitness w)]
  | .all e p w => Json.mkObj [("tag", .str "all"), ("enumeration", encIdent e), ("predicate", .str p), ("premise", encWitness w)]
  | .absent e w => Json.mkObj [("tag", .str "absent"), ("enumeration", encIdent e), ("premise", encWitness w)]
def decWitnessFuel : Nat → Json → Except String Witness
  | 0, _ => throw "invalid_request"
  | n+1, j => do
      match ← field j "tag" >>= decStr with
      | "attest" => fields j ["tag", "attestation"]; return .attest (← field j "attestation" >>= decIdent)
      | "truth" => fields j ["tag", "scope"]; return .truth (← field j "scope" >>= decScope)
      | "and" =>
          fields j ["tag", "left", "right"]
          return .and (← field j "left" >>= decWitnessFuel n) (← field j "right" >>= decWitnessFuel n)
      | "specialize" =>
          fields j ["tag", "scope", "premise"]
          return .specialize (← field j "scope" >>= decScope) (← field j "premise" >>= decWitnessFuel n)
      | "all" =>
          fields j ["tag", "enumeration", "predicate", "premise"]
          return .all (← field j "enumeration" >>= decIdent) (← field j "predicate" >>= decStr) (← field j "premise" >>= decWitnessFuel n)
      | "absent" =>
          fields j ["tag", "enumeration", "premise"]
          return .absent (← field j "enumeration" >>= decIdent) (← field j "premise" >>= decWitnessFuel n)
      | _ => throw "invalid_request"
def decWitness (j : Json) : Except String Witness := do
  let w ← decWitnessFuel 256 j
  if witnessWf w then pure w else throw "invalid_request"

def encDerivation (v : Derivation) : Json := Json.mkObj [
  ("id", encIdent v.id),
  ("claim", encRef v.claim),
  ("witness", encWitness v.witness)]
def decDerivation (j : Json) : Except String Derivation := do
  fields j ["id", "claim", "witness"]
  let id ← field j "id" >>= decIdent
  let claim ← field j "claim" >>= decRef
  let witness ← field j "witness" >>= decWitness
  let v : Derivation := ⟨id, claim, witness⟩
  pure v

def encCorrection (v : Correction) : Json := Json.mkObj [
  ("id", encIdent v.id),
  ("kind", encCorrectionKind v.kind),
  ("target", encRef v.target),
  ("replacement", (encOpt encRef) v.replacement),
  ("recorded_at", encNat v.recordedAt)]
def decCorrection (j : Json) : Except String Correction := do
  fields j ["id", "kind", "target", "replacement", "recorded_at"]
  let id ← field j "id" >>= decIdent
  let kind ← field j "kind" >>= decCorrectionKind
  let target ← field j "target" >>= decRef
  let replacement ← field j "replacement" >>= (decOpt decRef)
  let recordedAt ← field j "recorded_at" >>= decNat
  let v : Correction := ⟨id, kind, target, replacement, recordedAt⟩
  pure v

def encPolicy (v : Policy) : Json := Json.mkObj [
  ("id", encIdent v.id),
  ("require_fresh", encBool v.requireFresh),
  ("require_validation", encBool v.requireValidation),
  ("require_uncontested", encBool v.requireUncontested),
  ("ttl", encTtlPolicy v.ttl),
  ("authorized_actors", encList encIdent v.authorizedActors)]
def decPolicy (j : Json) : Except String Policy := do
  fields j ["id", "require_fresh", "require_validation", "require_uncontested", "ttl", "authorized_actors"]
  let id ← field j "id" >>= decIdent
  let requireFresh ← field j "require_fresh" >>= decBool
  let requireValidation ← field j "require_validation" >>= decBool
  let requireUncontested ← field j "require_uncontested" >>= decBool
  let ttl ← field j "ttl" >>= decTtlPolicy
  let authorizedActors ← field j "authorized_actors" >>= decList decIdent
  let v : Policy := ⟨id, requireFresh, requireValidation, requireUncontested, ttl, authorizedActors⟩
  pure v

def encSourceSelection (v : SourceSelection) : Json := Json.mkObj [
  ("source", encIdent v.source), ("revision", encIdent v.revision), ("content", encIdent v.content)]
def decSourceSelection (j : Json) : Except String SourceSelection := do
  fields j ["source", "revision", "content"]
  return ⟨← field j "source" >>= decIdent, ← field j "revision" >>= decIdent, ← field j "content" >>= decIdent⟩

def encContext (v : Context) : Json := Json.mkObj [
  ("snapshot", encIdent v.snapshot),
  ("semantic_version", encStr v.semanticVersion),
  ("ruleset", encIdent v.ruleset),
  ("checker", encIdent v.checker),
  ("policy", encPolicy v.policy),
  ("now", encNat v.now),
  ("target", encScope v.target),
  ("intended_use", encStr v.intendedUse), ("sources", encList encSourceSelection v.sources)]
def decContext (j : Json) : Except String Context := do
  fields j ["snapshot", "semantic_version", "ruleset", "checker", "policy", "now", "target", "intended_use", "sources"]
  let snapshot ← field j "snapshot" >>= decIdent
  let semanticVersion ← field j "semantic_version" >>= decStr
  let ruleset ← field j "ruleset" >>= decIdent
  let checker ← field j "checker" >>= decIdent
  let policy ← field j "policy" >>= decPolicy
  let now ← field j "now" >>= decNat
  let target ← field j "target" >>= decScope
  let intendedUse ← field j "intended_use" >>= decStr
  let sources ← field j "sources" >>= decList decSourceSelection
  let v : Context := ⟨snapshot, semanticVersion, ruleset, checker, policy, now, target, intendedUse, sources⟩
  if contextWf v then pure v else throw "invalid_request"

def encDependency : Dependency → Json
  | .observation v => Json.mkObj [("tag", .str "observation"), ("value", encObservation v)]
  | .claim v => Json.mkObj [("tag", .str "claim"), ("value", encClaim v)]
  | .attestation v => Json.mkObj [("tag", .str "attestation"), ("value", encAttestation v)]
  | .enumeration v => Json.mkObj [("tag", .str "enumeration"), ("value", encEnumeration v)]
  | .context v => Json.mkObj [("tag", .str "context"), ("value", encContext v)]
  | .corrections r es => Json.mkObj [("tag", .str "corrections"), ("target", encRef r), ("events", encList encCorrection es)]
def decDependency (j : Json) : Except String Dependency := do
  match ← field j "tag" >>= decStr with
  | "observation" => fields j ["tag", "value"]; return .observation (← field j "value" >>= decObservation)
  | "claim" => fields j ["tag", "value"]; return .claim (← field j "value" >>= decClaim)
  | "attestation" => fields j ["tag", "value"]; return .attestation (← field j "value" >>= decAttestation)
  | "enumeration" => fields j ["tag", "value"]; return .enumeration (← field j "value" >>= decEnumeration)
  | "context" =>
      fields j ["tag", "value"]
      let context ← field j "value" >>= decContext
      if context.now == 0 then return .context context else throw "invalid_request"
  | "corrections" => fields j ["tag", "target", "events"]; return .corrections (← field j "target" >>= decRef) (← field j "events" >>= decList decCorrection)
  | _ => throw "invalid_request"

def encResult (b : Bool) : Json := .str (if b then "pass" else "fail")
def decResult (j : Json) : Except String Bool := do
  match ← decStr j with
  | "pass" => pure true
  | "fail" => pure false
  | _ => throw "invalid_request"
def encReceipt (v : Receipt) : Json := Json.mkObj [
  ("id", encIdent v.id),
  ("claim", encRef v.claim),
  ("context", encContext v.context),
  ("witness", encWitness v.witness),
  ("dependencies", (encList encDependency) v.dependencies),
  ("result", encResult v.passed),
  ("expires_at", encNat v.expiresAt)]
def decReceipt (j : Json) : Except String Receipt := do
  fields j ["id", "claim", "context", "witness", "dependencies", "result", "expires_at"]
  let id ← field j "id" >>= decIdent
  let claim ← field j "claim" >>= decRef
  let context ← field j "context" >>= decContext
  let witness ← field j "witness" >>= decWitness
  let dependencies ← field j "dependencies" >>= (decList decDependency)
  let passed ← field j "result" >>= decResult
  let expiresAt ← field j "expires_at" >>= decNat
  let v : Receipt := ⟨id, claim, context, witness, dependencies, passed, expiresAt⟩
  pure v

def encKB (v : KB) : Json := Json.mkObj [
  ("snapshot", encIdent v.snapshot),
  ("observations", (encList encObservation) v.observations),
  ("claims", (encList encClaim) v.claims),
  ("attestations", (encList encAttestation) v.attestations),
  ("enumerations", (encList encEnumeration) v.enumerations),
  ("derivations", (encList encDerivation) v.derivations),
  ("corrections", (encList encCorrection) v.corrections),
  ("receipts", (encList encReceipt) v.receipts)]
/-- Structural parsing only; decKB is the globally guarded public admission boundary. -/
def parseKB (j : Json) : Except String KB := do
  fields j ["snapshot", "observations", "claims", "attestations", "enumerations", "derivations", "corrections", "receipts"]
  let snapshot ← field j "snapshot" >>= decIdent
  let observations ← field j "observations" >>= (decList decObservation)
  let claims ← field j "claims" >>= (decList decClaim)
  let attestations ← field j "attestations" >>= (decList decAttestation)
  let enumerations ← field j "enumerations" >>= (decList decEnumeration)
  let derivations ← field j "derivations" >>= (decList decDerivation)
  let corrections ← field j "corrections" >>= (decList decCorrection)
  let receipts ← field j "receipts" >>= (decList decReceipt)
  let v : KB := ⟨snapshot, observations, claims, attestations, enumerations, derivations, corrections, receipts⟩
  pure v

def decKB (j : Json) : Except String KB := do
  let k ← parseKB j
  if k.wellFormed then pure k else throw "invalid_request"

theorem decKB_wellFormed {j : Json} {k : KB} (h : decKB j = .ok k) : k.wellFormed = true := by
  cases hp : parseKB j with
  | error error => simp [decKB, hp, bind, Except.bind] at h
  | ok value =>
      simp only [decKB, hp, bind, Except.bind] at h
      split at h
      · cases h; assumption
      · contradiction

def encAuthority (v : Authority) : Json := Json.mkObj [
  ("actor", encIdent v.actor),
  ("target", encRef v.target),
  ("intended_use", encStr v.intendedUse),
  ("policy", encIdent v.policy),
  ("statement", encStatement v.statement),
  ("approved", encKB v.approved),
  ("approvals", (encList encClaim) v.approvals), ("context", encContext v.context)]
def decAuthority (j : Json) : Except String Authority := do
  fields j ["actor", "target", "intended_use", "policy", "statement", "approved", "approvals", "context"]
  let actor ← field j "actor" >>= decIdent
  let target ← field j "target" >>= decRef
  let intendedUse ← field j "intended_use" >>= decStr
  let policy ← field j "policy" >>= decIdent
  let statement ← field j "statement" >>= decStatement
  let approved ← field j "approved" >>= decKB
  let approvals ← field j "approvals" >>= (decList decClaim)
  let context ← field j "context" >>= decContext
  let v : Authority := ⟨actor, target, intendedUse, policy, statement, approved, approvals, context⟩
  pure v

def encPlan (v : Plan) : Json := Json.mkObj [
  ("id", encIdent v.id),
  ("expected_snapshot", encIdent v.expectedSnapshot),
  ("candidate", encKB v.candidate),
  ("authority", encAuthority v.authority),
  ("claim", encRef v.claim),
  ("witness", encWitness v.witness)]
def decPlan (j : Json) : Except String Plan := do
  fields j ["id", "expected_snapshot", "candidate", "authority", "claim", "witness"]
  let id ← field j "id" >>= decIdent
  let expectedSnapshot ← field j "expected_snapshot" >>= decIdent
  let candidate ← field j "candidate" >>= decKB
  let authority ← field j "authority" >>= decAuthority
  let claim ← field j "claim" >>= decRef
  let witness ← field j "witness" >>= decWitness
  let v : Plan := ⟨id, expectedSnapshot, candidate, authority, claim, witness⟩
  pure v

def encJournalEntry (v : JournalEntry) : Json := Json.mkObj [
  ("plan", encPlan v.plan)]
def decJournalEntry (j : Json) : Except String JournalEntry := do
  fields j ["plan"]
  let plan ← field j "plan" >>= decPlan
  let v : JournalEntry := ⟨plan⟩
  pure v

def encVerifiedApproval (a : VerifiedApproval) : Json := Json.mkObj [("plan", encPlan a.plan)]
def decVerifiedApproval (j : Json) : Except String VerifiedApproval := do
  fields j ["plan"]
  return ⟨← field j "plan" >>= decPlan⟩

def encProposal (v : Proposal) : Json := Json.mkObj [
  ("id", encIdent v.id),
  ("revision", encIdent v.revision),
  ("target", encRef v.target),
  ("status", encProposalStatus v.status),
  ("actor", encOptionalIdent v.actor),
  ("executor", encOptionalIdent v.executor),
  ("acceptor", encOptionalIdent v.acceptor),
  ("gates", (encList encIdent) v.gates)]
def decProposal (j : Json) : Except String Proposal := do
  fields j ["id", "revision", "target", "status", "actor", "executor", "acceptor", "gates"]
  let id ← field j "id" >>= decIdent
  let revision ← field j "revision" >>= decIdent
  let target ← field j "target" >>= decRef
  let status ← field j "status" >>= decProposalStatus
  let actor ← field j "actor" >>= decOptionalIdent
  let executor ← field j "executor" >>= decOptionalIdent
  let acceptor ← field j "acceptor" >>= decOptionalIdent
  let gates ← field j "gates" >>= (decList decIdent)
  let v : Proposal := ⟨id, revision, target, status, actor, executor, acceptor, gates⟩
  pure v

def encHypothesis (v : Hypothesis) : Json := Json.mkObj [
  ("text", encStr v.text),
  ("status", encHypothesisStatus v.status)]
def decHypothesis (j : Json) : Except String Hypothesis := do
  fields j ["text", "status"]
  let text ← field j "text" >>= decStr
  let status ← field j "status" >>= decHypothesisStatus
  let v : Hypothesis := ⟨text, status⟩
  pure v

def encInvestigation (v : Investigation) : Json := Json.mkObj [
  ("checked_against", encStr v.checkedAgainst),
  ("scope_and_limits", encStr v.scopeAndLimits),
  ("hypotheses", (encList encHypothesis) v.hypotheses)]
def decInvestigation (j : Json) : Except String Investigation := do
  fields j ["checked_against", "scope_and_limits", "hypotheses"]
  let checkedAgainst ← field j "checked_against" >>= decStr
  let scopeAndLimits ← field j "scope_and_limits" >>= decStr
  let hypotheses ← field j "hypotheses" >>= (decList decHypothesis)
  let v : Investigation := ⟨checkedAgainst, scopeAndLimits, hypotheses⟩
  pure v

def encChecked (v : Checked) : Json := Json.mkObj [
  ("statement", encStatement v.statement),
  ("dependencies", (encList encDependency) v.dependencies)]
def decChecked (j : Json) : Except String Checked := do
  fields j ["statement", "dependencies"]
  let statement ← field j "statement" >>= decStatement
  let dependencies ← field j "dependencies" >>= (decList decDependency)
  let v : Checked := ⟨statement, dependencies⟩
  pure v

def encAssessment (v : Assessment) : Json := Json.mkObj [
  ("support", encSupport v.support),
  ("applicable", encBool v.applicable),
  ("freshness", encFresh v.freshness),
  ("validated", encBool v.validated),
  ("contested", encBool v.contested),
  ("available", encBool v.available),
  ("usable", encBool v.usable)]
def decAssessment (j : Json) : Except String Assessment := do
  fields j ["support", "applicable", "freshness", "validated", "contested", "available", "usable"]
  let support ← field j "support" >>= decSupport
  let applicable ← field j "applicable" >>= decBool
  let freshness ← field j "freshness" >>= decFresh
  let validated ← field j "validated" >>= decBool
  let contested ← field j "contested" >>= decBool
  let available ← field j "available" >>= decBool
  let usable ← field j "usable" >>= decBool
  let v : Assessment := ⟨support, applicable, freshness, validated, contested, available, usable⟩
  pure v

def encApplyResult (v : ApplyResult) : Json := Json.mkObj [
  ("kb", encKB v.kb),
  ("journal", (encList encJournalEntry) v.journal),
  ("outcome", encApplyOutcome v.outcome)]
def decApplyResult (j : Json) : Except String ApplyResult := do
  fields j ["kb", "journal", "outcome"]
  let kb ← field j "kb" >>= decKB
  let journal ← field j "journal" >>= (decList decJournalEntry)
  let outcome ← field j "outcome" >>= decApplyOutcome
  let v : ApplyResult := ⟨kb, journal, outcome⟩
  pure v

def encSequenceResult (v : SequenceResult) : Json := Json.mkObj [
  ("kb", encKB v.kb),
  ("journal", (encList encJournalEntry) v.journal),
  ("outcomes", (encList encApplyOutcome) v.outcomes)]
def decSequenceResult (j : Json) : Except String SequenceResult := do
  fields j ["kb", "journal", "outcomes"]
  let kb ← field j "kb" >>= decKB
  let journal ← field j "journal" >>= (decList decJournalEntry)
  let outcomes ← field j "outcomes" >>= (decList decApplyOutcome)
  let v : SequenceResult := ⟨kb, journal, outcomes⟩
  pure v

def encRetrieval (r : Retrieval) : Json := Json.mkObj [
  ("snapshot", encIdent r.snapshot),
  ("records", encList (fun pair => Json.mkObj [("claim", encClaim pair.1), ("assessment", encAssessment pair.2)]) r.records),
  ("omitted", encNat r.omitted), ("complete", encBool r.complete), ("next_offset", encOpt encNat r.nextOffset)]

end Kctx
