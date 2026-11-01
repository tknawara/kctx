"""Incident workflow Click commands and nominal identity boundaries."""

import click

from kctx.cli.context import CliState
from kctx.cli.help import RichCommand, RichGroup
from kctx.cli.result import Reply
from kctx.cli.values import decode, many, optional
from kctx.domain.ids import AssetId, InvestigationId, OperationId, SignatureId
from kctx.domain.targets import parse_fix_reference
from kctx.domain.vocabulary import CorrectionKind, InvestigationTrigger, SignatureStatus
from kctx.services import corrections, dossiers, investigations, ktlo, signatures


@click.group(cls=RichGroup)
def dossier() -> None:
    """Create and archive asset dossiers."""


@dossier.command("new")
@click.argument("asset")
@click.pass_obj
def dossier_new(state: CliState, asset: str) -> Reply:
    return Reply(dossiers.result_to_wire(dossiers.new(state.root, decode("asset", asset, AssetId))))


@dossier.command("archive")
@click.argument("asset")
@click.option("--force", is_flag=True)
@click.pass_obj
def dossier_archive(state: CliState, asset: str, force: bool) -> Reply:
    return Reply(
        dossiers.result_to_wire(
            dossiers.archive(state.root, decode("asset", asset, AssetId), force=force)
        )
    )


@click.group("ktlo", cls=RichGroup)
def ktlo_group() -> None:
    """Capture and promote operational tickets."""


@ktlo_group.command("new")
@click.argument("ticket")
@click.option("--title", required=True)
@click.option("--asset", "assets", multiple=True)
@click.pass_obj
def ktlo_new(state: CliState, ticket: str, title: str, assets: tuple[str, ...]) -> Reply:
    return Reply(
        ktlo.result_to_wire(
            ktlo.new(
                state.root,
                ticket=decode("ticket", ticket, ktlo.normalize_ticket),
                title=title,
                assets=many("assets", assets, AssetId),
            )
        )
    )


@ktlo_group.command("promote")
@click.argument("ticket")
@click.argument("project")
@click.pass_obj
def ktlo_promote(state: CliState, ticket: str, project: str) -> Reply:
    return Reply(
        ktlo.result_to_wire(
            ktlo.promote(state.root, decode("ticket", ticket, ktlo.normalize_ticket), project)
        )
    )


@click.group(cls=RichGroup)
def inv() -> None:
    """Track operational investigations."""


@inv.command("new")
@click.argument("slug")
@click.option("--trigger", required=True)
@click.option("--title")
@click.option("--ticket", "tickets", multiple=True)
@click.option("--alert", "alerts", multiple=True)
@click.option("--asset", "assets", multiple=True)
@click.option("--window", "windows", multiple=True)
@click.option("--impact-summary", default="")
@click.option("--created", help="Historical creation date (YYYY-MM-DD); defaults to today.")
@click.pass_obj
def inv_new(
    state: CliState,
    slug: str,
    trigger: str,
    title: str | None,
    tickets: tuple[str, ...],
    alerts: tuple[str, ...],
    assets: tuple[str, ...],
    windows: tuple[str, ...],
    impact_summary: str,
    created: str | None,
) -> Reply:
    return Reply(
        investigations.result_to_wire(
            investigations.new(
                state.root,
                slug,
                trigger=decode("trigger", trigger, InvestigationTrigger),
                title=title,
                tickets=many("tickets", tickets, ktlo.normalize_ticket),
                alerts=many("alerts", alerts, AssetId),
                assets=many("assets", assets, AssetId),
                windows=windows,
                impact_summary=impact_summary,
                created=created,
            )
        )
    )


@inv.command("list")
@click.option("--open", "open_only", is_flag=True)
@click.option("--asset")
@click.pass_obj
def inv_list(state: CliState, open_only: bool, asset: str | None) -> Reply:
    return Reply(
        [
            investigations.frontmatter_to_wire(entry)
            for entry in investigations.list_investigations(
                state.root,
                open_only=open_only,
                asset=optional("asset", asset, AssetId),
            )
        ]
    )


