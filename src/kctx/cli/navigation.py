"""Repository navigation and admission Click commands."""

import click

from kctx.cli.context import CliState
from kctx.cli.help import RichCommand
from kctx.cli.result import Reply
from kctx.cli.values import decode
from kctx.domain.targets import parse_use_target
from kctx.services import admit as admission
from kctx.services import backlinks, discovery, freshness
from kctx.services import context as context_service
from kctx.services import validate as validation


@click.command(cls=RichCommand)
@click.pass_obj
def validate(state: CliState) -> Reply:
    """Validate authored inventory, proposal and run records."""
    result = validation.validate(state.root)
    return Reply(validation.result_to_wire(result), 0 if result.ok else 1)


@click.command(cls=RichCommand)
@click.argument("ident")
@click.pass_obj
def home(state: CliState, ident: str) -> Reply:
    """Find an identifier's canonical home."""
    result = discovery.home(state.root, ident)
    return Reply(result, 0 if result["candidates"] else 2)


@click.command(cls=RichCommand)
@click.argument("ident")
@click.option("--depth", type=int, default=2)
@click.pass_obj
def context(state: CliState, ident: str, depth: int) -> Reply:
    """Gather authored context around an identifier."""
    return Reply(context_service.context(state.root, ident, depth=depth))


@click.command(cls=RichCommand)
@click.option("--project")
@click.option("--offline", is_flag=True, help="Use only offline freshness checks.")
@click.option(
    "--drain", is_flag=True, help="Touch and mark citations, then report remaining judgment items."
)
@click.argument("paths", nargs=-1)
@click.pass_obj
def stale(
    state: CliState, project: str | None, offline: bool, drain: bool, paths: tuple[str, ...]
) -> Reply:
    """Report stale evidence or drain citation maintenance."""
    if drain:
        result = freshness.drain(state.root, project=project, paths=list(paths) or None)
        code = (
            3 if not result["citations_available"] else (0 if result["total_remaining"] == 0 else 2)
        )
        return Reply(result, code, presentation="drain")
    return Reply(freshness.stale(state.root, project=project, offline=offline))


@click.command(cls=RichCommand)
@click.argument("pr_ref", required=False)
@click.option("--repo", help="Repository org/repo to sweep from its cursor to head.")
@click.option("--since", help="SHA or date; required for a repository without a cursor.")
@click.option("--dry-run", is_flag=True)
@click.pass_obj
def admit(
    state: CliState, pr_ref: str | None, repo: str | None, since: str | None, dry_run: bool
) -> Reply:
    """Admit a PR or sweep repository changes."""
    result = admission.admit(state.root, repo=repo, pr_ref=pr_ref, since=since, dry_run=dry_run)
    return Reply(result, result["exit_code"])


@click.command(cls=RichCommand)
@click.argument("text")
@click.pass_obj
def match(state: CliState, text: str) -> Reply:
    """Match incident signatures, investigations and tickets."""
    result = discovery.match(state.root, text)
    return Reply(
        result, 0 if result["signatures"] or result["investigations"] or result["ktlo"] else 2
    )


@click.command(cls=RichCommand)
@click.argument("ident")
@click.pass_obj
def timeline(state: CliState, ident: str) -> Reply:
    """Show an identifier's authored timeline."""
    return Reply(discovery.timeline(state.root, ident))


@click.command(cls=RichCommand)
@click.argument("target")
@click.pass_obj
def uses(state: CliState, target: str) -> Reply:
    """Find authored referrers to an exact target."""
    result = backlinks.uses(state.root, decode("target", target, parse_use_target))
    return Reply(result, 0 if result["referrers"] else 2)


def register(root: click.Group) -> None:
    for command in (validate, home, context, stale, admit, match, timeline, uses):
        root.add_command(command)
