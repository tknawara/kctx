"""Exact Python twin of the proved schema-3 authored design workflow.

Design acceptance and implementation binding are separate judgments. Neither is
an Ed25519 knowledge approval or a proof of natural-language implementation truth.
"""

from dataclasses import replace

from kctx.domain.ids import ActorId
from kctx.semantics.model import AuthoredStatus
from kctx.semantics.workflow import (
    authored_candidate_problems,
    authored_candidate_valid,
    authored_edge,
)
from kctx.semantics.workflow_models import (
    DesignBindingCommand,
    DesignProposal,
    DesignReopenCommand,
    ImplementationBinding,
)

_ACTIVE = (
    AuthoredStatus.ACCEPTED,
    AuthoredStatus.LANDING,
    AuthoredStatus.APPLIED,
    AuthoredStatus.VERIFIED,
)
_FINAL = (AuthoredStatus.APPLIED, AuthoredStatus.VERIFIED)
_BINDABLE = (AuthoredStatus.ACCEPTED, AuthoredStatus.LANDING)


def implementation_binding_valid(
    proposal: DesignProposal, binding: ImplementationBinding, now: int
) -> bool:
    return (
        binding.design_revision == proposal.authored.proposal_revision
        and binding.design_revision == proposal.authored.accepted_revision
        and binding.source == proposal.target_source
        and bool(binding.actor.val.strip())
        and bool(binding.source.val.strip())
        and bool(binding.design_revision.val.strip())
        and bool(binding.target_revision.val.strip())
        and binding.observed_at <= now
    )


def implementation_bound(proposal: DesignProposal, now: int) -> bool:
    binding = proposal.binding
    return (
        binding is not None
        and implementation_binding_valid(proposal, binding, now)
        and binding.target_revision == proposal.authored.target_revision
    )


def design_candidate_valid(proposal: DesignProposal, target: AuthoredStatus, now: int) -> bool:
    return (
        authored_candidate_valid(proposal.authored, target, now)
        and (target not in _ACTIVE or bool(proposal.target_source.val.strip()))
        and (target not in _FINAL or implementation_bound(proposal, now))
    )


def design_candidate_problems(
    proposal: DesignProposal, target: AuthoredStatus, now: int
) -> tuple[str, ...]:
    problems = list(authored_candidate_problems(proposal.authored, target, now))
    if target in _ACTIVE and not proposal.target_source.val.strip():
        problems.append("known implementation source")
    if target in _FINAL and not implementation_bound(proposal, now):
        problems.append("implementation binding to the accepted design and current target")
    return tuple(problems)


def design_transition(proposal: DesignProposal, target: AuthoredStatus, now: int) -> bool:
    return authored_edge(proposal.authored.status, target) and design_candidate_valid(
        proposal, target, now
    )


def design_with_binding(proposal: DesignProposal, binding: ImplementationBinding) -> DesignProposal:
    return replace(
        proposal,
        authored=replace(
            proposal.authored,
            target_revision=binding.target_revision,
            landed_refs=(),
            resolved_landed=(),
        ),
        binding=binding,
    )


def bind_implementation(
    current: DesignProposal, command: DesignBindingCommand, now: int
) -> DesignProposal | None:
    if (
        current == command.expected
        and current.authored.status in _BINDABLE
        and design_candidate_valid(current, current.authored.status, now)
        and implementation_binding_valid(current, command.binding, now)
    ):
        return design_with_binding(current, command.binding)
    return None


def design_reopened(proposal: DesignProposal, actor: ActorId) -> DesignProposal:
    return replace(
        proposal,
        authored=replace(
            proposal.authored,
            status=AuthoredStatus.PROPOSED,
            actor=actor,
            accepted_revision=None,
            acceptor=None,
            executor=None,
            verifier=None,
            target_revision=None,
            landed_refs=(),
            resolved_landed=(),
        ),
        binding=None,
    )


def reopen_design(current: DesignProposal, command: DesignReopenCommand) -> DesignProposal | None:
    if (
        current == command.expected
        and current.authored.status in _BINDABLE
        and command.actor.val.strip()
        and command.reason.strip()
    ):
        return design_reopened(current, command.actor)
    return None
