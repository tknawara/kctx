"""Freshness reporting and mechanical citation draining."""

from pathlib import Path
from typing import NotRequired, TypedDict

from kctx.adapters.files.contained import contained_markdown
from kctx.adapters.files.storage import read_json
from kctx.citations.scan import (
    CitationResult,
    CitationStale,
    StaleAggregate,
    StaleEntry,
    StaleGroup,
    run_check,
    run_stale,
)
from kctx.codecs.frontmatter import read_frontmatter
from kctx.codecs.records import decode_run_manifest
from kctx.domain.ids import AssetId
from kctx.domain.time import is_past_ttl, parse_flexible_timestamp
from kctx.domain.vocabulary import CoverageOutcome
from kctx.errors import KctxError
from kctx.services import dossiers, inventory, investigations, runs, signatures


class Regression(TypedDict):
    investigation: str
    signature: str
    created: str
    fixed_at: str


class OpenCorrection(TypedDict):
    file: str
    target: str
    referrer: str
    status: str


class StaleAsset(TypedDict):
    asset: str
    verified_at: str
    ttl: str


class StaleRun(TypedDict):
    run: str
    items: list[str]


class StaleResult(TypedDict):
    project: str | None
    offline: bool
    stale_assets: list[StaleAsset]
    citations: CitationStale
    stale_runs: list[StaleRun]
    regressions: list[Regression]
    open_corrections: list[OpenCorrection]
    warnings: NotRequired[list[str]]


class LineChange(TypedDict):
    line_no: int
    before: str
    after: str


class TouchedFile(TypedDict):
    file: str
    changes: list[LineChange]


class CitationJudgment(TypedDict):
    file: str
    line_no: int
    kind: str | None
    status: str


class DrainResult(TypedDict):
    project: str | None
    paths: list[str]
    citations_available: bool
    note: str | None
    touched_files: list[TouchedFile]
    remaining: dict[str, list[CitationJudgment]]
    total_remaining: int
    open_corrections: NotRequired[list[OpenCorrection]]
    open_corrections_total: NotRequired[int]


DRAIN_BUCKET_HINTS = {
    "expired_noncode": "re-run its q= via MCP, then `cite make` anew",
    "changed_gone_code": "re-read the code at head=, fix or annotate the claim, re-cite",
    "changed_gone_other": "re-check the live record (proposal/gate/record), re-cite",
    "unverifiable": "couldn't be classified (missing seen=, unresolvable repo, ...); investigate directly",
}


def _snapshot_md_files(paths: list[str]) -> dict[str, str]:
    """Reads every .md file under the given files/dirs. Used to detect what
    `cite check --touch --mark` actually rewrote: its directory-scan JSON
    (unlike the single `--line` form) carries no `touched_line` per result,
    so a before/after content diff is the only way to report it."""
    with contained_markdown(paths) as sources:
        return {str(source.path): source.text() for source in sources}


def _changed_lines(before: str, after: str) -> list[LineChange]:
    """Line-level diff between a file's content before/after a write-back.
    cite's own field replacement is always an in-place, same-line rewrite
    (never an insert/delete of a line), so a line-by-line zip is enough --
    this is a generic text diff, not a re-implementation of cite's own
    blob/span or field-parsing logic."""
    before_lines, after_lines = before.splitlines(), after.splitlines()
    return [
        {"line_no": i, "before": b, "after": a}
        for i, (b, a) in enumerate(zip(before_lines, after_lines, strict=True), start=1)
        if b != a
    ]


def regression_flags(root: Path, *, skipped: list[str] | None = None) -> list[Regression]:
    fixed = {
        record.id: record.fixed_at
        for record in signatures.list_signatures(root, skipped=skipped)
        if record.fixed_at
    }
    flags: list[Regression] = []
    for record in investigations.list_investigations(root, skipped=skipped):
        if not record.created:
            continue
        for signature in record.signatures:
            fixed_at = fixed.get(signature)
            if not fixed_at:
                continue
            try:
                after = parse_flexible_timestamp(record.created) > parse_flexible_timestamp(
                    fixed_at
                )
            except KctxError:
                continue
            if after:
                flags.append(
                    {
                        "investigation": record.id.val,
                        "signature": signature.val,
                        "created": record.created,
                        "fixed_at": fixed_at,
                    }
                )
    return flags


def _dossier_asset_is_active(root: Path, asset: AssetId) -> bool:
    try:
        record = inventory.get_asset(root, asset)
    except KctxError:
        return False
    for project in record.projects:
        path = root / project / "STATUS.md"
        if path.is_file():
            phase = (
                read_frontmatter(path.read_text(encoding="utf-8")).get("phase", "").strip().lower()
            )
            if phase not in ("done", "closed"):
                return True
    return False


def _filter_dossier_stale_entries(root: Path, entries: list[StaleEntry]) -> list[StaleEntry]:
    directory = dossiers.dossiers_root(root)
    if not directory.exists():
        return entries
    kept: list[StaleEntry] = []
    for entry in entries:
        try:
            Path(entry["file"]).resolve().relative_to(directory.resolve())
        except ValueError:
            kept.append(entry)
            continue
        if _dossier_asset_is_active(root, AssetId(Path(entry["file"]).stem)):
            kept.append(entry)
    return kept


