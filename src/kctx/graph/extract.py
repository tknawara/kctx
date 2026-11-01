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
from typing import TypedDict

from kctx.adapters.git.citations import ORG_REPO_RE
from kctx.citations.syntax import CITE_LINE_RE, is_illustrative, parse_cite_body
from kctx.codecs.frontmatter import read_frontmatter, split_commas_respecting_brackets
from kctx.domain.ids import ProposalId
from kctx.domain.json import JsonObject, JsonValue, object_value, optional_text, texts
from kctx.domain.targets import CodeLocator, EvidenceRef, parse_fix_reference
from kctx.errors import KctxError
from kctx.graph.identity import RepositoryIdentity, canonical_repo, capture_repository_identity
from kctx.graph.models import Edge, ExtractionDiagnostic, GraphEdgeId, GraphNodeId, Node
from kctx.graph.source_tokens import (
    decode_json_source,
    iter_source_tokens,
    json_field_string_sources,
)
from kctx.observability import get_logger, run_logged, span

# Mirrors nav._uses_boundary_pattern's id-character class exactly (kept as
# its own copy rather than importing nav, which is being edited concurrently
# this session for the same `uses` id-boundary fix -- see that module's own
# docstring for the false-positive/false-negative reasoning this matches).
_ID_CHARS = "A-Za-z0-9_./-"

MAX_SOURCE_FILES = 100_000
MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_GRAPH_NODES = 1_000_000
MAX_GRAPH_EDGES = 1_000_000
MAX_MENTION_WORK = 10_000_000
MAX_DIAGNOSTICS = 100_000


def _check_source_size(path: str, size: int, count: int, total: int) -> None:
    if count > MAX_SOURCE_FILES:
        raise KctxError("malformed", f"source file count exceeds limit {MAX_SOURCE_FILES}")
    if size > MAX_FILE_BYTES:
        raise KctxError("malformed", f"{path}: source bytes exceed limit {MAX_FILE_BYTES}")
    if total > MAX_SOURCE_BYTES:
        raise KctxError("malformed", f"aggregate source bytes exceed limit {MAX_SOURCE_BYTES}")


def _boundary_pattern(s: str) -> "re.Pattern[str]":
    return re.compile(rf"(?<![{_ID_CHARS}]){re.escape(s)}(?![A-Za-z0-9_/-])(?!\.[A-Za-z0-9_])")


SHORT_LOCATOR_RE = re.compile(
    r"^(?P<repo>[\w./-]+)@(?P<rev>[0-9a-fA-F]{7,40}(?:\+dirty)?):(?P<path>[^:]+)"
    r"(?::(?P<L>\d+(?:-\d+)?))?$"
)
PROPOSAL_ID_RE = re.compile(r"^[\w-]+/\d{4}-\d{2}-\d{2}-[\w-]+$")


def edge_id(
    src_node: GraphNodeId,
    dst_node: GraphNodeId,
    rel: str,
    src_path: str | None,
    src_line: int | None,
    ordinal: int | None = None,
) -> GraphEdgeId:
    """Includes src_path/src_line (unlike the prototype's edge_id, which
    collapsed every citation from the same src/dst/rel into one row -- see
    RESULTS.md gotcha 5) so two separate citations of the same target from
    the same record each get their own binding row, per handover-v2 S6.2."""
    key = f"{src_node.val}|{dst_node.val}|{rel}|{src_path or ''}|{src_line or ''}|{'' if ordinal is None else ordinal}"
    return GraphEdgeId(hashlib.sha256(key.encode()).hexdigest()[:20])


class ExtractStats:
    def __init__(self) -> None:
        self.files_scanned = 0
        self.cite_tokens_seen = 0
        self.cite_tokens_illus = 0
        self.diagnostics: list[ExtractionDiagnostic] = []
        self.unresolved_repo_aliases: list[str] = []

    def add_diagnostic(self, item: ExtractionDiagnostic) -> None:
        if len(self.diagnostics) >= MAX_DIAGNOSTICS:
            raise KctxError(
                "malformed", f"extraction diagnostic count exceeds limit {MAX_DIAGNOSTICS}"
            )
        self.diagnostics.append(item)

    @property
    def cite_tokens_dropped(self) -> list[JsonObject]:
        """Historical skip payload; diagnostics are the authoritative records."""
        return [
            {
                "src_path": item.src_path,
                "line": item.src_line,
                "reason": item.reason,
                "illus": item.illus,
                "raw": item.raw,
            }
            for item in self.diagnostics
            if item.category == "citation-skip"
        ]


