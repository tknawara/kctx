"""Asset and relationship records, plus bounded impact traversal."""

from pathlib import Path
from typing import Any, Dict, List, Optional

from errors import KctxError
from records import (
    ASSET_KINDS,
    LIFECYCLES,
    REL_STATUSES,
    REL_TYPES,
    Asset,
    Relationship,
    require_choice,
)
from storage import atomic_write_json, list_json_files, read_json, slugify


def assets_dir(root: Path) -> Path:
    return root / "inventory" / "assets"


def relationships_dir(root: Path) -> Path:
    return root / "inventory" / "relationships"


def load_all_assets(root: Path) -> List[Asset]:
    return [Asset.from_dict(read_json(p)) for p in list_json_files(assets_dir(root))]


def load_all_relationships(root: Path) -> List[Relationship]:
    return [
        Relationship.from_dict(read_json(p))
        for p in list_json_files(relationships_dir(root))
    ]


def asset_add(
    root: Path,
    *,
    kind: str,
    name: str,
    id: Optional[str] = None,
    aliases: Optional[List[str]] = None,
    locator: str = "",
    owner: str = "unknown",
    owner_source: str = "",
    lifecycle: str = "active",
    inspect: str = "",
    projects: Optional[List[str]] = None,
    verified_at: Optional[str] = None,
    ttl: Optional[str] = None,
    notes: str = "",
) -> Dict[str, Any]:
    require_choice(kind, ASSET_KINDS, "kind")
    require_choice(lifecycle, LIFECYCLES, "lifecycle")
    asset_id = id or f"{kind}-{slugify(name)}"
    path = assets_dir(root) / f"{asset_id}.json"
    if path.exists():
        raise KctxError("conflict", f"asset {asset_id} already exists")
    asset = Asset(
        id=asset_id,
        kind=kind,
        name=name,
        locator=locator,
        aliases=list(aliases or []),
        owner=owner,
        owner_source=owner_source,
        lifecycle=lifecycle,
        inspect=inspect,
        projects=list(projects or []),
        verified_at=verified_at,
        ttl=ttl,
        notes=notes,
    )
    atomic_write_json(path, asset.to_dict())
    return asset.to_dict()


def resolve_asset(root: Path, ident: str) -> Asset:
    """Resolve an asset by exact id first, then by alias or exact name."""
    path = assets_dir(root) / f"{ident}.json"
    if path.exists():
        return Asset.from_dict(read_json(path))
    for asset in load_all_assets(root):
        if ident in asset.aliases or ident == asset.name:
            return asset
    raise KctxError("not-found", f"no asset matches id or alias {ident!r}")


def asset_show(root: Path, ident: str) -> Dict[str, Any]:
    return resolve_asset(root, ident).to_dict()


def asset_list(
    root: Path, *, kind: Optional[str] = None, project: Optional[str] = None
) -> List[Dict[str, Any]]:
    out = []
    for asset in load_all_assets(root):
        if kind and asset.kind != kind:
            continue
        if project and project not in asset.projects:
            continue
        out.append(asset.to_dict())
    return out


def rel_add(
    root: Path,
    *,
    type: str,
    from_: str,
    to: str,
    id: Optional[str] = None,
    status: str = "explicit",
    evidence: Optional[List[str]] = None,
    applicability: str = "",
) -> Dict[str, Any]:
    require_choice(type, REL_TYPES, "type")
    require_choice(status, REL_STATUSES, "status")
    rel_id = id or f"{slugify(type)}__{slugify(from_)}__{slugify(to)}"
    path = relationships_dir(root) / f"{rel_id}.json"
    if path.exists():
        raise KctxError("conflict", f"relationship {rel_id} already exists")
    rel = Relationship(
        id=rel_id,
        type=type,
        from_=from_,
        to=to,
        status=status,
        evidence=list(evidence or []),
        applicability=applicability,
    )
    atomic_write_json(path, rel.to_dict())
    return rel.to_dict()


IMPACT_BOUNDARY_NOTE = (
    "Inventory absence is not proof of no consumers: a fresh search in the relevant "
    "sources is required before treating an interface change as unaffected."
)


def impact(root: Path, ident: str, depth: int = 2) -> Dict[str, Any]:
    """Bounded BFS over relationships in both directions from `ident`.

    Always reports the coverage-boundary note, and reports edges leaving the
    final frontier that the depth budget did not let the traversal follow.
    """
    start = resolve_asset(root, ident)
    rels = load_all_relationships(root)
    by_node: Dict[str, List[Relationship]] = {}
    for r in rels:
        by_node.setdefault(r.from_, []).append(r)
        by_node.setdefault(r.to, []).append(r)

    visited = {start.id}
    frontier = {start.id}
    reached: List[Dict[str, Any]] = []
    current_depth = 0
    while frontier and current_depth < depth:
        next_frontier = set()
        for node in frontier:
            for r in by_node.get(node, []):
                other = r.to if r.from_ == node else r.from_
                if other in visited:
                    continue
                visited.add(other)
                next_frontier.add(other)
                reached.append(
                    {
                        "asset": other,
                        "via": node,
                        "relationship": r.id,
                        "type": r.type,
                        "status": r.status,
                    }
                )
        frontier = next_frontier
        current_depth += 1

    unexplored: List[Dict[str, Any]] = []
    for node in frontier:
        for r in by_node.get(node, []):
            other = r.to if r.from_ == node else r.from_
            if other not in visited:
                unexplored.append(
                    {"from": node, "relationship": r.id, "to": other, "type": r.type}
                )

    return {
        "asset": start.id,
        "depth": depth,
        "reached": reached,
        "unexplored_edges": unexplored,
        "note": IMPACT_BOUNDARY_NOTE,
    }
