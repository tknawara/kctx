#!/usr/bin/env bash
# Nagini job: verify the annotated contracts, then run the equivalence grid
# against the production core. Contract failure OR equivalence mismatch
# fails the job.
set -euo pipefail
cd "$(dirname "$0")/../../../"

echo "=== nagini: verify contracts ==="
nagini formal/nagini/assess_fresh_contracts.py

echo "=== twin drift check: annotated body == runtime body ==="
python3 formal/nagini/twin_drift_check.py

echo "=== equivalence grid: verified twin vs production core ==="
python3 formal/nagini/equivalence_grid.py

echo "NAGINI_CHECK_OK"
