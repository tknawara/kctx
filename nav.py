"""Cross-cutting navigation over the knowledge workspace: which project or
ktlo record a change belongs to (`home`), a compact context pack for an
asset (`context`), and what's gone stale (`stale`).

These read what inventory.py, ktlo.py, and runs.py already expose, plus the
<project>/ directories and ktlo/ records on disk. Citations are never
re-verified here: every status comes from shelling out to the grounding
skill's `cite` script (see LOCATORS.md), never from re-implementing its
blob/span comparison.
"""

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import dossiers as dossiers_mod
import inventory
import investigations as inv_mod
import ktlo as ktlo_mod
import proposals as proposals_mod
import runs as runs_mod
import signatures as sig_mod
from errors import KctxError
from storage import (
    is_past_ttl,
    parse_flexible_timestamp,
    read_frontmatter,
    read_json,
    split_list_value,
)


def iso_now_minute() -> str:
    """Matches the grounding cite skill's own `seen=` timestamp precision
    (minute, not second) so a citation admit.py rewrites looks the same as
    one `cite make`/`cite check --touch` would have written."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


_SHARED_DIRS = {
    "inventory",
    "runs",
    "proposals",
    "tools",
    "ktlo",
    "investigations",
    "signatures",
    "runbooks",
    "queries",
}
_PROJECT_REFERENCE_FILES = ("README.md", "inventory.md", "STATUS.md")
_DOC_LIKE_KINDS = {"doc", "dashboard", "alert", "runbook"}


def runbooks_root(root: Path) -> Path:
    return root / "runbooks"


def all_runbook_paths(root: Path) -> List[Path]:
    base = runbooks_root(root)
    if not base.exists():
        return []
    return sorted(base.glob("*/*.md"))


def project_dirs(root: Path) -> List[Path]:
    if not root.exists():
        return []
    return [
        p
        for p in sorted(root.iterdir())
        if p.is_dir() and not p.name.startswith(".") and p.name not in _SHARED_DIRS
    ]


# --------------------------------------------------------------------------
# cite integration: locate the standalone script, never reimplement it
# --------------------------------------------------------------------------


def locate_cite_bin() -> Optional[str]:
    candidates = []
    env = os.environ.get("CITE_BIN")
    if env:
        candidates.append(env)
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        candidates.append(str(Path(config_dir) / "skills" / "grounding" / "cite"))
    candidates.append(str(Path.home() / ".claude" / "skills" / "grounding" / "cite"))
    candidates.append(
        str(
            Path.home()
            / "workspace"
            / "dotfiles"
            / ".claude"
            / "skills"
            / "grounding"
            / "cite"
        )
    )
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def run_cite_check(
    paths: List[str], *, touch: bool = False, mark: bool = False
) -> Dict[str, Any]:
    """Batch `cite check` over the given files/dirs in one invocation,
    optionally writing back `--touch`/`--mark` results. Returns
    available=False (never a fabricated 'fresh') when the script can't be
    found or doesn't run cleanly."""
    if not paths:
        return {"available": True, "results": [], "warnings": []}
    cite_bin = locate_cite_bin()
    if cite_bin is None:
        return {
            "available": False,
            "results": [],
            "warnings": [],
            "note": "cite script not found; citations unverifiable",
        }
    cmd = [cite_bin, "--json", "check", *paths]
    if touch:
        cmd.append("--touch")
    if mark:
        cmd.append("--mark")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {
            "available": False,
            "results": [],
            "warnings": [],
            "note": f"cite check failed to run: {e}",
        }
    if not (proc.stdout or "").strip():
        return {
            "available": False,
            "results": [],
            "warnings": [],
            "note": (
                f"cite check produced no output (exit {proc.returncode}): "
                f"{(proc.stderr or '').strip()[:200]}"
            ),
        }
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {
            "available": False,
            "results": [],
            "warnings": [],
            "note": f"cite check produced unparseable output (exit {proc.returncode})",
        }
    if "results" not in payload:
        return {
            "available": False,
            "results": [],
            "warnings": [],
            "note": f"cite check output missing 'results' (exit {proc.returncode}): {payload}",
        }
    return {
        "available": True,
        "results": payload.get("results", []),
        "warnings": payload.get("warnings", []),
    }


_CITE_STALE_EMPTY = {"entries": [], "groups": {}, "total": 0, "oldest_age_days": 0.0}


