"""Explicit knowledge capture, approval, publication and pinned retrieval."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import click

from kctx.adapters.files.knowledge import load
from kctx.cli.context import CliState
from kctx.cli.help import RichGroup
from kctx.cli.result import Reply
from kctx.cli.values import optional
from kctx.config import Config
from kctx.domain.ids import (
    AuthorityKeyId,
    ContextId,
    PlanId,
    PolicyDigest,
    ReleaseId,
    SourceId,
    SourceRevision,
)
from kctx.domain.json import object_value, text
from kctx.errors import KctxError
from kctx.semantics.wire import dec_context, dec_ref
from kctx.semantics.workflow_wire import dec_named_context
from kctx.services.knowledge import KnowledgeEngine
from kctx.services.knowledge_models import Approval, CaptureKind


@contextmanager
def knowledge_engine(state: CliState) -> Iterator[KnowledgeEngine]:
    """Resolve configured authority and translate failures at the I/O edge."""
    try:
        config = Config.load()
        if config.knowledge_dir is None:
            raise KctxError("incomplete", "configure knowledge_dir in config.toml")
        anchor = (
            PolicyDigest(config.knowledge_policy_digest) if config.knowledge_policy_digest else None
        )
        yield KnowledgeEngine(state.root, config.knowledge_dir, anchor)
    except ValueError as exc:
        raise KctxError("malformed", str(exc)) from exc
    except FileNotFoundError as exc:
        raise KctxError("not-found", str(exc)) from exc
    except PermissionError as exc:
        raise KctxError("permission", str(exc)) from exc
    except OSError as exc:
        raise KctxError("conflict", str(exc)) from exc


@click.group(cls=RichGroup)
def knowledge() -> None:
    """Capture and publish approved canonical knowledge generations."""


@knowledge.command()
@click.option("--kind", required=True, type=click.Choice([kind.value for kind in CaptureKind]))
@click.option("--source", required=True)
@click.option("--revision", required=True)
@click.option("--file", required=True)
@click.option("--observed-at", type=int, required=True)
@click.pass_obj
def capture(
    state: CliState, kind: str, source: str, revision: str, file: str, observed_at: int
) -> Reply:
    """Retain exact source bytes without inferring prose truth."""
    with knowledge_engine(state) as engine:
        return Reply(
            engine.capture(
                CaptureKind(kind),
                SourceId(source),
                SourceRevision(revision),
                Path(file).read_bytes(),
                observed_at,
            ).wire()
        )


@knowledge.command()
@click.option("--candidate", required=True)
@click.option("--target-use", required=True)
@click.option("--now", type=int, required=True)
@click.pass_obj
def propose(state: CliState, candidate: str, target_use: str, now: int) -> Reply:
    """Validate an explicit candidate against the completed predecessor."""
    with knowledge_engine(state) as engine:
        return Reply(engine.propose(load(Path(candidate)), target_use, now).wire())


@knowledge.command()
@click.argument("plan")
@click.option("--private-key", required=True)
@click.option("--key-id", required=True)
@click.pass_obj
def sign(state: CliState, plan: str, private_key: str, key_id: str) -> Reply:
    """Create detached Ed25519 approval with an operator-held key."""
    with knowledge_engine(state) as engine:
        return Reply(engine.sign(PlanId(plan), Path(private_key), AuthorityKeyId(key_id)).wire())


@knowledge.command()
@click.argument("plan")
@click.option("--approval", required=True)
@click.pass_obj
def admit(state: CliState, plan: str, approval: str) -> Reply:
    """Publish exactly the signed candidate."""
    with knowledge_engine(state) as engine:
        return Reply(engine.admit(PlanId(plan), Approval.decode(load(Path(approval)))))


@knowledge.command()
@click.option("--release", required=True)
@click.option("--context", required=True)
@click.option("--key-id", required=True)
@click.pass_obj
def rollback(state: CliState, release: str, context: str, key_id: str) -> Reply:
    """Propose an authorized forward retained-snapshot selection."""
    with knowledge_engine(state) as engine:
        payload = load(Path(context))
        if set(payload) != {"contexts", "target_use"} or not isinstance(payload["contexts"], list):
            raise KctxError("malformed", "rollback requires contexts array and explicit target_use")
        return Reply(
            engine.rollback(
                ReleaseId(release),
                tuple(dec_named_context(value) for value in payload["contexts"]),
                AuthorityKeyId(key_id),
                target_use=text(payload["target_use"], "target_use"),
            ).wire()
        )


def query(
    state: CliState,
    request: str,
    release: str | None,
    limit: int = 20,
    continuation: str | None = None,
    *,
    explain: bool,
) -> Reply:
    with knowledge_engine(state) as engine:
        payload = load(Path(request))
        if set(payload) != {"context_id", "context", "claims"} or not isinstance(
            payload["claims"], list
        ):
            raise KctxError("malformed", "request requires context_id, context and claims array")
        context_id = ContextId(text(payload["context_id"], "context_id"))
        claims = tuple(dec_ref(object_value(value)) for value in payload["claims"])
        context = dec_context(payload["context"])
        release_id = optional("release", release, ReleaseId)
        if explain:
            if len(claims) != 1:
                raise KctxError("malformed", "explain requires one exact claim revision")
            return Reply(engine.explain(claims[0], context, release_id, context_id=context_id))
        cursor = load(Path(continuation)) if continuation is not None else None
        return Reply(
            engine.context(claims, context, limit, cursor, release_id, context_id=context_id)
        )


@knowledge.command()
@click.option("--release")
@click.pass_obj
def contexts(state: CliState, release: str | None) -> Reply:
    """Discover full authenticated named contexts in a pinned release."""
    with knowledge_engine(state) as engine:
        return Reply(engine.contexts(optional("release", release, ReleaseId)))


@knowledge.command()
@click.option(
    "--request", required=True, help="JSON with context_id, context and exact claim refs."
)
@click.option("--release")
@click.option("--limit", type=int, default=20)
@click.option("--continuation")
@click.pass_obj
def context(
    state: CliState, request: str, release: str | None, limit: int, continuation: str | None
) -> Reply:
    """Retrieve pinned knowledge context."""
    return query(state, request, release, limit, continuation, explain=False)


@knowledge.command()
@click.option(
    "--request", required=True, help="JSON with context_id, context and one exact claim ref."
)
@click.option("--release")
@click.pass_obj
def explain(state: CliState, request: str, release: str | None) -> Reply:
    """Explain the authority of an exact claim revision."""
    return query(state, request, release, explain=True)


@knowledge.command()
@click.pass_obj
def recover(state: CliState) -> Reply:
    """Resume durable authenticated operations."""
    with knowledge_engine(state) as engine:
        return Reply(engine.recover())


@knowledge.command()
@click.option("--source")
@click.option("--apply", is_flag=True)
@click.option("--rollback")
@click.option("--restore-to")
@click.option("--migration")
@click.pass_obj
def migrate(
    state: CliState,
    source: str | None,
    apply: bool,
    rollback: str | None,
    restore_to: str | None,
    migration: str | None,
) -> Reply:
    """Account, quarantine or stage legacy sources; never autoapprove."""
    with knowledge_engine(state) as engine:
        if restore_to is not None:
            if migration is None:
                raise KctxError("incomplete", "missing migration")
            return Reply(engine.restore_migration(PlanId(migration), Path(restore_to)))
        if source is None:
            raise KctxError("incomplete", "missing source")
        return Reply(engine.migrate(Path(source), apply, optional("rollback", rollback, PlanId)))


@knowledge.command()
@click.argument("destination")
@click.pass_obj
def backup(state: CliState, destination: str) -> Reply:
    """Back up retained knowledge state."""
    with knowledge_engine(state) as engine:
        return Reply(engine.backup(Path(destination)))


@knowledge.command()
@click.argument("source")
@click.pass_obj
def restore(state: CliState, source: str) -> Reply:
    """Restore retained knowledge state."""
    with knowledge_engine(state) as engine:
        return Reply(engine.restore(Path(source)))


def register(root: click.Group) -> None:
    root.add_command(knowledge)
