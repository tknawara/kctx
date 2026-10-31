"""Node-identity normalization, so a citation's `repo=` field resolves to one
node id regardless of which alias the author typed.

Prototype finding (scratch/2026-10-30-dolt-graph/RESULTS.md, "Identity-
normalization gap"): two proposals cited the same tnawara/kb repo under two
different literal `repo=` strings -- `repo=kb` (the local checkout's
directory name) and `repo=tnawara/kb` (org/repo form) -- and a naive
`code:{repo}:{path}` node-id scheme split them into two nodes. The built-in
citation Git adapter resolves aliases identically for citation authoring and
graph extraction, so written aliases do not create duplicate identities.
"""

from dataclasses import dataclass
from pathlib import Path

from kctx.adapters.git.citations import ORG_REPO_RE, get_origin_url, repo_from_url


@dataclass(frozen=True, slots=True)
class RepositoryIdentity:
    checkout_name: str
    origin_url: str | None


def capture_repository_identity(kb_root: Path) -> RepositoryIdentity:
    return RepositoryIdentity(kb_root.name, get_origin_url(kb_root))


def canonical_repo(
    repo_field: str | None,
    url_field: str | None,
    identity: RepositoryIdentity,
) -> str:
    """Resolve a citation's `repo=`/`url=` fields to one canonical identity.

    1. A `url=` field is the most explicit signal: resolve org/repo with the
       shared citation Git adapter.
    2. An org/repo-shaped `repo=` field is already canonical.
    3. A bare alias matching the captured checkout name resolves using the
       captured origin URL. No mutable Git/config read occurs per token.
    4. Anything else is returned unchanged -- an unresolvable alias is a gap
       to report (see graph.extract's unresolved-alias counter), not one to
       paper over with an invented mapping.
    """
    if url_field:
        canon = repo_from_url(url_field)
        if canon:
            return "/".join(canon)
    if not repo_field:
        return repo_field or ""
    if ORG_REPO_RE.match(repo_field):
        return repo_field
    if repo_field == identity.checkout_name:
        canon = repo_from_url(identity.origin_url) if identity.origin_url else None
        if canon:
            return "/".join(canon)
    return repo_field