@inv.command("show")
@click.argument("id")
@click.pass_obj
def inv_show(state: CliState, id: str) -> Reply:
    return Reply(
        investigations.result_to_wire(
            investigations.show(state.root, decode("id", id, InvestigationId))
        )
    )


@inv.command("conclude")
@click.argument("id")
@click.pass_obj
def inv_conclude(state: CliState, id: str) -> Reply:
    return Reply(
        investigations.result_to_wire(
            investigations.conclude(state.root, decode("id", id, InvestigationId))
        )
    )


@inv.command("promote")
@click.argument("id")
@click.argument("project")
@click.pass_obj
def inv_promote(state: CliState, id: str, project: str) -> Reply:
    return Reply(
        investigations.result_to_wire(
            investigations.promote(state.root, decode("id", id, InvestigationId), project)
        )
    )


@click.group(cls=RichGroup)
def sig() -> None:
    """Author and inspect incident signatures."""


@sig.command("new")
@click.argument("slug")
@click.option("--title")
@click.option("--match", multiple=True)
@click.option("--match-where", default="")
@click.option("--asset", "assets", multiple=True)
@click.option("--owner-group")
@click.option("--status", default="suspected")
@click.option("--first-seen")
@click.option("--last-seen")
@click.option("--workaround", default="")
@click.option("--fix", multiple=True, help="Proposal ID, ev:<home>/<stem>, or pinned code locator.")
@click.option("--fixed-at")
@click.option("--verified-at")
@click.option("--ttl")
@click.pass_obj
def sig_new(
    state: CliState,
    slug: str,
    title: str | None,
    match: tuple[str, ...],
    match_where: str,
    assets: tuple[str, ...],
    owner_group: str | None,
    status: str,
    first_seen: str | None,
    last_seen: str | None,
    workaround: str,
    fix: tuple[str, ...],
    fixed_at: str | None,
    verified_at: str | None,
    ttl: str | None,
) -> Reply:
    return Reply(
        signatures.result_to_wire(
            signatures.new(
                state.root,
                slug,
                title=title,
                match=match,
                match_where=match_where,
                assets=many("assets", assets, AssetId),
                owner_group=owner_group,
                status=decode("status", status, SignatureStatus),
                first_seen=first_seen,
                last_seen=last_seen,
                workaround=workaround,
                fix=many("fix", fix, parse_fix_reference),
                fixed_at=fixed_at,
                verified_at=verified_at,
                ttl=ttl,
            )
        )
    )


@sig.command("list")
@click.pass_obj
def sig_list(state: CliState) -> Reply:
    return Reply(
        [signatures.frontmatter_to_wire(entry) for entry in signatures.list_signatures(state.root)]
    )


@sig.command("show")
@click.argument("id")
@click.pass_obj
def sig_show(state: CliState, id: str) -> Reply:
    return Reply(
        signatures.result_to_wire(signatures.show(state.root, decode("id", id, SignatureId)))
    )


@click.command(cls=RichCommand)
@click.argument("target")
@click.option("--reason", required=True)
@click.option("--kind", required=True, type=click.Choice(["retract", "dispute", "supersede"]))
@click.option("--by-replacement")
@click.option("--operation-id", help="Stable correction identity; retries must retain exact input.")
@click.pass_obj
def retract(
    state: CliState,
    target: str,
    reason: str,
    kind: str,
    by_replacement: str | None,
    operation_id: str | None,
) -> Reply:
    """Apply a durable correction and its review projections."""
    return Reply(
        corrections.result_to_wire(
            corrections.retract(
                state.root,
                decode("target", target, corrections.parse_correction_target),
                reason=reason,
                kind=decode("kind", kind, CorrectionKind),
                by_replacement=by_replacement,
                operation_id=optional("operation_id", operation_id, OperationId),
            )
        )
    )


@click.group(cls=RichGroup)
def correction() -> None:
    """Recover durable correction operations."""


@correction.command("recover")
@click.pass_obj
def correction_recover(state: CliState) -> Reply:
    return Reply(
        {
            "operations": [
                corrections.result_to_wire(result) for result in corrections.recover(state.root)
            ]
        }
    )


def register(root: click.Group) -> None:
    for command in (dossier, ktlo_group, inv, sig, retract, correction):
        root.add_command(command)
