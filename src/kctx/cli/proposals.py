"""Proposal Click commands and nominal service boundaries."""

from pathlib import Path

import click

from kctx.adapters.files.mutations import FileRevision
from kctx.cli.context import CliState
from kctx.cli.help import RichGroup
from kctx.cli.result import Reply
from kctx.cli.values import decode, many, optional
from kctx.codecs.gates import encode_gate_result
from kctx.codecs.proposals import encode_added, encode_listing, encode_shown, encode_updated
from kctx.domain.ids import GateId, ProposalId, SourceId, TargetRevision
from kctx.domain.vocabulary import (
    GateOutcome,
    ProposalKind,
    ProposalOrigin,
    ProposalStatus,
    ProposalType,
)
from kctx.errors import KctxError
from kctx.services import proposals


def relative_path(path: Path, root: Path) -> str:
    return str(path.relative_to(root) if path.is_absolute() else path)


@click.group(cls=RichGroup)
def proposal() -> None:
    """Author proposals and record revision-bound gates."""


@proposal.command("add")
@click.option("--kind", required=True)
@click.option("--origin", required=True)
@click.option("--type", "types", multiple=True)
@click.option("--title", required=True)
@click.option("--target", multiple=True)
@click.option("--context", required=True)
@click.option("--evidence", required=True)
@click.option("--change", required=True)
@click.option("--why", required=True)
@click.option("--research", default="")
@click.option("--alternatives", default="")
@click.option("--gates", default="", help="Markdown table or path to a file holding one.")
@click.option("--impact", default="")
@click.option("--plan", default="")
@click.option("--ref", "references", multiple=True)
@click.option("--project")
@click.option("--session", "source_session")
@click.option("--proposed-by")
@click.option("--requested-by")
@click.option("--force", is_flag=True)
@click.option("--target-revision")
@click.option("--target-source", help="Intended repository or local file; no revision required.")
@click.option("--environment")
@click.option("--scope")
@click.pass_obj
def add(
    state: CliState,
    kind: str,
    origin: str,
    types: tuple[str, ...],
    title: str,
    target: tuple[str, ...],
    context: str,
    evidence: str,
    change: str,
    why: str,
    research: str,
    alternatives: str,
    gates: str,
    impact: str,
    plan: str,
    references: tuple[str, ...],
    project: str | None,
    source_session: str | None,
    proposed_by: str | None,
    requested_by: str | None,
    force: bool,
    target_revision: str | None,
    target_source: str | None,
    environment: str | None,
    scope: str | None,
) -> Reply:
    decoded_types = many("type", types, ProposalType)
    proposal_type = decoded_types[0] if len(decoded_types) == 1 else decoded_types or None
    if gates and "\n" not in gates and "\r" not in gates:
        gates_path = Path(gates)
        try:
            if gates_path.is_file():
                gates = gates_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise KctxError("malformed", f"cannot read gates: {exc}") from exc
    root = state.root
    result = proposals.add(
        root,
        kind=decode("kind", kind, ProposalKind),
        origin=decode("origin", origin, ProposalOrigin),
        type=proposal_type,
        title=title,
        target=target,
        context=context,
        evidence=evidence,
        change=change,
        why=why,
        research=research,
        alternatives=alternatives,
        gates=gates,
        impact=impact,
        plan=plan,
        references=references,
        project=project,
        source_session=source_session,
        proposed_by=proposed_by,
        requested_by=requested_by,
        force=force,
        target_revision=optional("target_revision", target_revision, TargetRevision),
        target_source=optional("target_source", target_source, SourceId),
        environment=environment,
        scope=scope,
    )
    return Reply(
        encode_added(result), presentation="proposal-single", path=relative_path(result.path, root)
    )


@proposal.command("list")
@click.option("--status")
@click.option("--kind")
@click.option("--pending-gates", is_flag=True)
@click.pass_obj
def list_proposals(
    state: CliState, status: str | None, kind: str | None, pending_gates: bool
) -> Reply:
    entries = proposals.list_proposals(
        state.root,
        status=optional("status", status, ProposalStatus),
        kind=optional("kind", kind, ProposalKind),
        pending_gates=pending_gates,
    )
    return Reply([encode_listing(entry) for entry in entries], presentation="proposal-list")


@proposal.command("set")
@click.argument("id")
@click.option("--status")
@click.option("--by")
@click.option("--note")
@click.option("--superseded-by")
@click.option("--origin")
@click.option("--proposed-by")
@click.option("--requested-by")
@click.option("--swept-at")
@click.option("--landed", "landed_add", multiple=True)
@click.option("--target-revision")
@click.option("--target-source")
@click.option("--expected-revision", help="Proposal source revision returned by show.")
@click.option("--environment")
@click.option("--scope")
@click.pass_obj
def set_proposal(
    state: CliState,
    id: str,
    status: str | None,
    by: str | None,
    note: str | None,
    superseded_by: str | None,
    origin: str | None,
    proposed_by: str | None,
    requested_by: str | None,
    swept_at: str | None,
    landed_add: tuple[str, ...],
    target_revision: str | None,
    target_source: str | None,
    expected_revision: str | None,
    environment: str | None,
    scope: str | None,
) -> Reply:
    root = state.root
    proposal_id = decode("id", id, ProposalId)
    updated = proposals.set_status(
        root,
        proposal_id,
        status=optional("status", status, ProposalStatus),
        by=by,
        note=note,
        superseded_by=optional("superseded_by", superseded_by, ProposalId),
        origin=optional("origin", origin, ProposalOrigin),
        proposed_by=proposed_by,
        requested_by=requested_by,
        swept_at=swept_at,
        landed_add=landed_add or None,
        target_revision=optional("target_revision", target_revision, TargetRevision),
        target_source=optional("target_source", target_source, SourceId),
        expected_revision=optional("expected_revision", expected_revision, FileRevision),
        environment=environment,
        scope=scope,
    )
    path = relative_path(proposals.load(root, proposal_id).path, root) if not state.as_json else ""
    return Reply(encode_updated(updated), presentation="proposal-single", path=path)


