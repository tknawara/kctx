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

import json
from pathlib import Path

from kctx.domain.json import JsonObject
from kctx.domain.time import iso_now
from kctx.errors import KctxError
from kctx.graph.dolt_store import (
    DIAGNOSTIC_COLUMNS,
    EDGE_COLUMNS,
    GENERATION_INPUT_COLUMNS,
    KB_COMMIT_COLUMNS,
    NODE_COLUMNS,
    SYNC_STATE_COLUMNS,
    DoltStore,
)
from kctx.graph.extract import (
    commit_date,
    commit_subject,
    extract_graph,
    first_parent_record_commits,
    read_tree_at_sha,
)
from kctx.graph.generation import completed_pointer, completed_snapshot, publish
from kctx.graph.inputs import GenerationInputs, generation_inputs
from kctx.graph.models import DoltCommitId, SyncState, dolt_int
from kctx.graph.operations import activate, active_db_dir, recover, start, writer
from kctx.observability import get_logger, run_logged, span


def graph_dir() -> Path:
    from kctx.config import Config

    cfg = Config.load()
    if cfg.graph_dir is not None:
        return cfg.graph_dir
    if Path("/workarea").is_dir():
        return Path("/workarea/kb-graph")
    return Path.home() / ".local" / "share" / "kb-graph"


def dolt_db_dir() -> Path:
    return active_db_dir(graph_dir())


def head_sha(kb_root: Path) -> str:
    proc = run_logged(["git", "-C", str(kb_root), "rev-parse", "HEAD"], check=True)
    return proc.stdout.strip()


def latest_sync_state(store: DoltStore) -> SyncState | None:
    snapshot = completed_snapshot(store)
    return snapshot.state if snapshot else None


def _next_seq(store: DoltStore) -> int:
    rows = store.sql_read("SELECT COALESCE(MAX(seq), 0) AS m FROM kb_commits")
    return dolt_int(rows[0]["m"]) if rows else 0


def _write_one(
    store: DoltStore,
    kb_root: Path,
    sha: str,
    date: str,
    subject: str,
    seq: int,
    inputs: GenerationInputs,
) -> tuple[int, int, DoltCommitId]:
    with span("graph.sync.snapshot", kb_sha=sha, seq=seq):
        files = read_tree_at_sha(kb_root, sha)
        builder = extract_graph(
            files, sha, date, kb_root, repository_identity=inputs.repository_identity
        )
        node_rows = [n.to_wire() for n in builder.nodes.values()]
        edge_rows = [e.to_wire() for e in builder.edges.values()]

        store.replace_table("nodes", NODE_COLUMNS, node_rows)
        store.replace_table("edges", EDGE_COLUMNS, edge_rows)
        store.replace_table(
            "extraction_diagnostics",
            DIAGNOSTIC_COLUMNS,
            [
                {"diagnostic_id": index, "details": json.dumps(item.to_wire(), sort_keys=True)}
                for index, item in enumerate(builder.stats.diagnostics, 1)
            ],
        )
        store.upsert_rows(
            "generation_inputs",
            GENERATION_INPUT_COLUMNS,
            [
                {
                    "id": 1,
                    "input_digest": inputs.digest,
                    "manifest": json.dumps(inputs.to_wire(), sort_keys=True, ensure_ascii=False),
                }
            ],
        )
        store.upsert_rows(
            "kb_commits",
            KB_COMMIT_COLUMNS,
            [
                {
                    "kb_sha": sha,
                    "dolt_commit": None,
                    "subject": subject,
                    "committed_date": date,
                    "seq": seq,
                    "input_digest": inputs.digest,
                }
            ],
        )
        store.upsert_rows(
            "sync_state",
            SYNC_STATE_COLUMNS,
            [
                {
                    "id": 1,
                    "kb_sha": sha,
                    "kb_subject": subject,
                    "dolt_commit": None,
                    "synced_at": iso_now(),
                    "node_count": len(node_rows),
                    "edge_count": len(edge_rows),
                    "input_digest": inputs.digest,
                }
            ],
        )
        data_commit = DoltCommitId(
            store.commit(f"kb {sha} {subject}"[:4000], date=date, allow_empty=True)
        )
        new_hash = data_commit.val
        store.upsert_rows(
            "kb_commits",
            KB_COMMIT_COLUMNS,
            [
                {
                    "kb_sha": sha,
                    "dolt_commit": new_hash,
                    "subject": subject,
                    "committed_date": date,
                    "seq": seq,
                    "input_digest": inputs.digest,
                }
            ],
        )
        store.upsert_rows(
            "sync_state",
            SYNC_STATE_COLUMNS,
            [
                {
                    "id": 1,
                    "kb_sha": sha,
                    "kb_subject": subject,
                    "dolt_commit": new_hash,
                    "synced_at": iso_now(),
                    "node_count": len(node_rows),
                    "edge_count": len(edge_rows),
                    "input_digest": inputs.digest,
                }
            ],
        )
        metadata_commit = DoltCommitId(
            store.commit(f"backfill dolt_commit for {sha}", date=date, allow_empty=True)
        )
    return len(node_rows), len(edge_rows), metadata_commit


