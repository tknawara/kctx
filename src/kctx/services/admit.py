"""Admit landed repository changes without dropping pending human judgments."""

from pathlib import Path
from typing import NotRequired, TypedDict

from kctx.adapters.git.citations import (
    ensure_cache_clone,
    get_cache_path,
    git_rev_parse,
    resolve_default_branch_rev,
)
from kctx.errors import KctxError
from kctx.services.admission_changes import (
    ChangedPath,
    changed_path_set,
    diff_name_status,
    is_ancestor,
    resolve_since,
)
from kctx.services.admission_judgments import judgment_scan
from kctx.services.admission_state import Judgment, load_cursor, merge_pending, save_cursor
from kctx.services.citation_refresh import (
    PrRefresh,
    fetch_pr,
    parse_org_repo,
    parse_pr_ref,
    refresh_code_citations,
    refresh_pr_citations,
)
from kctx.services.freshness import DrainResult


class AdmitResult(TypedDict):
    repo: str
    exit_code: int
    blocked_reason: NotRequired[str]
    note: NotRequired[str]
    pr: NotRequired[int]
    base: NotRequired[str]
    head: NotRequired[str]
    merge_commit_sha: NotRequired[str]
    dry_run: NotRequired[bool]
    changed_paths: NotRequired[list[str]]
    code_citations: NotRequired[DrainResult]
    pr_citations: NotRequired[PrRefresh]
    judgment: NotRequired[list[Judgment]]
    judgment_new: NotRequired[list[Judgment]]
    pending_judgment: NotRequired[list[Judgment]]
    scanned_through: NotRequired[str]
    cursor_advanced: NotRequired[bool]


def admit_repo(
    root: Path, repo: str, *, since: str | None = None, dry_run: bool = False
) -> AdmitResult:
    org, name = parse_org_repo(repo)
    repo_full = f"{org}/{name}"

    cursor = load_cursor(root, org, name)
    if cursor is None and not since:
        return {
            "repo": repo_full,
            "exit_code": 3,
            "blocked_reason": "no cursor for this repo and no --since given",
        }

    cache_path = get_cache_path(org, name)
    try:
        ensure_cache_clone(cache_path, org, name)
        head = resolve_default_branch_rev(cache_path)
    except KctxError as e:
        return {
            "repo": repo_full,
            "exit_code": 3,
            "blocked_reason": f"could not resolve {repo_full}'s cache clone: {e.message}",
        }

    if cursor is not None:
        base = cursor["sha"]
        if not is_ancestor(cache_path, base, head):
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
            assert since is not None
            base = resolve_since(cache_path, since, head)
        except KctxError as e:
            return {"repo": repo_full, "exit_code": 3, "blocked_reason": e.message}

    if base == head:
        changes: list[ChangedPath] = []
    else:
        try:
            changes = diff_name_status(cache_path, base, head)
        except KctxError as e:
            return {"repo": repo_full, "exit_code": 3, "blocked_reason": e.message}
    changed_paths = changed_path_set(changes)

    code_result = refresh_code_citations(root, repo_full, changed_paths, dry_run=dry_run)
    pr_result = refresh_pr_citations(root, repo_full, dry_run=dry_run)
    judgment_new = judgment_scan(root, repo_full, pr_result["merged_numbers"])

    # Pending judgment work is carried in the cursor: a second no-change
    # invocation re-reports it (it is not re-discovered — the PR range is
    # empty once the cursor has advanced), and advancing the cursor never
    # drops it.
    prior_pending = cursor["pending"] if cursor is not None else []
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


def admit_pr(root: Path, pr_ref: str, *, dry_run: bool = False) -> AdmitResult:
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

    cache_path = get_cache_path(org, name)
    try:
        ensure_cache_clone(cache_path, org, name)
        parent = git_rev_parse(cache_path, f"{merge_sha}^")
        if not parent:
            raise KctxError("not-found", f"{merge_sha} has no parent in the cache clone")
        changes = diff_name_status(cache_path, parent, merge_sha)
    except KctxError as e:
        return {
            "repo": repo_full,
            "pr": number,
            "exit_code": 3,
            "blocked_reason": f"could not diff PR #{number}'s merge commit: {e.message}",
        }
    changed_paths = changed_path_set(changes)

    code_result = refresh_code_citations(root, repo_full, changed_paths, dry_run=dry_run)
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


def admit(
    root: Path,
    *,
    repo: str | None = None,
    pr_ref: str | None = None,
    since: str | None = None,
    dry_run: bool = False,
) -> AdmitResult:
    if repo and pr_ref:
        raise KctxError("malformed", "pass either --repo or a PR reference, not both")
    if repo:
        return admit_repo(root, repo, since=since, dry_run=dry_run)
    if pr_ref:
        return admit_pr(root, pr_ref, dry_run=dry_run)
    raise KctxError("incomplete", "admit requires --repo <org/repo> or a PR reference")
