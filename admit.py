"""`kctx admit`: event-driven complement to `kctx stale --drain`. Where drain
is a session-driven sweep, admit reacts to code actually landing on a repo's
default branch (or one merged PR), refreshes exactly the citations that
intersect the changed paths, and reports -- never edits -- the judgment calls
(STATUS/inventory lines, ktlo, investigations, open signatures, asset
verified_at, dossiers) that a human still has to make.

Git plumbing (the shared blobless cache clone, default-branch resolution) is
imported directly from the grounding skill's cite.py rather than duplicated,
the same script nav.py shells out to for `cite check`/`cite stale`. PR state
needs `gh`, which cite.py deliberately never calls (LOCATORS.md: git only) --
that network edge lives here instead, via an injectable `gh` binary so tests
never hit bbgithub.
"""

import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import dossiers as dossiers_mod
import inventory
import investigations as inv_mod
import ktlo as ktlo_mod
import nav
import signatures as sig_mod
from errors import KctxError
from storage import atomic_write_json, iso_now, read_json

CITE_LINE_RE = re.compile(r"⟦cite(?P<body>.*?)⟧", re.DOTALL)
FIELD_RE = re.compile(r'(\w+)=(?:"([^"]*)"|(\S+))')
ORG_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PR_SHORTCUT_RE = re.compile(r"^([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+)$")
PR_URL_RE = re.compile(r"[\w.-]+/([^/]+)/([^/]+)/pull(?:s)?/(\d+)")

GH_HOSTNAME = "bbgithub.dev.bloomberg.com"


# --------------------------------------------------------------------------
# cite.py reuse: import its git plumbing directly rather than shelling out
# through a CLI surface it doesn't have for this (ensure_cache_clone and
# resolve_default_branch_rev aren't `cite` subcommands).
# --------------------------------------------------------------------------


def load_cite_module():
    cite_bin = nav.locate_cite_bin()
    if cite_bin is None:
        return None
    cite_py = Path(cite_bin).resolve().parent / "cite.py"
    if not cite_py.is_file():
        return None
    spec = importlib.util.spec_from_file_location("kctx_admit_cite", cite_py)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_cite_body(body: str) -> Dict[str, str]:
    fields = {}
    for m in FIELD_RE.finditer(body):
        key = m.group(1)
        val = m.group(2) if m.group(2) is not None else m.group(3)
        fields[key] = val
    return fields


def _format_field(key: str, value: Any) -> str:
    value = str(value)
    if re.search(r"\s", value) or value == "":
        return f'{key}="{value}"'
    return f"{key}={value}"


def _replace_field(raw_cite: str, key: str, new_value: str) -> str:
    token = _format_field(key, new_value)
    pattern = re.compile(rf'\b{re.escape(key)}=(?:"[^"]*"|\S+)')
    new_text, n = pattern.subn(token, raw_cite, count=1)
    if n:
        return new_text
    if raw_cite.endswith("⟧"):
        return raw_cite[:-1].rstrip() + " " + token + "⟧"
    return raw_cite + " " + token


def _all_md_files(root: Path) -> List[Path]:
    return sorted(root.rglob("*.md"))


# --------------------------------------------------------------------------
# Cursors: inventory/cursors/<org>__<repo>.json
# --------------------------------------------------------------------------


def cursors_dir(root: Path) -> Path:
    return root / "inventory" / "cursors"


def cursor_path(root: Path, org: str, name: str) -> Path:
    return cursors_dir(root) / f"{org}__{name}.json"


def load_cursor(root: Path, org: str, name: str) -> Optional[Dict[str, Any]]:
    p = cursor_path(root, org, name)
    if not p.exists():
        return None
    return read_json(p)


