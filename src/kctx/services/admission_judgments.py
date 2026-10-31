"""Report human judgments without editing the authored records."""

from pathlib import Path

from kctx.services import dossiers as dossiers_mod
from kctx.services import inventory
from kctx.services import investigations as inv_mod
from kctx.services import ktlo as ktlo_mod
from kctx.services import signatures as sig_mod
from kctx.services.admission_state import Judgment
from kctx.services.discovery import project_dirs


def _mentions(text: str, repo_full: str, pr_numbers: list[int]) -> bool:
    if repo_full in text:
        return True
    return any(f"#{n}" in text or f"pulls/{n}" in text for n in pr_numbers)


def _grep_lines(
    root: Path, path: Path, repo_full: str, pr_numbers: list[int], reason: str
) -> list[Judgment]:
    out: list[Judgment] = []
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


def judgment_scan(root: Path, repo_full: str, pr_numbers: list[int]) -> list[Judgment]:
    """Mentions of the repo or a merged PR number in places admit never
    edits: project STATUS/inventory lines, ktlo records, investigation
    follow-ups, open (no fixed_at) signatures, and any asset/dossier whose
    locator is this repo."""
    items: list[Judgment] = []

    for proj in project_dirs(root):
        for fname in ("STATUS.md", "inventory.md"):
            p = proj / fname
            if p.is_file():
                items.extend(_grep_lines(root, p, repo_full, pr_numbers, "project reference"))

    for p in ktlo_mod.all_paths(root):
        items.extend(_grep_lines(root, p, repo_full, pr_numbers, "ktlo record"))

    for p in sig_mod.all_paths(root):
        parsed = sig_mod.parse(p.read_text(encoding="utf-8"))
        if parsed.frontmatter.fixed_at:
            continue
        items.extend(_grep_lines(root, p, repo_full, pr_numbers, "open signature"))

    for p in inv_mod.all_paths(root):
        items.extend(_grep_lines(root, p, repo_full, pr_numbers, "investigation"))

    for a in inventory.load_all_assets(root):
        if a.locator and repo_full in a.locator:
            asset_path = inventory.assets_dir(root) / f"{a.id}.json"
            line_no = 1
            for i, line in enumerate(asset_path.read_text(encoding="utf-8").splitlines(), start=1):
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