class GraphBuilder:
    def __init__(self, kb_sha: str, seen_date: str) -> None:
        self.kb_sha = kb_sha
        self.seen_date = seen_date
        self.nodes: dict[GraphNodeId, Node] = {}
        self.edges: dict[GraphEdgeId, Edge] = {}
        self.known_ids: set[GraphNodeId] = set()
        self.stats = ExtractStats()

    def add_node(
        self, nid: str, kind: str, label: str | None = None, home_path: str | None = None
    ) -> None:
        if not nid:
            return
        node_id = GraphNodeId(nid)
        if node_id not in self.nodes:
            if len(self.nodes) >= MAX_GRAPH_NODES:
                raise KctxError("malformed", f"graph node count exceeds limit {MAX_GRAPH_NODES}")
            self.nodes[node_id] = Node(
                id=node_id, kind=kind, label=label or nid, home_path=home_path
            )
        elif home_path is not None:
            existing = self.nodes[node_id]
            if existing.home_path is not None and existing.home_path != home_path:
                raise KctxError(
                    "malformed",
                    f"ambiguous graph identity {nid!r}: {existing.home_path!r} and {home_path!r}",
                )
            if existing.home_path is None:
                self.nodes[node_id] = Node(
                    id=node_id, kind=kind, label=label or nid, home_path=home_path
                )
        self.known_ids.add(node_id)

    def add_edge(
        self,
        src_node: str,
        dst_node: str,
        rel: str,
        *,
        src_path: str | None = None,
        src_line: int | None = None,
        cite_kind: str | None = None,
        rev: str | None = None,
        blob_sha: str | None = None,
        span_: str | None = None,
        line_selector: str | None = None,
        seen: str | None = None,
        state: str | None = None,
        illus: bool = False,
        ordinal: int | None = None,
        raw: str | None = None,
    ) -> None:
        if not src_node or not dst_node:
            return
        source = GraphNodeId(src_node)
        target = GraphNodeId(dst_node)
        eid = edge_id(source, target, rel, src_path, src_line, ordinal)
        if eid not in self.edges and len(self.edges) >= MAX_GRAPH_EDGES:
            raise KctxError("malformed", f"graph edge count exceeds limit {MAX_GRAPH_EDGES}")
        self.edges[eid] = Edge(
            edge_id=eid,
            src_node=source,
            src_path=src_path,
            src_line=src_line,
            dst_node=target,
            rel=rel,
            cite_kind=cite_kind,
            rev=rev,
            blob_sha=blob_sha,
            span=span_,
            line_selector=line_selector,
            seen=seen or self.seen_date,
            state=state,
            illus=illus,
            raw=raw,
        )


# --------------------------------------------------------------------------
# git plumbing: read every tracked .md/.json file at one sha, in memory
# --------------------------------------------------------------------------
def read_tree_at_sha(kb_root: Path, sha: str) -> dict[str, str]:
    with span("extract.read_tree", sha=sha):
        metadata = run_logged(
            ["git", "-C", str(kb_root), "ls-tree", "-r", "-l", "-z", sha],
            check=True,
            text=False,
        )
        total = 0
        count = 0
        suffixes: set[str] = set()
        for record in metadata.stdout.split(b"\0"):
            if not record:
                continue
            header, raw_path = record.split(b"\t", 1)
            path = raw_path.decode("utf-8", errors="replace")
            if not path.endswith((".md", ".json")):
                continue
            fields = header.split()
            if fields[1] != b"blob":
                continue
            size = int(fields[3])
            count += 1
            total += size
            _check_source_size(path, size, count, total)
            suffixes.add(PurePosixPath(path).suffix)
        if not suffixes:
            return {}
        proc = run_logged(
            [
                "git",
                "-C",
                str(kb_root),
                "archive",
                "--format=tar",
                sha,
                "--",
                *(f"*{suffix}" for suffix in sorted(suffixes)),
            ],
            check=True,
            text=False,
        )
        files: dict[str, str] = {}
        with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                if not (member.name.endswith(".md") or member.name.endswith(".json")):
                    continue
                data = tf.extractfile(member)
                if data is None:
                    continue
                files[member.name] = data.read().decode("utf-8", errors="replace")
    return files


