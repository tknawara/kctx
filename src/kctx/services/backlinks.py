"""Reverse references and canonical homes; no separate usage index."""

import re
import subprocess
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import NotRequired, TypedDict, assert_never

from kctx.adapters.files.storage import decode_json
from kctx.citations.syntax import CITE_LINE_RE, parse_cite_body
from kctx.codecs.documents import parse_document
from kctx.codecs.proposals import decode_proposal
from kctx.codecs.records import decode_asset
from kctx.domain.ids import AssetId, EvidenceId
from kctx.domain.records import Asset
from kctx.domain.targets import (
    AssetRef,
    CodeLocator,
    DossierRef,
    EvidenceRef,
    InvRef,
    ProposalRef,
    SigRef,
    UseTarget,
    line_range,
    search_strings,
)
from kctx.errors import KctxError
from kctx.services import dossiers as dossiers_mod
from kctx.services import inventory
from kctx.services import investigations as inv_mod
from kctx.services import proposals as proposals_mod
from kctx.services import signatures as sig_mod
from kctx.services.discovery import is_project_name, project_dirs


class Referrer(TypedDict):
    file: str
    kind: str
    self: NotRequired[bool]


class UsesResult(TypedDict):
    target: str
    referrers: list[Referrer]
    by_kind: dict[str, list[Referrer]]
    note: str


USES_COVERAGE_NOTE = (
    "Uncited reliance is not traced: a referrer that paraphrased this claim "
    "without a citation won't show up here. Anything outside the kb (a posted "
    "PR comment, a Slack message) is out of reach."
)


_USES_SCAN_SUFFIXES = (".md", ".json")


def _uses_boundary_pattern(s: str) -> "re.Pattern[str]":
    """A plain `s in text` substring check false-positives on an id that's a
    prefix of a longer one sharing the same separators (`repo-pbp` inside
    `repo-pbp-lua`, `failure-paths` inside `failure-paths-extended`). Ids use
    `[A-Za-z0-9_./-]`, so neither side of the match may be flanked by one of
    those -- except a trailing `.` still counts as a boundary (end of a
    sentence), unless that `.` is itself followed by an id character (an
    extension-like continuation, e.g. `id.json`)."""
    return re.compile(
        r"(?<![A-Za-z0-9_./-])" + re.escape(s) + r"(?![A-Za-z0-9_/-])(?!\.[A-Za-z0-9_])"
    )


def resolve_ev_path(root: Path, home: str, stem: EvidenceId) -> Path | None:
    """An `ev:<home>/<stem>` id's `home` is normally a full relative path
    from root (a project directory, or `investigations/<inv-id>`), but some
    records still cite an investigation's bare `<inv-id>` (no `investigations/`
    prefix) from before that prefix convention existed -- tried second so
    both forms resolve to the same file without `kctx uses` itself having to
    tolerate that id's migration history (see the retract-a-claim proposal's
    Evidence section)."""
    direct = root / home / "evidence" / f"{stem}.md"
    if direct.is_file():
        return direct
    under_inv = root / "investigations" / home / "evidence" / f"{stem}.md"
    if under_inv.is_file():
        return under_inv
    return None


