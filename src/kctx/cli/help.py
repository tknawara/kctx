"""Click owns grammar and layout; Rich styles only the human help surface."""

import io
import sys

import click
from rich.console import Console
from rich.text import Text

from kctx.cli.context import CliState
from kctx.presentation import color_enabled


def _styled_help(context: click.Context, text: str) -> str:
    state = context.find_object(CliState)
    choice = state.color if state is not None else None
    enabled = color_enabled(sys.stdout, choice)
    if not enabled:
        return text
    buffer = io.StringIO()
    output = Console(
        file=buffer,
        force_terminal=True,
        width=context.terminal_width or 80,
        markup=False,
        highlight=False,
    )
    for line in text.splitlines():
        rendered = Text(line)
        if line.startswith("Usage:") or (line and not line.startswith(" ") and line.endswith(":")):
            rendered.stylize("bold cyan")
        else:
            rendered.highlight_regex(r"(?<!\w)--?[a-zA-Z][a-zA-Z0-9-]*", "cyan")
        output.print(rendered, soft_wrap=True)
    return buffer.getvalue().rstrip("\n")


class RichCommand(click.Command):
    def get_help(self, ctx: click.Context) -> str:
        return _styled_help(ctx, super().get_help(ctx))

    def invoke(self, ctx: click.Context) -> object:
        from kctx.cli.result import Reply
        from kctx.errors import KctxError
        from kctx.observability import get_logger

        state = ctx.find_object(CliState)
        if state is not None:
            state.protocol_mode = ctx.command_path == "kctx serve"
            state.start_logging(machine=state.protocol_mode)
        if ctx.command_path == "kctx logs":
            return super().invoke(ctx)
        log = get_logger()
        log.info("command.start", command=ctx.command_path)
        try:
            result: object = super().invoke(ctx)
        except click.exceptions.Exit as exit_request:
            log.info("command.end", command=ctx.command_path, exit_code=exit_request.exit_code)
            raise
        except Exception as failure:
            log.error(
                "command.failed",
                command=ctx.command_path,
                category=failure.category
                if isinstance(failure, KctxError)
                else type(failure).__name__,
            )
            raise
        log.info(
            "command.end",
            command=ctx.command_path,
            exit_code=result.code if isinstance(result, Reply) else 0,
        )
        return result


class RichGroup(click.Group):
    command_class = RichCommand
    group_class = type

    def get_help(self, ctx: click.Context) -> str:
        return _styled_help(ctx, super().get_help(ctx))
