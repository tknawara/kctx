#!/usr/bin/env bash
# Locked quality orchestration: the same commands CI runs.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== unittest (ambient interpreter; graph tests skip without deps) =="
python3 -m unittest discover -s tests

echo "== semantics contracts =="
python3 scripts/check_contracts.py

echo "== conformance (Lean reference vs Python core) =="
python3 scripts/conformance_check.py

echo "QUALITY_OK"
