"""Extracts citation bindings and typed relationships from every tracked
.md/.json file in the kb repo, at one git commit.

Scope is the prototype's one concrete finding corrected: scratch/
2026-10-30-dolt-graph/RESULTS.md's extractor only walked four record
directories (inventory, signatures, proposals, investigations) and missed
real mentions in ktlo/ and project notes. This module walks *every* tracked
.md/.json file (handover-v2's own wording, design item 5): a file matching a
known record shape (asset/relationship JSON, dossier/sig/inv/proposal/
evidence markdown) gets a record-identity node id; anything else still gets
scanned for ⟦cite⟧ tokens and id mentions, keyed by its path (`doc:<path>`),
so a citation or mention in STATUS.md, a ktlo record, or a project's own
notes is no longer silently invisible to the graph.

Reads the tree via `git archive <sha>` into memory -- never the working
tree, so uncommitted edits in a concurrently-edited checkout never leak into
a sync (see sync.py's docstring for why this matters for --history replay).
"""

import hashlib
import io
import json
import re
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from errors import KctxError

from graph.cite_loader import load_cite_module
from graph.identity import canonical_repo
from graph.models import Edge, Node
from graph.observability import get_logger, run_logged, span

# Mirrors nav._uses_boundary_pattern's id-character class exactly (kept as
# its own copy rather than importing nav, which is being edited concurrently
# this session for the same `uses` id-boundary fix -- see that module's own
# docstring for the false-positive/false-negative reasoning this matches).
_ID_CHARS = "A-Za-z0-9_./-"


def _boundary_pattern(s: str) -> "re.Pattern[str]":
    return re.compile(
        rf"(?<![{_ID_CHARS}]){re.escape(s)}(?![A-Za-z0-9_/-])(?!\.[A-Za-z0-9_])"
    )


SHORT_LOCATOR_RE = re.compile(
    r"^(?P<repo>[\w./-]+)@(?P<rev>[0-9a-fA-F]{7,40}(?:\+dirty)?):(?P<path>[^:]+)"
    r"(?::(?P<L>\d+(?:-\d+)?))?$"
)
PR_REF_RE = re.compile(r"^(?P<repo>[\w./-]+)#(?P<n>\d+)$")
PROPOSAL_ID_RE = re.compile(r"^[\w-]+/\d{4}-\d{2}-\d{2}-[\w-]+$")


def edge_id(
    src_node: str, dst_node: str, rel: str, src_path: Optional[str], src_line: Optional[int],
    ordinal: Optional[int] = None,
) -> str:
    """Includes src_path/src_line (unlike the prototype's edge_id, which
    collapsed every citation from the same src/dst/rel into one row -- see
    RESULTS.md gotcha 5) so two separate citations of the same target from
    the same record each get their own binding row, per handover-v2 S6.2."""
    key = f"{src_node}|{dst_node}|{rel}|{src_path or ''}|{src_line or ''}|{'' if ordinal is None else ordinal}"
    return hashlib.sha256(key.encode()).hexdigest()[:20]


class ExtractStats:
    def __init__(self):
        self.files_scanned = 0
        self.cite_tokens_seen = 0
        self.cite_tokens_illus = 0
        self.cite_tokens_dropped: List[Dict[str, str]] = []
        self.unresolved_repo_aliases: List[str] = []


class GraphBuilder:
    def __init__(self, kb_sha: str, seen_date: str):
        self.kb_sha = kb_sha
        self.seen_date = seen_date
        self.nodes: Dict[str, Node] = {}
        self.edges: Dict[str, Edge] = {}
        self.known_ids: set = set()
        self.stats = ExtractStats()

    def add_node(self, nid: str, kind: str, label: Optional[str] = None, home_path: Optional[str] = None) -> None:
        if not nid:
            return
        if nid not in self.nodes:
            self.nodes[nid] = Node(id=nid, kind=kind, label=label or nid, home_path=home_path)
        self.known_ids.add(nid)

    def add_edge(
        self,
        src_node: str,
        dst_node: str,
        rel: str,
        *,
        src_path: Optional[str] = None,
        src_line: Optional[int] = None,
        cite_kind: Optional[str] = None,
        rev: Optional[str] = None,
        blob_sha: Optional[str] = None,
        span_: Optional[str] = None,
        seen: Optional[str] = None,
        state: Optional[str] = None,
        illus: bool = False,
        ordinal: Optional[int] = None,
        raw: Optional[str] = None,
    ) -> None:
        if not src_node or not dst_node:
            return
        eid = edge_id(src_node, dst_node, rel, src_path, src_line, ordinal)
        self.edges[eid] = Edge(
            edge_id=eid,
            src_node=src_node,
            src_path=src_path,
            src_line=src_line,
            dst_node=dst_node,
            rel=rel,
            cite_kind=cite_kind,
            rev=rev,
            blob_sha=blob_sha,
            span=span_,
            seen=seen or self.seen_date,
            state=state,
            illus=illus,
            raw=raw,
        )


