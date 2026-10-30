import Kctx.Ids
import Kctx.Time
set_option autoImplicit false

/-! Core model: scopes, propositions, records, states.

Deliberately bounded v1 vocabulary (handover §4). State dimensions are
independent fields, never one status string.

Bounded v1 design decisions (recorded in `formal/theorems.json`):
* conjunction conjoins *flat atoms* — nested conjunctions are not expressible
  in v1, which keeps `ClaimProp` a non-recursive inductive and equality
  derivable in core Lean (no mathlib);
* propositions, not whole records, are what derivations compare.

Lean core (4.21) has no `deriving BEq` handler, so BEq instances are explicit.
Whole records carrying propositions (Claim, Derivation, KB) deliberately have
no equality instances: the calculus compares identities, verdicts, and
propositions, never whole records. -/

namespace Kctx

/-- Scope: project + optional finer discriminator (empty `extra` = whole
project). Scope restriction is rule-specific; by default exact matching. -/
structure Scope where
  project : String
  extra : String
deriving DecidableEq, Repr, Inhabited

/-- `target.specializes source = true` iff `target` denotes a sub-scope of
`source`: same project, and `source` is broad (`extra` empty) or identical. -/
def Scope.specializes (target source : Scope) : Bool :=
  target.project == source.project && (source.extra == "" || source.extra == target.extra)

theorem specializes_refl (s : Scope) : s.specializes s = true := by
  simp [Scope.specializes]

