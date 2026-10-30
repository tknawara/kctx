import Lean.Data.Json
import Kctx.Model
import Kctx.Time
import Kctx.WellFormed
import Kctx.Checker
import Kctx.Workflow

set_option autoImplicit false

/-! Versioned JSON interchange (Lean ⇄ Python conformance).

Format: **positional JSON arrays** with explicit arity checks. Chosen
deliberately: every leaf codec round-trips by `rfl`/`simp` in core Lean
(array-literal `match` patterns cannot generate equation lemmas in Lean
4.21, so decoders read positionally via `fieldAt`). Field order is the
contract; the Python codec mirrors these orders exactly and both sides carry
`SEMANTIC_VERSION`.

Layering: component decoders (scope, ref, prop, witness, deps) are pure
parsers with unconditional round-trips; the five record decoders (observation,
claim, binding, derivation, correction) run their `recordWf*` check before
returning, so decoding success *is* admission to a well-formed value (T01). -/

namespace Kctx

open Lean

/-! ## Base helpers. -/

def fieldAt (a : Array Json) (i : Nat) : Except String Json :=
  if h : i < a.size then pure a[i] else throw "missing field"

def encStr (s : String) : Json := .str s
def decStr : Json → Except String String
  | .str s => pure s
  | _ => throw "expected string"

def encBool (b : Bool) : Json := .bool b
def decBool : Json → Except String Bool
  | .bool b => pure b
  | _ => throw "expected bool"

def encInt (i : Int) : Json := .num (JsonNumber.fromInt i)
def decInt : Json → Except String Int := Json.getInt?

theorem decStr_encStr (s : String) : decStr (encStr s) = pure s := by rfl
theorem decBool_encBool (b : Bool) : decBool (encBool b) = pure b := by rfl
theorem decInt_encInt (i : Int) : decInt (encInt i) = pure i := by rfl

def encList {α : Type} (f : α → Json) (xs : List α) : Json :=
  .arr ((xs.map f).toArray)

/-- Positional list decode (own recursion: controllable equations). -/
def decJsonList {α : Type} (g : Json → Except String α) : List Json → Except String (List α)
  | [] => pure []
  | x :: xs => do
    let y ← g x
    let ys ← decJsonList g xs
    pure (y :: ys)

def decList {α : Type} (g : Json → Except String α) : Json → Except String (List α)
  | .arr a => decJsonList g a.toList
  | _ => throw "expected array"

theorem decJsonList_map {α : Type} (f : α → Json) (g : Json → Except String α)
    (xs : List α) (h : ∀ x ∈ xs, g (f x) = pure x) :
    decJsonList g (xs.map f) = pure xs := by
  induction xs with
  | nil => rfl
  | cons x xs ih =>
    simp only [decJsonList, List.map_cons, h x (List.mem_cons_self ..),
      pure_bind, ih (fun y hy => h y (List.mem_cons_of_mem _ hy))]

theorem decList_encList {α : Type} (f : α → Json) (g : Json → Except String α)
    (xs : List α) (h : ∀ x ∈ xs, g (f x) = pure x) :
    decList g (encList f xs) = pure xs := by
  simp only [encList, decList, List.toArray_toList, decJsonList_map f g xs h]

def encOpt {α : Type} (f : α → Json) : Option α → Json
  | none => .arr #[.str "none"]
  | some x => .arr #[.str "some", f x]

def decOpt {α : Type} (g : Json → Except String α) : Json → Except String (Option α)
  | .arr a =>
    if a.size == 1 then do
      let tag ← fieldAt a 0
      match decStr tag with
      | .ok "none" => pure none
      | _ => throw "bad option"
    else if a.size == 2 then do
      let tag ← fieldAt a 0
      match decStr tag with
      | .ok "some" => do
        let x ← fieldAt a 1
        some <$> g x
      | _ => throw "bad option"
    else throw "bad option"
  | _ => throw "bad option"

