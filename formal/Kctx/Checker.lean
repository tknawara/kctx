import Kctx.Semantics

set_option autoImplicit false
namespace Kctx

/-- Structural recursion follows actual finite proof trees, not reference lookups. -/
def checkWitness (k : KB) (e : Context) : Witness → Option Checked
  | .attest id => leafEvidence k e id
  | .truth s => if scopeWf s then some ⟨⟨.truth, s, .positive⟩, []⟩ else none
  | .and wa wb => do
      let a ← checkWitness k e wa
      let b ← checkWitness k e wb
      if andAllowed a b then some (andResult a b) else none
  | .specialize s w => do
      let a ← checkWitness k e w
      if narrower s a.statement.scope then
        some { a with statement := { a.statement with scope := s } }
      else none
  | .all id p w => do
      let (z, o) ← enumerationEvidence k e id
      let a ← checkWitness k e w
      if allAllowed z p a then some (allResult z o p a) else none
  | .absent id w => do
      let (z, o) ← enumerationEvidence k e id
      let a ← checkWitness k e w
      if absenceAllowed z a then some (absenceResult z o a) else none

def check (k : KB) (e : Context) (w : Witness) : Option Checked :=
  if contextValid k e then
    (checkWitness k e w).map (fun r => { r with dependencies := mergeDependencies r.dependencies [contextDependency e] })
  else none

def checkedDerivation (k : KB) (e : Context) (d : Derivation) : Option Checked := do
  let c ← claimAt k d.claim
  if activeRetracted k e d.claim then none else do
    if !contextValid k e then none else do
      let r ← checkWitness k e d.witness
      if r.statement == c.statement then
        some { r with dependencies := mergeDependencies r.dependencies [.claim c, correctionDependency k e d.claim, contextDependency e] }
      else none

def alternatives (k : KB) (e : Context) (s : Statement) : List Checked :=
  k.derivations.filterMap (fun d => do
    let r ← checkedDerivation k e d
    if r.statement == s then some r else none)

def exactAlternatives (k : KB) (e : Context) (r : Ref) : List Checked :=
  k.derivations.filterMap (fun d => if d.claim == r then checkedDerivation k e d else none)

def supportAlternatives (k : KB) (e : Context) (r : Ref) (p : Polarity) : List Checked :=
  match claimAt k r with
  | none => []
  | some c => if p == c.statement.polarity then exactAlternatives k e r
    else alternatives k e { c.statement with polarity := p }

def supported (k : KB) (e : Context) (r : Ref) (p : Polarity) : Bool :=
  !(supportAlternatives k e r p).isEmpty

def pathFresh (e : Context) (r : Checked) : Fresh :=
  let observations := evidenceObservations r.dependencies
  if observations.isEmpty then .unknown else
  let fs := observations.map (fun o => assessFresh e.policy.ttl o.observedAt e.now)
  if fs.contains .stale then .stale else if fs.all (· == .fresh) then .fresh else .unknown

def alternativeFresh (e : Context) (rs : List Checked) : Fresh :=
  if rs.isEmpty then .unknown else
  let fs := rs.map (pathFresh e)
  if fs.contains .fresh then .fresh else if fs.all (· == .stale) then .stale else .unknown

def reusable (k : KB) (e : Context) (r : Ref) (receipt : Receipt) : Bool :=
  receipt.claim == r && receipt.passed && sameContext receipt.context e &&
  receipt.context.now ≤ e.now && e.now ≤ receipt.expiresAt &&
  k.derivations.any (fun d => d.claim == r && d.witness == receipt.witness &&
    match checkedDerivation k e d with
    | some result => result.dependencies == receipt.dependencies
    | none => false)

def validationCurrent (k : KB) (e : Context) (r : Ref) : Bool :=
  k.receipts.any (reusable k e r)

def contested (k : KB) (e : Context) (r : Ref) : Bool :=
  (match claimAt k r with
   | some c => supported k e r (if c.statement.polarity == .positive then .negative else .positive)
   | none => false) || k.corrections.any
    (fun c => c.kind == .dispute && c.target == r && c.recordedAt ≤ e.now)

def assess (k : KB) (e : Context) (r : Ref) : Assessment :=
  let pos := supported k e r .positive
  let neg := supported k e r .negative
  let support := if pos then (if neg then Support.both else .positive) else
    (if neg then .negative else .none)
  let applicable := contextValid k e && match claimAt k r with
    | some c => decide (narrower e.target c.statement.scope)
    | none => false
  let freshness := match claimAt k r with
    | some _ => alternativeFresh e (exactAlternatives k e r)
    | none => .unknown
  let validated := validationCurrent k e r
  let disputed := contested k e r
  let available := pos || neg
  let selected := match claimAt k r with
    | some c => if c.statement.polarity == .positive then pos else neg
    | none => false
  let usable := selected && applicable && (!e.policy.requireFresh || freshness == .fresh) &&
    (!e.policy.requireValidation || validated) && (!e.policy.requireUncontested || !disputed)
  ⟨support, applicable, freshness, validated, disputed, available, usable⟩

def usableFor (k : KB) (e : Context) (r : Ref) : Bool := (assess k e r).usable

structure Retrieval where
  snapshot : SnapshotId
  records : List (Claim × Assessment)
  omitted : Nat
  complete : Bool
  nextOffset : Option Nat
  deriving DecidableEq, BEq, Repr, Inhabited

def retrieve (k : KB) (e : Context) (offset limit : Nat) : Retrieval :=
  let relevant := if contextValid k e then k.claims.filter (fun c => decide (narrower e.target c.statement.scope)) else []
  let page := (relevant.drop offset).take limit
  let next := offset + page.length
  let omitted := relevant.length - next
  ⟨k.snapshot, page.map (fun c => (c, assess k e c.ref)), omitted, omitted == 0,
    if omitted == 0 then none else some next⟩

end Kctx