def run_cite_stale(paths: List[str], *, offline: bool = False) -> Dict[str, Any]:
    """Batch `cite stale` over the given files/dirs -- the live or
    `--offline` judgment of what's due for attention, mirroring
    run_cite_check's availability handling (available=False, never a
    fabricated empty-clean result, when the script can't be found or run)."""
    if not paths:
        return {"available": True, **_CITE_STALE_EMPTY}
    cite_bin = locate_cite_bin()
    if cite_bin is None:
        return {
            "available": False,
            **_CITE_STALE_EMPTY,
            "note": "cite script not found; citations unverifiable",
        }
    cmd = [cite_bin, "--json", "stale"]
    if offline:
        cmd.append("--offline")
    cmd.extend(paths)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {
            "available": False,
            **_CITE_STALE_EMPTY,
            "note": f"cite stale failed to run: {e}",
        }
    if not (proc.stdout or "").strip():
        return {
            "available": False,
            **_CITE_STALE_EMPTY,
            "note": (
                f"cite stale produced no output (exit {proc.returncode}): "
                f"{(proc.stderr or '').strip()[:200]}"
            ),
        }
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {
            "available": False,
            **_CITE_STALE_EMPTY,
            "note": f"cite stale produced unparseable output (exit {proc.returncode})",
        }
    if "entries" not in payload:
        return {
            "available": False,
            **_CITE_STALE_EMPTY,
            "note": f"cite stale output missing 'entries' (exit {proc.returncode}): {payload}",
        }
    return {
        "available": True,
        "entries": payload.get("entries", []),
        "groups": payload.get("groups", {}),
        "total": payload.get("total", 0),
        "oldest_age_days": payload.get("oldest_age_days", 0.0),
    }


# --------------------------------------------------------------------------
# kctx home
# --------------------------------------------------------------------------

HOME_BOUNDARY_NOTE = (
    "No project or ktlo home matched: this may be a brand-new area, or the "
    "inventory simply hasn't caught up -- absence here is not proof nothing "
    "tracks it."
)


def _asset_candidates(root: Path, ident: str) -> List[Dict[str, Any]]:
    try:
        asset = inventory.resolve_asset(root, ident)
    except KctxError:
        asset = None
        for a in inventory.load_all_assets(root):
            if a.locator and ident.lower() in a.locator.lower():
                asset = a
                break
    if asset is None:
        return []
    if asset.projects:
        return [
            {
                "type": "project",
                "target": proj,
                "evidence": f"asset {asset.id} projects includes {proj!r}",
            }
            for proj in asset.projects
        ]
    return [
        {
            "type": "asset-only",
            "target": asset.id,
            "evidence": f"asset {asset.id} matched but lists no projects",
        }
    ]


def _project_grep_candidates(root: Path, ident: str) -> List[Dict[str, Any]]:
    out = []
    needle = ident.lower()
    for proj_dir in project_dirs(root):
        for fname in _PROJECT_REFERENCE_FILES:
            p = proj_dir / fname
            if p.is_file() and needle in p.read_text(encoding="utf-8").lower():
                out.append(
                    {
                        "type": "project",
                        "target": proj_dir.name,
                        "evidence": f"{proj_dir.name}/{fname} references {ident!r}",
                    }
                )
    return out


def _ktlo_candidates(root: Path, ident: str) -> List[Dict[str, Any]]:
    out = []
    try:
        norm = ktlo_mod.normalize_ticket(ident)
    except KctxError:
        norm = None
    for p in ktlo_mod.all_paths(root):
        fm = ktlo_mod.parse(p.read_text(encoding="utf-8"))["frontmatter"]
        reasons = []
        if norm and fm.get("ticket") == norm["id"]:
            reasons.append(f"ticket={fm.get('ticket')}")
        if ident in (fm.get("assets") or []):
            reasons.append(f"assets includes {ident!r}")
        if reasons:
            out.append(
                {
                    "type": "ktlo",
                    "target": str(p.relative_to(root)),
                    "evidence": "; ".join(reasons),
                }
            )
    return out


def _investigation_candidates(root: Path, ident: str) -> List[Dict[str, Any]]:
    out = []
    try:
        norm = ktlo_mod.normalize_ticket(ident)
    except KctxError:
        norm = None
    for fm in inv_mod.list_investigations(root):
        reasons = []
        if norm and norm["id"] in (fm.get("tickets") or []):
            reasons.append(f"tickets includes {norm['id']!r}")
        if ident in (fm.get("assets") or []):
            reasons.append(f"assets includes {ident!r}")
        if ident in (fm.get("alerts") or []):
            reasons.append(f"alerts includes {ident!r}")
        if reasons:
            out.append(
                {
                    "type": "investigation",
                    "target": fm.get("id"),
                    "evidence": "; ".join(reasons),
                }
            )
    return out


def home(root: Path, ident: str) -> Dict[str, Any]:
    raw = (
        _asset_candidates(root, ident)
        + _project_grep_candidates(root, ident)
        + _ktlo_candidates(root, ident)
        + _investigation_candidates(root, ident)
    )
    deduped: Dict[Any, Dict[str, Any]] = {}
    for c in raw:
        key = (c["type"], c["target"])
        if key in deduped:
            if c["evidence"] not in deduped[key]["evidence"]:
                deduped[key]["evidence"] += "; " + c["evidence"]
        else:
            deduped[key] = dict(c)
    candidates = list(deduped.values())
    result: Dict[str, Any] = {"ident": ident, "candidates": candidates}
    if not candidates:
        result["note"] = HOME_BOUNDARY_NOTE
    return result


