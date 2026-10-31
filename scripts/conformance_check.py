#!/usr/bin/env python3
"""Lean ⇄ Python conformance check (G05).

Runs the versioned case files through BOTH the pinned Lean reference
evaluator (``formal/.lake/build/bin/kctxref``) and the actual Python
production core (``kctx.semantics``), then compares every response line.
CI must fail on reference timeout/crash/malformed output/version mismatch —
it never silently skips conformance.

Usage:
    python3 scripts/conformance_check.py [--lean BIN] [--cases DIR]

The Lean side requires the proof environment (elan with the pinned
toolchain). Without it, the script reports SKIPPED and exits 3 (a release
job must treat that as unqualified, not passed).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kctx.semantics import (  # noqa: E402
    SEMANTIC_VERSION,
    ClaimRef,
    EvalCtx,
    KB,
    check_derivation_v,
    commit_op,
    plan_transition,
    can_conclude,
    Investigation,
    Hypothesis,
    HypStatus,
    usable_for,
    supported,
    reusable,
    assess_fresh,
)
from kctx.semantics import wire  # noqa: E402
from kctx.semantics.time import assess_fresh as py_assess_fresh
from kctx.semantics.model import Ttl

DEFAULT_LEAN_BIN = ROOT / "formal" / ".lake" / "build" / "bin" / "kctxref"
DEFAULT_CASES = ROOT / "tests" / "conformance"


def _py_plan_transition(req: dict):
    from kctx.semantics import Proposal, ProposalStatus

    p = req["proposal"]
    prop = Proposal(
        id=p["id"],
        status=ProposalStatus(p["status"]),
        research_present=p["researchPresent"],
        research_justified_skip=p["researchJustifiedSkip"],
        alternatives_count=p["alternativesCount"],
        gates_table_present=p["gatesTablePresent"],
        legacy_profile=p["legacyProfile"],
        land_gates_passed=p["landGatesPassed"],
        deploy_use_gates_passed=p["deployUseGatesPassed"],
    )
    out = plan_transition(
        prop,
        ProposalStatus(req["target"]),
        req.get("actor"),
        tuple(req.get("landedRefs", ())),
        req["refsResolvable"],
    )
    if out[0] == "refused":
        return ["refused", out[1]]
    return ["planned"]


def _py_conclude(req: dict):
    i = req["investigation"]
    inv = Investigation(
        id="inv",
        checked_against=i["checkedAgainst"],
        scope_and_limits=i["scopeAndLimits"],
        hypotheses=tuple(
            Hypothesis(text=h["text"], status=HypStatus(h["status"]))
            for h in i["hypotheses"]
        ),
    )
    return can_conclude(inv)


def python_handle(req: dict):
    op = req["op"]
    if op == "plan_transition":
        return _py_plan_transition(req)
    if op == "conclude_investigation":
        return _py_conclude(req)
    return _python_handle_base(req)


def _python_handle_base(req: dict):
    op = req["op"]
    if op == "semantic_version":
        return SEMANTIC_VERSION
    if op == "assess_fresh":
        ttl = wire.dec_ttl(req["ttl"])
        return py_assess_fresh(ttl, req["observedAt"], req["now"]).value
    if op == "check_derivation":
        kb = wire.dec_kb(req["kb"])
        ctx = wire.dec_eval_ctx(req["ctx"])
        d = wire.dec_derivation(req["derivation"])
        v = check_derivation_v(kb.view(), ctx, d)
        return ["accepted"] if v == "accepted" else v
    if op == "reusable":
        kb = wire.dec_kb(req["kb"])
        ctx = wire.dec_eval_ctx(req["ctx"])
        d = wire.dec_derivation(req["derivation"])
        observed = [wire.dec_dep(x) for x in req["observed"]]
        return reusable(kb.view(), ctx, d, observed)
    if op == "supported":
        kb = wire.dec_kb(req["kb"])
        ctx = wire.dec_eval_ctx(req["ctx"])
        return supported(kb.view(), ctx, wire.dec_claim_ref(req["ref"]))
    if op == "usable":
        kb = wire.dec_kb(req["kb"])
        ctx = wire.dec_eval_ctx(req["ctx"])
        return usable_for(kb.view(), ctx, wire.dec_claim_ref(req["ref"]))
    raise ValueError(f"unknown op {op}")


def run_lean(bin_path: Path, case_lines: list[str]) -> tuple[list[dict] | None, str]:
    if not bin_path.exists():
        return None, f"reference evaluator not found at {bin_path}"
    try:
        proc = subprocess.run(
            [str(bin_path)],
            input="\n".join(case_lines) + "\n",
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return None, "reference evaluator timed out"
    if proc.returncode != 0:
        return None, f"reference evaluator exited {proc.returncode}: {proc.stderr[:400]}"
    out = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            return None, f"malformed reference output: {e}: {line[:200]}"
    return out, ""


def normalize(x):
    """Json-decode Lean's compact output into plain structures."""
    if isinstance(x, list):
        return [normalize(i) for i in x]
    if isinstance(x, bool):
        return x
    return x


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--lean", default=str(DEFAULT_LEAN_BIN))
    ap.add_argument("--cases", default=str(DEFAULT_CASES))
    ap.add_argument("--skip-lean", action="store_true",
                    help="run the Python side only (exit 3 still signals 'not qualified')")
    args = ap.parse_args()

    cases_dir = Path(args.cases)
    case_files = sorted(cases_dir.glob("*.jsonl"))
    if not case_files:
        print(f"FAIL: no case files in {cases_dir}")
        return 1

    requests: list[dict] = []
    for f in case_files:
        for line in f.read_text().splitlines():
            if line.strip():
                requests.append(json.loads(line))

    # Python side must never trust fixture flags: it decodes and evaluates.
    py_results = []
    for req in requests:
        try:
            res = python_handle(req)
            py_results.append({"id": req.get("id", ""), "ok": True, "result": res})
        except Exception as e:  # noqa: BLE001 - reported as a failed case
            py_results.append({"id": req.get("id", ""), "ok": False, "error": str(e)})

    if args.skip_lean:
        print(f"SKIPPED-Lean: {len(requests)} cases ran on Python only")
        fails = [r for r in py_results if not r["ok"]]
        for r in fails:
            print(f"  py-fail {r['id']}: {r['error']}")
        return 3

    lean_out, err = run_lean(Path(args.lean), [json.dumps(r) for r in requests])
    if lean_out is None:
        print(f"FAIL: {err}")
        print("     (conformance cannot be skipped for a release; build formal/ first)")
        return 1

    mismatches = []
    for req, py, ln in zip(requests, py_results, lean_out):
        rid = req.get("id", "")
        if not ln.get("ok"):
            mismatches.append(f"{rid}: reference error: {ln.get('error')}")
            continue
        if not py["ok"]:
            mismatches.append(f"{rid}: python error: {py['error']}")
            continue
        if json.dumps(normalize(py["result"]), sort_keys=True) != json.dumps(
            normalize(ln["result"]), sort_keys=True
        ):
            mismatches.append(f"{rid}: lean={ln['result']!r} python={py['result']!r}")

    report = {
        "cases": len(requests),
        "mismatches": len(mismatches),
        "semantic_version": SEMANTIC_VERSION,
        "result": "pass" if not mismatches else "fail",
    }
    out_path = ROOT / "conformance-report.json"
    out_path.write_text(json.dumps(report, indent=2))
    for m in mismatches:
        print("MISMATCH", m)
    print(f"conformance: {report['result']} ({report['cases']} cases, "
          f"{report['mismatches']} mismatches); report: {out_path}")
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
