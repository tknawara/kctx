"""Native Click run capture and provenance commands."""

import click

from kctx.cli.context import CliState
from kctx.cli.help import RichCommand, RichGroup
from kctx.cli.result import Reply
from kctx.cli.values import decode, many, optional
from kctx.codecs.records import (
    encode_coverage_entry,
    encode_observation,
    encode_run_checkpoint,
    encode_run_manifest,
    encode_run_receipt,
    encode_run_resume,
)
from kctx.domain.capture import CoveragePolicy
from kctx.domain.ids import AssetId, ObservationId, RunId, SourceRevision
from kctx.domain.vocabulary import (
    CoverageOutcome,
    ObservationRole,
    ObservationStatus,
    ObservationSystem,
    Readiness,
    RunMode,
)
from kctx.services import runs


@click.group(cls=RichGroup)
def run() -> None:
    """Create durable task runs."""


@run.command("new")
@click.option("--project", required=True)
@click.option("--mode", type=click.Choice([mode.value for mode in RunMode]), required=True)
@click.option("--task", required=True)
@click.pass_obj
def new_run(state: CliState, project: str, mode: str, task: str) -> Reply:
    return Reply(
        encode_run_manifest(
            runs.new_run(
                state.root,
                project=project,
                mode=decode("mode", mode, RunMode),
                task=task,
            )
        )
    )


@click.command(cls=RichCommand)
@click.argument("run")
@click.option("--system", required=True)
@click.option("--locator", required=True)
@click.option("--asset")
@click.option("--revision")
@click.option("--role", default="note")
@click.option("--status", default="ok")
@click.option("--cmd", "observed_command")
@click.option("--environment")
@click.option("--evidence")
@click.option("--note")
@click.option(
    "--derived-from", multiple=True, help="Observation ID whose evidence this derives from."
)
@click.pass_obj
def observe(
    state: CliState,
    run: str,
    system: str,
    locator: str,
    asset: str | None,
    revision: str | None,
    role: str,
    status: str,
    observed_command: str | None,
    environment: str | None,
    evidence: str | None,
    note: str | None,
    derived_from: tuple[str, ...],
) -> Reply:
    """Capture an observation with exact provenance."""
    return Reply(
        encode_observation(
            runs.add_observation(
                state.root,
                decode("run", run, RunId),
                system=decode("system", system, ObservationSystem),
                locator=locator,
                asset=optional("asset", asset, AssetId),
                revision=optional("revision", revision, SourceRevision),
                role=decode("role", role, ObservationRole),
                status=decode("status", status, ObservationStatus),
                command=observed_command,
                environment=environment,
                evidence=evidence,
                note=note,
                derived_from=many("derived_from", derived_from, ObservationId),
            )
        )
    )


@click.command(cls=RichCommand)
@click.argument("run")
@click.option("--item", required=True)
@click.option("--outcome", required=True)
@click.option("--evidence", multiple=True)
@click.option("--reason", default="")
@click.option(
    "--policy",
    type=click.Choice(["single-source", "independent-origins"]),
    default="single-source",
    help="Named evidence support policy.",
)
@click.pass_obj
def cover(
    state: CliState,
    run: str,
    item: str,
    outcome: str,
    evidence: tuple[str, ...],
    reason: str,
    policy: str,
) -> Reply:
    """Record coverage supported by observations."""
    return Reply(
        encode_coverage_entry(
            runs.cover(
                state.root,
                decode("run", run, RunId),
                item=item,
                outcome=decode("outcome", outcome, CoverageOutcome),
                evidence=many("evidence", evidence, ObservationId),
                reason=reason,
                policy=decode("policy", policy, CoveragePolicy),
            )
        )
    )


@click.command(cls=RichCommand)
@click.argument("run")
@click.option("--require", multiple=True)
@click.pass_obj
def check(state: CliState, run: str, require: tuple[str, ...]) -> Reply:
    """Assess run readiness."""
    receipt = runs.check(state.root, decode("run", run, RunId), require=require)
    code = {Readiness.READY: 0, Readiness.PARTIAL: 2, Readiness.BLOCKED: 3}[receipt.readiness]
    return Reply(encode_run_receipt(receipt), code)


@click.command(cls=RichCommand)
@click.argument("run")
@click.pass_obj
def resume(state: CliState, run: str) -> Reply:
    """Resume a run from its persisted receipt."""
    return Reply(encode_run_resume(runs.resume(state.root, decode("run", run, RunId))))


@click.command(cls=RichCommand)
@click.argument("run")
@click.option("--note", required=True)
@click.pass_obj
def checkpoint(state: CliState, run: str, note: str) -> Reply:
    """Persist a run checkpoint."""
    return Reply(
        encode_run_checkpoint(runs.checkpoint(state.root, decode("run", run, RunId), note=note))
    )


def register(root: click.Group) -> None:
    for command in (run, observe, cover, check, resume, checkpoint):
        root.add_command(command)
