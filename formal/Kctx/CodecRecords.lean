import Kctx.CodecProofs

set_option autoImplicit false
set_option maxHeartbeats 4800000
set_option maxRecDepth 16384
namespace Kctx
open Lean

theorem decStr_encStr (s : String) : decStr (encStr s) = .ok s := rfl
theorem decNat_encNat (n : Nat) : decNat (encNat n) = .ok n := by rfl
theorem decBool_encBool (b : Bool) : decBool (encBool b) = .ok b := rfl
theorem decResult_encResult (b : Bool) : decResult (encResult b) = .ok b := by cases b <;> rfl

theorem decOpt_encOpt {α : Type} (enc : α → Json) (dec : Json → Except String α)
    (v : Option α) (h : ∀ x, v = some x → dec (enc x) = .ok x)
    (nonnull : ∀ x, enc x ≠ Json.null) : decOpt dec (encOpt enc v) = .ok v := by
  cases v with
  | none => rfl
  | some x =>
      have hx := h x rfl
      simp only [encOpt, decOpt]
      split
      · next he => exact False.elim (nonnull x he)
      · simpa [hx, Functor.map, Except.map] using hx

def WireScope (s : Scope) : Prop := scopeWf s = true
def WireFormula (f : Formula) : Prop := formulaWf f = true ∧ formulaDepth f ≤ 256
def WireWitness (w : Witness) : Prop := witnessWf w = true ∧ witnessDepth w ≤ 256

theorem roundtripScope (s : Scope) (h : WireScope s) : decScope (encScope s) = .ok s := decScope_encScope s h
theorem roundtripFormula (f : Formula) (h : WireFormula f) : decFormula (encFormula f) = .ok f := T02_formula_roundtrip f h.1 h.2
theorem roundtripWitness (w : Witness) (h : WireWitness w) : decWitness (encWitness w) = .ok w := T02_witness_roundtrip w h.1 h.2

theorem roundtripPolarity (v : Polarity) : decPolarity (encPolarity v) = .ok v := by cases v <;> rfl
theorem roundtripOutcome (v : Outcome) : decOutcome (encOutcome v) = .ok v := by cases v <;> rfl
theorem roundtripCorrectionKind (v : CorrectionKind) : decCorrectionKind (encCorrectionKind v) = .ok v := by cases v <;> rfl
theorem roundtripProposalStatus (v : ProposalStatus) : decProposalStatus (encProposalStatus v) = .ok v := by cases v <;> rfl
theorem roundtripHypothesisStatus (v : HypothesisStatus) : decHypothesisStatus (encHypothesisStatus v) = .ok v := by cases v <;> rfl
theorem roundtripFresh (v : Fresh) : decFresh (encFresh v) = .ok v := by cases v <;> rfl
theorem roundtripSupport (v : Support) : decSupport (encSupport v) = .ok v := by cases v <;> rfl
theorem roundtripApplyOutcome (v : ApplyOutcome) : decApplyOutcome (encApplyOutcome v) = .ok v := by cases v <;> rfl

def WireStatement (v : Statement) : Prop := statementWf v = true ∧ (WireFormula v.formula) ∧ (WireScope v.scope)
theorem roundtripStatement (v : Statement) (h : WireStatement v) : decStatement (encStatement v) = .ok v := by
  rcases h with ⟨hg, h0, h1⟩
  have f0 := roundtripFormula v.formula h0
  have f1 := roundtripScope v.scope h1
  have f2 := roundtripPolarity v.polarity
  change (do
    let formula ← decFormula (encFormula v.formula)
    let scope ← decScope (encScope v.scope)
    let polarity ← decPolarity (encPolarity v.polarity)
    let value : Statement := ⟨formula, scope, polarity⟩
    if statementWf value then pure value else throw "invalid_request") = .ok v
  rw [f0, f1, f2]
  simpa only [bind, Except.bind, pure] using (show (if statementWf v then Except.ok v else .error "invalid_request") = .ok v from by simp [hg])

def WireRef (v : Ref) : Prop := refWf v = true
theorem roundtripRef (v : Ref) (h : WireRef v) : decRef (encRef v) = .ok v := by
  have hg : refWf v = true := h
  have f0 := decIdent_encIdent v.id
  have f1 := decIdent_encIdent v.revision
  change (do
    let id ← decIdent (encIdent v.id)
    let revision ← decIdent (encIdent v.revision)
    let value : Ref := ⟨id, revision⟩
    if refWf value then pure value else throw "invalid_request") = .ok v
  rw [f0, f1]
  simpa only [bind, Except.bind, pure] using (show (if refWf v then Except.ok v else .error "invalid_request") = .ok v from by simp [hg])