theorem decOpt_encOpt {α : Type} (f : α → Json) (g : Json → Except String α)
    (h : ∀ x, g (f x) = pure x) (o : Option α) :
    decOpt g (encOpt f o) = pure o := by
  cases o with
  | none => rfl
  | some x =>
    have hr : decOpt g (encOpt f (some x)) = some <$> g (f x) := by rfl
    rw [hr, h x]
    rfl

/-! ## Enums (encode by name; decode via arr + tag). -/

def tagOf : Json → Except String String
  | .str s => pure s
  | _ => throw "expected tag string"

def encTtl : TtlPolicy → Json
  | .expireAfter s => .arr #[.str "expireAfter", encInt s]
  | .noExpiry => .str "noExpiry"
  | .missing => .str "missing"

def decTtl : Json → Except String TtlPolicy
  | .str "noExpiry" => pure .noExpiry
  | .str "missing" => pure .missing
  | .arr a =>
    if a.size == 2 then do
      let tag ← fieldAt a 0
      match tagOf tag with
      | .ok "expireAfter" => do
        let s ← fieldAt a 1
        .expireAfter <$> decInt s
      | _ => throw "bad ttl"
    else throw "bad ttl"
  | _ => throw "bad ttl"

theorem decTtl_encTtl (t : TtlPolicy) : decTtl (encTtl t) = pure t := by
  cases t <;> rfl

def encObsOutcome : ObsOutcome → Json
  | .ok => .str "ok"
  | .timedOut => .str "timedOut"
  | .partialResult => .str "partialResult"
  | .truncated => .str "truncated"
  | .denied => .str "denied"
  | .unavailable => .str "unavailable"

def decObsOutcome : Json → Except String ObsOutcome
  | .str "ok" => pure .ok
  | .str "timedOut" => pure .timedOut
  | .str "partialResult" => pure .partialResult
  | .str "truncated" => pure .truncated
  | .str "denied" => pure .denied
  | .str "unavailable" => pure .unavailable
  | _ => throw "bad obs outcome"

theorem decObsOutcome_encObsOutcome (o : ObsOutcome) :
    decObsOutcome (encObsOutcome o) = pure o := by cases o <;> rfl

def encSupportRole : SupportRole → Json
  | .supports => .str "supports"
  | .contradicts => .str "contradicts"
  | .contextualizes => .str "contextualizes"

def decSupportRole : Json → Except String SupportRole
  | .str "supports" => pure .supports
  | .str "contradicts" => pure .contradicts
  | .str "contextualizes" => pure .contextualizes
  | _ => throw "bad support role"

theorem decSupportRole_encSupportRole (r : SupportRole) :
    decSupportRole (encSupportRole r) = pure r := by cases r <;> rfl

def encRuleId : RuleId → Json
  | .andIntro => .str "andIntro"
  | .specialize => .str "specialize"
  | .obsSupports => .str "obsSupports"
  | .allChecked => .str "allChecked"

def decRuleId : Json → Except String RuleId
  | .str "andIntro" => pure .andIntro
  | .str "specialize" => pure .specialize
  | .str "obsSupports" => pure .obsSupports
  | .str "allChecked" => pure .allChecked
  | _ => throw "bad rule"

theorem decRuleId_encRuleId (r : RuleId) : decRuleId (encRuleId r) = pure r := by
  cases r <;> rfl

def encDepKind : DepKind → Json
  | .sourceContent => .str "sourceContent"
  | .kbRecord => .str "kbRecord"
  | .policy => .str "policy"
  | .checker => .str "checker"
  | .correction => .str "correction"
  | .discovery => .str "discovery"

def decDepKind : Json → Except String DepKind
  | .str "sourceContent" => pure .sourceContent
  | .str "kbRecord" => pure .kbRecord
  | .str "policy" => pure .policy
  | .str "checker" => pure .checker
  | .str "correction" => pure .correction
  | .str "discovery" => pure .discovery
  | _ => throw "bad dep kind"

theorem decDepKind_encDepKind (k : DepKind) : decDepKind (encDepKind k) = pure k := by
  cases k <;> rfl

def encCorrectionKind : CorrectionKind → Json
  | .retract => .str "retract"
  | .dispute => .str "dispute"
  | .supersede => .str "supersede"

