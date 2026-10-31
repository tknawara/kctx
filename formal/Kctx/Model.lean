import Kctx.Time

set_option autoImplicit false
namespace Kctx

instance (priority := low) decidableBEq {α : Type} [DecidableEq α] : BEq α :=
  ⟨fun a b => decide (a = b)⟩
instance {α : Type} [DecidableEq α] : @LawfulBEq α decidableBEq where
  eq_of_beq := of_decide_eq_true
  rfl := by intro a; exact decide_eq_true rfl

def semanticVersion : String := "2.0.0"

structure Scope where
  project : ProjectId
  selector : String
  deriving DecidableEq, Repr, Inhabited

def narrower (a b : Scope) : Prop :=
  a.project = b.project ∧ (a.selector = b.selector ∨ b.selector = "")
instance (a b : Scope) : Decidable (narrower a b) := inferInstanceAs (Decidable (_ ∧ _))

structure Atom where
  subject : String
  predicate : String
  args : List String
  deriving DecidableEq, Repr, Inhabited

inductive Formula where
  | atom (value : Atom)
  | truth
  | and (left right : Formula)
  | all (enumeration : EnumerationId) (predicate : String)
  | absent (enumeration : EnumerationId)
  | inventory (enumeration : EnumerationId)
  deriving DecidableEq, Repr, Inhabited

inductive Polarity where
  | positive | negative
  deriving DecidableEq, Repr, Inhabited

structure Statement where
  formula : Formula
  scope : Scope
  polarity : Polarity
  deriving DecidableEq, Repr, Inhabited

structure Ref where
  id : ClaimId
  revision : ClaimRevision
  deriving DecidableEq, Repr, Inhabited

structure Claim where
  id : ClaimId
  revision : ClaimRevision
  statement : Statement
  deriving DecidableEq, Repr, Inhabited

def Claim.ref (c : Claim) : Ref := ⟨c.id, c.revision⟩

inductive Outcome where
  | ok | timeout | «partial» | truncated | denied | unavailable
  deriving DecidableEq, Repr, Inhabited

structure Observation where
  id : ObservationId
  source : SourceId
  revision : SourceRevision
  content : ContentId
  observedAt : Nat
  outcome : Outcome
  deriving DecidableEq, Repr, Inhabited

structure Attestation where
  id : AttestationId
  claim : Ref
  observation : ObservationId
  statement : Statement
  authority : ActorId
  deriving DecidableEq, Repr, Inhabited

structure Enumeration where
  id : EnumerationId
  source : SourceId
  revision : SourceRevision
  query : String
  scope : Scope
  observation : ObservationId
  members : List String
  «universe» : List String
  method : String
  deriving DecidableEq, Repr, Inhabited

/-- Finite proof trees have no reference-following recursion or cyclic witnesses. -/
inductive Witness where
  | attest (attestation : AttestationId)
  | truth (scope : Scope)
  | and (left right : Witness)
  | specialize (scope : Scope) (premise : Witness)
  | all (enumeration : EnumerationId) (predicate : String) (premise : Witness)
  | absent (enumeration : EnumerationId) (premise : Witness)
  deriving DecidableEq, Repr, Inhabited

structure Derivation where
  id : DerivationId
  claim : Ref
  witness : Witness
  deriving DecidableEq, Repr, Inhabited

inductive CorrectionKind where
  | retract | dispute | supersede
  deriving DecidableEq, Repr, Inhabited

structure Correction where
  id : CorrectionId
  kind : CorrectionKind
  target : Ref
  replacement : Option Ref
  recordedAt : Nat
  deriving DecidableEq, Repr, Inhabited

structure Policy where
  id : PolicyId
  requireFresh : Bool
  requireValidation : Bool
  requireUncontested : Bool
  ttl : TtlPolicy
  authorizedActors : List ActorId
  deriving DecidableEq, Repr, Inhabited

structure SourceSelection where
  source : SourceId
  revision : SourceRevision
  content : ContentId
  deriving DecidableEq, Repr, Inhabited

structure Context where
  snapshot : SnapshotId
  semanticVersion : String
  ruleset : RuleVersion
  checker : CheckerId
  policy : Policy
  now : Nat
  target : Scope
  intendedUse : String
  sources : List SourceSelection
  deriving DecidableEq, Repr, Inhabited

def sourceSelected (e : Context) (o : Observation) : Bool :=
  e.sources.contains ⟨o.source, o.revision, o.content⟩

inductive Dependency where
  | observation (value : Observation)
  | claim (value : Claim)
  | attestation (value : Attestation)
  | enumeration (value : Enumeration)
  | corrections (target : Ref) (events : List Correction)
  | context (value : Context)
  deriving DecidableEq, Repr, Inhabited

structure Receipt where
  id : ReceiptId
  claim : Ref
  context : Context
  witness : Witness
  dependencies : List Dependency
  passed : Bool
  expiresAt : Nat
  deriving DecidableEq, Repr, Inhabited

structure KB where
  snapshot : SnapshotId
  observations : List Observation
  claims : List Claim
  attestations : List Attestation
  enumerations : List Enumeration
  derivations : List Derivation
  corrections : List Correction
  receipts : List Receipt
  deriving DecidableEq, Repr, Inhabited

structure Checked where
  statement : Statement
  dependencies : List Dependency
  deriving DecidableEq, Repr, Inhabited

def memberFormula (members : List String) (predicate : String) : Formula :=
  members.foldr (fun m rest => .and (.atom ⟨m, predicate, []⟩) rest) .truth

def claimAt (k : KB) (r : Ref) : Option Claim := k.claims.find? (fun c => c.ref == r)
def observationAt (k : KB) (id : ObservationId) : Option Observation := lookup (·.id) k.observations id
def attestationAt (k : KB) (id : AttestationId) : Option Attestation := lookup (·.id) k.attestations id
def enumerationAt (k : KB) (id : EnumerationId) : Option Enumeration := lookup (·.id) k.enumerations id

def activeRetracted (k : KB) (e : Context) (r : Ref) : Bool :=
  k.corrections.any (fun c => c.kind == .retract && c.target == r && c.recordedAt ≤ e.now)


def dedupDependencies (seen : List Dependency) : List Dependency → List Dependency
  | [] => []
  | d :: ds => if seen.contains d then dedupDependencies seen ds
    else d :: dedupDependencies (d :: seen) ds

def mergeDependencies (a b : List Dependency) : List Dependency := dedupDependencies [] (a ++ b)

def correctionDependency (k : KB) (e : Context) (r : Ref) : Dependency :=
  .corrections r (k.corrections.filter (fun c => c.target == r && c.recordedAt ≤ e.now))

def contextDependency (e : Context) : Dependency := .context { e with now := 0 }

def evidenceObservations (ds : List Dependency) : List Observation :=
  ds.filterMap (fun d => match d with | .observation o => some o | _ => none)

def sameContext (a b : Context) : Bool := { a with now := b.now } == b

inductive Support where
  | none | positive | negative | both
  deriving DecidableEq, Repr, Inhabited

structure Assessment where
  support : Support
  applicable : Bool
  freshness : Fresh
  validated : Bool
  contested : Bool
  available : Bool
  usable : Bool
  deriving DecidableEq, Repr, Inhabited


end Kctx