def WireClaim (v : Claim) : Prop := refWf v.ref = true ∧ (WireStatement v.statement)
theorem roundtripClaim (v : Claim) (h : WireClaim v) : decClaim (encClaim v) = .ok v := by
  rcases h with ⟨hg, h2⟩
  have f0 := decIdent_encIdent v.id
  have f1 := decIdent_encIdent v.revision
  have f2 := roundtripStatement v.statement h2
  change (do
    let id ← decIdent (encIdent v.id)
    let revision ← decIdent (encIdent v.revision)
    let statement ← decStatement (encStatement v.statement)
    let value : Claim := ⟨id, revision, statement⟩
    if refWf value.ref then pure value else throw "invalid_request") = .ok v
  rw [f0, f1, f2]
  simpa only [bind, Except.bind, pure] using (show (if refWf v.ref then Except.ok v else .error "invalid_request") = .ok v from by simp [hg])

def WireObservation (v : Observation) : Prop := observationWf v = true
theorem roundtripObservation (v : Observation) (h : WireObservation v) : decObservation (encObservation v) = .ok v := by
  have hg : observationWf v = true := h
  have f0 := decIdent_encIdent v.id
  have f1 := decIdent_encIdent v.source
  have f2 := decIdent_encIdent v.revision
  have f3 := decIdent_encIdent v.content
  have f4 := decNat_encNat v.observedAt
  have f5 := roundtripOutcome v.outcome
  change (do
    let id ← decIdent (encIdent v.id)
    let source ← decIdent (encIdent v.source)
    let revision ← decIdent (encIdent v.revision)
    let content ← decIdent (encIdent v.content)
    let observedAt ← decNat (encNat v.observedAt)
    let outcome ← decOutcome (encOutcome v.outcome)
    let value : Observation := ⟨id, source, revision, content, observedAt, outcome⟩
    if observationWf value then pure value else throw "invalid_request") = .ok v
  rw [f0, f1, f2, f3, f4, f5]
  simpa only [bind, Except.bind, pure] using (show (if observationWf v then Except.ok v else .error "invalid_request") = .ok v from by simp [hg])

def WireAttestation (v : Attestation) : Prop := true = true ∧ (WireRef v.claim) ∧ (WireStatement v.statement)
theorem roundtripAttestation (v : Attestation) (h : WireAttestation v) : decAttestation (encAttestation v) = .ok v := by
  rcases h with ⟨hg, h1, h3⟩
  have f0 := decIdent_encIdent v.id
  have f1 := roundtripRef v.claim h1
  have f2 := decIdent_encIdent v.observation
  have f3 := roundtripStatement v.statement h3
  have f4 := decIdent_encIdent v.authority
  change (do
    let id ← decIdent (encIdent v.id)
    let claim ← decRef (encRef v.claim)
    let observation ← decIdent (encIdent v.observation)
    let statement ← decStatement (encStatement v.statement)
    let authority ← decIdent (encIdent v.authority)
    let value : Attestation := ⟨id, claim, observation, statement, authority⟩
    pure value) = .ok v
  rw [f0, f1, f2, f3, f4]
  rfl

def WireEnumeration (v : Enumeration) : Prop := true = true ∧ (WireScope v.scope)
theorem roundtripEnumeration (v : Enumeration) (h : WireEnumeration v) : decEnumeration (encEnumeration v) = .ok v := by
  rcases h with ⟨hg, h4⟩
  have f0 := decIdent_encIdent v.id
  have f1 := decIdent_encIdent v.source
  have f2 := decIdent_encIdent v.revision
  have f3 := decStr_encStr v.query
  have f4 := roundtripScope v.scope h4
  have f5 := decIdent_encIdent v.observation
  have f6 := decList_encList encStr decStr v.members (fun x hx => decStr_encStr x)
  have f7 := decList_encList encStr decStr v.«universe» (fun x hx => decStr_encStr x)
  have f8 := decStr_encStr v.method
  change (do
    let id ← decIdent (encIdent v.id)
    let source ← decIdent (encIdent v.source)
    let revision ← decIdent (encIdent v.revision)
    let query ← decStr (encStr v.query)
    let scope ← decScope (encScope v.scope)
    let observation ← decIdent (encIdent v.observation)
    let members ← (decList decStr) ((encList encStr) v.members)
    let «universe» ← (decList decStr) ((encList encStr) v.«universe»)
    let method ← decStr (encStr v.method)
    let value : Enumeration := ⟨id, source, revision, query, scope, observation, members, «universe», method⟩
    pure value) = .ok v
  rw [f0, f1, f2, f3, f4, f5, f6, f7, f8]
  rfl

