import Kctx.DesignWorkflow

set_option autoImplicit false
set_option maxHeartbeats 1600000
namespace Kctx.DesignWorkflowExamples

/-- These are concrete synthetic adapter outputs, not claims about an external
repository. All gate/context/freshness checks still run through the real predicates. -/
def designer : ActorId := ⟨"designer", by decide⟩
def reviewer : ActorId := ⟨"reviewer", by decide⟩
def implementer : ActorId := ⟨"implementer", by decide⟩
def source : SourceId := ⟨"local:synthetic-project", by decide⟩
def target : TargetRevision := ⟨"local:synthetic-tree-1", by decide⟩
def secondTarget : TargetRevision := ⟨"local:synthetic-tree-2", by decide⟩
def revision : ProposalRevision := ⟨"design:1", by decide⟩
def checker : CheckerId := ⟨"synthetic-checker", by decide⟩

def landGate : GateDefinition :=
  ⟨⟨"land", by decide⟩, "implementation matches the accepted design", "check local tree",
    .land, some reviewer, some checker⟩
def deployGate : GateDefinition :=
  ⟨⟨"deploy", by decide⟩, "implementation deploys in the named environment", "check local deployment",
    .deploy, some reviewer, some checker⟩
def useGate : GateDefinition :=
  ⟨⟨"use", by decide⟩, "implementation satisfies the intended use", "check local use",
    .use, some reviewer, some checker⟩

def accepted : DesignProposal :=
  { authored :=
      { status := .accepted
        profile := .modern
        researchPresent := true
        alternativesCount := 2
        targetRevision := none
        gateDefinitions := [landGate, deployGate, useGate]
        gateResults := []
        actor := some designer
        acceptor := some reviewer
        executor := none
        verifier := none
        landedRefs := []
        regressionNote := ""
        id := ⟨"synthetic-design", by decide⟩
        supersededBy := none
        proposals := []
        acceptedRevision := some revision
        proposalRevision := some revision
        environment := "local-synthetic"
        scope := "synthetic-project/intended-use"
        resolvedLanded := [] }
    targetSource := source
    binding := none }

def binding : ImplementationBinding := ⟨revision, source, target, implementer, 10⟩
def bound : DesignProposal := designWithBinding accepted binding

def checkedResult (gate : GateDefinition) : GateResult :=
  ⟨gate, some target, some checker, .pass, 10, 100, some revision,
    accepted.authored.environment, accepted.authored.scope, ["local:synthetic-check-record"], some reviewer⟩

def landing : DesignProposal :=
  { bound with
      authored := { bound.authored with
        status := .landing
        executor := some implementer
        gateResults := [checkedResult landGate]
        landedRefs := ["local:synthetic-landing"]
        resolvedLanded := [⟨"local:synthetic-landing", target⟩] } }

def applied : DesignProposal :=
  { landing with authored := { landing.authored with status := .applied } }

def verifiedCandidate : DesignProposal :=
  { applied with
      authored := { applied.authored with
        verifier := some reviewer
        gateResults := [checkedResult landGate, checkedResult deployGate, checkedResult useGate] } }

def verified : DesignProposal :=
  { verifiedCandidate with authored := { verifiedCandidate.authored with status := .verified } }

theorem accepted_without_implementation :
    designCandidateValid accepted .accepted 10 = true ∧ accepted.binding = none ∧
    accepted.authored.targetRevision = none ∧ implementationBound accepted 10 = false := by decide

theorem acceptance_before_implementation_transition :
    designTransition { accepted with authored := { accepted.authored with status := .proposed } }
      .accepted 10 = true := by decide

theorem binds_local_synthetic_target :
    bindImplementation accepted ⟨accepted, binding⟩ 10 = some bound ∧
    implementationBound bound 10 = true ∧ bound.authored.status = .accepted := by decide

theorem binding_alone_not_applied : designCandidateValid bound .applied 10 = false := by decide

theorem landing_before_gate_can_start :
    designTransition { bound with authored := { bound.authored with executor := some implementer } }
      .landing 10 = true := by decide

theorem checked_landing_can_apply : designTransition landing .applied 10 = true := by decide

theorem all_checked_phases_can_verify : designTransition verifiedCandidate .verified 10 = true := by decide

theorem landed_target_mismatch_rejected :
    designCandidateValid
      { landing with authored := { landing.authored with
          resolvedLanded := [⟨"local:synthetic-landing", secondTarget⟩] } }
      .applied 10 = false := by decide