def commit_subject(kb_root: Path, sha: str) -> str:
    proc = run_logged(["git", "-C", str(kb_root), "log", "-1", "--format=%s", sha], check=True)
    return proc.stdout.strip()


def commit_date(kb_root: Path, sha: str) -> str:
    proc = run_logged(["git", "-C", str(kb_root), "log", "-1", "--format=%cI", sha], check=True)
    return proc.stdout.strip()


def first_parent_record_commits(
    kb_root: Path, limit: int | None = None
) -> list[tuple[str, str, str]]:
    """(sha, iso_date, subject) for first-parent commits touching *.md/*.json,
    oldest first. `limit` keeps only the last N (closest to HEAD)."""
    proc = run_logged(
        [
            "git",
            "-C",
            str(kb_root),
            "log",
            "--first-parent",
            "--reverse",
            "--format=%H\x1f%cI\x1f%s",
            "--",
            "*.md",
            "*.json",
        ],
        check=True,
    )
    commits: list[tuple[str, str, str]] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        sha, date, subject = line.split("\x1f", 2)
        commits.append((sha, date, subject))
    if limit is not None and limit > 0:
        commits = commits[-limit:]
    return commits


# --------------------------------------------------------------------------
# Frontmatter uses the same ambiguity-refusing codec as document reads.
# --------------------------------------------------------------------------
def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    fm = read_frontmatter(text)
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return fm, text
    for index, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return fm, "".join(lines[index + 1 :])
    return fm, text


def parse_list_value(v: str | None) -> list[str]:
    v = (v or "").strip()
    if not v or v == "[]":
        return []
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    return split_commas_respecting_brackets(v)


# --------------------------------------------------------------------------
# Citation-token extraction uses the built-in citation syntax parser.
# --------------------------------------------------------------------------
class CitationFields(TypedDict, total=False):
    rev: str | None
    blob_sha: str | None
    span_: str | None
    line_selector: str | None
    seen: str | None
    state: str | None


def _cite_target(
    f: dict[str, str], kind: str, repository_identity: RepositoryIdentity
) -> tuple[str | None, str, str | None, CitationFields]:
    """Returns (dst_node_id, dst_kind, label, extra_edge_fields) for one
    parsed ⟦cite ...⟧ body, or (None, ..., ...) only when the body genuinely
    carries no usable identity (never for a merely-uncommon kind -- those
    fall through to the generic hash-keyed branch at the end so nothing is
    silently dropped, per G1)."""
    if kind == "code":
        repo = canonical_repo(f.get("repo"), f.get("url"), repository_identity)
        path = f.get("path", "")
        dst = f"code:{repo}:{path}"
        return (
            dst,
            "code",
            f"{repo}:{path}",
            {
                "rev": f.get("rev"),
                "blob_sha": f.get("blob"),
                "span_": f.get("span"),
                "line_selector": f.get("L"),
                "seen": f.get("seen"),
            },
        )
    if kind == "commit":
        repo = canonical_repo(f.get("repo"), f.get("url"), repository_identity)
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
        repo = canonical_repo(f.get("repo"), f.get("url"), repository_identity)
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


def _record_unresolved_repo(
    b: GraphBuilder,
    repo: str,
    path: str,
    line: int | None,
    raw: str,
    *,
    illus: bool = False,
) -> None:
    if ORG_REPO_RE.fullmatch(repo):
        return
    if repo not in b.stats.unresolved_repo_aliases:
        b.stats.unresolved_repo_aliases.append(repo)
    b.stats.add_diagnostic(
        ExtractionDiagnostic(
            category="unresolved-repo",
            src_path=path,
            src_line=line,
            reason=f"repository alias {repo!r} has no canonical org/repo identity",
            raw=raw,
            illus=illus,
        )
    )