def WireDerivation (v : Derivation) : Prop := true = true ∧ (WireRef v.claim) ∧ (WireWitness v.witness)
theorem roundtripDerivation (v : Derivation) (h : WireDerivation v) : decDerivation (encDerivation v) = .ok v := by
  rcases h with ⟨hg, h1, h2⟩
  have f0 := decIdent_encIdent v.id
  have f1 := roundtripRef v.claim h1
  have f2 := roundtripWitness v.witness h2
  change (do
    let id ← decIdent (encIdent v.id)
    let claim ← decRef (encRef v.claim)
    let witness ← decWitness (encWitness v.witness)
    let value : Derivation := ⟨id, claim, witness⟩
    pure value) = .ok v
  rw [f0, f1, f2]
  rfl

def WireCorrection (v : Correction) : Prop := true = true ∧ (WireRef v.target) ∧ (∀ x, v.replacement = some x → WireRef x)
theorem roundtripCorrection (v : Correction) (h : WireCorrection v) : decCorrection (encCorrection v) = .ok v := by
  rcases h with ⟨hg, h2, h3⟩
  have f0 := decIdent_encIdent v.id
  have f1 := roundtripCorrectionKind v.kind
  have f2 := roundtripRef v.target h2
  have f3 := decOpt_encOpt encRef decRef v.replacement (fun x hx => roundtripRef x (h3 x hx)) (fun _ => by intro h; cases h)
  have f4 := decNat_encNat v.recordedAt
  change (do
    let id ← decIdent (encIdent v.id)
    let kind ← decCorrectionKind (encCorrectionKind v.kind)
    let target ← decRef (encRef v.target)
    let replacement ← (decOpt decRef) ((encOpt encRef) v.replacement)
    let recordedAt ← decNat (encNat v.recordedAt)
    let value : Correction := ⟨id, kind, target, replacement, recordedAt⟩
    pure value) = .ok v
  rw [f0, f1, f2, f3, f4]
  rfl

def WireTtlPolicy (ttl : TtlPolicy) : Prop := ttlWf ttl = true

theorem roundtripTtlPolicy (ttl : TtlPolicy) (h : WireTtlPolicy ttl) :
    decTtlPolicy (encTtlPolicy ttl) = .ok ttl := by
  cases ttl with
  | missing => rfl
  | noExpiry => rfl
  | expireAfter seconds =>
      cases seconds with
      | ofNat seconds => rfl
      | negSucc seconds => simp [WireTtlPolicy, ttlWf] at h

def WirePolicy (v : Policy) : Prop := WireTtlPolicy v.ttl
theorem roundtripPolicy (v : Policy) (h : WirePolicy v) : decPolicy (encPolicy v) = .ok v := by
  have hg := h
  have f0 := decIdent_encIdent v.id
  have f1 := decBool_encBool v.requireFresh
  have f2 := decBool_encBool v.requireValidation
  have f3 := decBool_encBool v.requireUncontested
  have f4 := roundtripTtlPolicy v.ttl h
  have f5 := decList_encList encIdent decIdent v.authorizedActors (fun x hx => decIdent_encIdent x)
  change (do
    let id ← decIdent (encIdent v.id)
    let requireFresh ← decBool (encBool v.requireFresh)
    let requireValidation ← decBool (encBool v.requireValidation)
    let requireUncontested ← decBool (encBool v.requireUncontested)
    let ttl ← decTtlPolicy (encTtlPolicy v.ttl)
    let authorizedActors ← (decList decIdent) ((encList encIdent) v.authorizedActors)
    let value : Policy := ⟨id, requireFresh, requireValidation, requireUncontested, ttl, authorizedActors⟩
    pure value) = .ok v
  rw [f0, f1, f2, f3, f4, f5]
  rfl

theorem roundtripSourceSelection (v : SourceSelection) :
    decSourceSelection (encSourceSelection v) = .ok v := by
  change (do
    let source ← decIdent (encIdent v.source)
    let revision ← decIdent (encIdent v.revision)
    let content ← decIdent (encIdent v.content)
    pure (SourceSelection.mk source revision content)) = .ok v
  rw [decIdent_encIdent]
  simp only [bind, Except.bind, pure, Except.pure]
  rw [decIdent_encIdent]
  simp only [bind, Except.bind, pure, Except.pure]
  rw [decIdent_encIdent]

