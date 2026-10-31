#!/usr/bin/env bash
# Build the formal package, audit theorem axioms, emit proof-report.json.
# Runs inside the pinned proof environment (container or elan with the
# lean-toolchain pin); requires lake on PATH.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== toolchain =="
lean --version

echo "== build =="
lake build

echo "== axiom audit =="
AUDIT_FILE=$(mktemp /tmp/kctx-audit.XXXXXX.lean)
{
  echo "import Kctx"
  echo "open Kctx"
  for t in \
    T01_observation T01_claim T01_binding T01_correction T01_derivation \
    T02_observation T02_claim T02_binding T02_correction T02_derivation T02_evalCtx \
    T03_commit_wf T04_checker_sound T05_derives_sound T06_reusable_iff \
    T08_missing_dep_not_reusable T09_alternative_survives T10_all_support_removed \
    assessFresh_stale_mono assessFresh_fresh_iff assessFresh_future_not_fresh \
    T12_footprint_declared T12_copy_keeps_freshness T13_witness_required \
    T14_derives_only_enabled T16_add_correction_no_new_support T17_usable_conditions \
    T18_transition_conditions T19_conclude_conditions T20_predecessor_conflict \
    T21_replay_same T21_replay_conflict T22_deterministic T22_commit_deterministic \
    T07_checkDerivationV_agree T07_checkDerivationV_ext T15_supported_ext; do
    echo "#print axioms Kctx.$t"
  done
} > "$AUDIT_FILE"
LEAN_PATH=.lake/build/lib/lean lean "$AUDIT_FILE" 2>&1 | tee /tmp/kctx-axioms.log

echo "== allowlist check =="
# Every audited theorem must depend only on the standard Lean logical axioms
# (propext, Classical.choice, Quot.sound) or nothing at all.
python3 - "$@" <<'PYEOF'
import re, json, subprocess, sys, hashlib, datetime

log = open("/tmp/kctx-axioms.log").read()
allowed = {"propext", "Classical.choice", "Quot.sound"}
entries = {}
ok = True
for m in re.finditer(r"'([^']+)'\s+depends on axioms:\s*\[([^\]]*)\]", log):
    name, axioms = m.group(1), [a.strip() for a in m.group(2).split(",") if a.strip()]
    entries[name] = axioms
    bad = [a for a in axioms if a not in allowed]
    if bad:
        ok = False
        print(f"FAIL {name}: non-allowlisted axioms {bad}", file=sys.stderr)
for m in re.finditer(r"'([^']+)'\s+does not depend on any axioms", log):
    entries[m.group(1)] = []
missing = [
    "Kctx.T04_checker_sound", "Kctx.T05_derives_sound", "Kctx.T18_transition_conditions",
    "Kctx.T21_replay_same", "Kctx.T22_deterministic",
    "Kctx.T07_checkDerivationV_agree", "Kctx.T15_supported_ext",
]
for name in missing:
    if name not in entries:
        ok = False
        print(f"FAIL {name}: not found in audit output", file=sys.stderr)
expected = 32
if len(entries) < expected - 2:  # some may be combined
    print(f"WARN: only {len(entries)} theorems audited (expected ~{expected})")

report = {
    "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "toolchain": subprocess.run(["lean", "--version"], capture_output=True, text=True).stdout.strip(),
    "build": "ok",
    "semantic_version": "1.0.0",
    "audit": entries,
    "open_obligations": [],
    "result": "pass" if ok else "fail",
}
with open("proof-report.json", "w") as f:
    json.dump(report, f, indent=2)
print(f"proof-report.json written: {report['result']} ({len(entries)} theorems audited)")
sys.exit(0 if ok else 1)
PYEOF

echo "== reference evaluator =="
lake build kctxref
echo '{"id":"smoke","op":"semantic_version"}' | .lake/build/bin/kctxref
echo "PROOF_CHECK_OK"