def scan_cites(
    b: GraphBuilder,
    src_node: str,
    src_path: str,
    text: str,
    repository_identity: RepositoryIdentity,
) -> None:
    for token in iter_source_tokens(src_path, text):
        b.stats.cite_tokens_seen += 1
        illus = is_illustrative(token.body)
        b.stats.cite_tokens_illus += int(illus)
        try:
            if not token.complete:
                raise KctxError("malformed", "unterminated citation token")
            fields = parse_cite_body(token.body)
            kind = fields.get("kind")
            if not kind:
                raise KctxError("malformed", "no kind= field")
            dst, dst_kind, label, extra = _cite_target(fields, kind, repository_identity)
            if dst is None:
                raise KctxError("malformed", f"unresolvable kind={kind}")
        except KctxError as exc:
            b.stats.add_diagnostic(
                ExtractionDiagnostic(
                    category="citation-skip",
                    src_path=src_path,
                    src_line=token.src_line,
                    reason=str(exc),
                    illus=illus,
                    raw=token.raw,
                )
            )
            continue
        if kind in ("code", "commit", "pr"):
            repo = canonical_repo(fields.get("repo"), fields.get("url"), repository_identity)
            _record_unresolved_repo(b, repo, src_path, token.src_line, token.raw, illus=illus)
        b.add_node(dst, dst_kind, label)
        b.add_edge(
            src_node,
            dst,
            "cites",
            src_path=src_path,
            src_line=token.src_line,
            cite_kind=kind,
            illus=illus,
            ordinal=token.ordinal,
            raw=token.raw,
            **extra,
        )


def build_mention_index(
    known_ids: set[GraphNodeId],
) -> list[tuple[GraphNodeId, str, "re.Pattern[str]"]]:
    """Precompiles every (node id, its candidate strings, boundary pattern)
    once per snapshot, not once per (candidate, document) pair. The mentions
    pass below is O(candidates x documents) by nature -- every known id has
    to be checked against every document's text -- so paying regex
    compilation inside that double loop (as an earlier version of this
    module did) turned a few-thousand-row kb into a multi-minute `kctx graph
    sync --history N`, almost entirely CPU time re-compiling the same
    pattern over and over. Precompiling drops that to one compile per id."""
    index: list[tuple[GraphNodeId, str, re.Pattern[str]]] = []
    for cid in known_ids:
        bare = cid.val.split(":", 1)[1] if ":" in cid.val else cid.val
        candidates = [cid.val]
        if bare and bare != cid.val:
            candidates.append(bare)
        for cand in candidates:
            index.append((cid, cand, _boundary_pattern(cand)))
    return index


def scan_mentions(
    b: GraphBuilder,
    src_node: str,
    src_path: str,
    text: str,
    mention_index: list[tuple[GraphNodeId, str, "re.Pattern[str]"]],
) -> None:
    """Literal id mentions outside ⟦cite ...⟧ spans, using an id-boundary
    regex (not a plain substring check -- see _boundary_pattern's docstring
    for the false-positive this avoids on a shared-prefix id). A cheap `in`
    substring check gates the (already-compiled) regex: CPython's substring
    search is fast enough that filtering the overwhelming majority of
    candidates that don't even appear in a given document this way, before
    ever invoking the regex engine, is the other half of what keeps this
    pass fast at kb's real scale (see build_mention_index's docstring)."""
    stripped = CITE_LINE_RE.sub(" ", text)
    matched: set[GraphNodeId] = set()
    for cid, cand, pattern in mention_index:
        if cid.val == src_node or cid in matched:
            continue
        if cand not in stripped:
            continue
        if pattern.search(stripped):
            b.add_edge(src_node, cid.val, "mentions", src_path=src_path)
            matched.add(cid)


# --------------------------------------------------------------------------
# per-record-kind extraction, generalized over the whole tree
# --------------------------------------------------------------------------
def _path_parts(path: str) -> list[str]:
    return list(PurePosixPath(path).parts)


def _ev_id_for_path(path: str) -> str | None:
    parts = _path_parts(path)
    if "evidence" not in parts:
        return None
    idx = parts.index("evidence")
    home = "/".join(parts[:idx])
    stem = PurePosixPath(path).stem
    if not home or not stem:
        return None
    return f"ev:{home}/{stem}"