def _recompute_stale_aggregate(entries: list[StaleEntry]) -> StaleAggregate:
    groups: dict[str, StaleGroup] = {}
    for entry in entries:
        group = groups.setdefault(entry["group"], {"count": 0, "oldest_age_days": 0.0})
        group["count"] += 1
        age = entry["age_days"]
        if age is not None and age > group["oldest_age_days"]:
            group["oldest_age_days"] = age
    ages = [entry["age_days"] for entry in entries if entry["age_days"] is not None]
    return {
        "entries": entries,
        "groups": groups,
        "total": len(entries),
        "oldest_age_days": max(ages) if ages else 0.0,
    }


def _open_corrections(root: Path, *, skipped: list[str] | None = None) -> list[OpenCorrection]:
    from kctx.domain.vocabulary import CorrectionRowStatus
    from kctx.services import corrections

    rows: list[OpenCorrection] = []
    for path in corrections.all_paths(root):
        try:
            parsed = corrections.parse(path.read_text(encoding="utf-8"))
        except (KctxError, ValueError, OSError) as error:
            if skipped is None:
                raise
            skipped.append(f"correction {path.relative_to(root)}: {error}")
            continue
        for row in parsed.rows:
            if isinstance(row.status, CorrectionRowStatus) and row.status in (
                CorrectionRowStatus.PENDING,
                CorrectionRowStatus.UNRESOLVED,
            ):
                rows.append(
                    {
                        "file": str(path.relative_to(root)),
                        "target": parsed.frontmatter.target.spelling,
                        "referrer": row.file,
                        "status": row.status.value,
                    }
                )
    return rows


def stale(root: Path, *, project: str | None = None, offline: bool = False) -> StaleResult:
    """One unreadable signature, investigation, asset or correction file limits
    its own section and is disclosed as a warning, never the whole report."""
    skipped: list[str] = []
    assets: list[StaleAsset] = []
    for asset in inventory.load_all_assets(root, skipped=skipped):
        if project and project not in asset.projects:
            continue
        if asset.verified_at and asset.ttl and is_past_ttl(asset.verified_at, asset.ttl):
            assets.append(
                {"asset": asset.id.val, "verified_at": asset.verified_at, "ttl": asset.ttl}
            )
    directory = root / project if project else root
    citations: CitationStale = run_stale(
        [str(directory)] if directory.exists() or directory.is_symlink() else [], offline=offline
    )
    if citations["available"]:
        aggregate = _recompute_stale_aggregate(
            _filter_dossier_stale_entries(root, citations["entries"])
        )
        citations["entries"] = aggregate["entries"]
        citations["groups"] = aggregate["groups"]
        citations["total"] = aggregate["total"]
        citations["oldest_age_days"] = aggregate["oldest_age_days"]
        citations["note"] = citations.get("note")
    else:
        citations["note"] = citations.get("note")
    stale_runs: list[StaleRun] = []
    for path in sorted((root / "runs").glob("run-*/manifest.json")):
        manifest = decode_run_manifest(read_json(path))
        if project and manifest.project != project:
            continue
        coverage = runs.load_coverage(root, manifest.run_id)
        needs = [
            entry.item
            for entry in coverage.entries
            if entry.outcome is CoverageOutcome.NEEDS_RECHECK
        ]
        if needs:
            stale_runs.append({"run": manifest.run_id.val, "items": needs})
    return {
        "project": project,
        "offline": offline,
        "stale_assets": assets,
        "citations": citations,
        "stale_runs": stale_runs,
        "regressions": regression_flags(root, skipped=skipped),
        "open_corrections": _open_corrections(root, skipped=skipped),
        "warnings": sorted(dict.fromkeys(skipped)),
    }


def bucket_cite_results(results: list[CitationResult]) -> dict[str, list[CitationJudgment]]:
    buckets: dict[str, list[CitationJudgment]] = {name: [] for name in DRAIN_BUCKET_HINTS}
    for result in results:
        status = result["status"]
        kind = result["fields"].get("kind")
        file, line_no = result["file"], result["line_no"]
        if file is None or line_no is None:
            raise KctxError("malformed", "file citation result requires file and line_no")
        entry: CitationJudgment = {"file": file, "line_no": line_no, "kind": kind, "status": status}
        if status == "expired":
            buckets["expired_noncode"].append(entry)
        elif status in ("changed", "gone"):
            buckets["changed_gone_code" if kind == "code" else "changed_gone_other"].append(entry)
        elif status == "unverifiable":
            buckets["unverifiable"].append(entry)
    return buckets


def drain(root: Path, *, project: str | None = None, paths: list[str] | None = None) -> DrainResult:
    if paths:
        scan_paths = list(paths)
    elif project:
        scan_paths = [str(root / project)]
    else:
        raise KctxError("incomplete", "stale --drain requires --project or explicit paths")
    existing = scan_paths
    before = _snapshot_md_files(existing)
    citations = run_check(existing, touch=True, mark=True)
    after = _snapshot_md_files(existing)
    touched: list[TouchedFile] = [
        {"file": path, "changes": _changed_lines(text, after.get(path, text))}
        for path, text in sorted(before.items())
        if after.get(path, text) != text
    ]
    buckets = bucket_cite_results(citations["results"])
    corrections = _open_corrections(root)
    return {
        "project": project,
        "paths": scan_paths,
        "citations_available": citations["available"],
        "note": citations.get("note"),
        "touched_files": touched,
        "remaining": buckets,
        "total_remaining": sum(len(bucket) for bucket in buckets.values()),
        "open_corrections": corrections,
        "open_corrections_total": len(corrections),
    }
