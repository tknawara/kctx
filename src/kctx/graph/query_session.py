"""Pinned typed graph read sessions, shared by Python and the unified engine."""

from contextlib import ExitStack
from pathlib import Path
from time import perf_counter
from types import TracebackType

from kctx.adapters.dolt.read_session import DoltReadSession
from kctx.domain.json import JsonObject
from kctx.errors import KctxError
from kctx.graph import queries
from kctx.graph.dolt_store import DoltStore
from kctx.graph.models import GraphNodeId
from kctx.graph.operations import active_db_dir, graph_home
from kctx.graph.sync import dolt_db_dir


class QuerySession:
    """Explicit managed session; open/close costs are not query latency.

    The selected immutable publication and native data/metadata commits remain
    fixed until close. Methods use the ordinary graph query implementations.
    This object is single-client, sequential, and not thread-safe.
    """

    def __init__(self, kb_root: Path, *, store: DoltStore | None = None) -> None:
        self.kb_root = kb_root
        self._store = store
        self._stack = ExitStack()
        self._context: queries.QueryContext | None = None
        self._reader: DoltReadSession | None = None
        self._home: Path | None = None
        self.startup_ms = 0.0

    def __enter__(self) -> "QuerySession":
        if self._context is not None:
            raise KctxError("conflict", "query session is already open")
        started = perf_counter()
        store = self._store if self._store is not None else DoltStore(dolt_db_dir())
        snapshot = queries.select_snapshot(store, self.kb_root)
        home = graph_home(store)
        if store.db_dir == home / "dolt":
            raise KctxError(
                "conflict",
                "query sessions require an immutable published generation; run graph sync",
            )
        try:
            reader = self._stack.enter_context(store.read_session())
            self._reader = reader
            self._context = queries.QueryContext(reader, snapshot, store.db_dir)
            self._home = home
            self.startup_ms = (perf_counter() - started) * 1000
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._context = None
        self._home = None
        self._stack.close()

    @property
    def context(self) -> queries.QueryContext:
        if self._context is None:
            raise KctxError("conflict", "query session is not open")
        return self._context

    def resource_identity(self) -> JsonObject:
        """Expose native ownership for out-of-band measurement, not query timing."""
        if self._reader is None:
            raise KctxError("conflict", "query session has not been opened")
        return self._reader.resource_identity()

    def identity(self) -> JsonObject:
        context = self.context
        snapshot = context.snapshot
        home = self._home
        if home is None:
            raise KctxError("conflict", "query session is not open")
        return {
            "selection": "pinned",
            "graph_dir": str(context.db_dir),
            "metadata_commit": snapshot.metadata_commit.val,
            "data_commit": snapshot.data_commit.val,
            "kb_sha": snapshot.state.kb_sha,
            "input_digest": snapshot.state.input_digest,
            "is_current_publication": active_db_dir(home) == context.db_dir,
        }

    def status(self) -> JsonObject:
        return queries.status(self.kb_root, context=self.context)

    def uses(
        self, target: GraphNodeId, *, limit: int = 50, include_illus: bool = False
    ) -> JsonObject:
        return queries.uses(
            target,
            kb_root=self.kb_root,
            limit=limit,
            include_illus=include_illus,
            context=self.context,
        )

    def impact(
        self, target: GraphNodeId, *, depth: int = 3, rel: list[str] | None = None, limit: int = 100
    ) -> JsonObject:
        return queries.impact(
            target, kb_root=self.kb_root, depth=depth, rel=rel, limit=limit, context=self.context
        )

    def diff(self, kb_sha_a: str, kb_sha_b: str, *, limit: int = 200) -> JsonObject:
        return queries.diff(
            kb_sha_a, kb_sha_b, kb_root=self.kb_root, limit=limit, context=self.context
        )

    def source_paths(
        self, target: GraphNodeId, *, revision: str = "HEAD", limit: int = 1000
    ) -> JsonObject:
        return queries.source_paths(
            target, kb_root=self.kb_root, revision=revision, limit=limit, context=self.context
        )
