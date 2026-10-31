"""Reviewed structured evidence examples shared with production qualification."""
from __future__ import annotations

from dataclasses import replace

from kctx.domain.ids import (
    AttestationId, CheckerId, ClaimId, ClaimRevision, DerivationId, ObservationId,
    OperationId, PolicyId, RuleVersion, SnapshotId,
    SourceId, SourceRevision, ContentId, ProjectId, ActorId,
)
from kctx.semantics import model as M
from kctx.semantics import wire

SCOPE = M.Scope(ProjectId("payments"), "")
REF = M.ClaimRef(ClaimId("limit"), ClaimRevision("r1"))
STATEMENT = M.Statement(M.Atomic(M.Atom("batch", "limit", ("500",))), SCOPE)
WITNESS = M.AttestWitness(AttestationId("attestation-1"))


def context(snapshot: str = "snapshot-1", now: int = 110) -> M.Context:
    return M.Context(SnapshotId(snapshot), M.SEMANTIC_VERSION, RuleVersion("core-2"),
                     CheckerId("kctx-2"), M.Policy(PolicyId("review-policy"), True, False, True, M.ttl_expire_after(10), (ActorId("reviewer-key"), ActorId("independent-reviewer"))),
                     now, SCOPE, "review", (M.SourceSelection(SourceId("repo:payments"), SourceRevision("commit-1"), ContentId("sha256:retained-bytes")),))


def valid_kb(snapshot: str = "snapshot-1") -> M.KB:
    observation = M.Observation(ObservationId("observation-1"), SourceId("repo:payments"), SourceRevision("commit-1"), ContentId("sha256:retained-bytes"), 100, M.ObsOutcome.OK)
    claim = M.Claim(REF.id, REF.rev, STATEMENT)
    attestation = M.Attestation(WITNESS.attestation, REF, observation.id, STATEMENT, ActorId("reviewer-key"))
    derivation = M.Derivation(DerivationId("derivation-1"), REF, WITNESS)
    return M.KB(SnapshotId(snapshot), (observation,), (claim,), (attestation,), (), (derivation,))


def plan() -> M.Plan:
    return M.Plan(OperationId("admit-1"), SnapshotId("snapshot-0"), valid_kb(),
                  M.Authority(ActorId("reviewer-key"), REF, "review", PolicyId("review-policy"), STATEMENT,
                              valid_kb(), valid_kb().claims, context("snapshot-0")), REF, WITNESS)


def wire_kb(snapshot: str = "snapshot-1") -> dict[str, object]:
    return wire.enc_kb(valid_kb(snapshot))


def wire_context(snapshot: str = "snapshot-1", now: int = 110) -> dict[str, object]:
    return wire.enc_context(context(snapshot, now))


def negative_kb() -> M.KB:
    kb = valid_kb()
    ref = M.ClaimRef(ClaimId("limit-negative"), ClaimRevision("r1"))
    statement = replace(STATEMENT, polarity=M.Polarity.NEGATIVE)
    observation = replace(kb.observations[0], id=ObservationId("observation-2"))
    attestation = M.Attestation(AttestationId("attestation-2"), ref, observation.id, statement, ActorId("independent-reviewer"))
    return replace(kb, observations=(*kb.observations, observation), claims=(*kb.claims, M.Claim(ref.id, ref.rev, statement)),
                   attestations=(*kb.attestations, attestation), derivations=(*kb.derivations,
                       M.Derivation(DerivationId("derivation-2"), ref, M.AttestWitness(attestation.id))))