private theorem context_object (s v r c p n t u sources : Json) :
    decContext (Json.mkObj [("snapshot", s), ("semantic_version", v), ("ruleset", r),
      ("checker", c), ("policy", p), ("now", n), ("target", t), ("intended_use", u), ("sources", sources)]) =
    (do
      let s ← decIdent s; let v ← decStr v; let r ← decIdent r; let c ← decIdent c
      let p ← decPolicy p; let n ← decNat n; let t ← decScope t; let u ← decStr u
      let sources ← decList decSourceSelection sources
      let value : Context := ⟨s, v, r, c, p, n, t, u, sources⟩
      if contextWf value then pure value else throw "invalid_request") := rfl

def WireContext (v : Context) : Prop := contextWf v = true ∧ (WirePolicy v.policy) ∧ (WireScope v.target)
theorem roundtripContext (v : Context) (h : WireContext v) : decContext (encContext v) = .ok v := by
  rcases h with ⟨hg, h4, h6⟩
  have f0 := decIdent_encIdent v.snapshot
  have f1 := decStr_encStr v.semanticVersion
  have f2 := decIdent_encIdent v.ruleset
  have f3 := decIdent_encIdent v.checker
  have f4 := roundtripPolicy v.policy h4
  have f5 := decNat_encNat v.now
  have f6 := roundtripScope v.target h6
  have f7 := decStr_encStr v.intendedUse
  have f8 := decList_encList encSourceSelection decSourceSelection v.sources (fun x _ => roundtripSourceSelection x)
  simp only [encContext, context_object]
  rw [f0, f1, f2, f3, f4, f5, f6, f7, f8]
  simpa only [bind, Except.bind, pure] using (show (if contextWf v then Except.ok v else .error "invalid_request") = .ok v from by simp [hg])

def WireDependency : Dependency → Prop
  | .observation v => WireObservation v
  | .claim v => WireClaim v
  | .attestation v => WireAttestation v
  | .enumeration v => WireEnumeration v
  | .context v => WireContext v ∧ v.now = 0
  | .corrections r es => WireRef r ∧ ∀ e ∈ es, WireCorrection e

private theorem dep_observation (j : Json) :
    decDependency (Json.mkObj [("tag", .str "observation"), ("value", j)]) =
      (do let v ← decObservation j; pure (Dependency.observation v)) := rfl
private theorem dep_claim (j : Json) :
    decDependency (Json.mkObj [("tag", .str "claim"), ("value", j)]) =
      (do let v ← decClaim j; pure (Dependency.claim v)) := rfl
private theorem dep_attestation (j : Json) :
    decDependency (Json.mkObj [("tag", .str "attestation"), ("value", j)]) =
      (do let v ← decAttestation j; pure (Dependency.attestation v)) := rfl
private theorem dep_enumeration (j : Json) :
    decDependency (Json.mkObj [("tag", .str "enumeration"), ("value", j)]) =
      (do let v ← decEnumeration j; pure (Dependency.enumeration v)) := rfl
private theorem dep_context (j : Json) :
    decDependency (Json.mkObj [("tag", .str "context"), ("value", j)]) =
      (do let v ← decContext j
          if v.now == 0 then pure (Dependency.context v) else throw "invalid_request") := rfl
private theorem dep_corrections (r es : Json) :
    decDependency (Json.mkObj [("tag", .str "corrections"), ("target", r), ("events", es)]) =
      (do let r ← decRef r; let es ← decList decCorrection es; pure (Dependency.corrections r es)) := rfl

theorem roundtripDependency (d : Dependency) (h : WireDependency d) : decDependency (encDependency d) = .ok d := by
  cases d with
  | observation v =>
      simp only [encDependency, dep_observation]
      rw [roundtripObservation v h]; rfl
  | claim v =>
      simp only [encDependency, dep_claim]
      rw [roundtripClaim v h]; rfl
  | attestation v =>
      simp only [encDependency, dep_attestation]
      rw [roundtripAttestation v h]; rfl
  | enumeration v =>
      simp only [encDependency, dep_enumeration]
      rw [roundtripEnumeration v h]; rfl
  | context v =>
      simp only [encDependency, dep_context]
      rw [roundtripContext v h.1]
      simp [h.2, bind, Except.bind, pure, Except.pure]
  | corrections r es =>
      simp only [encDependency, dep_corrections]
      rw [roundtripRef r h.1, decList_encList encCorrection decCorrection es (fun x hx => roundtripCorrection x (h.2 x hx))]
      rfl

private theorem receipt_object (id claim context witness deps result expiry : Json) :
    decReceipt (Json.mkObj [("id", id), ("claim", claim), ("context", context), ("witness", witness),
      ("dependencies", deps), ("result", result), ("expires_at", expiry)]) =
    (do
      let id ← decIdent id; let claim ← decRef claim; let context ← decContext context
      let witness ← decWitness witness; let deps ← decList decDependency deps
      let result ← decResult result; let expiry ← decNat expiry
      pure (Receipt.mk id claim context witness deps result expiry)) := rfl

