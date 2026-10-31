#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --locked --group dev
uv run --locked ruff check src/kctx
uv run --locked ruff format --check src/kctx
uv run --locked pyright
uv run --locked python3 scripts/check_type_contracts.py
uv run --locked python3 scripts/run_tests.py
echo QUALITY_OK
