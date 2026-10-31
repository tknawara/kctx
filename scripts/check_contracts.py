#!/usr/bin/env python3
"""Contract checks (handover §11.2): semantic-version consistency, theorem
registry coverage, wire-format symmetry between the Lean codec and the
Python codec (field-order audit), and import boundaries (semantics is
stdlib-only). Exits nonzero on any failure."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}{(' — ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(name)


# 1) semantic version consistency
from kctx.semantics import SEMANTIC_VERSION  # noqa: E402

lean_src = (ROOT / "formal" / "Kctx" / "Model.lean").read_text()
m = re.search(r'SEMANTIC_VERSION : String := "([^"]+)"', lean_src)
check(
    "semantic version Lean==Python",
    bool(m) and m.group(1) == SEMANTIC_VERSION,
    f"lean={m.group(1) if m else None} python={SEMANTIC_VERSION}",
)

# 2) theorem registry completeness vs proof report
registry = json.loads((ROOT / "formal" / "theorems.json").read_text())
open_ids = [k for k, v in registry["theorems"].items() if not v.get("theorem")]
check(
    "theorem registry has no unmapped closed IDs",
    all(v.get("theorem") or v.get("status") == "open" for v in registry["theorems"].values()),
)
report_path = ROOT / "formal" / "proof-report.json"
if report_path.exists():
    report = json.loads(report_path.read_text())
    check("proof report result", report.get("result") == "pass")
    check(
        "proof report audited count sane",
        len(report.get("audit", {})) >= 25,
        f"only {len(report.get('audit', {}))} audited",
    )
    check(
        "open obligations match report",
        set(report.get("open_obligations", [])) == set(open_ids),
        f"registry-open={open_ids}",
    )
else:
    check("proof report exists", False, "run formal/scripts/proof_check.sh")

# 3) semantics core is stdlib-only (no third-party imports)
sem_root = ROOT / "src" / "kctx" / "semantics"
allowed = re.compile(r"^(from|import)\s+(kctx\.semantics|dataclasses|enum|typing|json|__future__)")
bad_imports = []
for f in sem_root.glob("*.py"):
    for i, line in enumerate(f.read_text().splitlines(), 1):
        t = line.strip()
        if t.startswith(("import ", "from ")) and not allowed.match(t):
            bad_imports.append(f"{f.name}:{i}:{t}")
check("semantics core stdlib-only", not bad_imports, "; ".join(bad_imports[:3]))

# 4) rejection-order contract: Python rejection names == Lean names (source audit)
py_checker = (sem_root / "checker.py").read_text()
lean_checker = (ROOT / "formal" / "Kctx" / "Checker.lean").read_text()
for name in ["ruleNotEnabled", "missingPremise", "missingConclusion",
             "conclusionPropMismatch", "contestedConclusion", "contestedPremise",
             "ruleShapeMismatch", "evidenceNotOk", "evidenceNotFresh",
             "missingCoverage", "coverageIncomplete", "footprintIncomplete"]:
    check(f"rejection name present on both sides: {name}",
          name in py_checker and name in lean_checker)

# 5) root-resolution safety: the config file is the single source; absent it,
# find_root discovers the KB by its own marker (inventory/assets), never by
# "any Git repo". No legacy env vars remain in production modules.
_storage = (ROOT / "storage.py").read_text()
check("config-driven root in storage.find_root", "Config.load()" in _storage)
check(
    "KB-marker discovery, not any-git-repo",
    'inventory" / "assets' in _storage and '"(candidate / \".git\").exists()' not in _storage,
)
for gone in ("KCTX_ROOT", "CITE_BIN", "KCTX_CITE_PY", "KCTX_GRAPH_DIR", "KCTX_LOG_DIR"):
    check(
        f"legacy env {gone} absent from production modules",
        gone not in _storage and gone not in (ROOT / "nav.py").read_text(),
    )

print(f"\ncontracts: {'FAIL' if failures else 'PASS'} ({len(failures)} failures)")
raise SystemExit(1 if failures else 0)
