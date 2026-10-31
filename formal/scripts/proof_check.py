#!/usr/bin/env python3
"""Clean kernel build and complete registry-driven transitive axiom audit.

Kernel acceptance is not handover completeness: the separate theorem fidelity
review records whether a theorem states the required obligation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

FORMAL = Path(__file__).resolve().parents[1]
ROOT = FORMAL.parent
ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}


def run(*args: str) -> str:
    process = subprocess.run(args, cwd=FORMAL, text=True, capture_output=True, check=False)
    print(process.stdout, end="")
    print(process.stderr, end="")
    if process.returncode:
        raise RuntimeError(f"{args!r} exited {process.returncode}")
    return process.stdout


def source_digest() -> str:
    digest = hashlib.sha256()
    paths = [*FORMAL.rglob("*.lean"), *FORMAL.joinpath("scripts").glob("*.py"), *FORMAL.joinpath("scripts").glob("*.sh"), FORMAL / "theorems.json", FORMAL / "lean-toolchain", FORMAL / "lake-manifest.json", FORMAL / "Dockerfile"]
    for path in sorted(p for p in paths if ".lake" not in p.parts):
        digest.update(str(path.relative_to(FORMAL)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> int:
    report: dict[str, object] = {
        "schema_version": 2,
        "generated": datetime.now(timezone.utc).isoformat(),
        "source_sha256": source_digest(),
        "command": "formal/scripts/proof_check.sh",
        "result": "fail",
        "scope": "kernel build and registry axiom integrity, not handover theorem fidelity",
    }
    audit_path: Path | None = None
    try:
        revision = subprocess.run(["git", "-c", f"safe.directory={ROOT}", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True)
        report["implementation_revision"] = revision.stdout.strip()
        registry = json.loads((FORMAL / "theorems.json").read_text(encoding="utf-8"))
        obligations = registry["theorems"]
        required = {f"T{number:02}" for number in range(1, 23)}
        if set(obligations) != required:
            raise RuntimeError("registry must enumerate exactly T01–T22")
        names: set[str] = set()
        open_obligations: list[str] = []
        for identity, entry in obligations.items():
            declared = entry.get("theorem")
            if not isinstance(declared, list) or not declared:
                open_obligations.append(identity)
                continue
            for name in declared:
                if not isinstance(name, str) or re.fullmatch(r"Kctx\.(?:[A-Za-z0-9_]+\.)*[A-Za-z0-9_]+", name) is None:
                    raise RuntimeError(f"invalid theorem name for {identity}: {name!r}")
                names.add(name)
        for name in registry.get("nonvacuity", []):
            if not isinstance(name, str) or re.fullmatch(r"Kctx\.(?:[A-Za-z0-9_]+\.)*[A-Za-z0-9_]+", name) is None:
                raise RuntimeError(f"invalid nonvacuity declaration: {name!r}")
            names.add(name)
        report["open_obligations"] = open_obligations
        if open_obligations:
            raise RuntimeError(f"unmapped obligations: {open_obligations}")
        report["semantic_version"] = registry["semantic_version"]
        report["toolchain"] = run("lean", "--version").strip()
        report["pinned_toolchain"] = (FORMAL / "lean-toolchain").read_text().strip()
        run("lake", "clean")
        run("lake", "build")
        report["build"] = "ok"
        run("python3", "scripts/check_nominal.py")
        report["nominal_compilefail"] = json.loads((FORMAL / "nominal-compilefail-report.json").read_text())
        descriptor, raw_path = tempfile.mkstemp(prefix="kctx-audit-", suffix=".lean")
        audit_path = Path(raw_path)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write("import Kctx\n")
            for name in sorted(names):
                output.write(f"#check {name}\n#print axioms {name}\n")
        audit_output = run("lake", "env", "lean", str(audit_path))
        entries: dict[str, list[str]] = {}
        for match in re.finditer(r"'([^']+)'\s+depends on axioms:\s*\[([^\]]*)\]", audit_output):
            entries[match[1]] = [axiom.strip() for axiom in match[2].split(",") if axiom.strip()]
        for match in re.finditer(r"'([^']+)'\s+does not depend on any axioms", audit_output):
            entries[match[1]] = []
        report["audit"] = entries
        report["theorem_statements_and_axioms"] = audit_output
        if set(entries) != names:
            raise RuntimeError(f"incomplete axiom audit: missing={sorted(names - entries.keys())}, unexpected={sorted(entries.keys() - names)}")
        bad = {name: sorted(set(axioms) - ALLOWED_AXIOMS) for name, axioms in entries.items() if set(axioms) - ALLOWED_AXIOMS}
        if bad:
            raise RuntimeError(f"unapproved transitive axioms: {bad}")
        run("lake", "build", "kctxref")
        reference = FORMAL / ".lake/build/bin/kctxref"
        report["reference_sha256"] = hashlib.sha256(reference.read_bytes()).hexdigest()
        request = {"schema_version": 2, "semantic_version": registry["semantic_version"], "id": "smoke", "op": "semantic_version"}
        process = subprocess.run([str(reference)], input=json.dumps(request) + "\n", cwd=FORMAL, text=True, capture_output=True, check=True)
        smoke = json.loads(process.stdout)
        if smoke.get("ok") is not True or smoke.get("result") != registry["semantic_version"] or smoke.get("id") != "smoke":
            raise RuntimeError(f"unexpected reference version response: {smoke!r}")
        report["reference_smoke"] = smoke
        report["result"] = "pass"
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
        report["error"] = str(exc)
        print(f"PROOF_CHECK_FAILED: {exc}")
    finally:
        if audit_path is not None:
            audit_path.unlink(missing_ok=True)
        (FORMAL / "proof-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if report["result"] == "pass":
        print("PROOF_CHECK_OK")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
