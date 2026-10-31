"""One native Click application for people, JSON consumers and stdio clients."""

import json
import sys
from collections.abc import Sequence

import click

from kctx.cli.context import CliState
from kctx.cli.help import RichGroup
from kctx.cli.rendering import render_diagnostic, render_text
from kctx.cli.result import Reply
from kctx.errors import KctxError


def _json_option(ctx: click.Context, _parameter: click.Parameter, value: bool) -> bool:
    ctx.ensure_object(CliState).as_json = value
    return value


def _color_option(ctx: click.Context, _parameter: click.Parameter, value: str) -> str:
    ctx.ensure_object(CliState).color = {"auto": None, "always": True, "never": False}[value]
    return value


@click.group(cls=RichGroup, context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    callback=_json_option,
    help="Emit machine-readable JSON; diagnostics never mix with result text.",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Show diagnostic events on stderr; full JSONL logs are retained.",
)
@click.option(
    "--color",
    type=click.Choice(["auto", "always", "never"]),
    default="auto",
    callback=_color_option,
    help="Human output colors. Auto honors NO_COLOR and each stream's TTY.",
)
@click.pass_obj
def cli(state: CliState, as_json: bool, verbose: bool, color: str) -> None:
    """Retain evidence, admit scoped knowledge, and retrieve exact generations.

    Citations, authored workflows, native Dolt queries, and the agent protocol
    share this application. Locations come only from config.toml.
    """
    state.as_json = as_json
    state.verbose = verbose
    state.color = {"auto": None, "always": True, "never": False}[color]


def _finish(state: CliState, result: object, **_options: object) -> int:
    if not isinstance(result, Reply):
        raise TypeError("command did not return a typed Reply")
    if state.as_json:
        click.echo(json.dumps(result.payload, ensure_ascii=False, allow_nan=False))
    else:
        render_text(result, color=state.color)
    return result.code


cli.result_callback()(click.pass_obj(_finish))


@cli.command()
@click.pass_context
def serve(ctx: click.Context) -> None:
    """Serve the versioned JSON-RPC engine over newline-delimited stdio."""
    from kctx.engine import serve as serve_engine

    state = ctx.ensure_object(CliState)
    ctx.exit(serve_engine(state.root, sys.stdin.buffer, sys.stdout))


def _register() -> None:
    from kctx.citations import cli as citations
    from kctx.cli import incidents, inventory, knowledge, logs, navigation, proposals, runs
    from kctx.graph import cli_graph

    for module in (
        inventory,
        proposals,
        runs,
        incidents,
        navigation,
        knowledge,
        citations,
        cli_graph,
        logs,
    ):
        module.register(cli)


_register()


def _error(error: KctxError, state: CliState) -> int:
    if state.protocol_mode:
        from kctx.engine.protocol import error as protocol_error

        click.echo(
            json.dumps(
                protocol_error(-32000, "Engine startup failed", failure=error), allow_nan=False
            )
        )
    elif state.as_json:
        click.echo(
            json.dumps(
                {
                    "schema_version": 1,
                    "error": error.category,
                    "message": error.message,
                    "diagnostics": [error.diagnostic.to_wire()],
                },
                ensure_ascii=False,
                allow_nan=False,
            )
        )
    else:
        render_diagnostic(error.diagnostic, color=state.color)
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    state = CliState()
    try:
        result: object = cli.main(
            args=arguments, prog_name="kctx", standalone_mode=False, obj=state
        )
        return result if isinstance(result, int) else 0
    except click.ClickException as error:
        # A root parsing error can occur before option callbacks run. Ask Click
        # itself to recover global mode flags, without reinterpreting values in
        # a subcommand or scanning tokens that may contain literal '--json'.
        if not state.as_json:
            with cli.make_context(
                "kctx", arguments, obj=state, resilient_parsing=True, ignore_unknown_options=True
            ) as context:
                state.as_json = context.params.get("as_json") is True
        help_text = (
            f"Run {error.ctx.command_path} --help for accepted arguments."
            if isinstance(error, click.UsageError) and error.ctx is not None
            else "Run kctx --help for accepted arguments."
        )
        return _error(KctxError("malformed", error.format_message(), help=help_text), state)
    except KctxError as error:
        return _error(error, state)
    except FileNotFoundError as error:
        return _error(KctxError("not-found", str(error)), state)
    except PermissionError as error:
        return _error(KctxError("permission", str(error)), state)
    except click.Abort:
        return _error(
            KctxError("incomplete", "operation interrupted; inspect durable state before retrying"),
            state,
        )
    except BrokenPipeError:
        return 1
