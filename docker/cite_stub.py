"""Container-only stub of the grounding skill's cite.py.

The real cite.py lives in the user's dotfiles checkout (work environment);
the compose verify stack pins KCTX_CITE_PY here so extraction/sync have a
deterministic citation parser in CI. Exposes exactly the module surface the
graph extractor uses (CITE_LINE_RE, is_illustrative, parse_cite_body,
ORIG_REPO_RE/canonical_repo conventions). NOT a production parser — results
against real citations must be qualified with the real skill (G13 in
docs/kctx/gates.md).
"""

import re

CITE_LINE_RE = re.compile(r"⟦cite (?P<body>.*?)⟧", re.DOTALL)

_FIELD_RE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<val>\"[^\"]*\"|[^\s⟧]+)")

_ILLUS_MARKERS = ("illustrative", "illus", "example")


def is_illustrative(body: str) -> bool:
    low = body.lower()
    return any(m in low for m in _ILLUS_MARKERS)


def parse_cite_body(body: str) -> dict:
    out = {}
    for m in _FIELD_RE.finditer(body):
        val = m.group("val")
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        out[m.group("key")] = val
    return out


# canonical_repo() in identity.py consults these on the loaded cite module.
ORG_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _org_repo_from_url(url):
    m = re.search(r"github[^/]+/([^/]+/[^/]+?)(?:\.git)?$", url or "")
    return m.group(1) if m else None


def get_origin_url(kb_root):
    # container stub: no real remotes; identity.py falls back to the repo=
    # field when this returns None
    return None
