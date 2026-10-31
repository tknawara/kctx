#!/usr/bin/env python3
"""Negative consumer examples must fail for namespace/nonempty type errors."""

import hashlib
import json
import subprocess
from pathlib import Path

FORMAL = Path(__file__).resolve().parents[1]


def main() -> int:
    fixtures = sorted((FORMAL / "compilefail").glob("*.lean"))
    if not fixtures:
        raise RuntimeError("nominal compile-fail fixtures missing")
    results = []
    for fixture in fixtures:
        process = subprocess.run(["lake", "env", "lean", str(fixture)], cwd=FORMAL, capture_output=True, text=True)
        diagnostics = process.stdout + process.stderr
        expected = "tactic 'decide' proved" if fixture.name == "empty_identifier.lean" else "type mismatch"
        rejected = process.returncode != 0 and expected.lower() in diagnostics.lower()
        results.append({"path": str(fixture.relative_to(FORMAL.parent)), "sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(), "exit_code": process.returncode, "rejected": rejected, "diagnostics": diagnostics})
        print(f"{'PASS' if rejected else 'FAIL'} nominal rejection {fixture.name}")
        if not rejected:
            print(diagnostics)
    report = {"schema_version": 1, "command": "formal/scripts/check_nominal.py", "tests": results, "passed": all(row["rejected"] for row in results)}
    (FORMAL / "nominal-compilefail-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
