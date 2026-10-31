import Kctx.Checker

set_option autoImplicit false
namespace Kctx

def nonblank (s : String) : Bool := s.toList.any (fun c => !c.isWhitespace)

def identPresent {kind : IdKind} (id : Option (Ident kind)) : Bool :=
  id.any (fun value => nonblank value.val)

structure Authority where
  actor : ActorId
  target : Ref
  intendedUse : String
  policy : PolicyId
  statement : Statement
  approved : KB
  approvals : List Claim
  context : Context
  deriving DecidableEq, Repr, Inhabited

structure Plan where
  id : OperationId
  expectedSnapshot : SnapshotId
  candidate : KB
  authority : Authority
  claim : Ref
  witness : Witness
  deriving DecidableEq, Repr, Inhabited

/-- Constructed by the authenticated adapter, never from ordinary candidate input. -/
structure VerifiedApproval where
  plan : Plan
  deriving DecidableEq, Repr, Inhabited

def authorized (e : Context) (p : Plan) (trusted : List VerifiedApproval) : Bool :=
  e.policy.authorizedActors.contains p.authority.actor && trusted.any (fun a => a.plan == p)

structure JournalEntry where
  plan : Plan
  deriving DecidableEq, Repr, Inhabited

inductive ApplyOutcome where
  | applied | alreadyApplied | inputConflict | predecessorConflict | rejected
  deriving DecidableEq, Repr, Inhabited

structure ApplyResult where
  kb : KB
  journal : List JournalEntry
  outcome : ApplyOutcome
  deriving DecidableEq, Repr, Inhabited

def isPrefix {α : Type} [BEq α] (a b : List α) : Bool := b.take a.length == a

def extendsKB (a b : KB) : Bool :=
  isPrefix a.observations b.observations && isPrefix a.claims b.claims &&
  isPrefix a.attestations b.attestations && isPrefix a.enumerations b.enumerations &&
  isPrefix a.derivations b.derivations && isPrefix a.corrections b.corrections &&
  isPrefix a.receipts b.receipts

def planValid (k : KB) (e : Context) (p : Plan) : Bool :=
  let ce := { e with snapshot := p.candidate.snapshot }
  token p.id.val && contextValid k e && p.candidate.wellFormed &&
  p.candidate.snapshot != k.snapshot && extendsKB k p.candidate &&
  nonblank p.authority.actor.val && p.authority.target == p.claim &&
  p.authority.intendedUse == e.intendedUse && p.authority.policy == e.policy.id &&
  p.authority.context == e &&
  p.authority.approved == p.candidate &&
  p.authority.approvals == p.candidate.claims.drop k.claims.length &&
  (match claimAt p.candidate p.claim, check p.candidate ce p.witness with
   | some c, some r => c.statement == p.authority.statement && r.statement == c.statement &&
       p.candidate.derivations.any (fun d => d.claim == p.claim && d.witness == p.witness) &&
       usableFor p.candidate ce p.claim
   | _, _ => false) &&
  (p.candidate.claims.drop k.claims.length).all (fun c => usableFor p.candidate ce c.ref)

/-- Canonical inputs are the typed plan itself, not an unrelated caller digest.
The journal producer and replay consumer share this single state transition. -/
def applyPlan (k : KB) (e : Context) (journal : List JournalEntry) (p : Plan)
    (trusted : List VerifiedApproval := []) : ApplyResult :=
  match journal.find? (fun j => j.plan.id == p.id) with
  | some j => ⟨k, journal, if j.plan == p then .alreadyApplied else .inputConflict⟩
  | none => if p.expectedSnapshot != k.snapshot then ⟨k, journal, .predecessorConflict⟩
    else if authorized e p trusted && planValid k e p then ⟨p.candidate, ⟨p⟩ :: journal, .applied⟩
    else ⟨k, journal, .rejected⟩

structure SequenceResult where
  kb : KB
  journal : List JournalEntry
  outcomes : List ApplyOutcome
  deriving DecidableEq, Repr, Inhabited

def applySequence (k : KB) (e : Context) (journal : List JournalEntry)
    (trusted : List VerifiedApproval) : List Plan → SequenceResult
  | [] => ⟨k, journal, []⟩
  | p :: ps =>
      let a := applyPlan k { e with snapshot := k.snapshot } journal p trusted
      let rest := applySequence a.kb e a.journal trusted ps
      ⟨rest.kb, rest.journal, a.outcome :: rest.outcomes⟩

