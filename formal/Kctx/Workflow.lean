import Kctx.Model
import Kctx.WellFormed

set_option autoImplicit false

/-! Workflow transitions: proposals, investigation conclusions, and
conditionally-applied operation plans with idempotent commit (T18–T21).

All functions are pure; `CommitOutcome` results never collapse distinctions
(committed / already committed / predecessor conflict / input conflict /
rejected invalid) into booleans or opaque exceptions. -/

namespace Kctx

/-! ## Proposals. -/

inductive ProposalStatus where
  | draft
  | proposed
  | accepted
  | rejected
  | deferred
  | landing
  | applied
  | verified
  | regressed
  | superseded
deriving DecidableEq, Repr, Inhabited

instance : BEq ProposalStatus := ⟨fun a b => decide (a = b)⟩

/-- Transition table mirroring the existing CLI lifecycle
(`draft → proposed → accepted → landing → applied → verified`, with
`rejected`/`deferred` from proposed, `regressed` from applied/verified, and
`superseded` from anywhere except itself). -/
def legalTransition (src tgt : ProposalStatus) : Bool :=
  match src, tgt with
  | .draft, .proposed => true
  | .proposed, .accepted => true
  | .proposed, .rejected => true
  | .proposed, .deferred => true
  | .accepted, .landing => true
  | .landing, .applied => true
  | .applied, .verified => true
  | .applied, .regressed => true
  | .verified, .regressed => true
  | .superseded, .superseded => false
  | _, .superseded => true
  | _, _ => false

structure Proposal where
  id : Ident IdKind.proposal
  status : ProposalStatus
  researchPresent : Bool
  researchJustifiedSkip : Bool
  alternativesCount : Int
  gatesTablePresent : Bool
  legacyProfile : Bool
  decidedBy : Option String
  landedRefs : List String
  landGatesPassed : Bool
  deployUseGatesPassed : Bool
deriving DecidableEq, Repr, Inhabited

/-- Statuses that require an actor (`--by` in the current CLI):
accepted, rejected, applied, landing. -/
def decidedStatus (s : ProposalStatus) : Bool :=
  match s with
  | .accepted => true
  | .rejected => true
  | .applied => true
  | .landing => true
  | _ => false

/-- One readiness predicate, used by BOTH filing-as-proposed and
draft→proposed (the readiness-bypass fix; the old bypass fixture is
intentionally superseded). Research present OR justified skip, two or more
alternatives, and a gates table unless explicitly legacy-profiled. -/

def readyForProposed (p : Proposal) : Bool :=
  (p.researchPresent || p.researchJustifiedSkip)
  && 2 ≤ p.alternativesCount
  && (p.gatesTablePresent || p.legacyProfile)

inductive TransitionError where
  | illegalTransition
  | notReady
  | missingActor
  | gatesNotPassed
  | landedRefsUnresolved
deriving DecidableEq, Repr, Inhabited

inductive PlanOutcome where
  | planned (p : Proposal)
  | refused (e : TransitionError)
deriving DecidableEq, Repr, Inhabited

/-- Pure proposal transition planning (T18). The candidate is constructed
from every change in the command, then checked as a whole. -/

def planTransition (p : Proposal) (target : ProposalStatus)
    (actor : Option String) (landedRefs : List String)
    (refsResolvable : Bool) : PlanOutcome :=
  if !legalTransition p.status target then .refused .illegalTransition
  else if target == .proposed && !readyForProposed p then .refused .notReady
  else if decidedStatus target && actor.isNone then .refused .missingActor
  else if target == .applied
      && !(p.landGatesPassed && refsResolvable && !landedRefs.isEmpty)
    then .refused .gatesNotPassed
  else if target == .verified && !p.deployUseGatesPassed
    then .refused .gatesNotPassed
  else
    .planned
      { p with
        status := target
        decidedBy :=
          if decidedStatus target then actor
          else if target == .proposed then none
          else p.decidedBy
        landedRefs :=
          if target == .applied then landedRefs else p.landedRefs }

/-! ## Investigation conclusions (T19). -/

inductive HypStatus where
  | openH
  | supportedH
  | refutedH
  | unknownH
  | malformedH
deriving DecidableEq, Repr, Inhabited

structure Hypothesis where
  text : String
  status : HypStatus
deriving DecidableEq, Repr, Inhabited

structure Investigation where
  id : Ident IdKind.investigation
  checkedAgainst : String
  scopeAndLimits : String
  hypotheses : List Hypothesis
deriving Repr, Inhabited

/-- Typed conclusion predicate: both sections non-empty, no open hypothesis,
and no malformed hypothesis bullet (malformed is a blocker, never invisible). -/

def canConclude (i : Investigation) : Bool :=
  !i.checkedAgainst.isEmpty
  && !i.scopeAndLimits.isEmpty
  && !i.hypotheses.any (fun h => h.status == .openH || h.status == .malformedH)

/-! ## Operation plans and conditional commit (T03, T20, T21). -/

inductive Change where
  | addClaim (c : Claim)
  | addObservation (o : Observation)
  | addDerivation (d : Derivation)
  | addCorrection (c : Correction)
  | addValidation (r : ClaimRef) (digest : String)
deriving Repr, Inhabited

structure Op where
  id : String
  expectedHead : String
  changes : List Change
  inputDigest : String
deriving Repr, Inhabited

structure JournalEntry where
  id : String
  head : String
  digest : String
deriving DecidableEq, Repr, Inhabited

instance : BEq JournalEntry := ⟨fun a b => decide (a = b)⟩

inductive CommitOutcome where
  | committed
  | alreadyCommitted
  | predecessorConflict
  | inputConflict
  | rejectedInvalid
deriving DecidableEq, Repr, Inhabited

def applyChange (kb : KB) : Change → KB
  | .addClaim c => { kb with claims := kb.claims ++ [c] }
  | .addObservation o => { kb with observations := kb.observations ++ [o] }
  | .addDerivation d => { kb with derivations := kb.derivations ++ [d] }
  | .addCorrection c => { kb with corrections := kb.corrections ++ [c] }
  | .addValidation r digest => { kb with validations := kb.validations ++ [(r, digest)] }

def applyChanges (kb : KB) (changes : List Change) : KB :=
  changes.foldl applyChange kb

/-- Conditionally apply an operation (T20/T21). Rejection of any kind leaves
the modeled state unchanged; success requires the expected predecessor, an
unseen (or identically-replayed) operation id, and a resulting state that
still satisfies well-formedness. -/

def commitOp (kb : KB) (journal : List JournalEntry) (op : Op) : KB × CommitOutcome :=
  match journal.find? (fun e => e.id == op.id) with
  | some e =>
    if e.digest == op.inputDigest && e.head == op.expectedHead
      then (kb, .alreadyCommitted)
      else (kb, .inputConflict)
  | none =>
    if kb.head != op.expectedHead then (kb, .predecessorConflict)
    else if (applyChanges kb op.changes).wellFormed then
      ({ (applyChanges kb op.changes) with head := op.id }, .committed)
    else (kb, .rejectedInvalid)

def journalAfter (journal : List JournalEntry) (kb : KB) (op : Op) : List JournalEntry :=
  match journal.find? (fun e => e.id == op.id) with
  | some _ => journal
  | none =>
    if kb.head == op.expectedHead
    then journal ++ [JournalEntry.mk op.id op.id op.inputDigest]
    else journal

end Kctx