# --------------------------------------------------------------------------
# kctx context
# --------------------------------------------------------------------------


def _resolve_for_context(root: Path, ident: str):
    try:
        return inventory.resolve_asset(root, ident)
    except KctxError:
        matches = [
            a
            for a in inventory.load_all_assets(root)
            if a.locator and ident.lower() in a.locator.lower()
        ]
        if not matches:
            raise KctxError("not-found", f"no asset matches {ident!r}")
        return matches[0]


def _asset_kind(root: Path, asset_id: str) -> Optional[str]:
    try:
        return inventory.resolve_asset(root, asset_id).kind
    except KctxError:
        return None


def _runbooks_for_asset(root: Path, asset_id: str) -> List[Dict[str, Any]]:
    """A runbook isn't a schema-enforced kctx record (no `kctx runbook`
    command -- see ops-knowledge-layer proposal section 1c): it's a Markdown
    file under runbooks/<layer>/<slug>.md with optional flat frontmatter,
    found the same grep-ish way _project_grep_candidates finds a project."""
    out = []
    for p in all_runbook_paths(root):
        fm = read_frontmatter(p.read_text(encoding="utf-8"))
        alerts = split_list_value(fm.get("alerts", "")) if fm.get("alerts") else []
        assets = split_list_value(fm.get("assets", "")) if fm.get("assets") else []
        if asset_id in alerts or asset_id in assets:
            out.append(
                {
                    "path": str(p.relative_to(root)),
                    "layer": fm.get("layer"),
                }
            )
    return out


def _dossier_for_asset(root: Path, asset_id: str) -> Optional[Dict[str, Any]]:
    """Slots in like `_runbooks_for_asset`: a dossier isn't a bounded-query
    record either, just a file found by asset id. Returns None rather than an
    empty dict when no dossier exists, so callers can tell 'no dossier' apart
    from 'dossier with no headings yet'."""
    path = dossiers_mod.for_asset(root, asset_id)
    if path is None:
        return None
    parsed = dossiers_mod.parse(path.read_text(encoding="utf-8"))
    headings = [
        h
        for h in dossiers_mod.HEADINGS + dossiers_mod.OPTIONAL_HEADINGS
        if h in parsed["body"]
    ]
    corrections_text = parsed["body"].get(dossiers_mod.CORRECTIONS_HEADING, "")
    return {
        "path": str(path.relative_to(root)),
        "headings": headings,
        "open_corrections": bool(corrections_text.strip()),
    }


def context(root: Path, ident: str, *, depth: int = 2) -> Dict[str, Any]:
    primary = _resolve_for_context(root, ident)

    siblings = [
        a
        for a in inventory.load_all_assets(root)
        if a.id != primary.id and primary.locator and a.locator == primary.locator
    ]
    assets = [primary.to_dict()] + [a.to_dict() for a in siblings]

    impact = inventory.impact(root, primary.id, depth=depth)
    linked_docs = [
        r for r in impact["reached"] if _asset_kind(root, r["asset"]) in _DOC_LIKE_KINDS
    ]

    home_result = home(root, primary.id)
    projects = sorted(
        {c["target"] for c in home_result["candidates"] if c["type"] == "project"}
    )
    ktlo_hits = [c for c in home_result["candidates"] if c["type"] == "ktlo"]
    investigation_hits = timeline(root, primary.id)["investigations"]
    signature_ids = sorted(
        {
            sid
            for fm in inv_mod.list_investigations(root)
            if fm.get("id") in {h["id"] for h in investigation_hits}
            for sid in (fm.get("signatures") or [])
        }
    )
    signature_hits = [
        {"id": fm["id"], "title": fm.get("title"), "status": fm.get("status")}
        for fm in sig_mod.list_signatures(root)
        if fm.get("id") in signature_ids
    ]
    runbook_hits = _runbooks_for_asset(root, primary.id)
    dossier = _dossier_for_asset(root, primary.id)

    needles = {primary.id, *primary.aliases, *projects}
    runs_hits = []
    runs_dir = root / "runs"
    if runs_dir.exists():
        for manifest_path in sorted(runs_dir.glob("run-*/manifest.json")):
            text = manifest_path.read_text(encoding="utf-8")
            if any(n and n in text for n in needles):
                manifest = read_json(manifest_path)
                runs_hits.append(
                    {
                        "run": manifest["run_id"],
                        "project": manifest.get("project"),
                        "task": manifest.get("task"),
                    }
                )

    referenced_files: List[str] = []
    for proj in projects:
        for fname in _PROJECT_REFERENCE_FILES:
            p = root / proj / fname
            if p.is_file():
                referenced_files.append(str(p))
    for hit in ktlo_hits:
        p = root / hit["target"]
        if p.is_file():
            referenced_files.append(str(p))
    if dossier:
        referenced_files.append(str(root / dossier["path"]))

    citations = run_cite_check(referenced_files)

    return {
        "asset": primary.id,
        "depth": depth,
        "assets": assets,
        "impact": impact,
        "linked_docs": linked_docs,
        "projects": projects,
        "ktlo": ktlo_hits,
        "runs": runs_hits,
        "investigations": investigation_hits,
        "signatures": signature_hits,
        "runbooks": runbook_hits,
        "dossier": dossier,
        "freshness": {
            "asset_verified_at": primary.verified_at,
            "asset_ttl": primary.ttl,
            "asset_past_ttl": bool(
                primary.verified_at
                and primary.ttl
                and is_past_ttl(primary.verified_at, primary.ttl)
            ),
            "citations": citations,
        },
    }


