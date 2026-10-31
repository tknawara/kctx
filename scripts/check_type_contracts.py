#!/usr/bin/env python3
"""Run positive consumer typing and require rejection at every negative use."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_fixture(filename: str, *, negative: bool) -> int:
    path = ROOT / "tests" / "typing" / filename
    process = subprocess.run(["pyright", "--outputjson", str(path)], cwd=ROOT, text=True, capture_output=True, check=False)
    try:
        report = json.loads(process.stdout)
    except ValueError:
        print(process.stdout, process.stderr)
        return 1
    diagnostics = report["generalDiagnostics"]
    if not negative:
        if process.returncode != 0 or diagnostics:
            print(json.dumps(report, indent=2))
            return 1
        print("type contract: valid typed consumer PASS")
        return 0
    expected = {index for index, line in enumerate(path.read_text().splitlines()) if "# expect-error" in line}
    errors = [item for item in diagnostics if item["severity"] == "error"]
    observed = {item["range"]["start"]["line"] for item in errors if Path(item["file"]).resolve() == path.resolve()}
    unrelated = [item for item in diagnostics if Path(item["file"]).resolve() != path.resolve() or item["range"]["start"]["line"] not in expected]
    if process.returncode != 1 or observed != expected or unrelated:
        print(f"type contract FAIL: expected={sorted(expected)}, observed={sorted(observed)}")
        print(json.dumps(report, indent=2))
        return 1
    print(f"type contract: {len(expected)} ID/enum misuse sites rejected PASS")
    return 0


def main() -> int:
    return check_fixture("valid_ids.py", negative=False) or check_fixture("invalid_ids.py", negative=True)


if __name__ == "__main__":
    raise SystemExit(main())