def _tracked_files(root: Path) -> list[Path]:
    """Every file `git ls-files` reports, so untracked scratch/build junk
    isn't scanned. Falls back to a plain filesystem walk when `root` isn't a
    git repo at all (a test fixture's throwaway config root)."""
    if (root / ".git").exists():
        try:
            proc = subprocess.run(
                ["git", "-C", str(root), "ls-files"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            proc = None
        if proc is not None and proc.returncode == 0:
            return [root / line for line in proc.stdout.splitlines() if line]
    skip_dirs = {".git", "__pycache__"}
    return [
        p
        for p in root.rglob("*")
        if p.is_file() and not any(part in skip_dirs for part in p.relative_to(root).parts)
    ]


def _uses_group(root: Path, rel: str, project_names: set[str]) -> str:
    if rel.startswith("proposals/"):
        return "proposal"
    if rel.startswith("inventory/dossiers/"):
        return "dossier"
    if rel.startswith("signatures/"):
        return "signature"
    if rel.startswith("investigations/"):
        return "investigation"
    if rel.startswith("ktlo/"):
        return "ktlo"
    if rel.startswith("runs/"):
        return "run coverage"
    if rel.split("/", 1)[0] in project_names:
        return "notes/log"
    return "other"


def _ev_home_readme(root: Path, home: str) -> str | None:
    """The narrative home record for an `ev:<home>/<stem>` id's `home`
    component -- an investigation's own README.md, or a project's -- tried
    the same two ways as resolve_ev_path. Used only to mark that file `self`
    in `kctx uses`; it never resolves the evidence file itself."""
    direct = root / home / "README.md"
    if direct.is_file():
        return str(direct.relative_to(root))
    under_inv = root / "investigations" / home / "README.md"
    if under_inv.is_file():
        return str(under_inv.relative_to(root))
    return None


def _resolve_asset_for_uses(root: Path, target: str) -> Asset | None:
    """Resolves a bare (non-`ev:`/`sig:`/`inv:`/`proposal/`) `kctx uses`
    target to its asset record, the same two ways `kctx home` resolves one --
    by id/alias first, then a locator-substring fallback. Computed once per
    call and shared by `_uses_search_strings` and `_uses_home_files` so a
    target that only resolves via the substring fallback (e.g. `widget-repo`
    matching asset `repo-widget`'s locator) still gets marked `self` against
    its own asset/dossier files, instead of those two functions resolving
    independently and disagreeing."""
    try:
        return inventory.resolve_asset(root, target)
    except KctxError as error:
        if error.category != "not-found":
            raise
        for a in inventory.load_all_assets(root):
            if a.locator and target.lower() in a.locator.lower():
                return a
        return None


def _uses_home_files(root: Path, target: UseTarget, asset: Asset | None) -> set[str]:
    homes: set[str] = set()
    try:
        match target:
            case EvidenceRef(home, stem):
                readme = _ev_home_readme(root, home)
                if readme:
                    homes.add(readme)
                path = resolve_ev_path(root, home, stem)
                if path:
                    homes.add(str(path.relative_to(root)))
            case SigRef(id):
                path = sig_mod.path_for_id(root, id)
                if path.is_file():
                    homes.add(str(path.relative_to(root)))
            case InvRef(id):
                path = inv_mod.path_for_id(root, id)
                if path.is_file():
                    homes.add(str(path.relative_to(root)))
            case ProposalRef(id):
                homes.add(str(proposals_mod.load(root, id).path.relative_to(root)))
            case AssetRef() | DossierRef():
                asset_id = (
                    asset.id
                    if asset is not None
                    else (target.id if isinstance(target, DossierRef) else AssetId(target.ident))
                )
                if asset is not None:
                    path = inventory.assets_dir(root) / f"{asset_id}.json"
                    if path.is_file():
                        homes.add(str(path.relative_to(root)))
                path = dossiers_mod.dossier_path(root, asset_id)
                if path.is_file():
                    homes.add(str(path.relative_to(root)))
            case CodeLocator():
                pass
            case _:
                assert_never(target)
    except KctxError:
        return homes
    return homes


def _uses_code_locator_hit(text: str, locator: CodeLocator) -> bool:
    for match in CITE_LINE_RE.finditer(text):
        fields = parse_cite_body(match.group("body"))
        revision = fields.get("rev", "")
        if fields.get("repo") != locator.repo:
            continue
        if not (revision.startswith(locator.sha) or locator.sha.startswith(revision)):
            continue
        if fields.get("path") != locator.path:
            continue
        if locator.line is not None:
            span = line_range(fields.get("L"))
            if span is None or span[1] < locator.line[0] or span[0] > locator.line[1]:
                continue
        return True
    return False


def uses(root: Path, target: UseTarget) -> UsesResult:
    project_names = {path.name for path in project_dirs(root)}
    asset: Asset | None = None
    if isinstance(target, AssetRef):
        asset = _resolve_asset_for_uses(root, target.ident)
    elif isinstance(target, DossierRef):
        try:
            asset = inventory.get_asset(root, target.id)
        except KctxError:
            pass
    return _scan_uses(
        root,
        target,
        _tracked_text(root),
        asset,
        _uses_home_files(root, target, asset),
        project_names,
    )


def _tracked_text(root: Path) -> Iterator[tuple[str, str]]:
    for path in _tracked_files(root):
        if path.suffix not in _USES_SCAN_SUFFIXES:
            continue
        try:
            yield str(path.relative_to(root)), path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


def _scan_uses(
    root: Path,
    target: UseTarget,
    files: Iterable[tuple[str, str]],
    asset: Asset | None,
    homes: set[str],
    project_names: set[str],
) -> UsesResult:
    needles = (asset.id.val, *asset.aliases) if asset is not None else search_strings(target)
    patterns = tuple(_uses_boundary_pattern(needle) for needle in needles)
    referrers: list[Referrer] = []
    by_kind: dict[str, list[Referrer]] = {}
    for relative, text in files:
        if Path(relative).suffix not in _USES_SCAN_SUFFIXES:
            continue
        hit = (
            _uses_code_locator_hit(text, target)
            if isinstance(target, CodeLocator)
            else any(pattern.search(text) for pattern in patterns)
        )
        if not hit:
            continue
        referrer: Referrer = {"file": relative, "kind": _uses_group(root, relative, project_names)}
        if relative in homes:
            referrer["self"] = True
        referrers.append(referrer)
        by_kind.setdefault(referrer["kind"], []).append(referrer)
    return {
        "target": target.spelling,
        "referrers": referrers,
        "by_kind": by_kind,
        "note": USES_COVERAGE_NOTE,
    }


def _snapshot_home_files(
    root: Path,
    target: UseTarget,
    asset: Asset | None,
    files: Mapping[str, str],
) -> set[str]:
    """Resolve canonical homes solely from the supplied committed inventory."""
    homes: set[str] = set()

    def first_existing(candidates: tuple[str, ...]) -> None:
        for candidate in candidates:
            if candidate in files:
                homes.add(candidate)
                break

    try:
        match target:
            case EvidenceRef(home, stem):
                first_existing((f"{home}/README.md", f"investigations/{home}/README.md"))
                first_existing(
                    (f"{home}/evidence/{stem}.md", f"investigations/{home}/evidence/{stem}.md")
                )
            case SigRef(id):
                first_existing((str(sig_mod.path_for_id(root, id).relative_to(root)),))
            case InvRef(id):
                first_existing((str(inv_mod.path_for_id(root, id).relative_to(root)),))
            case ProposalRef(id):
                candidates: list[str] = []
                for name in files:
                    parts = Path(name).parts
                    if (
                        len(parts) not in (3, 4)
                        or parts[0] != "proposals"
                        or parts[1].startswith(".")
                    ):
                        continue
                    if (len(parts) == 3 and Path(name).suffix == ".md") or (
                        len(parts) == 4 and parts[3] == "proposal.md"
                    ):
                        candidates.append(name)
                for name in sorted(
                    candidates, key=lambda name: (Path(name).parts[1], Path(name).parts[2])
                ):
                    if decode_proposal(parse_document(files[name])).id == id:
                        homes.add(name)
                        break
            case AssetRef() | DossierRef():
                asset_id = (
                    asset.id
                    if asset is not None
                    else (target.id if isinstance(target, DossierRef) else AssetId(target.ident))
                )
                if asset is not None:
                    first_existing(
                        (str((inventory.assets_dir(root) / f"{asset_id}.json").relative_to(root)),)
                    )
                first_existing((str(dossiers_mod.dossier_path(root, asset_id).relative_to(root)),))
            case CodeLocator():
                pass
            case _:
                assert_never(target)
    except KctxError:
        return homes
    return homes


def _snapshot_asset(target: AssetRef | DossierRef, files: Mapping[str, str]) -> Asset | None:
    def read_asset(name: str) -> Asset:
        return decode_asset(decode_json(files[name], source=name))

    if isinstance(target, DossierRef):
        name = f"inventory/assets/{target.id}.json"
        if name not in files:
            return None
        try:
            asset = read_asset(name)
            return asset if asset.id == target.id else None
        except KctxError:
            return None
    exact = Path("inventory/assets") / f"{target.ident}.json"
    if exact.parent == Path("inventory/assets") and exact.as_posix() in files:
        return read_asset(exact.as_posix())
    assets = tuple(
        read_asset(name)
        for name in sorted(files)
        if Path(name).parent == Path("inventory/assets") and Path(name).suffix == ".json"
    )
    try:
        return inventory.resolve_asset_candidates(assets, target.ident)
    except KctxError as error:
        if error.category != "not-found":
            raise
        return next(
            (
                asset
                for asset in assets
                if asset.locator and target.ident.lower() in asset.locator.lower()
            ),
            None,
        )


def uses_from_files(root: Path, target: UseTarget, files: Mapping[str, str]) -> UsesResult:
    """Apply ``uses`` to one pinned tree, never consulting the live workspace.

    Keys are root-relative POSIX paths and values are decoded file contents.
    Alias resolution, canonical homes and grouping all belong to this tree;
    ``root`` only anchors pure path construction for canonical record names.
    """
    asset = _snapshot_asset(target, files) if isinstance(target, (AssetRef, DossierRef)) else None
    projects = {
        name.split("/", 1)[0]
        for name in files
        if "/" in name and is_project_name(name.split("/", 1)[0])
    }
    homes = _snapshot_home_files(root, target, asset, files)
    return _scan_uses(root, target, files.items(), asset, homes, projects)