inductive ProposalStatus where
  | draft | proposed | approved | applied | verified | rejected
  deriving DecidableEq, Repr, Inhabited

structure Proposal where
  id : ProposalId
  revision : ProposalRevision
  target : Ref
  status : ProposalStatus
  actor : Option ActorId
  executor : Option ActorId
  acceptor : Option ActorId
  gates : List ReceiptId
  deriving DecidableEq, Repr, Inhabited

def legalTransition : ProposalStatus → ProposalStatus → Bool
  | .draft, .proposed | .proposed, .approved | .proposed, .rejected |
    .approved, .applied | .approved, .rejected | .applied, .verified => true
  | _, _ => false

def transition (k : KB) (e : Context) (p : Proposal) (target : ProposalStatus) : Bool :=
  legalTransition p.status target && p.id.val != "" && p.revision.val != "" &&
  identPresent p.actor && usableFor k e p.target &&
  p.gates.all (fun id => k.receipts.any (fun r => r.id == id && reusable k e p.target r)) &&
  (!(target == .approved || target == .applied || target == .verified) || !p.gates.isEmpty) &&
  (!(target == .applied || target == .verified) || identPresent p.executor) &&
  (target != .verified || (identPresent p.acceptor && p.executor != p.acceptor))

inductive HypothesisStatus where
  | supported | refuted | unk | open
  deriving DecidableEq, Repr, Inhabited

structure Hypothesis where
  text : String
  status : HypothesisStatus
  deriving DecidableEq, Repr, Inhabited

structure Investigation where
  checkedAgainst : String
  scopeAndLimits : String
  hypotheses : List Hypothesis
  deriving DecidableEq, Repr, Inhabited

/-- Structural incident completion is separate from factual claim admission. -/
def conclude (i : Investigation) : Bool :=
  nonblank i.checkedAgainst && nonblank i.scopeAndLimits &&
  i.hypotheses.all (fun h => nonblank h.text && h.status != .open)


inductive AuthoredStatus where
  | draft | proposed | accepted | rejected | landing | applied | verified
  | regressed | deferred | superseded
  deriving DecidableEq, Repr, Inhabited

inductive Profile where
  | modern | legacyLimited
  deriving DecidableEq, Repr, Inhabited

inductive GatePhase where
  | land | deploy | use
  deriving DecidableEq, Repr, Inhabited

inductive GateOutcome where
  | pass | fail | unk
  deriving DecidableEq, Repr, Inhabited

structure GateDefinition where
  id : GateId
  claim : String
  check : String
  when : GatePhase
  byActor : Option ActorId
  checker : Option CheckerId
  deriving DecidableEq, Repr, Inhabited

structure GateResult where
  definition : GateDefinition
  targetRevision : Option TargetRevision
  checker : Option CheckerId
  result : GateOutcome
  observedAt : Nat
  expiresAt : Nat
  proposalRevision : Option ProposalRevision
  environment : String
  scope : String
  evidenceRefs : List String
  actor : Option ActorId
  deriving DecidableEq, Repr, Inhabited

structure AuthoredReplacement where
  id : ProposalId
  supersededBy : Option ProposalId
  deriving DecidableEq, Repr, Inhabited

structure AuthoredLanded where
  reference : String
  targetRevision : TargetRevision
  deriving DecidableEq, Repr, Inhabited

structure AuthoredProposal where
  status : AuthoredStatus
  profile : Profile
  researchPresent : Bool
  alternativesCount : Nat
  targetRevision : Option TargetRevision
  gateDefinitions : List GateDefinition
  gateResults : List GateResult
  actor : Option ActorId
  acceptor : Option ActorId
  executor : Option ActorId
  verifier : Option ActorId
  landedRefs : List String
  regressionNote : String
  id : ProposalId
  supersededBy : Option ProposalId
  proposals : List AuthoredReplacement
  acceptedRevision : Option ProposalRevision
  proposalRevision : Option ProposalRevision
  environment : String
  scope : String
  resolvedLanded : List AuthoredLanded
  deriving DecidableEq, Repr, Inhabited

def gateDefinitionValid (g : GateDefinition) : Bool :=
  nonblank g.id.val && nonblank g.claim && nonblank g.check && identPresent g.byActor