# --------------------------------------------------------------------------
# git plumbing: read every tracked .md/.json file at one sha, in memory
# --------------------------------------------------------------------------
def read_tree_at_sha(kb_root: Path, sha: str) -> Dict[str, str]:
    with span("extract.read_tree", sha=sha):
        proc = run_logged(
            ["git", "-C", str(kb_root), "archive", "--format=tar", sha],
            check=True,
            text=False,
        )
        files: Dict[str, str] = {}
        with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                if not (member.name.endswith(".md") or member.name.endswith(".json")):
                    continue
                data = tf.extractfile(member)
                if data is None:
                    continue
                try:
                    files[member.name] = data.read().decode("utf-8", errors="replace")
                except Exception:
                    continue
    return files


def commit_subject(kb_root: Path, sha: str) -> str:
    proc = run_logged(["git", "-C", str(kb_root), "log", "-1", "--format=%s", sha], check=True)
    return proc.stdout.strip()


def commit_date(kb_root: Path, sha: str) -> str:
    proc = run_logged(["git", "-C", str(kb_root), "log", "-1", "--format=%cI", sha], check=True)
    return proc.stdout.strip()


def first_parent_record_commits(kb_root: Path, limit: Optional[int] = None) -> List[Tuple[str, str, str]]:
    """(sha, iso_date, subject) for first-parent commits touching *.md/*.json,
    oldest first. `limit` keeps only the last N (closest to HEAD)."""
    proc = run_logged(
        [
            "git", "-C", str(kb_root), "log", "--first-parent", "--reverse",
            "--format=%H\x1f%cI\x1f%s", "--", "*.md", "*.json",
        ],
        check=True,
    )
    commits = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        sha, date, subject = line.split("\x1f", 2)
        commits.append((sha, date, subject))
    if limit is not None and limit > 0:
        commits = commits[-limit:]
    return commits


# --------------------------------------------------------------------------
# frontmatter helpers (kb's flat `key: value` block, same shape storage.py's
# read_frontmatter parses -- reimplemented here since extraction works on
# in-memory git-archive text, not files on disk).
# --------------------------------------------------------------------------
def split_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_text = text[4:end]
    body = text[end + 4:].lstrip("\n")
    fm: Dict[str, str] = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm, body


def parse_list_value(v: Optional[str]) -> List[str]:
    v = (v or "").strip()
    if not v or v == "[]":
        return []
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    parts = [p.strip() for p in v.split(",")]
    return [p for p in parts if p]