def WireReceipt (v : Receipt) : Prop := true = true ∧ (WireRef v.claim) ∧ (WireContext v.context) ∧ (WireWitness v.witness) ∧ (∀ x ∈ v.dependencies, WireDependency x)
theorem roundtripReceipt (v : Receipt) (h : WireReceipt v) : decReceipt (encReceipt v) = .ok v := by
  rcases h with ⟨hg, h1, h2, h3, h4⟩
  have f0 := decIdent_encIdent v.id
  have f1 := roundtripRef v.claim h1
  have f2 := roundtripContext v.context h2
  have f3 := roundtripWitness v.witness h3
  have f4 := decList_encList encDependency decDependency v.dependencies (fun x hx => roundtripDependency x (h4 x hx))
  have f5 := decResult_encResult v.passed
  have f6 := decNat_encNat v.expiresAt
  simp only [encReceipt, receipt_object]
  rw [f0, f1, f2, f3, f4, f5, f6]
  rfl

private theorem kb_object (snapshot obs claims attestations enumerations derivations corrections receipts : Json) :
    parseKB (Json.mkObj [("snapshot", snapshot), ("observations", obs), ("claims", claims), ("attestations", attestations),
      ("enumerations", enumerations), ("derivations", derivations), ("corrections", corrections), ("receipts", receipts)]) =
    (do
      let snapshot ← decIdent snapshot; let obs ← decList decObservation obs; let claims ← decList decClaim claims
      let attestations ← decList decAttestation attestations; let enumerations ← decList decEnumeration enumerations
      let derivations ← decList decDerivation derivations; let corrections ← decList decCorrection corrections
      let receipts ← decList decReceipt receipts
      pure (KB.mk snapshot obs claims attestations enumerations derivations corrections receipts)) := rfl

def WireKB (v : KB) : Prop := v.wellFormed = true ∧ (∀ x ∈ v.observations, WireObservation x) ∧ (∀ x ∈ v.claims, WireClaim x) ∧ (∀ x ∈ v.attestations, WireAttestation x) ∧ (∀ x ∈ v.enumerations, WireEnumeration x) ∧ (∀ x ∈ v.derivations, WireDerivation x) ∧ (∀ x ∈ v.corrections, WireCorrection x) ∧ (∀ x ∈ v.receipts, WireReceipt x)
theorem roundtripKB (v : KB) (h : WireKB v) : decKB (encKB v) = .ok v := by
  rcases h with ⟨hg, h1, h2, h3, h4, h5, h6, h7⟩
  have f0 := decIdent_encIdent v.snapshot
  have f1 := decList_encList encObservation decObservation v.observations (fun x hx => roundtripObservation x (h1 x hx))
  have f2 := decList_encList encClaim decClaim v.claims (fun x hx => roundtripClaim x (h2 x hx))
  have f3 := decList_encList encAttestation decAttestation v.attestations (fun x hx => roundtripAttestation x (h3 x hx))
  have f4 := decList_encList encEnumeration decEnumeration v.enumerations (fun x hx => roundtripEnumeration x (h4 x hx))
  have f5 := decList_encList encDerivation decDerivation v.derivations (fun x hx => roundtripDerivation x (h5 x hx))
  have f6 := decList_encList encCorrection decCorrection v.corrections (fun x hx => roundtripCorrection x (h6 x hx))
  have f7 := decList_encList encReceipt decReceipt v.receipts (fun x hx => roundtripReceipt x (h7 x hx))
  have parsed : parseKB (encKB v) = .ok v := by
    simp only [encKB, kb_object]
    rw [f0, f1, f2, f3, f4, f5, f6, f7]
    rfl
  simp [decKB, parsed, hg, bind, Except.bind, pure, Except.pure]

/-- Full version-two state codec preservation over the declared bounded wire syntax.
The validity premise is syntactic wellformedness/depth, never assumed codec success. -/
theorem T02_full_state_roundtrip (k : KB) (h : WireKB k) : decKB (encKB k) = .ok k := roundtripKB k h

def canonicalKB (j : Json) : Except String Json := encKB <$> decKB j

theorem T02_canonicalization_preserves {j : Json} {k : KB}
    (decoded : decKB j = .ok k) (valid : WireKB k) :
    (canonicalKB j >>= decKB) = .ok k := by
  simp [canonicalKB, decoded, roundtripKB k valid, bind, Except.bind, Functor.map, Except.map]

end Kctx