def gatePassed (p : AuthoredProposal) (now : Nat) (g : GateDefinition) : Bool :=
  gateDefinitionValid g && identPresent p.targetRevision && identPresent p.proposalRevision &&
  nonblank p.environment && nonblank p.scope &&
  match p.gateResults.reverse.find? (fun r =>
      r.definition == g && r.targetRevision == p.targetRevision &&
      r.proposalRevision == p.proposalRevision && r.environment == p.environment && r.scope == p.scope &&
      identPresent r.checker && (g.checker.isNone || r.checker == g.checker) && r.observedAt ≤ now) with
  | some r => r.result == .pass && now ≤ r.expiresAt && identPresent r.actor &&
      !r.evidenceRefs.isEmpty && r.evidenceRefs.all nonblank
  | none => false
def authoredLegal (a b : AuthoredStatus) : Bool :=
  (b == .superseded && a != b) || match a, b with
  | .draft, .proposed | .proposed, .draft | .proposed, .accepted | .proposed, .rejected |
    .accepted, .landing | .accepted, .deferred | .landing, .applied |
    .applied, .verified | .applied, .regressed | .verified, .regressed => true
  | _, _ => false
def authoredReady (p : AuthoredProposal) : Bool :=
  p.researchPresent && p.alternativesCount ≥ 2 && !p.gateDefinitions.isEmpty &&
  unique (p.gateDefinitions.map (·.id)) && p.gateDefinitions.all gateDefinitionValid
def needsReadiness (s : AuthoredStatus) : Bool :=
  s == .proposed || s == .accepted || s == .landing || s == .applied || s == .verified
def hasPhase (p : AuthoredProposal) (phase : GatePhase) : Bool :=
  p.gateDefinitions.any (fun g => g.when == phase)
def replacementChain (proposals : List AuthoredReplacement) : Nat → List ProposalId → ProposalId → Bool
  | 0, _, _ => false
  | n + 1, seen, id =>
      if seen.contains id then false else
      match proposals.find? (fun p => p.id == id) with
      | none => false
      | some p => match p.supersededBy with
        | none => true
        | some next => replacementChain proposals n (id :: seen) next
def replacementValid (p : AuthoredProposal) : Bool :=
  unique (p.proposals.map (·.id)) && p.proposals.any (fun q => q.id == p.id) &&
  match p.supersededBy with
  | none => false
  | some next => replacementChain p.proposals (p.proposals.length + 1) [p.id] next

def authoredCandidateValid (p : AuthoredProposal) (target : AuthoredStatus) (now : Nat) : Bool :=
  (!(target == .accepted || target == .landing || target == .applied || target == .verified) ||
    (identPresent p.acceptedRevision && p.acceptedRevision == p.proposalRevision)) &&
  (target != .superseded || replacementValid p) &&
  (!(target == .accepted || target == .rejected || target == .landing || target == .applied) || identPresent p.actor) &&
  (p.profile == .legacyLimited || !needsReadiness target || authoredReady p) &&
  (!(target == .accepted || target == .landing || target == .applied || target == .verified) || identPresent p.acceptor) &&
  (!(target == .landing || target == .applied || target == .verified) || identPresent p.executor) &&
  (!(target == .applied || target == .verified) || (!p.landedRefs.isEmpty && p.landedRefs.all nonblank &&
    p.landedRefs.all (fun ref => p.resolvedLanded.any (fun resolved => resolved.reference == ref)) &&
    p.resolvedLanded.any (fun resolved => p.landedRefs.contains resolved.reference && some resolved.targetRevision == p.targetRevision))) &&
  (target != .applied || (hasPhase p .land &&
    (p.gateDefinitions.filter (fun g => g.when == .land)).all (gatePassed p now))) &&
  (target != .verified || (hasPhase p .deploy && hasPhase p .use && p.gateDefinitions.all (gatePassed p now))) &&
  (target != .regressed || nonblank p.regressionNote)

def authoredTransition (p : AuthoredProposal) (target : AuthoredStatus) (now : Nat) : Bool :=
  authoredLegal p.status target && authoredCandidateValid p target now

theorem authored_transition_candidate (p : AuthoredProposal) (target : AuthoredStatus) (now : Nat) :
    authoredTransition p target now = (authoredLegal p.status target && authoredCandidateValid p target now) := rfl


end Kctx