# --------------------------------------------------------------------------
# citation-token extraction (reuses cite.py's own parser, not a reimplementation)
# --------------------------------------------------------------------------
def _cite_target(
    f: Dict[str, str], kind: str, kb_root: Path, cite_mod
) -> Tuple[Optional[str], str, Optional[str], Dict[str, Any]]:
    """Returns (dst_node_id, dst_kind, label, extra_edge_fields) for one
    parsed ⟦cite ...⟧ body, or (None, ..., ...) only when the body genuinely
    carries no usable identity (never for a merely-uncommon kind -- those
    fall through to the generic hash-keyed branch at the end so nothing is
    silently dropped, per G1)."""
    if kind == "code":
        repo = canonical_repo(f.get("repo"), f.get("url"), kb_root, cite_mod)
        path = f.get("path", "")
        dst = f"code:{repo}:{path}"
        return dst, "code", f"{repo}:{path}", {
            "rev": f.get("rev"), "blob_sha": f.get("blob"), "span_": f.get("span"), "seen": f.get("seen"),
        }
    if kind == "commit":
        repo = canonical_repo(f.get("repo"), f.get("url"), kb_root, cite_mod)
        dst = f"code:{repo}@{f.get('rev')}"
        return dst, "code", dst, {"rev": f.get("rev"), "seen": f.get("seen")}
    if kind == "ev":
        dst = f"ev:{f.get('id')}"
        return dst, "ev", f.get("id"), {"seen": f.get("seen")}
    if kind == "proposal":
        dst = f"proposal:{f.get('id')}"
        return dst, "proposal", f.get("id"), {"state": f.get("state"), "seen": f.get("seen")}
    if kind in ("web", "doc"):
        url = f.get("url", "")
        dst = f"{kind}:{url}" + (f"#{f.get('section')}" if f.get("section") else "")
        return dst, kind, url, {"seen": f.get("seen")}
    if kind == "pr":
        repo = canonical_repo(f.get("repo"), f.get("url"), kb_root, cite_mod)
        n = f.get("n", "")
        dst = f"pr:{repo}#{n}"
        return dst, "pr", dst, {"state": f.get("state"), "seen": f.get("seen")}
    if kind == "ticket":
        dst = f"ticket:{f.get('id')}"
        return dst, "ticket", f.get("id"), {"seen": f.get("seen")}
    if kind == "query":
        key = hashlib.sha256((f.get("sys", "") + f.get("q", "")).encode()).hexdigest()[:12]
        dst = f"query:{key}"
        return dst, "query", f.get("q"), {"seen": f.get("seen")}
    if kind == "record":
        dst = f"doc:{f.get('path')}"
        return dst, "doc", f.get("path"), {"state": f.get("state"), "seen": f.get("seen")}
    if kind == "usr":
        dst = f"usr:{f.get('date')}"
        return dst, "note", dst, {"seen": f.get("seen")}
    # breg/deploy/gate and any future kind: never drop the row for G1's
    # "zero dropped" bar. Node id is stable (hash of the sorted field dict),
    # just not individually typed/identity-resolved the way the common kinds
    # above are -- a real design should split these into their own domain
    # tables (handover-v2 S5.1 already expects this), not extend this branch.
    key = hashlib.sha256(json.dumps(f, sort_keys=True).encode()).hexdigest()[:16]
    dst = f"{kind}:{key}"
    return dst, kind, " ".join(f"{k}={v}" for k, v in sorted(f.items())), {"seen": f.get("seen")}


def scan_cites(
    b: GraphBuilder, src_node: str, src_path: str, text: str, kb_root: Path, cite_mod
) -> None:
    for ordinal, m in enumerate(cite_mod.CITE_LINE_RE.finditer(text)):
        body = m.group("body")
        b.stats.cite_tokens_seen += 1
        illus = cite_mod.is_illustrative(body)
        if illus:
            b.stats.cite_tokens_illus += 1
        f = cite_mod.parse_cite_body(body)
        kind = f.get("kind")
        if not kind:
            b.stats.cite_tokens_dropped.append({
                "src_path": src_path, "line": text.count("\n", 0, m.start()) + 1,
                "reason": "no kind= field", "illus": illus, "raw": m.group(0)[:120],
            })
            continue
        line_no = text.count("\n", 0, m.start()) + 1
        dst, dst_kind, label, extra = _cite_target(f, kind, kb_root, cite_mod)
        if dst is None:
            b.stats.cite_tokens_dropped.append({
                "src_path": src_path, "line": line_no,
                "reason": f"unresolvable kind={kind}", "illus": illus, "raw": m.group(0)[:120],
            })
            continue
        b.add_node(dst, dst_kind, label)
        b.add_edge(src_node, dst, "cites", src_path=src_path, src_line=line_no, cite_kind=kind, illus=illus, ordinal=ordinal, raw=m.group(0)[:500], **extra)