def decCorrectionKind : Json → Except String CorrectionKind
  | .str "retract" => pure .retract
  | .str "dispute" => pure .dispute
  | .str "supersede" => pure .supersede
  | _ => throw "bad correction kind"

theorem decCorrectionKind_encCorrectionKind (k : CorrectionKind) :
    decCorrectionKind (encCorrectionKind k) = pure k := by cases k <;> rfl

def encProposalStatus : ProposalStatus → Json
  | .draft => .str "draft"
  | .proposed => .str "proposed"
  | .accepted => .str "accepted"
  | .rejected => .str "rejected"
  | .deferred => .str "deferred"
  | .landing => .str "landing"
  | .applied => .str "applied"
  | .verified => .str "verified"
  | .regressed => .str "regressed"
  | .superseded => .str "superseded"

def decProposalStatus : Json → Except String ProposalStatus
  | .str "draft" => pure .draft
  | .str "proposed" => pure .proposed
  | .str "accepted" => pure .accepted
  | .str "rejected" => pure .rejected
  | .str "deferred" => pure .deferred
  | .str "landing" => pure .landing
  | .str "applied" => pure .applied
  | .str "verified" => pure .verified
  | .str "regressed" => pure .regressed
  | .str "superseded" => pure .superseded
  | _ => throw "bad proposal status"

theorem decProposalStatus_encProposalStatus (s : ProposalStatus) :
    decProposalStatus (encProposalStatus s) = pure s := by cases s <;> rfl

def encHypStatus : HypStatus → Json
  | .openH => .str "openH"
  | .supportedH => .str "supportedH"
  | .refutedH => .str "refutedH"
  | .unknownH => .str "unknownH"
  | .malformedH => .str "malformedH"

def decHypStatus : Json → Except String HypStatus
  | .str "openH" => pure .openH
  | .str "supportedH" => pure .supportedH
  | .str "refutedH" => pure .refutedH
  | .str "unknownH" => pure .unknownH
  | .str "malformedH" => pure .malformedH
  | _ => throw "bad hyp status"

theorem decHypStatus_encHypStatus (s : HypStatus) :
    decHypStatus (encHypStatus s) = pure s := by cases s <;> rfl

/-! ## Components (pure parsers, unconditional round-trips). -/

-- Scope: [project, extra]
def encScope (s : Scope) : Json := .arr #[encStr s.project, encStr s.extra]

def decScope : Json → Except String Scope
  | .arr a =>
    if a.size != 2 then throw "expected scope [project, extra]" else do
    let p ← fieldAt a 0
    let e ← fieldAt a 1
    let project ← decStr p
    let extra ← decStr e
    pure { project, extra }
  | _ => throw "expected scope [project, extra]"

theorem decScope_encScope (s : Scope) : decScope (encScope s) = pure s := by
  rfl

-- ClaimRef: [id, rev]
def encClaimRef (r : ClaimRef) : Json := .arr #[encStr r.id.val, encStr r.rev]

def decClaimRef : Json → Except String ClaimRef
  | .arr a =>
    if a.size != 2 then throw "expected claimRef [id, rev]" else do
    let i ← fieldAt a 0
    let r ← fieldAt a 1
    let id ← decStr i
    let rev ← decStr r
    pure ⟨⟨id⟩, rev⟩
  | _ => throw "expected claimRef [id, rev]"

theorem decClaimRef_encClaimRef (r : ClaimRef) : decClaimRef (encClaimRef r) = pure r := by
  rfl

-- Atom: [subject, predicate, [args]]
def encAtom (a : Atom) : Json :=
  .arr #[encStr a.subject, encStr a.predicate, encList encStr a.args]

def decAtom : Json → Except String Atom
  | .arr a =>
    if a.size != 3 then throw "expected atom [subject, predicate, [args]]" else do
    let s ← fieldAt a 0
    let p ← fieldAt a 1
    let args ← fieldAt a 2
    let subject ← decStr s
    let predicate ← decStr p
    let as ← decList decStr args
    pure { subject, predicate, args := as }
  | _ => throw "expected atom [subject, predicate, [args]]"