# --------------------------------------------------------------------------
# kctx timeline
# --------------------------------------------------------------------------


def timeline(root: Path, ident: str) -> Dict[str, Any]:
    """Every investigation touching `ident` (an asset, alert, signature, or
    ticket id), oldest first -- "the 4th spike this month" made visible."""
    hits = []
    for fm in inv_mod.list_investigations(root):
        touches = (
            ident in (fm.get("assets") or [])
            or ident in (fm.get("alerts") or [])
            or ident in (fm.get("signatures") or [])
            or ident in (fm.get("tickets") or [])
        )
        if touches:
            hits.append(
                {
                    "id": fm.get("id"),
                    "title": fm.get("title"),
                    "status": fm.get("status"),
                    "created": fm.get("created"),
                }
            )
    hits.sort(key=lambda h: (h["created"] or "", h["id"] or ""))
    return {"ident": ident, "investigations": hits}


# --------------------------------------------------------------------------
# kctx match
# --------------------------------------------------------------------------

MATCH_BOUNDARY_NOTE = (
    "no known signature; this is not proof it's new -- a fresh search in the "
    "relevant systems is required before concluding so"
)


def match(root: Path, text: str) -> Dict[str, Any]:
    """Recurrence check, the rota entry point: rank known signatures whose
    `match` patterns hit `text`, then full-text hits against investigations'
    bodies and ktlo Symptom sections -- in that priority order, so a known
    signature is always surfaced ahead of a looser full-text coincidence."""
    signature_hits = sig_mod.match_signatures(root, text)

    needle = text.lower()
    investigation_hits = []
    for p in inv_mod.all_paths(root):
        full = p.read_text(encoding="utf-8")
        if needle in full.lower():
            fm = inv_mod.parse(full)["frontmatter"]
            investigation_hits.append(
                {
                    "id": fm.get("id"),
                    "title": fm.get("title"),
                    "status": fm.get("status"),
                }
            )

    ktlo_hits = []
    for p in ktlo_mod.all_paths(root):
        parsed = ktlo_mod.parse(p.read_text(encoding="utf-8"))
        symptom = parsed["body"].get("Symptom", "")
        if needle in symptom.lower():
            ktlo_hits.append(
                {
                    "ticket": parsed["frontmatter"].get("ticket"),
                    "path": str(p.relative_to(root)),
                }
            )

    result: Dict[str, Any] = {
        "query": text,
        "signatures": signature_hits,
        "investigations": investigation_hits,
        "ktlo": ktlo_hits,
    }
    if not signature_hits and not investigation_hits and not ktlo_hits:
        result["note"] = MATCH_BOUNDARY_NOTE
    return result


# --------------------------------------------------------------------------
# kctx uses: reverse lookup over the existing citation/id graph. No separate
# usage-tracking store -- a durable claim always carries a durable id that's
# referenced by literal text, so finding what relied on it is a grep over
# tracked files, the same backlink-reuse precedent as MediaWiki's "What
# links here" rather than a maintained reverse index.
# --------------------------------------------------------------------------

USES_COVERAGE_NOTE = (
    "Uncited reliance is not traced: a referrer that paraphrased this claim "
    "without a citation won't show up here. Anything outside the kb (a posted "
    "PR comment, a Slack message) is out of reach."
)