theorem specializes_same_project {s s' : Scope} (h : s'.specializes s = true) :
    (s'.project == s.project) = true := by
  simp only [Scope.specializes, Bool.and_eq_true] at h
  exact h.1

/-! ## Structured propositions.

Prose stays prose; LLM assertions enter as proposals, never axioms. `conj` is
explicit conjunction over flat atoms; `allChecked` is a universal over an
explicit finite member list (T13). -/

structure Atom where
  subject : String
  predicate : String
  args : List String
deriving DecidableEq, Repr, Inhabited, Hashable

inductive ClaimProp where
  | atom (a : Atom)
  | conj (ps : List Atom)
  | allChecked (predicate : String) (members : List String)
deriving DecidableEq, Repr, Inhabited

def ClaimProp.asAtom : ClaimProp → Option Atom
  | .atom a => some a
  | _ => none

inductive ObsOutcome where
  | ok
  | timedOut
  | partialResult
  | truncated
  | denied
  | unavailable
deriving DecidableEq, Repr, Inhabited

/-- Evidence roles: a mention or contextual citation is not support. -/
inductive SupportRole where
  | supports
  | contradicts
  | contextualizes
deriving DecidableEq, Repr, Inhabited

/-- The v1 rule registry is finite and closed. -/
inductive RuleId where
  | andIntro
  | specialize
  | obsSupports
  | allChecked
deriving DecidableEq, Repr, Inhabited

/-! ## Records. -/

structure Observation where
  id : ObservationId
  outcome : ObsOutcome
  observedAt : Int
  ttl : TtlPolicy
  system : String
  locator : String
deriving DecidableEq, Repr, Inhabited

structure Claim where
  id : ClaimId
  rev : String
  prop : ClaimProp
  scope : Scope
deriving Repr, Inhabited

/-- Evidence binding: which observation revision supports/contradicts which
claim revision. -/
structure Binding where
  obs : ObservationId
  ref : ClaimRef
  role : SupportRole
deriving DecidableEq, Repr, Inhabited

inductive DepKind where
  | sourceContent
  | kbRecord
  | policy
  | checker
  | correction
  | discovery
deriving DecidableEq, Repr, Inhabited

/-- One dependency footprint entry: what to watch, and the exact version/digest
required for reuse. -/
structure Dep where
  kind : DepKind
  target : String
  digest : String
deriving DecidableEq, Repr, Inhabited

/-- Coverage witness: evidence that a required set was enumerated within a
declared scope at a declared revision, with completeness status. -/
structure CoverageWitness where
  scope : Scope
  members : List String
  complete : Bool
deriving DecidableEq, Repr, Inhabited

/-! ## Derivations.

`premiseGroups` is a disjunction of conjunctions: `(a AND b) OR c2`
(handover §4.4). `evidence` is the declared observation used by
`obsSupports`; `witness` the declared coverage witness used by `allChecked`.
The declared `footprint` is the reuse contract; the checker requires each
rule's consulted record identities to appear in it (T12). -/

structure Derivation where
  id : String
  rule : RuleId
  premiseGroups : List (List ClaimRef)
  conclusion : ClaimRef
  conclusionProp : ClaimProp
  scope : Scope
  footprint : List Dep
  evidence : Option ObservationId
  witness : Option CoverageWitness
deriving Repr, Inhabited

inductive CorrectionKind where
  | retract
  | dispute
  | supersede
deriving DecidableEq, Repr, Inhabited

/-- Corrections target an identified record revision; they never rewrite what
the revision said. -/
structure Correction where
  kind : CorrectionKind
  target : ClaimRef
  recordedAt : Int
deriving DecidableEq, Repr, Inhabited

/-- Evaluation context: world snapshot + policy + explicit evaluation time. -/
structure EvalCtx where
  now : Int
  requireFreshEvidence : Bool
  requireValidated : Bool
  requireUncontested : Bool
deriving DecidableEq, Repr, Inhabited

def EvalCtx.default (now : Int) : EvalCtx where
  now := now
  requireFreshEvidence := true
  requireValidated := true
  requireUncontested := true

def SEMANTIC_VERSION : String := "1.0.0"

/-- Exactly these rules are enabled in v1. T14: nothing else derives. -/
def enabledRules : List RuleId :=
  [.andIntro, .specialize, .obsSupports, .allChecked]

/-! ## Knowledge base and the read view semantic evaluation consults. -/

structure KB where
  head : String
  observations : List Observation
  claims : List Claim
  bindings : List Binding
  derivations : List Derivation
  corrections : List Correction
  validations : List (ClaimRef × String)
deriving Repr, Inhabited

/-- The read-only view of a KB that semantic evaluation consults. Locality
(T07/T15) is stated over views. -/
structure KbView where
  observations : List Observation
  claims : List Claim
  bindings : List Binding
  corrections : List Correction
  derivations : List Derivation
  validations : List (ClaimRef × String)
deriving Repr, Inhabited

def KB.view (kb : KB) : KbView where
  observations := kb.observations
  claims := kb.claims
  bindings := kb.bindings
  corrections := kb.corrections
  derivations := kb.derivations
  validations := kb.validations

def KbView.findObs (v : KbView) (i : ObservationId) : Option Observation :=
  v.observations.find? (fun o => o.id == i)

def KbView.findClaim (v : KbView) (r : ClaimRef) : Option Claim :=
  v.claims.find? (fun c => c.id == r.id && c.rev == r.rev)

def KbView.hasCorrectionOn (v : KbView) (r : ClaimRef) : Bool :=
  v.corrections.any (fun c => c.target == r)

def KbView.propOf (v : KbView) (r : ClaimRef) : ClaimProp :=
  match v.findClaim r with
  | some c => c.prop
  | none => .atom { subject := "", predicate := "", args := [] }

def KbView.scopeOf (v : KbView) (r : ClaimRef) : Option Scope :=
  (v.findClaim r).map (fun c => c.scope)

/-! Explicit BEq instances (core has no `deriving BEq`). Ident and ClaimRef
instances live in Ids.lean. -/
instance : BEq RuleId := ⟨fun a b => decide (a = b)⟩
instance : BEq Dep := ⟨fun a b => decide (a = b)⟩
instance : BEq ClaimProp := ⟨fun a b => decide (a = b)⟩

end Kctx