theorem decAtom_encAtom (a : Atom) : decAtom (encAtom a) = pure a := by
  have hlist : decList decStr (encList encStr a.args) = pure a.args :=
    decList_encList _ _ _ (fun x _ => decStr_encStr x)
  simp [decAtom, encAtom, hlist, decStr_encStr, fieldAt]

-- ClaimProp: ["atom", atom] | ["conj", [atoms]] | ["allChecked", pred, [members]]
def encProp : ClaimProp → Json
  | .atom a => .arr #[.str "atom", encAtom a]
  | .conj ps => .arr #[.str "conj", encList encAtom ps]
  | .allChecked p ms => .arr #[.str "allChecked", encStr p, encList encStr ms]

def decProp : Json → Except String ClaimProp
  | .arr a =>
    if a.size != 2 then
      if a.size != 3 then throw "bad claimProp" else do
        let tag ← fieldAt a 0
        match tagOf tag with
        | .ok "allChecked" => do
          let p ← fieldAt a 1
          let ms ← fieldAt a 2
          let predicate ← decStr p
          let members ← decList decStr ms
          pure (.allChecked predicate members)
        | _ => throw "bad claimProp"
    else do
      let tag ← fieldAt a 0
      match tagOf tag with
      | .ok "atom" => do
        let x ← fieldAt a 1
        .atom <$> decAtom x
      | .ok "conj" => do
        let x ← fieldAt a 1
        .conj <$> decList decAtom x
      | _ => throw "bad claimProp"
  | _ => throw "bad claimProp"

theorem decProp_encProp (p : ClaimProp) : decProp (encProp p) = pure p := by
  cases p with
  | atom a =>
    have h : decAtom (encAtom a) = pure a := decAtom_encAtom a
    simp [decProp, encProp, h, fieldAt]
    rfl
  | conj ps =>
    have hlist : decList decAtom (encList encAtom ps) = pure ps :=
      decList_encList _ _ _ (fun x _ => decAtom_encAtom x)
    simp [decProp, encProp, hlist, fieldAt]
    rfl
  | allChecked pred ms =>
    have hlist : decList decStr (encList encStr ms) = pure ms :=
      decList_encList _ _ _ (fun x _ => decStr_encStr x)
    simp [decProp, encProp, hlist, decStr_encStr, fieldAt]
    rfl

-- Dep: [kind, target, digest]
def encDep (d : Dep) : Json :=
  .arr #[encDepKind d.kind, encStr d.target, encStr d.digest]

def decDep : Json → Except String Dep
  | .arr a =>
    if a.size != 3 then throw "expected dep [kind, target, digest]" else do
    let k ← fieldAt a 0
    let t ← fieldAt a 1
    let g ← fieldAt a 2
    let kind ← decDepKind k
    let target ← decStr t
    let digest ← decStr g
    pure { kind, target, digest }
  | _ => throw "expected dep [kind, target, digest]"

theorem decDep_encDep (d : Dep) : decDep (encDep d) = pure d := by
  cases d with
  | mk kind _ _ => cases kind <;> rfl

-- CoverageWitness: [scope, [members], complete]
def encWitness (w : CoverageWitness) : Json :=
  .arr #[encScope w.scope, encList encStr w.members, encBool w.complete]

def decWitness : Json → Except String CoverageWitness
  | .arr a =>
    if a.size != 3 then throw "expected witness [scope, [members], complete]" else do
    let s ← fieldAt a 0
    let m ← fieldAt a 1
    let c ← fieldAt a 2
    let scope ← decScope s
    let members ← decList decStr m
    let complete ← decBool c
    pure { scope, members, complete }
  | _ => throw "expected witness [scope, [members], complete]"

theorem decWitness_encWitness (w : CoverageWitness) :
    decWitness (encWitness w) = pure w := by
  have hlist : decList decStr (encList encStr w.members) = pure w.members :=
    decList_encList _ _ _ (fun x _ => decStr_encStr x)
  simp [decWitness, encWitness, hlist, decScope_encScope, decBool_encBool,
    decStr_encStr, fieldAt]

