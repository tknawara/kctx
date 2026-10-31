"""Refresh citations affected by landed changes, retaining provider failures."""

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import TypedDict

from kctx.adapters.files.contained import ContainedFile, contained_markdown
from kctx.citations.scan import run_check
from kctx.citations.syntax import (
    CITE_LINE_RE,
    is_illustrative,
    parse_cite_body,
    remove_field,
    replace_field,
)
from kctx.citations.time import iso_now_minute
from kctx.config import Config
from kctx.domain.json import object_value, text
from kctx.errors import KctxError
from kctx.services.freshness import DrainResult, bucket_cite_results, drain


class PullRequest(TypedDict):
    merged: bool
    state: str
    merge_commit_sha: str | None


class PrUpdate(TypedDict):
    file: str
    n: str
    state: str


class PrUnresolved(TypedDict):
    n: str
    reason: str


class PrRefresh(TypedDict):
    updated: list[PrUpdate]
    merged_numbers: list[int]
    unresolved: list[PrUnresolved]


def decode_pr(value: object) -> PullRequest:
    fields = object_value(value, "pull request")
    merged = fields.get("merged", False)
    if not isinstance(merged, bool):
        raise KctxError("malformed", "pull request merged must be boolean")
    sha = fields.get("merge_commit_sha")
    return {
        "merged": merged,
        "state": text(fields.get("state", "open"), "pull request state"),
        "merge_commit_sha": None if sha is None else text(sha, "merge commit sha"),
    }


def gh_binary() -> str:
    configured = Config.load().gh_bin
    return str(configured) if configured is not None else (shutil.which("gh") or "gh")


def empty_drain() -> DrainResult:
    return {
        "project": None,
        "paths": [],
        "citations_available": True,
        "note": None,
        "touched_files": [],
        "remaining": bucket_cite_results([]),
        "total_remaining": 0,
    }


ORG_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


PR_SHORTCUT_RE = re.compile(r"^([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+)$")


PR_URL_RE = re.compile(r"[\w.-]+/([^/]+)/([^/]+)/pull(?:s)?/(\d+)")


def parse_org_repo(repo: str) -> tuple[str, str]:
    if not ORG_REPO_RE.match(repo):
        raise KctxError("malformed", f"{repo!r} is not an org/repo spec")
    org, name = repo.split("/", 1)
    return org, name


def parse_pr_ref(ref: str) -> tuple[str, str, int]:
    m = PR_SHORTCUT_RE.match(ref)
    if m:
        org, name = m.group(1).split("/", 1)
        return org, name, int(m.group(2))
    m = PR_URL_RE.search(ref)
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    raise KctxError("malformed", f"{ref!r} is not a PR url or org/repo#N")


def fetch_pr(org: str, name: str, number: int) -> PullRequest:
    cmd = [
        gh_binary(),
        "api",
        f"repos/{org}/{name}/pulls/{number}",
        "--hostname",
        Config.load().github_host,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise KctxError("timeout", f"gh api pulls/{number} failed to run: {e}") from e
    if proc.returncode != 0:
        raise KctxError(
            "not-found",
            f"gh api repos/{org}/{name}/pulls/{number} failed: {(proc.stderr or '').strip()[:300]}",
        )
    try:
        return decode_pr(json.loads(proc.stdout))
    except json.JSONDecodeError:
        raise KctxError("malformed", f"gh api pulls/{number} returned unparseable JSON") from None


def _pr_state(pr: PullRequest) -> str:
    return "merged" if pr.get("merged") else (pr.get("state") or "open")


def refresh_pr_citations(root: Path, repo_full: str, *, dry_run: bool = False) -> PrRefresh:
    """Record a current PR-state advisory without changing the cited observation.

    Original state/seen and pinned locator fields remain immutable. The latest
    checked_at/current_state receipt is advisory, not a renewed observation.
    Every currently merged PR still participates in the judgment scan.
    """
    org, name = parse_org_repo(repo_full)
    updated: list[PrUpdate] = []
    merged_numbers: set[int] = set()
    unresolved: list[PrUnresolved] = []
    checked: dict[str, str | None] = {}

    with contained_markdown([str(root)], writable=not dry_run) as sources:
        updates: list[tuple[ContainedFile, str]] = []
        for source in sources:
            p = source.path
            text = source.text()
            if "⟦cite" not in text:
                continue
            new_text = text
            offset = 0
            for m in CITE_LINE_RE.finditer(text):
                if is_illustrative(m.group("body")):
                    continue
                fields = parse_cite_body(m.group("body"))
                if fields.get("kind") != "pr" or fields.get("repo") != repo_full:
                    continue
                n = fields.get("n")
                if not n:
                    continue
                if n not in checked:
                    try:
                        if not n.isdecimal():
                            raise KctxError(
                                "malformed", f"citation PR number {n!r} is not an integer"
                            )
                        checked[n] = _pr_state(fetch_pr(org, name, int(n)))
                    except KctxError as e:
                        checked[n] = None
                        unresolved.append({"n": n, "reason": e.message})
                state = checked[n]
                if state is None:
                    continue
                if state == "merged":
                    merged_numbers.add(int(n))
                raw = m.group(0)
                new_raw = replace_field(raw, "current_state", state)
                new_raw = replace_field(new_raw, "checked_at", iso_now_minute())
                new_raw = replace_field(new_raw, "check_status", "pr-observed")
                for key in ("current_rev", "current_L"):
                    if key in fields:
                        new_raw = remove_field(new_raw, key)
                if new_raw == raw:
                    continue
                start, end = m.start() + offset, m.end() + offset
                new_text = new_text[:start] + new_raw + new_text[end:]
                offset += len(new_raw) - (end - start)
                updated.append({"file": str(p), "n": n, "state": state})
            if not dry_run and new_text != text:
                updates.append((source, new_text))
        ContainedFile.write_updates(updates)

    return {
        "updated": updated,
        "merged_numbers": sorted(merged_numbers),
        "unresolved": unresolved,
    }


def find_citing_files(root: Path, repo_full: str, changed_paths: set[str]) -> list[str]:
    hits: set[str] = set()
    with contained_markdown([str(root)]) as sources:
        for source in sources:
            p = source.path
            text = source.text()
            if "⟦cite" not in text:
                continue
            for m in CITE_LINE_RE.finditer(text):
                if is_illustrative(m.group("body")):
                    continue
                fields = parse_cite_body(m.group("body"))
                if (
                    fields.get("kind") == "code"
                    and fields.get("repo") == repo_full
                    and fields.get("path") in changed_paths
                ):
                    hits.add(str(p))
                    break
    return sorted(hits)


def refresh_code_citations(
    root: Path, repo_full: str, changed_paths: set[str], *, dry_run: bool = False
) -> DrainResult:
    matching = find_citing_files(root, repo_full, changed_paths)
    if not matching:
        return empty_drain()
    if dry_run:
        cite_result = run_check(matching, touch=False, mark=False)
        buckets = bucket_cite_results(cite_result.get("results", []))
        return {
            "project": None,
            "paths": matching,
            "citations_available": cite_result.get("available", False),
            "note": cite_result.get("note"),
            "touched_files": [],
            "remaining": buckets,
            "total_remaining": sum(len(v) for v in buckets.values()),
        }
    return drain(root, paths=matching)