def secondBinding : ImplementationBinding := { binding with targetRevision := secondTarget, observedAt := 11 }
def retargeted : DesignProposal := designWithBinding landing secondBinding

/-- Fresh landing references alone do not rescue a pass recorded for the old tree. -/
def retargetedWithLanding : DesignProposal :=
  { retargeted with authored := { retargeted.authored with
      landedRefs := ["local:second-landing"], resolvedLanded := [⟨"local:second-landing", secondTarget⟩] } }

theorem retarget_preserves_acceptance_and_history :
    bindImplementation landing ⟨landing, secondBinding⟩ 11 = some retargeted ∧
    retargeted.authored.acceptedRevision = accepted.authored.acceptedRevision ∧
    retargeted.authored.proposalRevision = accepted.authored.proposalRevision ∧
    retargeted.authored.gateResults = landing.authored.gateResults ∧
    retargeted.authored.landedRefs = [] ∧ retargeted.authored.resolvedLanded = [] := by decide

theorem retarget_rejects_old_pass :
    designGateResultMatches retargetedWithLanding.authored 11 landGate (checkedResult landGate) = false ∧
    gatePassed retargetedWithLanding.authored 11 landGate = false ∧
    designCandidateValid retargetedWithLanding .applied 11 = false := by decide

theorem same_target_preserves_fresh_gate_history :
    gatePassed (designWithBinding landing binding).authored 11 landGate = true ∧
    (designWithBinding landing binding).authored.landedRefs = [] := by decide

theorem stale_command_rejected : bindImplementation bound ⟨accepted, binding⟩ 10 = none := by decide

theorem wrong_design_rejected :
    bindImplementation accepted ⟨accepted, { binding with designRevision := ⟨"other-design", by decide⟩ }⟩
      10 = none := by decide

theorem wrong_source_rejected :
    bindImplementation accepted ⟨accepted, { binding with source := ⟨"other-source", by decide⟩ }⟩
      10 = none := by decide

theorem future_binding_rejected :
    bindImplementation accepted ⟨accepted, { binding with observedAt := 11 }⟩ 10 = none := by decide

theorem blank_binding_actor_rejected :
    bindImplementation accepted ⟨accepted, { binding with actor := ⟨" ", by decide⟩ }⟩ 10 = none := by decide

/-- The source adapter recomputes the design digest when material changes. -/
def edited : DesignProposal :=
  { accepted with
      authored := { accepted.authored with
        environment := "local-synthetic-edited"
        proposalRevision := some ⟨"design:2", by decide⟩ } }

def reopenCommand : DesignReopenCommand := ⟨edited, designer, "revise the intended environment"⟩
def reopened : DesignProposal := designReopened edited designer

def newlyAcceptedCandidate : DesignProposal :=
  { reopened with authored := { reopened.authored with
      acceptedRevision := reopened.authored.proposalRevision, acceptor := some reviewer } }

theorem material_edit_invalidates_acceptance : designCandidateValid edited .accepted 10 = false := by decide

theorem invalid_edited_acceptance_can_reopen :
    reopenDesign edited reopenCommand = some reopened ∧
    reopened.authored.environment = edited.authored.environment ∧
    reopened.authored.proposalRevision = edited.authored.proposalRevision ∧
    reopened.authored.acceptedRevision = none ∧ reopened.binding = none := by decide

theorem edited_design_can_receive_new_acceptance :
    designTransition newlyAcceptedCandidate .accepted 10 = true ∧
    newlyAcceptedCandidate.authored.targetRevision = none ∧ newlyAcceptedCandidate.binding = none := by decide

theorem reopen_keeps_historical_gates :
    reopenDesign landing ⟨landing, designer, "revise the accepted design"⟩ =
      some (designReopened landing designer) ∧
    (designReopened landing designer).authored.gateResults = [checkedResult landGate] ∧
    implementationBound (designReopened landing designer) 10 = false := by decide

theorem stale_reopen_rejected :
    reopenDesign edited ⟨accepted, designer, "revise design"⟩ = none := by decide

theorem finalized_history_cannot_reopen_or_retarget :
    reopenDesign applied ⟨applied, designer, "rewrite applied history"⟩ = none ∧
    reopenDesign verified ⟨verified, designer, "rewrite verified history"⟩ = none ∧
    bindImplementation applied ⟨applied, secondBinding⟩ 11 = none ∧
    bindImplementation verified ⟨verified, secondBinding⟩ 11 = none := by decide

end Kctx.DesignWorkflowExamples