def save_cursor(
    root: Path,
    org: str,
    name: str,
    sha: str,
    by: str = "kctx admit",
    pending: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Write the cursor.

    Handover 8.3: the cursor records *scanned-through* `sha` separately from
    completed admission — unresolved judgment items are persisted alongside
    it (never dropped by advancing), so pending work survives a second
    no-change invocation, a restart, or a partial failure.
    """
    atomic_write_json(
        cursor_path(root, org, name),
        {
            "repo": f"{org}/{name}",
            "sha": sha,
            "admitted_at": iso_now(),
            "by": by,
            "pending": pending or [],
        },
    )


def _judgment_key(item: Dict[str, Any]) -> str:
    """Stable identity for deduplicating pending judgment items across
    runs: file + line (position-stable) falling back to reason + excerpt."""
    return "{file}:{line}:{reason}:{excerpt}".format(
        file=item.get("file", ""),
        line=item.get("line_no", item.get("line", "")),
        reason=item.get("reason", ""),
        excerpt=item.get("excerpt", ""),
    )


def merge_pending(
    prior: Optional[List[Dict[str, Any]]], new: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Idempotent merge: prior pending items survive, new duplicates of
    them don't double up."""
    seen = set()
    out: List[Dict[str, Any]] = []
    for item in list(prior or []) + list(new):
        key = _judgment_key(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def parse_org_repo(repo: str) -> Tuple[str, str]:
    if not ORG_REPO_RE.match(repo):
        raise KctxError("malformed", f"{repo!r} is not an org/repo spec")
    org, name = repo.split("/", 1)
    return org, name


def parse_pr_ref(ref: str) -> Tuple[str, str, int]:
    m = PR_SHORTCUT_RE.match(ref)
    if m:
        org, name = m.group(1).split("/", 1)
        return org, name, int(m.group(2))
    m = PR_URL_RE.search(ref)
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    raise KctxError("malformed", f"{ref!r} is not a PR url or org/repo#N")


# --------------------------------------------------------------------------
# gh: PR resolution and state, the one network edge cite.py never takes
# --------------------------------------------------------------------------


def gh_binary() -> str:
    return os.environ.get("KCTX_GH", "gh")


def fetch_pr(org: str, name: str, number: int) -> Dict[str, Any]:
    cmd = [
        gh_binary(),
        "api",
        f"repos/{org}/{name}/pulls/{number}",
        "--hostname",
        GH_HOSTNAME,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise KctxError("timeout", f"gh api pulls/{number} failed to run: {e}")
    if proc.returncode != 0:
        raise KctxError(
            "not-found",
            f"gh api repos/{org}/{name}/pulls/{number} failed: "
            f"{(proc.stderr or '').strip()[:300]}",
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise KctxError("malformed", f"gh api pulls/{number} returned unparseable JSON")


def _pr_state(pr: Dict[str, Any]) -> str:
    return "merged" if pr.get("merged") else (pr.get("state") or "open")


def refresh_pr_citations(
    root: Path, repo_full: str, *, dry_run: bool = False
) -> Dict[str, Any]:
    """Finds every `kind=pr repo=<repo_full>` citation anywhere in the KB,
    resolves its current state via `gh`, and rewrites `state=`/`seen=` in
    place when it changed. Returns every PR number found to be merged
    (whether freshly rewritten or already marked so), which is also the input
    the judgment scan greps for."""
    org, name = parse_org_repo(repo_full)
    updated: List[Dict[str, Any]] = []
    merged_numbers: Set[int] = set()
    unresolved: List[Dict[str, Any]] = []
    checked: Dict[str, Optional[str]] = {}

    for p in _all_md_files(root):
        text = p.read_text(encoding="utf-8")
        if "⟦cite" not in text or "kind=pr" not in text:
            continue
        new_text = text
        offset = 0
        for m in CITE_LINE_RE.finditer(text):
            fields = _parse_cite_body(m.group("body"))
            if fields.get("kind") != "pr" or fields.get("repo") != repo_full:
                continue
            n = fields.get("n")
            if not n:
                continue
            if n not in checked:
                try:
                    checked[n] = _pr_state(fetch_pr(org, name, int(n)))
                except KctxError as e:
                    checked[n] = None
                    unresolved.append({"n": n, "reason": e.message})
            state = checked[n]
            if state is None:
                continue
            if state == "merged":
                merged_numbers.add(int(n))
            if fields.get("state") == state:
                continue
            raw = m.group(0)
            new_raw = _replace_field(raw, "state", state)
            new_raw = _replace_field(new_raw, "seen", nav.iso_now_minute())
            start, end = m.start() + offset, m.end() + offset
            new_text = new_text[:start] + new_raw + new_text[end:]
            offset += len(new_raw) - (end - start)
            updated.append({"file": str(p), "n": n, "state": state})
        if not dry_run and new_text != text:
            p.write_text(new_text, encoding="utf-8")

    return {
        "updated": updated,
        "merged_numbers": sorted(merged_numbers),
        "unresolved": unresolved,
    }


# --------------------------------------------------------------------------
# Code citations: grep the KB, run cite check --touch --mark only over the
# files holding a citation on a path that actually changed.
# --------------------------------------------------------------------------

_EMPTY_DRAIN = {
    "project": None,
    "paths": [],
    "citations_available": True,
    "note": None,
    "touched_files": [],
    "remaining": {
        "expired_noncode": [],
        "changed_gone_code": [],
        "changed_gone_other": [],
        "unverifiable": [],
    },
    "total_remaining": 0,
}


def find_citing_files(root: Path, repo_full: str, changed_paths: Set[str]) -> List[str]:
    hits: Set[str] = set()
    for p in _all_md_files(root):
        text = p.read_text(encoding="utf-8")
        if "⟦cite" not in text or "kind=code" not in text:
            continue
        for m in CITE_LINE_RE.finditer(text):
            fields = _parse_cite_body(m.group("body"))
            if (
                fields.get("kind") == "code"
                and fields.get("repo") == repo_full
                and fields.get("path") in changed_paths
            ):
                hits.add(str(p))
                break
    return sorted(hits)


def refresh_code_citations(
    root: Path, repo_full: str, changed_paths: Set[str], *, dry_run: bool = False
) -> Dict[str, Any]:
    matching = find_citing_files(root, repo_full, changed_paths)
    if not matching:
        return dict(_EMPTY_DRAIN)
    if dry_run:
        cite_result = nav.run_cite_check(matching, touch=False, mark=False)
        buckets = nav.bucket_cite_results(cite_result.get("results", []))
        return {
            "project": None,
            "paths": matching,
            "citations_available": cite_result.get("available", False),
            "note": cite_result.get("note"),
            "touched_files": [],
            "remaining": buckets,
            "total_remaining": sum(len(v) for v in buckets.values()),
        }
    return nav.drain(root, paths=matching)


# --------------------------------------------------------------------------
# Git diff over the shared cache clone
# --------------------------------------------------------------------------


def diff_name_status(
    cite_mod, repo_path: Path, base: str, head: str
) -> List[Dict[str, str]]:
    r = cite_mod._run_git(
        ["diff", "--name-status", "-M", f"{base}..{head}"],
        cwd=repo_path,
        timeout=60,
    )
    if r.returncode != 0:
        raise KctxError(
            "not-found", f"git diff {base}..{head} failed: {r.stderr.strip()}"
        )
    changes = []
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R") and len(parts) == 3:
            changes.append({"status": "R", "old": parts[1], "new": parts[2]})
        elif len(parts) == 2:
            changes.append({"status": status, "path": parts[1]})
    return changes


def _changed_path_set(changes: List[Dict[str, str]]) -> Set[str]:
    out: Set[str] = set()
    for c in changes:
        if "path" in c:
            out.add(c["path"])
        if "old" in c:
            out.add(c["old"])
        if "new" in c:
            out.add(c["new"])
    return out


def resolve_since(cite_mod, repo_path: Path, since: str, head: str) -> str:
    sha = cite_mod.git_rev_parse(repo_path, since)
    if sha:
        return sha
    r = cite_mod._run_git(["rev-list", "-1", f"--before={since}", head], cwd=repo_path)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    raise KctxError(
        "malformed",
        f"--since {since!r} did not resolve to a revision or a date on {head}",
    )


def _is_ancestor(cite_mod, repo_path: Path, maybe_ancestor: str, rev: str) -> bool:
    r = cite_mod._run_git(
        ["merge-base", "--is-ancestor", maybe_ancestor, rev], cwd=repo_path
    )
    return r.returncode == 0


# --------------------------------------------------------------------------
# Judgment scan: report-only, never edited here.
# --------------------------------------------------------------------------


def _mentions(text: str, repo_full: str, pr_numbers: List[int]) -> bool:
    if repo_full in text:
        return True
    return any(f"#{n}" in text or f"pulls/{n}" in text for n in pr_numbers)


def _grep_lines(
    root: Path, path: Path, repo_full: str, pr_numbers: List[int], reason: str
) -> List[Dict[str, Any]]:
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if _mentions(line, repo_full, pr_numbers):
            out.append(
                {
                    "file": str(path.relative_to(root)),
                    "line_no": i,
                    "reason": reason,
                    "excerpt": line.strip(),
                }
            )
    return out


def judgment_scan(
    root: Path, repo_full: str, pr_numbers: List[int]
) -> List[Dict[str, Any]]:
    """Mentions of the repo or a merged PR number in places admit never
    edits: project STATUS/inventory lines, ktlo records, investigation
    follow-ups, open (no fixed_at) signatures, and any asset/dossier whose
    locator is this repo."""
    items: List[Dict[str, Any]] = []

    for proj in nav.project_dirs(root):
        for fname in ("STATUS.md", "inventory.md"):
            p = proj / fname
            if p.is_file():
                items.extend(
                    _grep_lines(root, p, repo_full, pr_numbers, "project reference")
                )

    for p in ktlo_mod.all_paths(root):
        items.extend(_grep_lines(root, p, repo_full, pr_numbers, "ktlo record"))

    for p in sig_mod.all_paths(root):
        parsed = sig_mod.parse(p.read_text(encoding="utf-8"))
        if parsed["frontmatter"].get("fixed_at"):
            continue
        items.extend(_grep_lines(root, p, repo_full, pr_numbers, "open signature"))

    for p in inv_mod.all_paths(root):
        items.extend(_grep_lines(root, p, repo_full, pr_numbers, "investigation"))

    for a in inventory.load_all_assets(root):
        if a.locator and repo_full in a.locator:
            asset_path = inventory.assets_dir(root) / f"{a.id}.json"
            line_no = 1
            for i, line in enumerate(
                asset_path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if '"locator"' in line:
                    line_no = i
                    break
            items.append(
                {
                    "file": str(asset_path.relative_to(root)),
                    "line_no": line_no,
                    "reason": "asset verified_at candidate",
                    "excerpt": f"asset {a.id} locator={a.locator}",
                }
            )
            dossier_path = dossiers_mod.for_asset(root, a.id)
            if dossier_path is not None:
                items.append(
                    {
                        "file": str(dossier_path.relative_to(root)),
                        "line_no": 1,
                        "reason": "dossier for repo asset",
                        "excerpt": f"dossier for {a.id}",
                    }
                )

    return items


# --------------------------------------------------------------------------
# kctx admit --repo
# --------------------------------------------------------------------------


def admit_repo(
    root: Path, repo: str, *, since: Optional[str] = None, dry_run: bool = False
) -> Dict[str, Any]:
    org, name = parse_org_repo(repo)
    repo_full = f"{org}/{name}"

    cite_mod = load_cite_module()
    if cite_mod is None:
        return {
            "repo": repo_full,
            "exit_code": 3,
            "blocked_reason": "cite script not found; cannot resolve the shared cache clone",
        }

    cursor = load_cursor(root, org, name)
    if cursor is None and not since:
        return {
            "repo": repo_full,
            "exit_code": 3,
            "blocked_reason": "no cursor for this repo and no --since given",
        }

    cache_path = cite_mod.get_cache_path(org, name)
    try:
        cite_mod.ensure_cache_clone(cache_path, org, name)
        head = cite_mod.resolve_default_branch_rev(cache_path)
    except cite_mod.CiteError as e:
        return {
            "repo": repo_full,
            "exit_code": 3,
            "blocked_reason": f"could not resolve {repo_full}'s cache clone: {e.message}",
        }

    if cursor is not None:
        base = cursor["sha"]
        if not _is_ancestor(cite_mod, cache_path, base, head):
            return {
                "repo": repo_full,
                "exit_code": 3,
                "blocked_reason": (
                    f"cursor {base[:12]} is not an ancestor of default-branch head "
                    f"{head[:12]} (force-push or history rewrite?); cursor left unchanged"
                ),
            }
    else:
        try:
            base = resolve_since(cite_mod, cache_path, since, head)
        except KctxError as e:
            return {"repo": repo_full, "exit_code": 3, "blocked_reason": e.message}

    if base == head:
        changes: List[Dict[str, str]] = []
    else:
        try:
            changes = diff_name_status(cite_mod, cache_path, base, head)
        except KctxError as e:
            return {"repo": repo_full, "exit_code": 3, "blocked_reason": e.message}
    changed_paths = _changed_path_set(changes)

    code_result = refresh_code_citations(
        root, repo_full, changed_paths, dry_run=dry_run
    )
    pr_result = refresh_pr_citations(root, repo_full, dry_run=dry_run)
    judgment_new = judgment_scan(root, repo_full, pr_result["merged_numbers"])

    # Pending judgment work is carried in the cursor: a second no-change
    # invocation re-reports it (it is not re-discovered — the PR range is
    # empty once the cursor has advanced), and advancing the cursor never
    # drops it.
    prior_pending = list((cursor or {}).get("pending") or [])
    judgment = merge_pending(prior_pending, judgment_new)

    if not dry_run and code_result["citations_available"]:
        save_cursor(root, org, name, head, pending=judgment)

    total_remaining = code_result["total_remaining"] + len(judgment)
    if not code_result["citations_available"]:
        exit_code = 3
    elif total_remaining == 0:
        exit_code = 0
    else:
        exit_code = 2

    return {
        "repo": repo_full,
        "base": base,
        "head": head,
        "dry_run": dry_run,
        "changed_paths": sorted(changed_paths),
        "code_citations": code_result,
        "pr_citations": pr_result,
        "judgment": judgment,
        "judgment_new": judgment_new,
        "pending_judgment": judgment,
        "scanned_through": head,
        "cursor_advanced": (not dry_run) and code_result["citations_available"],
        "exit_code": exit_code,
    }


# --------------------------------------------------------------------------
# kctx admit <PR url | org/repo#N>
# --------------------------------------------------------------------------


def admit_pr(root: Path, pr_ref: str, *, dry_run: bool = False) -> Dict[str, Any]:
    org, name, number = parse_pr_ref(pr_ref)
    repo_full = f"{org}/{name}"

    try:
        pr = fetch_pr(org, name, number)
    except KctxError as e:
        return {
            "repo": repo_full,
            "pr": number,
            "exit_code": 3,
            "blocked_reason": e.message,
        }

    if not pr.get("merged"):
        return {
            "repo": repo_full,
            "pr": number,
            "exit_code": 2,
            "note": f"PR #{number} is not merged",
        }

    merge_sha = pr.get("merge_commit_sha")
    if not merge_sha:
        return {
            "repo": repo_full,
            "pr": number,
            "exit_code": 3,
            "blocked_reason": "gh reported merged=true but no merge_commit_sha",
        }

    cite_mod = load_cite_module()
    if cite_mod is None:
        return {
            "repo": repo_full,
            "pr": number,
            "exit_code": 3,
            "blocked_reason": "cite script not found; cannot resolve the shared cache clone",
        }

    cache_path = cite_mod.get_cache_path(org, name)
    try:
        cite_mod.ensure_cache_clone(cache_path, org, name)
        parent = cite_mod.git_rev_parse(cache_path, f"{merge_sha}^")
        if not parent:
            raise cite_mod.CiteError(
                "not-found", f"{merge_sha} has no parent in the cache clone"
            )
        changes = diff_name_status(cite_mod, cache_path, parent, merge_sha)
    except cite_mod.CiteError as e:
        return {
            "repo": repo_full,
            "pr": number,
            "exit_code": 3,
            "blocked_reason": f"could not diff PR #{number}'s merge commit: {e.message}",
        }
    changed_paths = _changed_path_set(changes)

    code_result = refresh_code_citations(
        root, repo_full, changed_paths, dry_run=dry_run
    )
    pr_result = refresh_pr_citations(root, repo_full, dry_run=dry_run)
    judgment = judgment_scan(root, repo_full, pr_result["merged_numbers"])

    total_remaining = code_result["total_remaining"] + len(judgment)
    if not code_result["citations_available"]:
        exit_code = 3
    elif total_remaining == 0:
        exit_code = 0
    else:
        exit_code = 2

    return {
        "repo": repo_full,
        "pr": number,
        "merge_commit_sha": merge_sha,
        "dry_run": dry_run,
        "changed_paths": sorted(changed_paths),
        "code_citations": code_result,
        "pr_citations": pr_result,
        "judgment": judgment,
        "exit_code": exit_code,
    }


# --------------------------------------------------------------------------
# dispatch helper: distinguish `--repo org/repo` from a PR ref positional arg
# --------------------------------------------------------------------------


def admit(
    root: Path,
    *,
    repo: Optional[str] = None,
    pr_ref: Optional[str] = None,
    since: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    if repo and pr_ref:
        raise KctxError("malformed", "pass either --repo or a PR reference, not both")
    if repo:
        return admit_repo(root, repo, since=since, dry_run=dry_run)
    if pr_ref:
        return admit_pr(root, pr_ref, dry_run=dry_run)
    raise KctxError("incomplete", "admit requires --repo <org/repo> or a PR reference")