-- EvalCtx: [now, requireFreshEvidence, requireValidated, requireUncontested]
def encEvalCtx (c : EvalCtx) : Json :=
  .arr #[encInt c.now, encBool c.requireFreshEvidence, encBool c.requireValidated,
         encBool c.requireUncontested]

def decEvalCtx : Json → Except String EvalCtx
  | .arr a =>
    if a.size != 4 then throw "expected ctx [now, rf, rv, ru]" else do
    let n ← fieldAt a 0
    let rf ← fieldAt a 1
    let rv ← fieldAt a 2
    let ru ← fieldAt a 3
    let now ← decInt n
    let requireFreshEvidence ← decBool rf
    let requireValidated ← decBool rv
    let requireUncontested ← decBool ru
    pure { now, requireFreshEvidence, requireValidated, requireUncontested }
  | _ => throw "expected ctx [now, rf, rv, ru]"

theorem decEvalCtx_encEvalCtx (c : EvalCtx) : decEvalCtx (encEvalCtx c) = pure c := by
  rfl

/-! ## Records (parse + `recordWf*` admission = T01). -/

-- Observation: [id, outcome, observedAt, ttl, system, locator]
def encObservation (o : Observation) : Json :=
  .arr #[encStr o.id.val, encObsOutcome o.outcome, encInt o.observedAt,
         encTtl o.ttl, encStr o.system, encStr o.locator]

def decObservationRaw : Json → Except String Observation
  | .arr a =>
    if a.size != 6 then throw "expected observation" else do
    let idj ← fieldAt a 0
    let outj ← fieldAt a 1
    let atj ← fieldAt a 2
    let ttlj ← fieldAt a 3
    let sysj ← fieldAt a 4
    let locj ← fieldAt a 5
    let id ← decStr idj
    let outcome ← decObsOutcome outj
    let observedAt ← decInt atj
    let ttl ← decTtl ttlj
    let system ← decStr sysj
    let locator ← decStr locj
    pure ({ id := ⟨id⟩, outcome, observedAt, ttl, system, locator } : Observation)
  | _ => throw "expected observation"

def decObservation (j : Json) : Except String Observation :=
  match decObservationRaw j with
  | .ok x => if recordWfObservation x then pure x else throw "observation not well-formed"
  | .error e => throw e

theorem decObservationRaw_encObservation (o : Observation) (h : recordWfObservation o = true) :
    decObservationRaw (encObservation o) = pure o := by
  have hred : decObservationRaw (encObservation o) = pure o := by
    simp [decObservationRaw, encObservation, fieldAt, pure_bind, reduceIte, decStr_encStr, decInt_encInt, decObsOutcome_encObsOutcome, decTtl_encTtl]
  exact hred

theorem decObservation_encObservation (o : Observation) (h : recordWfObservation o = true) :
    decObservation (encObservation o) = pure o := by
  rw [decObservation, decObservationRaw_encObservation o h]
  show (if recordWfObservation o = true then pure o else throw "observation not well-formed") = pure o
  rw [if_pos h]

-- Claim: [claimRef, prop, scope]
def encClaim (c : Claim) : Json :=
  .arr #[encClaimRef ⟨c.id, c.rev⟩, encProp c.prop, encScope c.scope]

def decClaimRaw : Json → Except String Claim
  | .arr a =>
    if a.size != 3 then throw "expected claim [ref, prop, scope]" else do
    let rj ← fieldAt a 0
    let pj ← fieldAt a 1
    let sj ← fieldAt a 2
    let r ← decClaimRef rj
    let p ← decProp pj
    let s ← decScope sj
    pure ({ id := r.id, rev := r.rev, prop := p, scope := s } : Claim)
  | _ => throw "expected claim [ref, prop, scope]"

def decClaim (j : Json) : Except String Claim :=
  match decClaimRaw j with
  | .ok x => if recordWfClaim x then pure x else throw "claim not well-formed"
  | .error e => throw e

theorem decClaimRaw_encClaim (c : Claim) (h : recordWfClaim c = true) :
    decClaimRaw (encClaim c) = pure c := by
  have hred : decClaimRaw (encClaim c) = pure c := by
    simp [decClaimRaw, encClaim, fieldAt, pure_bind, reduceIte, decClaimRef_encClaimRef, decProp_encProp, decScope_encScope]
  exact hred

