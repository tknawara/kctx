#!/usr/bin/env python3
"""Version, registry integrity and package-boundary contracts (not proof fidelity)."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kctx.semantics.model import SEMANTIC_VERSION


def main() -> int:
    failures: list[str] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        print(f"{'PASS' if passed else 'FAIL'} {name}{': ' + detail if detail and not passed else ''}")
        if not passed:
            failures.append(name)

    model = (ROOT / "formal/Kctx/Model.lean").read_text()
    version = re.search(r'semanticVersion : String := "([^"]+)"', model)
    check("semantic version Lean == Python", version is not None and version[1] == SEMANTIC_VERSION)
    registry = json.loads((ROOT / "formal/theorems.json").read_text())
    check("registry semantic version", registry["semantic_version"] == SEMANTIC_VERSION)
    obligations = registry["theorems"]
    check("complete obligation registry", set(obligations) == {f"T{n:02}" for n in range(1, 23)})
    declared = {name for entry in obligations.values() for name in entry.get("theorem", [])}
    report_path = ROOT / "formal/proof-report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text())
        check("kernel proof report passes", report.get("result") == "pass")
        check("all registry theorems audited", declared <= set(report.get("audit", {})))
    else:
        check("kernel proof report exists", False, "run formal/scripts/proof_check.sh")

    flat = {"admit", "cli", "corrections", "dossiers", "errors", "gates", "git_utils", "inventory", "investigations", "ktlo", "nav", "proposals", "records", "runs", "storage", "validate"}
    bad_imports: list[str] = []
    weak_types: list[str] = []
    legacy_env: list[str] = []
    forbidden_env = {"KCTX_ROOT", "CITE_BIN", "KCTX_CITE_PY", "KCTX_GRAPH_DIR", "KCTX_LOG_DIR", "KCTX_GH", "KCTX_LOG"}
    for path in sorted((ROOT / "src/kctx").rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name in flat for alias in node.names):
                    bad_imports.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in flat:
                bad_imports.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            if isinstance(node, ast.Name) and node.id == "Any" and ("domain" in path.parts or "services" in path.parts):
                weak_types.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in forbidden_env:
                legacy_env.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.value}")
    check("no obsolete flat imports", not bad_imports, "; ".join(bad_imports))
    check("domain/services do not use Any", not weak_types, "; ".join(weak_types))
    check("no legacy configuration knobs", not legacy_env, "; ".join(legacy_env))
    check("flat implementations removed", not any((ROOT / f"{name}.py").exists() for name in flat))
    check("no module/package collisions", not any(path.with_suffix("").is_dir() for path in (ROOT / "src/kctx").rglob("*.py") if path.name != "__init__.py"))
    print(f"contracts: {'FAIL' if failures else 'PASS'} ({len(failures)} failures)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
