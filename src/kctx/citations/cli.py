"""Native Click commands for constructing, checking, and rendering citations."""

import re

import click

from kctx.citations.code import make_code
from kctx.citations.construction import KIND_SPECS, QUERY_ALIASES, make_other, make_proposal
from kctx.citations.rendering import extract_cite_items, render_one
from kctx.citations.scan import check_to_wire, run_check, run_stale, stale_to_wire
from kctx.cli.context import CliState
from kctx.cli.help import RichCommand, RichGroup
from kctx.cli.result import Reply
from kctx.domain.ids import ProposalId
from kctx.errors import KctxError


def _parse_fields(tokens: tuple[str, ...]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in tokens:
        if "=" not in token:
            raise KctxError("malformed", f"expected key=value, got {token!r}")
        key, value = token.split("=", 1)
        if not re.fullmatch(r"\w+", key):
            raise KctxError("malformed", f"invalid citation field name {key!r}")
        if key in fields:
            raise KctxError("malformed", f"duplicate citation field {key!r}")
        fields[key] = value
    return fields


@click.group(cls=RichGroup)
@click.option("--json", "as_json", is_flag=True, help="Emit structured JSON.")
@click.pass_obj
def cite(state: CliState, as_json: bool) -> None:
    """Construct, check, and render evidence citations."""
    if as_json:
        state.as_json = True


@cite.group()
def make() -> None:
    """Construct a citation of a known kind."""


@make.command("code")
@click.argument("repo")
@click.argument("path")
@click.argument("range")
@click.option("--sym")
@click.option("--rev")
@click.option("--ttl", default="14d", show_default=True)
@click.option("--allow-dirty", is_flag=True)
@click.option("--sens")
@click.option("--redact")
def code(
    repo: str,
    path: str,
    range: str,
    sym: str | None,
    rev: str | None,
    ttl: str,
    allow_dirty: bool,
    sens: str | None,
    redact: str | None,
) -> Reply:
    made = make_code(
        repo,
        path,
        range,
        sym=sym,
        rev=rev,
        ttl=ttl,
        allow_dirty=allow_dirty,
        sens=sens,
        redact=redact,
    )
    return Reply(made.to_wire(), presentation="cite-make")


def _field_command(kind: str) -> click.Command:
    @click.command(kind, cls=RichCommand)
    @click.argument("fields", nargs=-1)
    def construct(fields: tuple[str, ...]) -> Reply:
        values = _parse_fields(fields)
        if kind == "proposal":
            if not values.get("id"):
                raise KctxError("incomplete", "kind=proposal requires id=")
            made = make_proposal(ProposalId(values["id"]), ttl=values.get("ttl"))
        else:
            made = make_other(kind, values)
        return Reply(made.to_wire(), presentation="cite-make")

    construct.help = f"Construct a {kind} citation from key=value fields."
    return construct


for _kind in (*KIND_SPECS, *QUERY_ALIASES, "proposal"):
    make.add_command(_field_command(_kind))


@cite.command("check")
@click.argument("paths", nargs=-1)
@click.option("--line")
@click.option("--touch", is_flag=True)
@click.option("--touch-all", is_flag=True)
@click.option("--mark", is_flag=True)
def check(
    paths: tuple[str, ...], line: str | None, touch: bool, touch_all: bool, mark: bool
) -> Reply:
    """Check citations in files or an inline token."""
    checked = run_check(paths, inline_line=line, touch=touch, touch_all=touch_all, mark=mark)
    return Reply(check_to_wire(checked), checked["exit_code"])


@cite.command("stale")
@click.argument("paths", nargs=-1)
@click.option("--offline", is_flag=True)
def stale(paths: tuple[str, ...], offline: bool) -> Reply:
    """Find stale and due citations."""
    result = run_stale(paths, offline=offline)
    return Reply(stale_to_wire(result), result["exit_code"])


@cite.command("render")
@click.argument("target")
@click.option("--format", "fmt", type=click.Choice(("md", "slack", "plain")), default="plain")
@click.option("--audience", type=click.Choice(("internal", "tl", "external")), default="internal")
@click.option("--unredacted", is_flag=True)
@click.option("--check", "do_check", is_flag=True)
def render(target: str, fmt: str, audience: str, unredacted: bool, do_check: bool) -> Reply:
    """Render citation tokens for an audience."""
    rendered = [
        render_one(fields, fmt=fmt, audience=audience, unredacted=unredacted, do_check=do_check)
        for fields, _raw in extract_cite_items(target)
    ]
    return Reply({"rendered": rendered}, presentation="cite-render")


def register(root: click.Group) -> None:
    root.add_command(cite)
