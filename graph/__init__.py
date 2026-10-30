"""M2 shadow-mode citation/relationship graph (decision/2026-10-30-adopt-dolt-
handover-v2-staged-m2-shadow-mode-...).

Markdown/JSON files under the kb repo stay the single write authority.
`kctx graph sync` extracts citation bindings and typed relationships from
those files at a kb git commit and replays them into a Dolt database that
agents traverse via `kctx graph uses/impact/diff/check`. No agent writes SQL
directly, and no agent should treat this graph as authoritative over the
files it was built from.

This is the only part of kctx that imports third-party packages (pydantic,
structlog) -- every other kctx module stays stdlib-only, importable without
`uv run`.
"""