_USES_CITE_RE = re.compile(r"⟦cite(?P<body>.*?)⟧", re.DOTALL)
_USES_FIELD_RE = re.compile(r'(\w+)=(?:"([^"]*)"|(\S+))')
_USES_LOCATOR_RE = re.compile(
    r"^(?P<repo>[^@\s]+)@(?P<sha>[0-9a-fA-F]{7,40}):(?P<path>[^:\s]+)"
    r"(?::(?P<line>\d+(?:-\d+)?))?$"
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


def _parse_cite_body(body: str) -> Dict[str, str]:
    fields = {}
    for m in _USES_FIELD_RE.finditer(body):
        fields[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3)
    return fields


def _uses_line_range(raw: Optional[str]) -> Optional[Tuple[int, int]]:
    if not raw:
        return None
    a, _, b = raw.partition("-")
    try:
        return (int(a), int(b)) if b else (int(a), int(a))
    except ValueError:
        return None


def split_ev_id(ev_rest: str) -> Tuple[str, str]:
    """`ev:<home>/<stem>` -> (home, stem). `home` may itself contain `/`
    (a full relative path, or an investigation's own `YYYY/<slug>` id)."""
    if "/" not in ev_rest:
        raise KctxError("malformed", f"bad ev: id {ev_rest!r}, expected <home>/<stem>")
    home, _, stem = ev_rest.rpartition("/")
    return home, stem


def resolve_ev_path(root: Path, home: str, stem: str) -> Optional[Path]:
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


def _tracked_files(root: Path) -> List[Path]:
    """Every file `git ls-files` reports, so untracked scratch/build junk
    isn't scanned. Falls back to a plain filesystem walk when `root` isn't a
    git repo at all (a test fixture's throwaway KCTX_ROOT)."""
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
        if p.is_file()
        and not any(part in skip_dirs for part in p.relative_to(root).parts)
    ]


def _uses_group(root: Path, rel: str, project_names: set) -> str:
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


def _ev_home_readme(root: Path, home: str) -> Optional[str]:
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


def _resolve_asset_for_uses(root: Path, target: str) -> Optional[inventory.Asset]:
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
    except KctxError:
        for a in inventory.load_all_assets(root):
            if a.locator and target.lower() in a.locator.lower():
                return a
        return None


def _uses_home_files(
    root: Path, target: str, asset: Optional[inventory.Asset] = None
) -> set:
    """Every file that's the target's own canonical record rather than a
    referrer relying on it: an investigation/project's README.md for one of
    its own `ev:` ids (the evidence file itself almost never cites its own
    id, but is included too for consistency), a signature/proposal's own
    file, or -- for a bare asset id -- both its `inventory/assets/*.json`
    record and its dossier, since either would otherwise self-match a
    literal grep for the id. `asset`, when given, is the already-resolved
    asset for `target` (see `_resolve_asset_for_uses`) -- used instead of
    re-resolving from `target` so a locator-substring match keys off the
    asset's own id rather than the original search string."""
    homes: set = set()
    try:
        if target.startswith("ev:"):
            home, stem = split_ev_id(target[len("ev:") :])
            readme = _ev_home_readme(root, home)
            if readme:
                homes.add(readme)
            ev_path = resolve_ev_path(root, home, stem)
            if ev_path:
                homes.add(str(ev_path.relative_to(root)))
            return homes
        if target.startswith("sig:"):
            path = sig_mod.path_for_id(root, target[len("sig:") :])
            if path.is_file():
                homes.add(str(path.relative_to(root)))
            return homes
        if target.startswith("inv:"):
            path = inv_mod.path_for_id(root, target[len("inv:") :])
            if path.is_file():
                homes.add(str(path.relative_to(root)))
            return homes
        if target.startswith("proposal/"):
            found = proposals_mod.load(root, target[len("proposal/") :])
            homes.add(str(found["path"].relative_to(root)))
            return homes
        asset_id = target
        if asset is not None:
            asset_path = inventory.assets_dir(root) / f"{asset.id}.json"
            if asset_path.is_file():
                homes.add(str(asset_path.relative_to(root)))
            asset_id = asset.id
        dossier_path = dossiers_mod.dossier_path(root, asset_id)
        if dossier_path.is_file():
            homes.add(str(dossier_path.relative_to(root)))
        return homes
    except KctxError:
        return homes


def _uses_search_strings(
    root: Path, target: str, asset: Optional[inventory.Asset] = None
) -> List[str]:
    """What to literally grep for. `sig:`/`inv:`/`proposal/` ids are also
    referenced in a bare form elsewhere in this repo (an investigation's
    `signatures:` frontmatter list, a log's `config/<date>-<slug>` mention) --
    a different, already-established reference convention, not an id's
    migration history, so both forms are searched. `ev:` ids get no such
    widening: their only known alternate form is exactly the migration
    history this command is scoped to tolerate, not solve (see
    resolve_ev_path). `asset`, when given, is the already-resolved asset for
    `target` (see `_resolve_asset_for_uses`)."""
    if target.startswith("ev:"):
        return [target]
    if target.startswith("sig:"):
        return [target, target[len("sig:") :]]
    if target.startswith("inv:"):
        return [target, target[len("inv:") :]]
    if target.startswith("proposal/"):
        return [target, target[len("proposal/") :]]
    if asset is not None:
        return [asset.id, *asset.aliases]
    return [target]


