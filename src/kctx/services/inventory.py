"""Asset and relationship use cases, plus bounded impact traversal."""

from pathlib import Path

from kctx.adapters.files.storage import atomic_write_json, list_json_files, read_json, slugify
from kctx.codecs.records import decode_asset, decode_relationship, encode_asset, encode_relationship
from kctx.domain.ids import AssetId, RelationshipId
from kctx.domain.records import (
    Asset,
    Impact,
    ImpactReached,
    ImpactUnexplored,
    Relationship,
)
from kctx.domain.targets import EvidenceAddress
from kctx.domain.vocabulary import AssetKind, Lifecycle, RelationshipStatus, RelationshipType
from kctx.errors import KctxError


def assets_dir(root: Path) -> Path:
    return root / "inventory" / "assets"


def relationships_dir(root: Path) -> Path:
    return root / "inventory" / "relationships"


def load_all_assets(root: Path, *, skipped: list[str] | None = None) -> tuple[Asset, ...]:
    """Decode every asset; aggregate readers pass ``skipped`` to keep serving
    the readable records instead of aborting on the first malformed one."""
    out: list[Asset] = []
    for path in list_json_files(assets_dir(root)):
        try:
            out.append(decode_asset(read_json(path)))
        except (KctxError, ValueError, OSError) as error:
            if skipped is None:
                raise
            skipped.append(f"asset {path.relative_to(root)}: {error}")
    return tuple(out)


def load_all_relationships(
    root: Path, *, skipped: list[str] | None = None
) -> tuple[Relationship, ...]:
    out: list[Relationship] = []
    for path in list_json_files(relationships_dir(root)):
        try:
            out.append(decode_relationship(read_json(path)))
        except (KctxError, ValueError, OSError) as error:
            if skipped is None:
                raise
            skipped.append(f"relationship {path.relative_to(root)}: {error}")
    return tuple(out)


def asset_add(
    root: Path,
    *,
    kind: AssetKind,
    name: str,
    id: AssetId | None = None,
    aliases: tuple[str, ...] = (),
    locator: str = "",
    owner: str = "unknown",
    owner_source: str = "",
    lifecycle: Lifecycle = Lifecycle.ACTIVE,
    inspect: str = "",
    projects: tuple[str, ...] = (),
    verified_at: str | None = None,
    ttl: str | None = None,
    notes: str = "",
) -> Asset:
    asset_id = id if id is not None else AssetId(f"{kind.value}-{slugify(name)}")
    path = assets_dir(root) / f"{asset_id.val}.json"
    if path.exists():
        raise KctxError("conflict", f"asset {asset_id} already exists")
    asset = Asset(
        asset_id,
        kind,
        name,
        locator,
        aliases,
        owner,
        owner_source,
        lifecycle,
        inspect,
        projects,
        verified_at,
        ttl,
        notes,
    )
    atomic_write_json(path, encode_asset(asset))
    return asset


def get_asset(root: Path, asset_id: AssetId) -> Asset:
    """Load an exact identity without alias or prose resolution."""
    path = assets_dir(root) / f"{asset_id.val}.json"
    if not path.exists():
        raise KctxError("not-found", f"asset {asset_id} not found")
    asset = decode_asset(read_json(path))
    if asset.id != asset_id:
        raise KctxError("malformed", f"asset identity does not match {asset_id}")
    return asset


def resolve_asset(root: Path, ident: str) -> Asset:
    """Resolve an exact identity, alias, or name supplied as search prose."""
    path = assets_dir(root) / f"{ident}.json"
    if path.parent == assets_dir(root) and path.exists():
        return decode_asset(read_json(path))
    return resolve_asset_candidates(load_all_assets(root), ident)


def resolve_asset_candidates(assets: tuple[Asset, ...], ident: str) -> Asset:
    """Resolve alias/name prose in an explicitly selected inventory snapshot."""
    matches = tuple(asset for asset in assets if ident in asset.aliases or ident == asset.name)
    if len(matches) > 1:
        candidates = ", ".join(asset.id.val for asset in matches)
        raise KctxError("conflict", f"ambiguous asset {ident!r}; candidates: {candidates}")
    if matches:
        return matches[0]
    raise KctxError("not-found", f"no asset matches id or alias {ident!r}")


def asset_show(root: Path, ident: str) -> Asset:
    return resolve_asset(root, ident)


def asset_list(
    root: Path, *, kind: AssetKind | None = None, project: str | None = None
) -> tuple[Asset, ...]:
    return tuple(
        asset
        for asset in load_all_assets(root)
        if (kind is None or asset.kind is kind) and (not project or project in asset.projects)
    )


def rel_add(
    root: Path,
    *,
    type: RelationshipType,
    from_: AssetId,
    to: AssetId,
    id: RelationshipId | None = None,
    status: RelationshipStatus = RelationshipStatus.EXPLICIT,
    evidence: tuple[EvidenceAddress, ...] = (),
    applicability: str = "",
) -> Relationship:
    rel_id = id if id is not None else RelationshipId(f"{type.value}__{from_.val}__{to.val}")
    path = relationships_dir(root) / f"{rel_id.val}.json"
    if path.exists():
        raise KctxError("conflict", f"relationship {rel_id} already exists")
    relationship = Relationship(rel_id, type, from_, to, status, evidence, applicability)
    atomic_write_json(path, encode_relationship(relationship))
    return relationship


IMPACT_BOUNDARY_NOTE = (
    "Inventory absence is not proof of no consumers: a fresh search in the relevant "
    "sources is required before treating an interface change as unaffected."
)


def impact(root: Path, ident: AssetId | str, depth: int = 2) -> Impact:
    """Traverse an exact identity or resolve a prose search, disclosing limits.

    Undecodable relationship records are skipped and disclosed in the result
    warnings: one malformed file limits this traversal, never every one.
    """
    skipped: list[str] = []
    start = get_asset(root, ident) if isinstance(ident, AssetId) else resolve_asset(root, ident)
    relationships = load_all_relationships(root, skipped=skipped)
    return impact_from_records(start.id, relationships, depth, warnings=tuple(skipped))


def impact_from_records(
    start: AssetId,
    relationships: tuple[Relationship, ...],
    depth: int = 2,
    *,
    warnings: tuple[str, ...] = (),
) -> Impact:
    """Use one acquired inventory for all roots of a compound review query."""
    by_node: dict[AssetId, list[Relationship]] = {}
    for relationship in relationships:
        by_node.setdefault(relationship.from_, []).append(relationship)
        by_node.setdefault(relationship.to, []).append(relationship)
    visited = {start}
    frontier = {start}
    reached: list[ImpactReached] = []
    current_depth = 0
    while frontier and current_depth < depth:
        next_frontier: set[AssetId] = set()
        for node in frontier:
            for relationship in by_node.get(node, ()):
                other = relationship.to if relationship.from_ == node else relationship.from_
                if other in visited:
                    continue
                visited.add(other)
                next_frontier.add(other)
                reached.append(
                    ImpactReached(
                        other, node, relationship.id, relationship.type, relationship.status
                    )
                )
        frontier = next_frontier
        current_depth += 1
    unexplored: list[ImpactUnexplored] = []
    for node in frontier:
        for relationship in by_node.get(node, ()):
            other = relationship.to if relationship.from_ == node else relationship.from_
            if other not in visited:
                unexplored.append(ImpactUnexplored(node, relationship.id, other, relationship.type))
    return Impact(
        start,
        depth,
        tuple(reached),
        tuple(unexplored),
        IMPACT_BOUNDARY_NOTE,
        tuple(dict.fromkeys(warnings)),
    )
