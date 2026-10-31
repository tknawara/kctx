#!/usr/bin/env python3
"""Run behavioral fixtures and retain explicit failures and skipped capabilities."""

import hashlib
import json
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    digest = hashlib.sha256()
    for path in sorted([*(ROOT / "src/kctx").rglob("*.py"), *(ROOT / "tests").rglob("*.py")]):
        digest.update(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes() + b"\0")
    revision = subprocess.run(["git", "-c", f"safe.directory={ROOT}", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    report = {
        "schema_version": 1, "command": "python3 scripts/run_tests.py",
        "generated": datetime.now(timezone.utc).isoformat(), "implementation_revision": revision,
        "source_fixture_sha256": digest.hexdigest(), "tests_run": result.testsRun,
        "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
        "failures": [{"test": test.id(), "traceback": trace} for test, trace in result.failures],
        "errors": [{"test": test.id(), "traceback": trace} for test, trace in result.errors],
        "skipped": [{"test": test.id(), "reason": reason} for test, reason in result.skipped],
        "result": "pass" if result.wasSuccessful() else "fail",
        "qualification": "partial" if result.skipped else "complete-fixture-run",
    }
    (ROOT / "test-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