@proposal.command("bind")
@click.argument("id")
@click.option("--target-revision", required=True)
@click.option("--by", required=True)
@click.option("--expected-revision")
@click.pass_obj
def bind(
    state: CliState,
    id: str,
    target_revision: str,
    by: str,
    expected_revision: str | None,
) -> Reply:
    """Bind accepted design to resolved implementation, clearing old landing refs."""
    result = proposals.bind(
        state.root,
        decode("id", id, ProposalId),
        target_revision=decode("target_revision", target_revision, TargetRevision),
        by=by,
        expected_revision=optional("expected_revision", expected_revision, FileRevision),
    )
    path = (
        relative_path(proposals.load(state.root, result.proposal.id).path, state.root)
        if not state.as_json
        else ""
    )
    return Reply(encode_updated(result), presentation="proposal-single", path=path)


@proposal.command("reopen")
@click.argument("id")
@click.option("--by", required=True)
@click.option("--note", required=True)
@click.option("--target-source", help="Required for workflow2 migration unless target can resolve.")
@click.option("--expected-revision")
@click.pass_obj
def reopen(
    state: CliState,
    id: str,
    by: str,
    note: str,
    target_source: str | None,
    expected_revision: str | None,
) -> Reply:
    """Explicitly discard accepted/landing approval and reopen design review."""
    result = proposals.reopen(
        state.root,
        decode("id", id, ProposalId),
        by=by,
        note=note,
        target_source=optional("target_source", target_source, SourceId),
        expected_revision=optional("expected_revision", expected_revision, FileRevision),
    )
    path = (
        relative_path(proposals.load(state.root, result.proposal.id).path, state.root)
        if not state.as_json
        else ""
    )
    return Reply(encode_updated(result), presentation="proposal-single", path=path)


@proposal.command("adopt")
@click.argument("id")
@click.option("--by", required=True)
@click.option("--note", required=True)
@click.option("--target-source", help="Required unless the old target can resolve.")
@click.option("--expected-revision")
@click.pass_obj
def adopt(
    state: CliState,
    id: str,
    by: str,
    note: str,
    target_source: str | None,
    expected_revision: str | None,
) -> Reply:
    """Explicitly migrate workflow2 draft/proposed intent; never reuse acceptance."""
    result = proposals.adopt(
        state.root,
        decode("id", id, ProposalId),
        by=by,
        note=note,
        target_source=optional("target_source", target_source, SourceId),
        expected_revision=optional("expected_revision", expected_revision, FileRevision),
    )
    path = (
        relative_path(proposals.load(state.root, result.proposal.id).path, state.root)
        if not state.as_json
        else ""
    )
    return Reply(encode_updated(result), presentation="proposal-single", path=path)


@proposal.command("gate")
@click.argument("id")
@click.argument("gate")
@click.option("--outcome", required=True, type=click.Choice(["pass", "fail", "unk"]))
@click.option("--evidence", required=True)
@click.option("--by")
@click.option("--rev", help="Repository evidence such as org/repo@<sha>, retained verbatim.")
@click.option("--target-revision")
@click.option("--checker", required=True)
@click.option("--expires-at", required=True, help="Inclusive UTC epoch-second expiry.")
@click.option("--expected-revision")
@click.option("--environment")
@click.option("--scope")
@click.pass_obj
def gate(
    state: CliState,
    id: str,
    gate: str,
    outcome: str,
    evidence: str,
    by: str | None,
    rev: str | None,
    target_revision: str | None,
    checker: str,
    expires_at: str,
    expected_revision: str | None,
    environment: str | None,
    scope: str | None,
) -> Reply:
    result = proposals.gate(
        state.root,
        decode("id", id, ProposalId),
        decode("gate", gate, GateId),
        outcome=decode("outcome", outcome, GateOutcome),
        evidence=evidence,
        by=by,
        repo_rev=rev,
        target_revision=optional("target_revision", target_revision, TargetRevision),
        checker=checker,
        expires_at=decode("expires_at", expires_at, int),
        expected_revision=optional("expected_revision", expected_revision, FileRevision),
        environment=environment,
        scope=scope,
    )
    return Reply(encode_gate_result(result))


@proposal.command("show")
@click.argument("id")
@click.pass_obj
def show(state: CliState, id: str) -> Reply:
    return Reply(encode_shown(proposals.show(state.root, decode("id", id, ProposalId))))


def register(root: click.Group) -> None:
    root.add_command(proposal)