def build_mention_index(known_ids: set) -> List[Tuple[str, str, "re.Pattern[str]"]]:
    """Precompiles every (node id, its candidate strings, boundary pattern)
    once per snapshot, not once per (candidate, document) pair. The mentions
    pass below is O(candidates x documents) by nature -- every known id has
    to be checked against every document's text -- so paying regex
    compilation inside that double loop (as an earlier version of this
    module did) turned a few-thousand-row kb into a multi-minute `kctx graph
    sync --history N`, almost entirely CPU time re-compiling the same
    pattern over and over. Precompiling drops that to one compile per id."""
    index = []
    for cid in known_ids:
        bare = cid.split(":", 1)[1] if ":" in cid else cid
        candidates = [cid]
        if bare and bare != cid:
            candidates.append(bare)
        for cand in candidates:
            index.append((cid, cand, _boundary_pattern(cand)))
    return index


def scan_mentions(
    b: GraphBuilder, src_node: str, src_path: str, text: str,
    mention_index: List[Tuple[str, str, "re.Pattern[str]"]], cite_mod,
) -> None:
    """Literal id mentions outside ⟦cite ...⟧ spans, using an id-boundary
    regex (not a plain substring check -- see _boundary_pattern's docstring
    for the false-positive this avoids on a shared-prefix id). A cheap `in`
    substring check gates the (already-compiled) regex: CPython's substring
    search is fast enough that filtering the overwhelming majority of
    candidates that don't even appear in a given document this way, before
    ever invoking the regex engine, is the other half of what keeps this
    pass fast at kb's real scale (see build_mention_index's docstring)."""
    stripped = cite_mod.CITE_LINE_RE.sub(" ", text)
    matched: set = set()
    for cid, cand, pattern in mention_index:
        if cid == src_node or cid in matched:
            continue
        if cand not in stripped:
            continue
        if pattern.search(stripped):
            b.add_edge(src_node, cid, "mentions", src_path=src_path)
            matched.add(cid)


# --------------------------------------------------------------------------
# per-record-kind extraction, generalized over the whole tree
# --------------------------------------------------------------------------
def _path_parts(path: str) -> List[str]:
    return list(PurePosixPath(path).parts)


def _ev_id_for_path(path: str) -> Optional[str]:
    parts = _path_parts(path)
    if "evidence" not in parts:
        return None
    idx = parts.index("evidence")
    home = "/".join(parts[:idx])
    stem = PurePosixPath(path).stem
    if not home or not stem:
        return None
    return f"ev:{home}/{stem}"


