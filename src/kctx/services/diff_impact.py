"""Local diff review candidates; authored links never become admitted assertions."""

from pathlib import Path

from kctx.adapters.git.citations import run_git
from kctx.adapters.git.diff import read_local_diff, repository_matches
from kctx.adapters.git.knowledge import GitReleases
from kctx.codecs.records import encode_asset, encode_impact, encode_relationship
from kctx.config import Config
from kctx.domain.ids import AssetId, PolicyDigest, ReleaseId
from kctx.domain.json import JsonObject, JsonValue, object_value, text
from kctx.errors import KctxError
from kctx.services import inventory, signatures
from kctx.services.diff_citations import citations_for_diff
from kctx.services.knowledge import KnowledgeEngine

BOUNDARY = (
    "Review candidates, not a contradiction check or admission verdict. "
    "Authored Markdown and inventory are workspace reads, not an immutable release. "
    "Repository locators identify candidate assets, not proven file ownership. "
    + inventory.IMPACT_BOUNDARY_NOTE
)


def _knowledge_context(
    root: Path,
    assets: tuple[AssetId, ...],
    limit: int,
    continuation: JsonObject | None,
) -> JsonObject:
    """Distinguish an absent publication from inaccessible or invalid knowledge."""
    try:
        probe = run_git(["rev-parse", "--git-dir"], cwd=root, local_only=True)
        if probe.returncode:
            if "not a git repository" in probe.stderr.lower() and continuation is None:
                return {
                    "status": "no_release",
                    "reason": "authored workspace is not a Git repository",
                    "release": None,
                    "records": [],
                    "complete": False,
                }
            raise KctxError("incomplete", "cannot inspect the authored Git repository")
        current = GitReleases(root).current()
        if current is None and continuation is None:
            return {"status": "no_release", "release": None, "records": [], "complete": False}
        config = Config.load()
        if config.knowledge_dir is None:
            raise KctxError(
                "incomplete", "completed release exists but knowledge_dir is not configured"
            )
        anchor = (
            PolicyDigest(config.knowledge_policy_digest) if config.knowledge_policy_digest else None
        )
        engine = KnowledgeEngine(root, config.knowledge_dir, anchor)
        release = (
            ReleaseId(text(continuation.get("release"), "continuation release"))
            if continuation is not None
            else ReleaseId(current)
            if current is not None
            else None
        )
        return engine.context_for_assets(
            assets, limit=limit, release=release, continuation=continuation
        )
    except (KctxError, OSError, ValueError) as error:
        return {
            "status": "unavailable",
            "reason": str(error),
            "records": [],
            "complete": False,
        }


def impact_diff(
    root: Path,
    diff: str,
    *,
    repo: Path | None = None,
    depth: int = 2,
    claims_limit: int = 100,
    claims_continuation: JsonObject | None = None,
) -> JsonObject:
    """Compose one local commit comparison and one pinned admitted context."""
    if not 0 <= depth <= 10:
        raise KctxError("malformed", "diff impact depth must be between 0 and 10")
    if not 1 <= claims_limit <= 100:
        raise KctxError("malformed", "claims limit must be between 1 and 100")
    selected = read_local_diff(diff, repo)
    warnings: list[str] = []
    citations, citation_warnings = citations_for_diff(root, selected)
    warnings.extend(citation_warnings)
    all_assets = inventory.load_all_assets(root, skipped=warnings)
    relationships = inventory.load_all_relationships(root, skipped=warnings)
    known = {asset.id: asset for asset in all_assets}
    matched = tuple(asset for asset in all_assets if repository_matches(asset.locator, selected))
    matched_ids = tuple(asset.id for asset in matched)
    ids = frozenset(matched_ids)
    incident_records: list[JsonValue] = [
        object_value(signatures.frontmatter_to_wire(record))
        for record in signatures.list_signatures(root, skipped=warnings)
        if ids.intersection(record.assets)
    ]
    asset_records: list[JsonValue] = []
    traversal_complete = True
    for asset in matched:
        traced = inventory.impact_from_records(asset.id, relationships, depth)
        traversal_complete = traversal_complete and not traced.unexplored_edges
        related: list[JsonValue] = []
        for reached in traced.reached:
            if reached.asset in known:
                related.append(encode_asset(known[reached.asset]))
            else:
                warnings.append(f"relationship reaches missing asset {reached.asset.val}")
        asset_records.append(
            {
                "asset": encode_asset(asset),
                "inbound": [
                    encode_relationship(rel) for rel in relationships if rel.to == asset.id
                ],
                "outbound": [
                    encode_relationship(rel) for rel in relationships if rel.from_ == asset.id
                ],
                "impact": encode_impact(traced),
                "related_assets": related,
            }
        )
    knowledge = _knowledge_context(root, matched_ids, claims_limit, claims_continuation)
    if knowledge["status"] == "unavailable":
        warnings.append(f"admitted knowledge unavailable: {knowledge['reason']}")
    claims = knowledge.pop("records")
    files: list[JsonValue] = []
    for changed in selected.files:
        path = changed.new_path or changed.old_path
        if path is None:
            raise KctxError("malformed", "diff entry has neither old nor new path")
        files.append(
            {
                "path": path,
                "old_path": changed.old_path,
                "new_path": changed.new_path,
                "status": changed.status,
                "binary": changed.binary,
                "hunks": [
                    {
                        "old_start": hunk.old_start,
                        "old_count": hunk.old_count,
                        "new_start": hunk.new_start,
                        "new_count": hunk.new_count,
                    }
                    for hunk in changed.hunks
                ],
                "citations": list(citations.get(path, ())),
                "assets": asset_records,
                "signatures": incident_records,
                "claims": claims,
                "knowledge_status": knowledge["status"],
            }
        )
    return {
        "repository": selected.repository,
        "repo_path": str(selected.repo_path),
        "base": selected.base,
        "head": selected.head,
        "files": files,
        "knowledge": knowledge,
        "depth": depth,
        "complete": not warnings and traversal_complete and knowledge["complete"] is True,
        "warnings": list(dict.fromkeys(warnings)),
        "boundary": BOUNDARY,
    }