def sync(kb_root: Path, *, rebuild: bool = False, history: int | None = None) -> JsonObject:
    if history is not None and (type(history) is not int or not 1 <= history <= 1000):
        raise KctxError("malformed", "history must be an integer from 1 to 1000")
    log = get_logger()
    with (
        writer(graph_dir(), kb_root) as published,
        span("graph.sync", rebuild=rebuild, history=history),
    ):
        previous = completed_snapshot(published)
        current_sha = head_sha(kb_root)
        current_inputs = generation_inputs(kb_root, kb_sha=current_sha)
        recovered = recover(
            published, kb_root, current_inputs, previous, rebuild=rebuild, history=history
        )
        if recovered is not None:
            operation, snapshot = recovered
            if generation_inputs(kb_root, kb_sha=current_sha).digest != current_inputs.digest:
                raise KctxError(
                    "conflict",
                    "graph generation inputs changed during recovery; candidate retained",
                )
            if completed_pointer(operation.store) != snapshot.metadata_commit:
                publish(operation.store, snapshot.metadata_commit, operation.predecessor)
            activate(operation, snapshot, kb_root)
            log.info(
                "graph.sync.done",
                kb_sha=current_sha,
                commits_replayed=operation.record["commits_replayed"],
                nodes=snapshot.state.node_count,
                edges=snapshot.state.edge_count,
            )
            return {
                "status": "synced",
                "kb_sha": current_sha,
                "dolt_commit": snapshot.state.dolt_commit,
                "node_count": snapshot.state.node_count,
                "edge_count": snapshot.state.edge_count,
                "commits_replayed": operation.record["commits_replayed"],
                "input_digest": current_inputs.digest,
            }

        if not rebuild and not history:
            prior = previous.state if previous else None
            if (
                prior
                and prior.kb_sha == current_sha
                and prior.input_digest == current_inputs.digest
            ):
                log.info("graph.sync.noop", kb_sha=current_sha)
                return {
                    "status": "up-to-date",
                    "kb_sha": current_sha,
                    "dolt_commit": prior.dolt_commit,
                    "node_count": prior.node_count,
                    "edge_count": prior.edge_count,
                    "input_digest": prior.input_digest,
                }

        commits: list[tuple[str, str, str]]
        if history:
            commits = first_parent_record_commits(kb_root, limit=history)
            if not commits or commits[-1][0] != current_sha:
                commits.append(
                    (
                        current_sha,
                        commit_date(kb_root, current_sha),
                        commit_subject(kb_root, current_sha),
                    )
                )
        else:
            commits = [
                (
                    current_sha,
                    commit_date(kb_root, current_sha),
                    commit_subject(kb_root, current_sha),
                )
            ]

        # Only an isolated native backup/restore receives schema or table writes.
        operation = start(
            published,
            kb_root,
            current_inputs,
            previous,
            rebuild=rebuild,
            history=history,
            commits_replayed=len(commits),
        )
        store = operation.store
        store.ensure_init()

        seq = _next_seq(store)
        node_count = edge_count = 0
        metadata_commit: DoltCommitId | None = None
        for sha, date, subject in commits:
            seq += 1
            inputs = (
                current_inputs if sha == current_sha else generation_inputs(kb_root, kb_sha=sha)
            )
            node_count, edge_count, metadata_commit = _write_one(
                store, kb_root, sha, date, subject, seq, inputs
            )
        if metadata_commit is None:
            raise RuntimeError("sync produced no graph generation")
        if generation_inputs(kb_root, kb_sha=current_sha).digest != current_inputs.digest:
            raise KctxError(
                "conflict",
                "graph generation inputs changed during sync; candidate retained without publication",
            )
        publish(store, metadata_commit, previous.metadata_commit if previous else None)

        snapshot = completed_snapshot(store)
        if snapshot is None:
            raise KctxError("malformed", "native graph publication has no completed snapshot")
        activate(operation, snapshot, kb_root)
        final = snapshot.state
        log.info(
            "graph.sync.done",
            kb_sha=current_sha,
            commits_replayed=len(commits),
            nodes=node_count,
            edges=edge_count,
        )
        return {
            "status": "synced",
            "kb_sha": current_sha,
            "dolt_commit": final.dolt_commit if final else None,
            "node_count": node_count,
            "edge_count": edge_count,
            "commits_replayed": len(commits),
            "input_digest": current_inputs.digest,
        }
