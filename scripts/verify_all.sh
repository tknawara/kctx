#!/usr/bin/env bash
# One-command verification stack (compose `verify` service): python tests +
# contracts + Lean proofs + axiom audit + Lean<->Python conformance.
# Any failure fails the job; nothing is silently skipped.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== [1/4] python test suite (incl. graph integration: dolt is on PATH in this image) ==="
python3 -m unittest discover -s tests -v 2>&1 | tee /tmp/unittest.log | tail -5
if grep -q "skipped" /tmp/unittest.log; then
  echo "NOTE: some tests skipped:"; grep -E "skipped" /tmp/unittest.log | tail -2
fi

echo "=== [2/4] contracts ==="
python3 scripts/check_contracts.py

echo "=== [3/4] lean proofs + axiom audit ==="
(cd formal && ./scripts/proof_check.sh)

echo "=== [4/5] lean<->python conformance ==="
python3 scripts/conformance_check.py

echo "=== [5/5] dolt shadow-graph integration (real dolt CLI; stub citation parser) ==="
python3 scripts/dolt_smoke.py

echo "VERIFY_ALL_OK"
