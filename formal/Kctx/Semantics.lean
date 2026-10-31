import Kctx.WellFormed

set_option autoImplicit false
namespace Kctx

/-- Exact finite retained inventory serialization, not a caller's completeness flag. -/
def inventoryIdentity (members : List String) : ContentId :=
  ⟨"inventory:" ++ String.join (members.map (fun s => toString s.utf8ByteSize ++ ":" ++ s)), by
    generalize String.join (members.map (fun s => toString s.utf8ByteSize ++ ":" ++ s)) = suffix
    cases suffix with
    | mk chars =>
        intro impossible
        have dataEquality : ['i', 'n', 'v', 'e', 'n', 't', 'o', 'r', 'y', ':'] ++ chars = [] :=
          congrArg String.data impossible
        cases dataEquality⟩

def inventoryAttestation (k : KB) (a : Attestation) : Option Enumeration :=
  match a.statement.formula with | .inventory id => enumerationAt k id | _ => none

def inventoryDependencies (k : KB) (a : Attestation) : List Dependency :=
  (inventoryAttestation k a).toList.map Dependency.enumeration

def leafAllowed (k : KB) (e : Context) (a : Attestation) (o : Observation) : Bool :=
  a.authority.val != "" && sourceSelected e o && o.outcome == .ok && o.observedAt ≤ e.now &&
  !activeRetracted k e a.claim &&
  (match a.statement.formula with
   | .atom _ => true
   | .inventory _ => match inventoryAttestation k a with
     | some z => a.observation == z.observation && a.statement.scope == z.scope && a.statement.polarity == .positive
     | none => false
   | _ => false) &&
  (match claimAt k a.claim with | some c => c.statement == a.statement | none => false)

def enumerationAllowed (e : Context) (z : Enumeration) (o : Observation) : Bool :=
  sourceSelected e o && o.outcome == .ok && o.observedAt ≤ e.now && o.source == z.source &&
  o.revision == z.revision && z.members == z.universe && unique z.members &&
  z.query != "" && z.method != "" && o.content == inventoryIdentity z.universe

def leafEvidence (k : KB) (e : Context) (id : AttestationId) : Option Checked := do
  let a ← attestationAt k id
  let o ← observationAt k a.observation
  let c ← claimAt k a.claim
  if leafAllowed k e a o then
    some ⟨a.statement, [.observation o, .claim c, .attestation a, correctionDependency k e a.claim] ++ inventoryDependencies k a⟩
  else none

def enumerationEvidence (k : KB) (e : Context) (id : EnumerationId) : Option (Enumeration × Observation) := do
  let z ← enumerationAt k id
  let o ← observationAt k z.observation
  if enumerationAllowed e z o then some (z, o) else none

def andAllowed (a b : Checked) : Bool :=
  a.statement.scope == b.statement.scope && a.statement.polarity == .positive &&
  b.statement.polarity == .positive

def andResult (a b : Checked) : Checked :=
  ⟨⟨.and a.statement.formula b.statement.formula, a.statement.scope, .positive⟩,
   mergeDependencies a.dependencies b.dependencies⟩

def allAllowed (z : Enumeration) (p : String) (a : Checked) : Bool :=
  p != "" && a.statement == ⟨.and (.inventory z.id) (memberFormula z.members p), z.scope, .positive⟩

def allResult (z : Enumeration) (o : Observation) (p : String) (a : Checked) : Checked :=
  ⟨⟨.all z.id p, z.scope, .positive⟩, mergeDependencies a.dependencies [.observation o, .enumeration z]⟩

def absenceAllowed (z : Enumeration) (a : Checked) : Bool :=
  z.members == [] && a.statement == ⟨.inventory z.id, z.scope, .positive⟩
def absenceResult (z : Enumeration) (o : Observation) (a : Checked) : Checked :=
  ⟨⟨.absent z.id, z.scope, .positive⟩, mergeDependencies a.dependencies [.observation o, .enumeration z]⟩

/-- Declarative finite proof judgment. No constructor mentions the recursive checker. -/
inductive Derives (k : KB) (e : Context) : Witness → Checked → Prop where
  | attest {id : AttestationId} {r : Checked} : leafEvidence k e id = some r → Derives k e (.attest id) r
  | truth (s : Scope) : scopeWf s = true → Derives k e (.truth s) ⟨⟨.truth, s, .positive⟩, []⟩
  | and {wa wb : Witness} {a b : Checked} : Derives k e wa a → Derives k e wb b →
      andAllowed a b = true → Derives k e (.and wa wb) (andResult a b)
  | specialize {w : Witness} {a : Checked} (s : Scope) : Derives k e w a →
      narrower s a.statement.scope →
      Derives k e (.specialize s w) { a with statement := { a.statement with scope := s } }
  | all {w : Witness} {a : Checked} {id : EnumerationId} {p : String} {z : Enumeration} {o : Observation} :
      enumerationEvidence k e id = some (z, o) → Derives k e w a → allAllowed z p a = true →
      Derives k e (.all id p w) (allResult z o p a)
  | absent {id : EnumerationId} {w : Witness} {a : Checked} {z : Enumeration} {o : Observation} :
      enumerationEvidence k e id = some (z, o) → Derives k e w a → absenceAllowed z a = true →
      Derives k e (.absent id w) (absenceResult z o a)

/-- Atomic values are unconstrained and may independently support either polarity.
Global scope means all concrete subscopes, making explicit specialization sound. -/
structure Interpretation where
  atom : Atom → Scope → Polarity → Prop
  domain : SourceId → SourceRevision → String → Scope → String → List String

def atomHolds (i : Interpretation) (a : Atom) (s : Scope) (p : Polarity) : Prop :=
  ∀ t, narrower t s → i.atom a t p

def domainMembers (i : Interpretation) (z : Enumeration) : List String :=
  i.domain z.source z.revision z.query z.scope z.method

def holdsFormula (i : Interpretation) (k : KB) (s : Scope) (p : Polarity) : Formula → Prop
  | .atom a => atomHolds i a s p
  | .truth => p = .positive
  | .and a b => p = .positive ∧ holdsFormula i k s .positive a ∧ holdsFormula i k s .positive b
  | .all id predicate => p = .positive ∧ ∃ z, enumerationAt k id = some z ∧
      ∀ member ∈ domainMembers i z, atomHolds i ⟨member, predicate, []⟩ s .positive
  | .absent id => p = .positive ∧ ∃ z, enumerationAt k id = some z ∧ domainMembers i z = []
  | .inventory id => p = .positive ∧ ∃ z, enumerationAt k id = some z ∧ domainMembers i z = z.members

def Holds (i : Interpretation) (k : KB) (s : Statement) : Prop :=
  holdsFormula i k s.scope s.polarity s.formula

/-- The only external-world assumption: each actually selected, admitted exact
attestation entails its own proposition/polarity/scope. Acquisition alone implies nothing. -/
def EvidenceSound (i : Interpretation) (k : KB) (e : Context) : Prop :=
  ∀ id a o, attestationAt k id = some a → observationAt k a.observation = some o →
    leafAllowed k e a o = true → Holds i k a.statement

end Kctx