def _uses_code_locator_hit(text: str, locator: Dict[str, Any]) -> bool:
    for m in _USES_CITE_RE.finditer(text):
        fields = _parse_cite_body(m.group("body"))
        rev = fields.get("rev", "")
        if fields.get("repo") != locator["repo"]:
            continue
        if not (rev.startswith(locator["sha"]) or locator["sha"].startswith(rev)):
            continue
        if fields.get("path") != locator["path"]:
            continue
        if locator["line"] is not None:
            rng = _uses_line_range(fields.get("L"))
            if rng is None or rng[1] < locator["line"][0] or rng[0] > locator["line"][1]:
                continue
        return True
    return False


def uses(root: Path, target: str) -> Dict[str, Any]:
    """Reverse lookup: every tracked file that literally mentions `target`,
    grouped by kind. `target` is one of an `ev:<home>/<stem>` id, a
    `sig:<id>`/`inv:<id>` id, a `proposal/<kind>/<date>-slug` id, an asset
    id/alias (resolved the same way `kctx home` resolves one -- this covers a
    dossier target), or a `repo@sha:path:L` locator matched against a
    citation's own `path=`/`L=` fields, not against arbitrary free-text
    file:line mentions outside a citation."""
    locator_match = _USES_LOCATOR_RE.match(target)
    project_names = {p.name for p in project_dirs(root)}
    referrers: List[Dict[str, Any]] = []

    resolved_asset = (
        None
        if target.startswith(("ev:", "sig:", "inv:", "proposal/"))
        else _resolve_asset_for_uses(root, target)
    )

    if locator_match:
        locator = {
            "repo": locator_match.group("repo"),
            "sha": locator_match.group("sha"),
            "path": locator_match.group("path"),
            "line": _uses_line_range(locator_match.group("line")),
        }
        for f in _tracked_files(root):
            if f.suffix not in _USES_SCAN_SUFFIXES:
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "⟦cite" in text and _uses_code_locator_hit(text, locator):
                rel = str(f.relative_to(root))
                referrers.append({"file": rel, "kind": _uses_group(root, rel, project_names)})
    else:
        search_strings = _uses_search_strings(root, target, resolved_asset)
        patterns = [_uses_boundary_pattern(s) for s in search_strings]
        for f in _tracked_files(root):
            if f.suffix not in _USES_SCAN_SUFFIXES:
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if any(p.search(text) for p in patterns):
                rel = str(f.relative_to(root))
                referrers.append({"file": rel, "kind": _uses_group(root, rel, project_names)})

    home_files = _uses_home_files(root, target, resolved_asset)
    for r in referrers:
        if r["file"] in home_files:
            r["self"] = True

    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    for r in referrers:
        by_kind.setdefault(r["kind"], []).append(r)

    return {
        "target": target,
        "referrers": referrers,
        "by_kind": by_kind,
        "note": USES_COVERAGE_NOTE,
    }


# --------------------------------------------------------------------------
# Regression flag: an investigation linked to a signature after that
# signature's fixed_at is a possible regression (shared by `stale` and
# `validate`).
# --------------------------------------------------------------------------


def regression_flags(root: Path) -> List[Dict[str, Any]]:
    flags = []
    fixed_sigs = {
        fm["id"]: fm["fixed_at"]
        for fm in sig_mod.list_signatures(root)
        if fm.get("fixed_at")
    }
    if not fixed_sigs:
        return flags
    for fm in inv_mod.list_investigations(root):
        created = fm.get("created")
        if not created:
            continue
        for sid in fm.get("signatures") or []:
            fixed_at = fixed_sigs.get(sid)
            if not fixed_at:
                continue
            try:
                is_after = parse_flexible_timestamp(created) > parse_flexible_timestamp(
                    fixed_at
                )
            except KctxError:
                continue
            if is_after:
                flags.append(
                    {
                        "investigation": fm.get("id"),
                        "signature": sid,
                        "created": created,
                        "fixed_at": fixed_at,
                    }
                )
    return flags


# --------------------------------------------------------------------------
# kctx stale
# --------------------------------------------------------------------------


def _dossier_asset_is_active(root: Path, asset_id: str) -> bool:
    """An asset counts as 'active' for dossier-staleness purposes when it
    lists a project whose STATUS.md phase isn't done/closed -- the only
    existing signal kctx has for 'still being worked' (see CLAUDE.md's
    dossier retention rule)."""
    try:
        asset = inventory.resolve_asset(root, asset_id)
    except KctxError:
        return False
    for proj in asset.projects:
        status_path = root / proj / "STATUS.md"
        if not status_path.is_file():
            continue
        fm = read_frontmatter(status_path.read_text(encoding="utf-8"))
        phase = (fm.get("phase") or "").strip().lower()
        if phase not in ("done", "closed"):
            return True
    return False


