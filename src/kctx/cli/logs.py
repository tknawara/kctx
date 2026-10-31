"""Native Click access to recorded invocation events."""

import click

from kctx.cli.help import RichCommand
from kctx.cli.result import Reply
from kctx.observability import read_events


@click.command(cls=RichCommand)
@click.option("--run", "run_id", help="Read a specific run; defaults to the most recent.")
@click.option(
    "--last",
    "last_n",
    type=click.IntRange(min=1),
    metavar="N",
    help="Return only the last N events.",
)
def logs(run_id: str | None, last_n: int | None) -> Reply:
    """Show structured events for a recent kctx invocation."""
    events = read_events(run_id=run_id)
    if last_n is not None:
        events = events[-last_n:]
    return Reply(events, 0 if events else 2, presentation="logs")


def register(root: click.Group) -> None:
    root.add_command(logs)
