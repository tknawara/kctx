"""`kctx graph sync`: extracts the shadow graph from tracked .md/.json files
at a kb git commit and replays it into Dolt.

Reads the commit via `git archive <sha>` (graph.extract.read_tree_at_sha),
never the working tree -- so a concurrently-dirty checkout's uncommitted
edits never leak into the shadow graph. This is a deliberate choice, not an
accident of convenience: two agents can be mid-edit in the same kb working
tree while a third runs `kctx graph sync` and still get a graph that matches
some real git commit exactly, not a mix of that commit and in-flight edits.

Every snapshot is written as two Dolt commits, never one (handover-v2 §6.4:
"never write the Dolt commit hash into the rows of the same commit"): the
first commit lands the nodes/edges/kb_commits/sync_state rows with
dolt_commit left NULL (that commit's own hash can't be known before it's
made); the second commit updates just the hash column once it's known.
"""

import os
from pathlib import Path
from typing import List, Optional, Tuple

from storage import iso_now

from kctx.graph.dolt_store import (
    DoltStore,
    EDGE_COLUMNS,
    KB_COMMIT_COLUMNS,
    NODE_COLUMNS,
    SYNC_STATE_COLUMNS,
)
from kctx.graph.extract import (
    commit_date,
    commit_subject,
    extract_graph,
    first_parent_record_commits,
    read_tree_at_sha,
)
from kctx.graph.observability import get_logger, run_logged, span


def graph_dir() -> Path:
    from kctx.config import Config

    cfg = Config.load()
    if cfg.graph_dir is not None:
        return cfg.graph_dir
    if Path("/workarea").is_dir():
        return Path("/workarea/kb-graph")
    return Path.home() / ".local" / "share" / "kb-graph"


def dolt_db_dir() -> Path:
    return graph_dir() / "dolt"


def head_sha(kb_root: Path) -> str:
    proc = run_logged(["git", "-C", str(kb_root), "rev-parse", "HEAD"], check=True)
    return proc.stdout.strip()


def latest_sync_state(store: DoltStore) -> Optional[dict]:
    rows = store.sql_read("SELECT * FROM sync_state WHERE id = 1")
    return rows[0] if rows else None


def _next_seq(store: DoltStore) -> int:
    rows = store.sql_read("SELECT COALESCE(MAX(seq), 0) AS m FROM kb_commits")
    return int(rows[0]["m"]) if rows else 0


def _write_one(store: DoltStore, kb_root: Path, sha: str, date: str, subject: str, seq: int) -> Tuple[int, int]:
    with span("graph.sync.snapshot", kb_sha=sha, seq=seq):
        files = read_tree_at_sha(kb_root, sha)
        builder = extract_graph(files, sha, date, kb_root)
        node_rows = [n.model_dump() for n in builder.nodes.values()]
        edge_rows = [e.model_dump() for e in builder.edges.values()]

        store.replace_table("nodes", NODE_COLUMNS, node_rows)
        store.replace_table("edges", EDGE_COLUMNS, edge_rows)
        store.upsert_rows(
            "kb_commits", KB_COMMIT_COLUMNS,
            [{"kb_sha": sha, "dolt_commit": None, "subject": subject, "committed_date": date, "seq": seq}],
        )
        store.upsert_rows(
            "sync_state", SYNC_STATE_COLUMNS,
            [{
                "id": 1, "kb_sha": sha, "kb_subject": subject, "dolt_commit": None,
                "synced_at": iso_now(), "node_count": len(node_rows), "edge_count": len(edge_rows),
            }],
        )
        store.commit(f"kb {sha} {subject}"[:4000], date=date, allow_empty=True)

        new_hash = store.head_commit_hash()
        store.upsert_rows(
            "kb_commits", KB_COMMIT_COLUMNS,
            [{"kb_sha": sha, "dolt_commit": new_hash, "subject": subject, "committed_date": date, "seq": seq}],
        )
        store.upsert_rows(
            "sync_state", SYNC_STATE_COLUMNS,
            [{
                "id": 1, "kb_sha": sha, "kb_subject": subject, "dolt_commit": new_hash,
                "synced_at": iso_now(), "node_count": len(node_rows), "edge_count": len(edge_rows),
            }],
        )
        store.commit(f"backfill dolt_commit for {sha}", date=date, allow_empty=True)
    return len(node_rows), len(edge_rows)


def sync(kb_root: Path, *, rebuild: bool = False, history: Optional[int] = None) -> dict:
    log = get_logger()
    with span("graph.sync", rebuild=rebuild, history=history):
        store = DoltStore(dolt_db_dir())
        if rebuild:
            store.rebuild()
        else:
            store.ensure_init()

        current_sha = head_sha(kb_root)

        if not rebuild and not history:
            prior = latest_sync_state(store)
            if prior and prior.get("kb_sha") == current_sha:
                log.info("graph.sync.noop", kb_sha=current_sha)
                return {
                    "status": "up-to-date",
                    "kb_sha": current_sha,
                    "dolt_commit": prior.get("dolt_commit"),
                    "node_count": prior.get("node_count"),
                    "edge_count": prior.get("edge_count"),
                }

        commits: List[Tuple[str, str, str]]
        if history:
            commits = first_parent_record_commits(kb_root, limit=history)
            if not commits or commits[-1][0] != current_sha:
                commits = commits + [
                    (current_sha, commit_date(kb_root, current_sha), commit_subject(kb_root, current_sha))
                ]
        else:
            commits = [
                (current_sha, commit_date(kb_root, current_sha), commit_subject(kb_root, current_sha))
            ]

        seq = _next_seq(store)
        node_count = edge_count = 0
        for sha, date, subject in commits:
            seq += 1
            node_count, edge_count = _write_one(store, kb_root, sha, date, subject, seq)

        final = latest_sync_state(store)
        log.info("graph.sync.done", kb_sha=current_sha, commits_replayed=len(commits), nodes=node_count, edges=edge_count)
        return {
            "status": "synced",
            "kb_sha": current_sha,
            "dolt_commit": final.get("dolt_commit") if final else None,
            "node_count": node_count,
            "edge_count": edge_count,
            "commits_replayed": len(commits),
        }