def _filter_dossier_stale_entries(
    root: Path, entries: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """A dossier is never swept by age alone -- only `kctx context` (reading
    it) or `kctx admit` (code landing under it) surface its staleness. Drops
    any dossier-file entry whose asset isn't listed by an active project;
    non-dossier entries pass through untouched."""
    dossiers_dir = dossiers_mod.dossiers_root(root)
    if not dossiers_dir.exists():
        return entries
    kept = []
    for e in entries:
        try:
            Path(e["file"]).resolve().relative_to(dossiers_dir.resolve())
        except ValueError:
            kept.append(e)
            continue
        asset_id = Path(e["file"]).stem
        if _dossier_asset_is_active(root, asset_id):
            kept.append(e)
    return kept


def _recompute_stale_aggregate(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    groups: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        g = groups.setdefault(e.get("group"), {"count": 0, "oldest_age_days": 0.0})
        g["count"] += 1
        age = e.get("age_days")
        if age is not None and age > g["oldest_age_days"]:
            g["oldest_age_days"] = age
    ages = [e["age_days"] for e in entries if e.get("age_days") is not None]
    return {
        "entries": entries,
        "groups": groups,
        "total": len(entries),
        "oldest_age_days": max(ages) if ages else 0.0,
    }


def stale(
    root: Path, *, project: Optional[str] = None, offline: bool = False
) -> Dict[str, Any]:
    """Assets past ttl, runs with needs-recheck coverage, and possible
    regressions are all file-local checks and need no network either way.
    Citation freshness is the only part `--offline` changes: it goes to
    `cite stale --offline` (due-by-age only, no git fetch) instead of a live
    `cite stale` reclassification."""
    stale_assets = []
    for a in inventory.load_all_assets(root):
        if project and project not in a.projects:
            continue
        if a.verified_at and a.ttl and is_past_ttl(a.verified_at, a.ttl):
            stale_assets.append(
                {"asset": a.id, "verified_at": a.verified_at, "ttl": a.ttl}
            )

    scan_dir = root / project if project else root
    cite_result = (
        run_cite_stale([str(scan_dir)], offline=offline)
        if scan_dir.exists()
        else {"available": True, **_CITE_STALE_EMPTY}
    )
    if cite_result.get("available"):
        cite_agg = _recompute_stale_aggregate(
            _filter_dossier_stale_entries(root, cite_result.get("entries", []))
        )
    else:
        cite_agg = {
            "entries": cite_result.get("entries", []),
            "groups": cite_result.get("groups", {}),
            "total": cite_result.get("total", 0),
            "oldest_age_days": cite_result.get("oldest_age_days", 0.0),
        }

    stale_runs = []
    runs_dir = root / "runs"
    if runs_dir.exists():
        for manifest_path in sorted(runs_dir.glob("run-*/manifest.json")):
            manifest = read_json(manifest_path)
            if project and manifest.get("project") != project:
                continue
            coverage = runs_mod.load_coverage(root, manifest["run_id"])
            needs = [
                item
                for item, e in coverage.get("entries", {}).items()
                if e.get("outcome") == "needs-recheck"
            ]
            if needs:
                stale_runs.append({"run": manifest["run_id"], "items": needs})

    # Investigations have no `projects:` field of their own (they aren't
    # nested under <project>/), so a --project filter doesn't apply here --
    # every regression flag is always reported.
    regressions = regression_flags(root)

    return {
        "project": project,
        "offline": offline,
        "stale_assets": stale_assets,
        "citations": {
            "available": cite_result.get("available", False),
            "entries": cite_agg["entries"],
            "groups": cite_agg["groups"],
            "total": cite_agg["total"],
            "oldest_age_days": cite_agg["oldest_age_days"],
            "note": cite_result.get("note"),
        },
        "stale_runs": stale_runs,
        "regressions": regressions,
        "open_corrections": _open_corrections(root),
    }


def _open_corrections(root: Path) -> List[Dict[str, Any]]:
    """Referrer rows from corrections/*.md still `pending`/`unresolved`.
    Deferred import: corrections.py imports this module for `uses()` and
    `resolve_ev_path`, so importing it back at nav.py's own module level
    would cycle -- safe here since this only runs at call time, once both
    modules have already finished loading."""
    import corrections as corrections_mod
    from records import CORRECTION_OPEN_ROW_STATUSES

    open_rows = []
    for p in corrections_mod.all_paths(root):
        parsed = corrections_mod.parse(p.read_text(encoding="utf-8"))
        target = parsed["frontmatter"].get("target")
        for row in parsed["rows"]:
            if row.get("status") in CORRECTION_OPEN_ROW_STATUSES:
                open_rows.append(
                    {
                        "file": str(p.relative_to(root)),
                        "target": target,
                        "referrer": row.get("file"),
                        "status": row.get("status"),
                    }
                )
    return open_rows


# --------------------------------------------------------------------------
# kctx stale --drain
# --------------------------------------------------------------------------

DRAIN_BUCKET_HINTS = {
    "expired_noncode": "re-run its q= via MCP, then `cite make` anew",
    "changed_gone_code": "re-read the code at head=, fix or annotate the claim, re-cite",
    "changed_gone_other": "re-check the live record (proposal/gate/record), re-cite",
    "unverifiable": "couldn't be classified (missing seen=, unresolvable repo, ...); investigate directly",
}


def _snapshot_md_files(paths: List[str]) -> Dict[str, str]:
    """Reads every .md file under the given files/dirs. Used to detect what
    `cite check --touch --mark` actually rewrote: its directory-scan JSON
    (unlike the single `--line` form) carries no `touched_line` per result,
    so a before/after content diff is the only way to report it."""
    snapshot: Dict[str, str] = {}
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            files = sorted(pp.rglob("*.md"))
        elif pp.is_file():
            files = [pp]
        else:
            continue
        for f in files:
            try:
                snapshot[str(f)] = f.read_text(encoding="utf-8")
            except OSError:
                continue
    return snapshot


def _changed_lines(before: str, after: str) -> List[Dict[str, Any]]:
    """Line-level diff between a file's content before/after a write-back.
    cite's own field replacement is always an in-place, same-line rewrite
    (never an insert/delete of a line), so a line-by-line zip is enough --
    this is a generic text diff, not a re-implementation of cite's own
    blob/span or field-parsing logic."""
    before_lines, after_lines = before.splitlines(), after.splitlines()
    return [
        {"line_no": i, "before": b, "after": a}
        for i, (b, a) in enumerate(zip(before_lines, after_lines), start=1)
        if b != a
    ]


def bucket_cite_results(
    results: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Sorts `cite check` results into the judgment buckets a session (or
    `kctx admit`) still has to act on manually -- shared by `drain` and by
    admit's --dry-run preview, which needs the same classification without
    the write-back `drain` always performs."""
    buckets: Dict[str, List[Dict[str, Any]]] = {
        "expired_noncode": [],
        "changed_gone_code": [],
        "changed_gone_other": [],
        "unverifiable": [],
    }
    for r in results:
        status = r.get("status")
        kind = (r.get("fields") or {}).get("kind")
        entry = {
            "file": r.get("file"),
            "line_no": r.get("line_no"),
            "kind": kind,
            "status": status,
        }
        if status == "expired":
            buckets["expired_noncode"].append(entry)
        elif status in ("changed", "gone"):
            bucket = "changed_gone_code" if kind == "code" else "changed_gone_other"
            buckets[bucket].append(entry)
        elif status == "unverifiable":
            buckets["unverifiable"].append(entry)
    return buckets


def drain(
    root: Path, *, project: Optional[str] = None, paths: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Writes back the mechanical part of `cite check --touch --mark` over a
    project (or explicit paths), then buckets what's left into the judgment
    calls a session still has to make: an expired non-code citation needs its
    `q=` re-run and a fresh `cite make`; a changed/gone code citation needs
    the code re-read at `head=` and the claim fixed, annotated, or re-cited.
    `--touch`/`--mark` already handled fresh/moved/stale write-back, so
    nothing here re-derives that -- it only classifies what `cite check`
    itself reported as still needing a human look."""
    if paths:
        scan_paths = list(paths)
    elif project:
        scan_paths = [str(root / project)]
    else:
        raise KctxError(
            "incomplete", "stale --drain requires --project or explicit paths"
        )

    existing = [p for p in scan_paths if Path(p).exists()]
    before = _snapshot_md_files(existing) if existing else {}
    cite_result = (
        run_cite_check(existing, touch=True, mark=True)
        if existing
        else {"available": True, "results": [], "warnings": []}
    )
    after = _snapshot_md_files(existing) if existing else {}
    touched_files = [
        {"file": f, "changes": _changed_lines(text, after.get(f, text))}
        for f, text in sorted(before.items())
        if after.get(f, text) != text
    ]

    buckets = bucket_cite_results(cite_result.get("results", []))

    total_remaining = sum(len(v) for v in buckets.values())
    # Same resume-protocol signal `stale()` surfaces: open corrections aren't
    # scoped to `project` here either (a referrer row's file isn't reliably
    # under the project that's draining, and a target rarely is a project
    # path at all) -- every open row is reported, with a count alongside it.
    open_corrections = _open_corrections(root)
    return {
        "project": project,
        "paths": scan_paths,
        "citations_available": cite_result.get("available", False),
        "note": cite_result.get("note"),
        "touched_files": touched_files,
        "remaining": buckets,
        "total_remaining": total_remaining,
        "open_corrections": open_corrections,
        "open_corrections_total": len(open_corrections),
    }