def extract_graph(files: Dict[str, str], kb_sha: str, seen_date: str, kb_root: Path) -> GraphBuilder:
    cite_mod = load_cite_module()
    b = GraphBuilder(kb_sha, seen_date)

    asset_ids: set = set()
    relationship_paths: List[str] = []
    dossier_paths: List[str] = []
    sig_paths: List[str] = []
    inv_paths: List[str] = []
    proposal_paths: List[str] = []
    ev_paths: List[str] = []
    other_paths: List[str] = []

    for path in sorted(files):
        parts = _path_parts(path)
        if path.startswith("inventory/assets/") and path.endswith(".json"):
            continue  # pass 1 below
        if path.startswith("inventory/relationships/") and path.endswith(".json"):
            relationship_paths.append(path)
        elif path.startswith("inventory/dossiers/") and path.endswith(".md") and PurePosixPath(path).name != "README.md":
            dossier_paths.append(path)
        elif path.startswith("signatures/") and path.endswith(".md"):
            sig_paths.append(path)
        elif len(parts) >= 2 and parts[0] == "investigations" and PurePosixPath(path).name == "README.md":
            inv_paths.append(path)
        elif path.startswith("proposals/") and PurePosixPath(path).name == "proposal.md":
            proposal_paths.append(path)
        elif "evidence" in parts and path.endswith(".md"):
            ev_paths.append(path)
        else:
            other_paths.append(path)

    # pass 1: assets (other node kinds reference these by id)
    for path in sorted(files):
        if path.startswith("inventory/assets/") and path.endswith(".json"):
            b.stats.files_scanned += 1
            try:
                obj = json.loads(files[path])
            except json.JSONDecodeError:
                continue
            aid = obj.get("id")
            if not aid:
                continue
            asset_ids.add(aid)
            b.add_node(aid, "asset", obj.get("name", aid), home_path=path)

    # pass 2: typed relationships
    for path in relationship_paths:
        b.stats.files_scanned += 1
        try:
            obj = json.loads(files[path])
        except json.JSONDecodeError:
            continue
        src, dst, rtype = obj.get("from"), obj.get("to"), obj.get("type")
        if not (src and dst and rtype):
            continue
        rel = rtype.replace("-", "_")
        if dst not in asset_ids:
            b.add_node(dst, "asset", dst)
        b.add_node(src, "asset", src)
        b.add_edge(src, dst, rel, src_path=path, state=obj.get("status"))
        for loc in obj.get("evidence", []) or []:
            m = SHORT_LOCATOR_RE.match(loc)
            if m:
                repo = canonical_repo(m.group("repo"), None, kb_root, cite_mod)
                code_dst = f"code:{repo}:{m.group('path')}"
                b.add_node(code_dst, "code", loc)
                b.add_edge(src, code_dst, "cites", src_path=path, cite_kind="code", rev=m.group("rev"))

    # pass 3: dossiers
    for path in dossier_paths:
        b.stats.files_scanned += 1
        text = files[path]
        fm, body = split_frontmatter(text)
        asset = fm.get("asset")
        if not asset:
            other_paths.append(path)
            continue
        did = f"dossier:{asset}"
        b.add_node(did, "dossier", asset, home_path=path)
        if asset not in asset_ids:
            b.add_node(asset, "asset", asset)
        b.add_edge(did, asset, "dossier_of", src_path=path)
        scan_cites(b, did, path, text, kb_root, cite_mod)

    # pass 4: signatures
    for path in sig_paths:
        b.stats.files_scanned += 1
        text = files[path]
        fm, body = split_frontmatter(text)
        sid_raw = fm.get("id")
        if not sid_raw:
            other_paths.append(path)
            continue
        sid = f"sig:{sid_raw}"
        b.add_node(sid, "sig", fm.get("title", sid_raw), home_path=path)
        for a in parse_list_value(fm.get("assets")):
            if a not in asset_ids:
                b.add_node(a, "asset", a)
            b.add_edge(sid, a, "signature_of", src_path=path)
        for fixref in parse_list_value(fm.get("fix")):
            m = PR_REF_RE.match(fixref)
            if m:
                prid = f"pr:{fixref}"
                b.add_node(prid, "pr", fixref)
                b.add_edge(sid, prid, "mentions", src_path=path, cite_kind="pr")
        scan_cites(b, sid, path, text, kb_root, cite_mod)

    # pass 5: investigations
    for path in inv_paths:
        b.stats.files_scanned += 1
        text = files[path]
        fm, body = split_frontmatter(text)
        iid_raw = fm.get("id")
        if not iid_raw:
            other_paths.append(path)
            continue
        iid = f"inv:{iid_raw}"
        b.add_node(iid, "inv", fm.get("title", iid_raw), home_path=path)
        for a in parse_list_value(fm.get("assets")):
            if a not in asset_ids:
                b.add_node(a, "asset", a)
            b.add_edge(iid, a, "touches", src_path=path, state=fm.get("status"))
        for s in parse_list_value(fm.get("signatures")):
            sid = f"sig:{s}"
            b.add_node(sid, "sig", s)
            b.add_edge(iid, sid, "has_signature", src_path=path, state=fm.get("status"))
        for al in parse_list_value(fm.get("alerts")):
            aid = f"alert:{al}"
            b.add_node(aid, "note", al)
            b.add_edge(iid, aid, "mentions", src_path=path)
        for t in parse_list_value(fm.get("tickets")):
            tid = f"ticket:{t}"
            b.add_node(tid, "ticket", t)
            b.add_edge(iid, tid, "mentions", src_path=path)
        scan_cites(b, iid, path, text, kb_root, cite_mod)

    # pass 6: proposals
    for path in proposal_paths:
        b.stats.files_scanned += 1
        text = files[path]
        fm, body = split_frontmatter(text)
        pid_raw = fm.get("id")
        if not pid_raw:
            other_paths.append(path)
            continue
        pid = f"proposal:{pid_raw}"
        b.add_node(pid, "proposal", fm.get("title", pid_raw), home_path=path)
        state = fm.get("status")
        for ref in parse_list_value(fm.get("references")):
            m = SHORT_LOCATOR_RE.match(ref)
            if m:
                repo = canonical_repo(m.group("repo"), None, kb_root, cite_mod)
                dst = f"code:{repo}:{m.group('path')}"
                b.add_node(dst, "code", ref)
                b.add_edge(pid, dst, "references", src_path=path, cite_kind="code", rev=m.group("rev"), state=state)
            elif ref.startswith("http://") or ref.startswith("https://"):
                dst = f"web:{ref}"
                b.add_node(dst, "web", ref)
                b.add_edge(pid, dst, "references", src_path=path, cite_kind="web", state=state)
            elif PROPOSAL_ID_RE.match(ref):
                dst = f"proposal:{ref}"
                b.add_node(dst, "proposal", ref)
                b.add_edge(pid, dst, "references", src_path=path, cite_kind="proposal", state=state)
            elif ref.startswith("ev:"):
                b.add_node(ref, "ev", ref)
                b.add_edge(pid, ref, "references", src_path=path, cite_kind="ev", state=state)
            # else: an unparsed reference form -- not invented, not dropped
            # from the graph as a whole (the proposal node and its other
            # edges still land), just not turned into a typed `references`
            # edge. Tracked as a representability gap, same as the prototype.
        sup = fm.get("superseded_by")
        if sup:
            dst = f"proposal:{sup}"
            b.add_node(dst, "proposal", sup)
            b.add_edge(pid, dst, "supersedes", src_path=path)
        scan_cites(b, pid, path, text, kb_root, cite_mod)

    # pass 7: evidence records (their own node, so they're addressable and
    # so anything they themselves cite gets scanned with the right src_node)
    for path in ev_paths:
        b.stats.files_scanned += 1
        text = files[path]
        fm, body = split_frontmatter(text)
        eid = _ev_id_for_path(path)
        if not eid:
            other_paths.append(path)
            continue
        b.add_node(eid, "ev", fm.get("title", eid), home_path=path)
        scan_cites(b, eid, path, text, kb_root, cite_mod)

    # pass 8: every other tracked .md/.json file -- the scope fix. Keyed by
    # path (handover-v2 design item 5's "else path" fallback), always
    # scanned for ⟦cite⟧ tokens regardless of structure.
    for path in sorted(set(other_paths)):
        b.stats.files_scanned += 1
        text = files[path]  # full text, frontmatter included: a cite token can live in a
        # frontmatter list field (e.g. a proposal's `references:`), not just in prose body.
        did = f"doc:{path}"
        b.add_node(did, "doc", path, home_path=path)
        scan_cites(b, did, path, text, kb_root, cite_mod)

    # mentions pass needs the full known_ids set from every record type, so
    # it runs last, over every src this snapshot produced a node+body for.
    pending: List[Tuple[str, str, str]] = []
    for path in dossier_paths:
        if path in files:
            fm, body = split_frontmatter(files[path])
            if fm.get("asset"):
                pending.append((f"dossier:{fm['asset']}", path, body))
    for path in sig_paths:
        fm, body = split_frontmatter(files[path])
        if fm.get("id"):
            pending.append((f"sig:{fm['id']}", path, body))
    for path in inv_paths:
        fm, body = split_frontmatter(files[path])
        if fm.get("id"):
            pending.append((f"inv:{fm['id']}", path, body))
    for path in proposal_paths:
        fm, body = split_frontmatter(files[path])
        if fm.get("id"):
            pending.append((f"proposal:{fm['id']}", path, body))
    for path in ev_paths:
        eid = _ev_id_for_path(path)
        if eid:
            _, body = split_frontmatter(files[path])
            pending.append((eid, path, body))
    for path in sorted(set(other_paths)):
        text = files[path]
        body = split_frontmatter(text)[1] if path.endswith(".md") else text
        pending.append((f"doc:{path}", path, body))

    mention_index = build_mention_index(b.known_ids)
    for src_node, src_path, body in pending:
        scan_mentions(b, src_node, src_path, body, mention_index, cite_mod)

    log = get_logger()
    log.debug(
        "extract.done",
        kb_sha=kb_sha,
        files=b.stats.files_scanned,
        nodes=len(b.nodes),
        edges=len(b.edges),
        cite_tokens=b.stats.cite_tokens_seen,
        cite_tokens_illus=b.stats.cite_tokens_illus,
        cite_tokens_dropped=len(b.stats.cite_tokens_dropped),
    )
    return b
