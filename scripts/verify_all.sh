#!/usr/bin/env bash
# One pinned container; failed stages stop immediately and skips remain visible.
set -euo pipefail
cd "$(dirname "$0")/.."
echo '=== locked Python quality + static misuse contracts + behavioral suite ==='
./scripts/check_quality.sh
echo '=== clean Lean build + complete registry axiom audit ==='
./formal/scripts/proof_check.sh
echo '=== package and version contracts ==='
python3 scripts/check_contracts.py
echo '=== Lean/Python correspondence ==='
python3 scripts/conformance_check.py
echo '=== real Dolt graph integration with built-in citation grammar ==='
python3 scripts/dolt_smoke.py
echo VERIFY_ALL_OK
