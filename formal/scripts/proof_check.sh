#!/usr/bin/env bash
# One registry-driven owner: clean build, complete axiom audit, reference smoke.
set -euo pipefail
exec python3 "$(dirname "$0")/proof_check.py" "$@"
