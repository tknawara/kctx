"""Native Click commands for the immutable citation graph."""

import click

from kctx.cli.context import CliState
from kctx.cli.help import RichGroup
from kctx.cli.result import Reply
from kctx.domain.json import object_value
from kctx.graph import queries, sync
from kctx.graph.models import GraphNodeId


@click.group(cls=RichGroup)
def graph() -> None:
    """Inspect and synchronize the citation graph; files remain authoritative."""


@graph.command("sync")
@click.option("--rebuild", is_flag=True, help="Re-extract fully while retaining graph history.")
@click.option("--history", type=click.IntRange(1, 1000), metavar="N")
@click.pass_obj
def synchronize(state: CliState, rebuild: bool, history: int | None) -> Reply:
    """Extract tracked files and publish a complete graph generation."""
    return Reply(sync.sync(state.root, rebuild=rebuild, history=history))


@graph.command()
@click.pass_obj
def status(state: CliState) -> Reply:
    """Show synchronization state and node/edge counts."""
    return Reply(queries.status(state.root))


@graph.command()
@click.argument("target")
@click.option("--limit", type=click.IntRange(1, queries.MAX_QUERY_LIMIT), default=50)
@click.option("--include-illus", is_flag=True)
@click.pass_obj
def uses(state: CliState, target: str, limit: int, include_illus: bool) -> Reply:
    """Find direct inbound edges grouped by relationship."""
    result = queries.uses(
        GraphNodeId(target), kb_root=state.root, limit=limit, include_illus=include_illus
    )
    return Reply(result, 0 if result["total"] else 2)


@graph.command()
@click.argument("target")
@click.option("--depth", type=int, default=3)
@click.option("--rel", multiple=True, help="Restrict traversal to these relationship types.")
@click.option("--limit", type=click.IntRange(1, queries.MAX_QUERY_LIMIT), default=100)
@click.pass_obj
def impact(state: CliState, target: str, depth: int, rel: tuple[str, ...], limit: int) -> Reply:
    """Find transitive inbound dependents."""
    result = queries.impact(
        GraphNodeId(target),
        kb_root=state.root,
        depth=depth,
        rel=list(rel) if rel else None,
        limit=limit,
    )
    return Reply(result, 0 if result["total"] else 2)


@graph.command()
@click.argument("kb_sha_a")
@click.argument("kb_sha_b")
@click.option("--limit", type=click.IntRange(1, queries.MAX_QUERY_LIMIT), default=200)
@click.pass_obj
def diff(state: CliState, kb_sha_a: str, kb_sha_b: str, limit: int) -> Reply:
    """Compare edges at two immutable knowledge-base revisions."""
    return Reply(queries.diff(kb_sha_a, kb_sha_b, kb_root=state.root, limit=limit))


@graph.command()
@click.option("--sample", "sample_ids", multiple=True, help="Compare direct uses for an ID.")
@click.pass_obj
def check(state: CliState, sample_ids: tuple[str, ...]) -> Reply:
    """Compare exact graph bindings against authoritative files."""
    result = queries.check(
        state.root, sample_ids=[GraphNodeId(value) for value in sample_ids] if sample_ids else None
    )
    return Reply(result, 0 if object_value(result["parity"], "parity")["match"] else 2)


def register(root: click.Group) -> None:
    root.add_command(graph)
