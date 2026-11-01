"""Native Click inventory commands with nominal service boundaries."""

from pathlib import Path

import click

from kctx.adapters.files.knowledge import load
from kctx.cli.context import CliState
from kctx.cli.help import RichCommand, RichGroup
from kctx.cli.result import Reply
from kctx.cli.values import decode, many, optional
from kctx.codecs.records import encode_asset, encode_impact, encode_relationship
from kctx.domain.ids import AssetId, RelationshipId
from kctx.domain.targets import parse_evidence_address
from kctx.domain.vocabulary import AssetKind, Lifecycle, RelationshipStatus, RelationshipType
from kctx.services import inventory
from kctx.services.diff_impact import impact_diff


@click.group(cls=RichGroup)
def asset() -> None:
    """Create and inspect inventory assets."""


@asset.command("add")
@click.option("--kind", required=True)
@click.option("--name", required=True)
@click.option("--id", "ident")
@click.option("--alias", "aliases", multiple=True)
@click.option("--locator", default="")
@click.option("--owner", default="unknown")
@click.option("--owner-source", default="")
@click.option("--lifecycle", default="active")
@click.option("--inspect", default="")
@click.option("--project", "projects", multiple=True)
@click.option("--verified-at")
@click.option("--ttl")
@click.option("--notes", default="")
@click.pass_obj
def asset_add(
    state: CliState,
    kind: str,
    name: str,
    ident: str | None,
    aliases: tuple[str, ...],
    locator: str,
    owner: str,
    owner_source: str,
    lifecycle: str,
    inspect: str,
    projects: tuple[str, ...],
    verified_at: str | None,
    ttl: str | None,
    notes: str,
) -> Reply:
    return Reply(
        encode_asset(
            inventory.asset_add(
                state.root,
                kind=decode("kind", kind, AssetKind),
                name=name,
                id=optional("id", ident, AssetId),
                aliases=aliases,
                locator=locator,
                owner=owner,
                owner_source=owner_source,
                lifecycle=decode("lifecycle", lifecycle, Lifecycle),
                inspect=inspect,
                projects=projects,
                verified_at=verified_at,
                ttl=ttl,
                notes=notes,
            )
        )
    )


@asset.command("show")
@click.argument("ident")
@click.pass_obj
def asset_show(state: CliState, ident: str) -> Reply:
    return Reply(encode_asset(inventory.asset_show(state.root, ident)))


@asset.command("list")
@click.option("--kind")
@click.option("--project")
@click.pass_obj
def asset_list(state: CliState, kind: str | None, project: str | None) -> Reply:
    return Reply(
        [
            encode_asset(item)
            for item in inventory.asset_list(
                state.root,
                kind=optional("kind", kind, AssetKind),
                project=project,
            )
        ]
    )


@click.group(cls=RichGroup)
def rel() -> None:
    """Record inventory relationships."""


@rel.command("add")
@click.option("--type", "relationship_type", required=True)
@click.option("--from", "from_", required=True)
@click.option("--to", required=True)
@click.option("--id", "ident")
@click.option("--status", default="explicit")
@click.option("--evidence", multiple=True)
@click.option("--applicability", default="")
@click.pass_obj
def rel_add(
    state: CliState,
    relationship_type: str,
    from_: str,
    to: str,
    ident: str | None,
    status: str,
    evidence: tuple[str, ...],
    applicability: str,
) -> Reply:
    return Reply(
        encode_relationship(
            inventory.rel_add(
                state.root,
                type=decode("type", relationship_type, RelationshipType),
                from_=decode("from", from_, AssetId),
                to=decode("to", to, AssetId),
                id=optional("id", ident, RelationshipId),
                status=decode("status", status, RelationshipStatus),
                evidence=many("evidence", evidence, parse_evidence_address),
                applicability=applicability,
            )
        )
    )


@click.command(cls=RichCommand)
@click.argument("asset", required=False)
@click.option("--depth", type=int, default=2)
@click.option("--diff", "diff_range", help="Local commit comparison: <base>..<head>.")
@click.option("--repo", type=click.Path(path_type=Path, exists=True, file_okay=False))
@click.option(
    "--claims-limit", type=click.IntRange(1, 100), help="Admitted claims per page (default 100)."
)
@click.option("--claims-continuation", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.pass_obj
def impact(
    state: CliState,
    asset: str | None,
    depth: int,
    diff_range: str | None,
    repo: Path | None,
    claims_limit: int | None,
    claims_continuation: Path | None,
) -> Reply:
    """Trace an asset's impact or assemble a local diff review checklist."""
    if diff_range is not None:
        if asset is not None:
            raise click.UsageError("provide an asset or --diff, not both")
        result = impact_diff(
            state.root,
            diff_range,
            repo=repo,
            depth=depth,
            claims_limit=100 if claims_limit is None else claims_limit,
            claims_continuation=load(claims_continuation) if claims_continuation else None,
        )
        return Reply(result, 0 if result["complete"] is True else 2, presentation="diff-impact")
    if asset is None:
        raise click.UsageError("provide an asset or --diff")
    if repo is not None or claims_continuation is not None or claims_limit is not None:
        raise click.UsageError("--repo and --claims-* require --diff")
    traced = inventory.impact(state.root, asset, depth=depth)
    return Reply(encode_impact(traced), 2 if traced.warnings else 0)


def register(root: click.Group) -> None:
    for command in (asset, rel, impact):
        root.add_command(command)