theorem decClaim_encClaim (c : Claim) (h : recordWfClaim c = true) :
    decClaim (encClaim c) = pure c := by
  rw [decClaim, decClaimRaw_encClaim c h]
  show (if recordWfClaim c = true then pure c else throw "claim not well-formed") = pure c
  rw [if_pos h]

-- Binding: [obsId, claimRef, role]
def encBinding (b : Binding) : Json :=
  .arr #[encStr b.obs.val, encClaimRef b.ref, encSupportRole b.role]

def decBindingRaw : Json → Except String Binding
  | .arr a =>
    if a.size != 3 then throw "expected binding [obs, ref, role]" else do
    let oj ← fieldAt a 0
    let rj ← fieldAt a 1
    let rolej ← fieldAt a 2
    let obs ← decStr oj
    let r ← decClaimRef rj
    let role ← decSupportRole rolej
    pure ({ obs := ⟨obs⟩, ref := r, role } : Binding)
  | _ => throw "expected binding [obs, ref, role]"

def decBinding (j : Json) : Except String Binding :=
  match decBindingRaw j with
  | .ok x => if recordWfBinding x then pure x else throw "binding not well-formed"
  | .error e => throw e

theorem decBindingRaw_encBinding (b : Binding) (h : recordWfBinding b = true) :
    decBindingRaw (encBinding b) = pure b := by
  have hred : decBindingRaw (encBinding b) = pure b := by
    simp [decBindingRaw, encBinding, fieldAt, pure_bind, reduceIte, decStr_encStr, decClaimRef_encClaimRef, decSupportRole_encSupportRole]
  exact hred

theorem decBinding_encBinding (b : Binding) (h : recordWfBinding b = true) :
    decBinding (encBinding b) = pure b := by
  rw [decBinding, decBindingRaw_encBinding b h]
  show (if recordWfBinding b = true then pure b else throw "binding not well-formed") = pure b
  rw [if_pos h]

-- Correction: [kind, target, recordedAt]
def encCorrection (c : Correction) : Json :=
  .arr #[encCorrectionKind c.kind, encClaimRef c.target, encInt c.recordedAt]

def decCorrectionRaw : Json → Except String Correction
  | .arr a =>
    if a.size != 3 then throw "expected correction [kind, target, recordedAt]" else do
    let kj ← fieldAt a 0
    let tj ← fieldAt a 1
    let aj ← fieldAt a 2
    let kind ← decCorrectionKind kj
    let target ← decClaimRef tj
    let recordedAt ← decInt aj
    pure ({ kind, target, recordedAt } : Correction)
  | _ => throw "expected correction [kind, target, recordedAt]"

def decCorrection (j : Json) : Except String Correction :=
  match decCorrectionRaw j with
  | .ok x => if recordWfCorrection x then pure x else throw "correction not well-formed"
  | .error e => throw e

theorem decCorrectionRaw_encCorrection (c : Correction) (h : recordWfCorrection c = true) :
    decCorrectionRaw (encCorrection c) = pure c := by
  have hred : decCorrectionRaw (encCorrection c) = pure c := by
    simp [decCorrectionRaw, encCorrection, fieldAt, pure_bind, reduceIte, decCorrectionKind_encCorrectionKind, decClaimRef_encClaimRef, decInt_encInt]
  exact hred

theorem decCorrection_encCorrection (c : Correction) (h : recordWfCorrection c = true) :
    decCorrection (encCorrection c) = pure c := by
  rw [decCorrection, decCorrectionRaw_encCorrection c h]
  show (if recordWfCorrection c = true then pure c else throw "correction not well-formed") = pure c
  rw [if_pos h]

-- Derivation:
-- [id, rule, [groups], conclusionRef, conclusionProp, scope, [footprint],
--  evidenceOpt, witnessOpt]
def encDerivation (d : Derivation) : Json :=
  .arr #[encStr d.id, encRuleId d.rule,
         encList (encList encClaimRef) d.premiseGroups,
         encClaimRef d.conclusion, encProp d.conclusionProp, encScope d.scope,
         encList encDep d.footprint, encOpt (fun i => encStr i.val) d.evidence,
         encOpt encWitness d.witness]