def extract_graph(
    files: dict[str, str],
    kb_sha: str,
    seen_date: str,
    kb_root: Path,
    *,
    repository_identity: RepositoryIdentity | None = None,
) -> GraphBuilder:
    b = GraphBuilder(kb_sha, seen_date)
    total = 0
    for count, (path, text) in enumerate(files.items(), 1):
        size = len(text.encode("utf-8"))
        total += size
        _check_source_size(path, size, count, total)
    identity = repository_identity or capture_repository_identity(kb_root)
    b.stats.files_scanned = len(files)
    json_records: dict[str, JsonValue] = {}
    markdown_records: dict[str, tuple[dict[str, str], str]] = {}
    malformed_markdown: set[str] = set()
    for path, text in files.items():
        if path.endswith(".md"):
            try:
                markdown_records[path] = split_frontmatter(text)
            except KctxError as exc:
                markdown_records[path] = ({}, text)
                malformed_markdown.add(path)
                b.stats.add_diagnostic(
                    ExtractionDiagnostic(
                        category="record-malformed",
                        src_path=path,
                        src_line=1,
                        reason=str(exc),
                        raw=text,
                    )
                )
        if not path.endswith(".json"):
            continue
        try:
            json_records[path] = decode_json_source(text)
        except (json.JSONDecodeError, KctxError) as exc:
            b.stats.add_diagnostic(
                ExtractionDiagnostic(
                    category="record-malformed",
                    src_path=path,
                    src_line=exc.lineno if isinstance(exc, json.JSONDecodeError) else 1,
                    reason=str(exc),
                    raw=text,
                )
            )

    asset_ids: set[str] = set()
    relationship_paths: list[str] = []
    dossier_paths: list[str] = []
    sig_paths: list[str] = []
    inv_paths: list[str] = []
    proposal_paths: list[str] = []
    ev_paths: list[str] = []
    other_paths: list[str] = []

    for path in sorted(files):
        if path in malformed_markdown:
            other_paths.append(path)
            continue
        parts = _path_parts(path)
        if path.startswith("inventory/assets/") and path.endswith(".json"):
            continue  # pass 1 below
        if path.startswith("inventory/relationships/") and path.endswith(".json"):
            relationship_paths.append(path)
        elif (
            path.startswith("inventory/dossiers/")
            and path.endswith(".md")
            and PurePosixPath(path).name != "README.md"
        ):
            dossier_paths.append(path)
        elif path.startswith("signatures/") and path.endswith(".md"):
            sig_paths.append(path)
        elif (
            len(parts) >= 2
            and parts[0] == "investigations"
            and PurePosixPath(path).name == "README.md"
        ):
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
            if path not in json_records:
                other_paths.append(path)
                continue
            try:
                obj = object_value(json_records[path], path)
                aid = optional_text(obj.get("id"), "asset.id")
                if not aid:
                    raise KctxError("malformed", "asset.id is required and must not be empty")
                name = optional_text(obj.get("name", aid), "asset.name")
            except KctxError as exc:
                b.stats.add_diagnostic(
                    ExtractionDiagnostic(
                        category="record-malformed",
                        src_path=path,
                        src_line=1,
                        reason=str(exc),
                        raw=files[path],
                    )
                )
                other_paths.append(path)
                continue
            asset_ids.add(aid)
            b.add_node(aid, "asset", name, home_path=path)
            scan_cites(b, aid, path, files[path], identity)

    # pass 2: typed relationships
    for path in relationship_paths:
        if path not in json_records:
            other_paths.append(path)
            continue
        try:
            obj = object_value(json_records[path], path)
            src = optional_text(obj.get("from"), "relationship.from")
            dst = optional_text(obj.get("to"), "relationship.to")
            rtype = optional_text(obj.get("type"), "relationship.type")
            if not (src and dst and rtype):
                raise KctxError(
                    "malformed", "relationship.from, to and type are required and must not be empty"
                )
            state = optional_text(obj.get("status"), "relationship.status")
            texts(obj.get("evidence", []), "relationship.evidence")
        except KctxError as exc:
            b.stats.add_diagnostic(
                ExtractionDiagnostic(
                    category="record-malformed",
                    src_path=path,
                    src_line=1,
                    reason=str(exc),
                    raw=files[path],
                )
            )
            other_paths.append(path)
            continue
        rel = rtype.replace("-", "_")
        if dst not in asset_ids:
            b.add_node(dst, "asset", dst)
        b.add_node(src, "asset", src)
        b.add_edge(src, dst, rel, src_path=path, state=state)
        text = files[path]
        scan_cites(b, src, path, text, identity)
        # Retain source escapes and physical lines instead of reserializing JSON.
        for source in json_field_string_sources(text, "evidence"):
            loc = source.text
            match = SHORT_LOCATOR_RE.fullmatch(loc)
            if match:
                repo = canonical_repo(match.group("repo"), None, identity)
                code_dst = f"code:{repo}:{match.group('path')}"
                b.add_node(code_dst, "code", loc)
                start = source.offset(0)
                _record_unresolved_repo(
                    b,
                    repo,
                    path,
                    text.count("\n", 0, start) + 1,
                    text[start : source.offset(len(source.text))],
                )
                b.add_edge(
                    src,
                    code_dst,
                    "cites",
                    src_path=path,
                    src_line=text.count("\n", 0, start) + 1,
                    cite_kind="code",
                    rev=match.group("rev"),
                    line_selector=match.group("L"),
                    raw=text[start : source.offset(len(source.text))],
                    ordinal=-(start + 1),
                )

    # pass 3: dossiers
    for path in dossier_paths:
        text = files[path]
        fm, body = markdown_records[path]
        asset = fm.get("asset")
        if not asset:
            other_paths.append(path)
            continue
        did = f"dossier:{asset}"
        b.add_node(did, "dossier", asset, home_path=path)
        if asset not in asset_ids:
            b.add_node(asset, "asset", asset)
        b.add_edge(did, asset, "dossier_of", src_path=path)
        scan_cites(b, did, path, text, identity)

    # pass 4: signatures
    for path in sig_paths:
        text = files[path]
        fm, body = markdown_records[path]
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
        for ordinal, raw_fix in enumerate(parse_list_value(fm.get("fix"))):
            try:
                fix = parse_fix_reference(raw_fix)
            except KctxError as exc:
                b.stats.add_diagnostic(
                    ExtractionDiagnostic(
                        category="record-malformed",
                        src_path=path,
                        src_line=1,
                        reason=f"invalid signature fix: {exc}",
                        raw=raw_fix,
                    )
                )
                continue
            fields: dict[str, str]
            if isinstance(fix, ProposalId):
                kind = "proposal"
                fields = {"id": fix.val}
            elif isinstance(fix, EvidenceRef):
                kind = "ev"
                fields = {"id": f"{fix.home}/{fix.stem.val}"}
            else:
                kind = "code"
                fields = {"repo": fix.repo, "rev": fix.sha, "path": fix.path}
                if fix.line is not None:
                    fields["L"] = (
                        str(fix.line[0])
                        if fix.line[0] == fix.line[1]
                        else f"{fix.line[0]}-{fix.line[1]}"
                    )
            dst, dst_kind, label, extra = _cite_target(fields, kind, identity)
            if dst is None:
                continue
            if isinstance(fix, CodeLocator):
                repo = canonical_repo(fix.repo, None, identity)
                _record_unresolved_repo(b, repo, path, None, raw_fix)
            b.add_node(dst, dst_kind, label)
            b.add_edge(
                sid,
                dst,
                "mentions",
                src_path=path,
                cite_kind=kind,
                ordinal=ordinal,
                raw=raw_fix,
                **extra,
            )
        scan_cites(b, sid, path, text, identity)

    # pass 5: investigations
    for path in inv_paths:
        text = files[path]
        fm, body = markdown_records[path]
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
        scan_cites(b, iid, path, text, identity)

    # pass 6: proposals
    for path in proposal_paths:
        text = files[path]
        fm, body = markdown_records[path]
        pid_raw = fm.get("id")
        if not pid_raw:
            other_paths.append(path)
            continue
        pid = f"proposal:{pid_raw}"
        b.add_node(pid, "proposal", fm.get("title", pid_raw), home_path=path)
        state = fm.get("status")
        reference_field = re.search(r"(?m)^\s*references:", text)
        reference_offset = reference_field.end() if reference_field else 0
        for ordinal, ref in enumerate(parse_list_value(fm.get("references"))):
            start = text.find(ref, reference_offset)
            if start < 0:
                raise KctxError("malformed", f"{path}: reference has no authored source location")
            reference_offset = start + len(ref)
            reference_line = text.count("\n", 0, start) + 1
            m = SHORT_LOCATOR_RE.match(ref)
            if m:
                repo = canonical_repo(m.group("repo"), None, identity)
                _record_unresolved_repo(b, repo, path, reference_line, ref)
                dst = f"code:{repo}:{m.group('path')}"
                b.add_node(dst, "code", ref)
                b.add_edge(
                    pid,
                    dst,
                    "references",
                    src_path=path,
                    src_line=reference_line,
                    cite_kind="code",
                    rev=m.group("rev"),
                    line_selector=m.group("L"),
                    state=state,
                    raw=ref,
                    ordinal=ordinal,
                )
            elif ref.startswith("http://") or ref.startswith("https://"):
                dst = f"web:{ref}"
                b.add_node(dst, "web", ref)
                b.add_edge(
                    pid,
                    dst,
                    "references",
                    src_path=path,
                    src_line=reference_line,
                    cite_kind="web",
                    state=state,
                    raw=ref,
                    ordinal=ordinal,
                )
            elif PROPOSAL_ID_RE.match(ref):
                dst = f"proposal:{ref}"
                b.add_node(dst, "proposal", ref)
                b.add_edge(
                    pid,
                    dst,
                    "references",
                    src_path=path,
                    src_line=reference_line,
                    cite_kind="proposal",
                    state=state,
                    raw=ref,
                    ordinal=ordinal,
                )
            elif ref.startswith("ev:"):
                b.add_node(ref, "ev", ref)
                b.add_edge(
                    pid,
                    ref,
                    "references",
                    src_path=path,
                    src_line=reference_line,
                    cite_kind="ev",
                    state=state,
                    raw=ref,
                    ordinal=ordinal,
                )
            # else: an unparsed reference form -- not invented, not dropped
            # from the graph as a whole (the proposal node and its other
            # edges still land), just not turned into a typed `references`
            # edge. Tracked as a representability gap, same as the prototype.
        sup = fm.get("superseded_by")
        if sup:
            dst = f"proposal:{sup}"
            b.add_node(dst, "proposal", sup)
            b.add_edge(pid, dst, "supersedes", src_path=path)
        scan_cites(b, pid, path, text, identity)

    # pass 7: evidence records (their own node, so they're addressable and
    # so anything they themselves cite gets scanned with the right src_node)
    for path in ev_paths:
        text = files[path]
        fm, body = markdown_records[path]
        eid = _ev_id_for_path(path)
        if not eid:
            other_paths.append(path)
            continue
        b.add_node(eid, "ev", fm.get("title", eid), home_path=path)
        scan_cites(b, eid, path, text, identity)

    # pass 8: every other tracked .md/.json file -- the scope fix. Keyed by
    # path (handover-v2 design item 5's "else path" fallback), always
    # scanned for ⟦cite⟧ tokens regardless of structure.
    for path in sorted(set(other_paths)):
        text = files[path]  # full text, frontmatter included: a cite token can live in a
        # frontmatter list field (e.g. a proposal's `references:`), not just in prose body.
        did = f"doc:{path}"
        b.add_node(did, "doc", path, home_path=path)
        scan_cites(b, did, path, text, identity)

    # mentions pass needs the full known_ids set from every record type, so
    # it runs last, over every src this snapshot produced a node+body for.
    pending: list[tuple[str, str, str]] = []
    for path in dossier_paths:
        if path in files:
            fm, body = markdown_records[path]
            if fm.get("asset"):
                pending.append((f"dossier:{fm['asset']}", path, body))
    for path in sig_paths:
        fm, body = markdown_records[path]
        if fm.get("id"):
            pending.append((f"sig:{fm['id']}", path, body))
    for path in inv_paths:
        fm, body = markdown_records[path]
        if fm.get("id"):
            pending.append((f"inv:{fm['id']}", path, body))
    for path in proposal_paths:
        fm, body = markdown_records[path]
        if fm.get("id"):
            pending.append((f"proposal:{fm['id']}", path, body))
    for path in ev_paths:
        eid = _ev_id_for_path(path)
        if eid:
            _, body = markdown_records[path]
            pending.append((eid, path, body))
    for path in sorted(set(other_paths)):
        text = files[path]
        body = markdown_records[path][1] if path.endswith(".md") else text
        pending.append((f"doc:{path}", path, body))

    candidate_count = sum(1 + int(bool(cid.val.partition(":")[2])) for cid in b.known_ids)
    if candidate_count * len(pending) > MAX_MENTION_WORK:
        raise KctxError(
            "malformed", f"mention candidate/document work exceeds limit {MAX_MENTION_WORK}"
        )
    mention_index = build_mention_index(b.known_ids)
    for src_node, src_path, body in pending:
        scan_mentions(b, src_node, src_path, body, mention_index)

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
