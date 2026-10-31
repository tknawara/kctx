"""Node-identity normalization, so a citation's `repo=` field resolves to one
node id regardless of which alias the author typed.

Prototype finding (scratch/2026-10-30-dolt-graph/RESULTS.md, "Identity-
normalization gap"): two proposals cited the same tnawara/kb repo under two
different literal `repo=` strings -- `repo=kb` (the local checkout's
directory name) and `repo=tnawara/kb` (org/repo form) -- and a naive
`code:{repo}:{path}` node-id scheme split them into two nodes. cite.py
already resolves a local checkout's bare directory name to its canonical
org/repo form at citation-*authoring* time (`resolve_repo_for_make`, for a
local path argument); this module applies the same resolution post hoc, at
extraction time, to whatever repo alias already landed in a written citation.
"""

from pathlib import Path
from typing import Optional


def _repo_from_url(url: str, cite_mod) -> Optional[str]:
    """Prefers cite.py's own `_repo_field_from_url` (handles file://,
    Windows drive-letter paths, scp-like vs scheme-based remotes); falls
    back to the older, narrower `_org_repo_from_url` for a deployed skill
    that hasn't picked up the newer helper yet -- a real, observed gap: the
    laptop's own ~/.claude/skills/grounding/cite.py lagged the dotfiles
    checkout by exactly this function at the time this was written."""
    repo_from_url = getattr(cite_mod, "_repo_field_from_url", None)
    if repo_from_url is not None:
        return repo_from_url(url)
    org_repo = cite_mod._org_repo_from_url(url)
    return "/".join(org_repo) if org_repo else None


def canonical_repo(
    repo_field: Optional[str],
    url_field: Optional[str],
    kb_root: Path,
    cite_mod,
) -> str:
    """Resolve a citation's `repo=`/`url=` fields to one canonical identity.

    1. A `url=` field is the most explicit signal: resolve org/repo from it
       via cite.py's own `_repo_field_from_url` (same helper `cite make`
       uses for a local-checkout `repo` argument).
    2. An org/repo-shaped `repo=` field is already canonical.
    3. A bare alias that matches this checkout's own directory name (e.g.
       `repo=kb` written from inside /home/tnawara/workspace/kb) is resolved
       the same way: read this checkout's own `git remote get-url origin`
       and derive org/repo from it.
    4. Anything else is returned unchanged -- an unresolvable alias is a gap
       to report (see graph.extract's unresolved-alias counter), not one to
       paper over with an invented mapping.
    """
    if url_field:
        canon = _repo_from_url(url_field, cite_mod)
        if canon:
            return canon
    if not repo_field:
        return repo_field or ""
    if cite_mod.ORG_REPO_RE.match(repo_field):
        return repo_field
    if repo_field == kb_root.name:
        origin = cite_mod.get_origin_url(kb_root)
        canon = _repo_from_url(origin, cite_mod) if origin else None
        if canon:
            return canon
    return repo_field