def decDerivationRaw : Json → Except String Derivation
  | .arr a =>
    if a.size != 9 then throw "expected derivation" else do
    let idj ← fieldAt a 0
    let rulej ← fieldAt a 1
    let groupsj ← fieldAt a 2
    let conclusionj ← fieldAt a 3
    let propj ← fieldAt a 4
    let scopej ← fieldAt a 5
    let footj ← fieldAt a 6
    let evidencej ← fieldAt a 7
    let witnessj ← fieldAt a 8
    let id ← decStr idj
    let rule ← decRuleId rulej
    let premiseGroups ← decList (decList decClaimRef) groupsj
    let conclusion ← decClaimRef conclusionj
    let conclusionProp ← decProp propj
    let s ← decScope scopej
    let footprint ← decList decDep footj
    let evidence ← decOpt (fun j => (⟨·⟩) <$> decStr j) evidencej
    let witness ← decOpt decWitness witnessj
    pure (Derivation.mk id rule premiseGroups conclusion conclusionProp
      s footprint evidence witness)
  | _ => throw "expected derivation"

def decDerivation (j : Json) : Except String Derivation :=
  match decDerivationRaw j with
  | .ok x => if recordWfDerivation x then pure x else throw "derivation not well-formed"
  | .error e => throw e

theorem decDerivationRaw_encDerivation (d : Derivation) (h : recordWfDerivation d = true) :
    decDerivationRaw (encDerivation d) = pure d := by
  have hred : decDerivationRaw (encDerivation d) = pure d := by
    simp [decDerivationRaw, encDerivation, fieldAt, pure_bind, reduceIte, decStr_encStr, decRuleId_encRuleId, decClaimRef_encClaimRef, decProp_encProp, decScope_encScope, decDep_encDep, decList_encList, decOpt_encOpt, decWitness_encWitness]
  exact hred

theorem decDerivation_encDerivation (d : Derivation) (h : recordWfDerivation d = true) :
    decDerivation (encDerivation d) = pure d := by
  rw [decDerivation, decDerivationRaw_encDerivation d h]
  show (if recordWfDerivation d = true then pure d else throw "derivation not well-formed") = pure d
  rw [if_pos h]

/-! ## KB codec. -/

def encValidation (p : ClaimRef × String) : Json :=
  .arr #[encClaimRef p.1, encStr p.2]

def decValidation : Json → Except String (ClaimRef × String)
  | .arr a =>
    if a.size != 2 then throw "expected validation [ref, digest]" else do
    let rj ← fieldAt a 0
    let dj ← fieldAt a 1
    let r ← decClaimRef rj
    let d ← decStr dj
    pure (r, d)
  | _ => throw "expected validation [ref, digest]"

theorem decValidation_encValidation (p : ClaimRef × String) :
    decValidation (encValidation p) = pure p := by
  rfl

def encKB (kb : KB) : Json :=
  .arr #[encStr kb.head, encList encObservation kb.observations,
         encList encClaim kb.claims, encList encBinding kb.bindings,
         encList encDerivation kb.derivations, encList encCorrection kb.corrections,
         encList encValidation kb.validations]

def decKB : Json → Except String KB
  | .arr a =>
    if a.size != 7 then throw "expected kb" else do
    let hj ← fieldAt a 0
    let oj ← fieldAt a 1
    let cj ← fieldAt a 2
    let bj ← fieldAt a 3
    let dj ← fieldAt a 4
    let kj ← fieldAt a 5
    let vj ← fieldAt a 6
    let head ← decStr hj
    let observations ← decList decObservation oj
    let claims ← decList decClaim cj
    let bindings ← decList decBinding bj
    let derivations ← decList decDerivation dj
    let corrections ← decList decCorrection kj
    let validations ← decList decValidation vj
    pure { head, observations, claims, bindings, derivations, corrections, validations }
  | _ => throw "expected kb"

end Kctx
