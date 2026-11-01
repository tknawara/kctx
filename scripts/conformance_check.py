#!/usr/bin/env python3
"""Lean ⇄ Python conformance check (G05).

Runs the versioned case files through BOTH the pinned Lean reference
evaluator (``formal/.lake/build/bin/kctxref``) and the actual Python
production core (``kctx.semantics``), then compares every response line.
CI must fail on reference timeout/crash/malformed output/version mismatch —
it never silently skips conformance.

Usage:
    python3 scripts/conformance_check.py [--lean BIN] [--cases DIR]

Missing or invalid reference executables fail qualification. ``--skip-lean``
explicitly runs Python only and exits 3; every completed invocation writes
the same report schema, including failures and unqualified runs.
"""

from __future__ import annotations

import hashlib
import platform
import json
import subprocess
import sys
from pathlib import Path
from typing import TypeGuard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from kctx.semantics.model import SEMANTIC_VERSION
from kctx.semantics import wire

DEFAULT_LEAN_BIN = ROOT / "formal" / ".lake" / "build" / "bin" / "kctxref"
DEFAULT_CASES = ROOT / "tests" / "conformance"


def _is_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def _object(value: object) -> dict[str, object]:
    if not _is_object(value):
        raise ValueError("expected object")
    return value


def _is_array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _array(value: object) -> list[object]:
    if not _is_array(value):
        raise ValueError("expected array")
    return value


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("expected string")
    return value


def _bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("expected bool")
    return value


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expected int")
    return value


def request_payload(req: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in req.items()
            if key not in ("expected", "expected_response", "category", "trusted_environment", "raw_request")}


def python_handle(req: dict[str, object]) -> dict[str, object]:
    """Model an authenticated external environment, never authority from a request."""
    from kctx.semantics.model import VerifiedApproval, VerifiedSelectionApproval
    if "raw_request" in req:
        return wire.loads_request(wire.evaluate_json(_str(req["raw_request"])))
    environment = wire.obj(req.get("trusted_environment", {"approvals": [], "selections": [], "retained": []}),
                           "approvals selections retained")
    if req.get("schema_version") == 3:
        from kctx.semantics import workflow_reference, workflow_wire

        portfolio_approvals = wire.items(
            environment["approvals"], workflow_wire.dec_verified_portfolio_approval
        )
        portfolio_selections = wire.items(
            environment["selections"], workflow_wire.dec_verified_portfolio_selection_approval
        )
        portfolios = wire.items(environment["retained"], workflow_wire.dec_portfolio_state)
        if len({state.kb.snapshot for state in portfolios}) != len(portfolios):
            raise ValueError("duplicate trusted retained snapshot")
        return workflow_reference.evaluate_request(
            request_payload(req), trusted_approvals=portfolio_approvals,
            trusted_selections=portfolio_selections, retained=portfolios
        )
    approvals = wire.items(environment["approvals"],
                           lambda value: VerifiedApproval(wire.dec_plan(wire.obj(value, "plan")["plan"])))
    selections = wire.items(environment["selections"],
                            lambda value: VerifiedSelectionApproval(wire.dec_selection_plan(wire.obj(value, "plan")["plan"])))
    retained = wire.items(environment["retained"], wire.dec_kb)
    if len({kb.snapshot for kb in retained}) != len(retained):
        raise ValueError("duplicate trusted retained snapshot")
    return wire.evaluate_request(request_payload(req), trusted_approvals=approvals,
                                 trusted_selections=selections, retained=retained)


def reference_transport(req: dict[str, object]) -> dict[str, object]:
    payload = request_payload(req)
    if "trusted_environment" in req:
        return {"request": payload, "trusted_environment": req["trusted_environment"]}
    return payload


def reference_line(req: dict[str, object]) -> str:
    return _str(req["raw_request"]) if "raw_request" in req else _canonical(reference_transport(req))


def run_lean(bin_path: Path, case_lines: list[str]) -> tuple[list[dict[str, object]] | None, str]:
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
    except (OSError, UnicodeError) as exc:
        return None, f"reference evaluator could not run: {exc}"
    if proc.returncode != 0:
        return None, f"reference evaluator exited {proc.returncode}: {proc.stderr[:400]}"
    out: list[dict[str, object]] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        try:
            out.append(wire.loads_request(line))
        except ValueError as e:
            return None, f"malformed reference output: {e}: {line[:200]}"
    return out, ""


HANDSHAKE_ID = "__kctx_semantic_version__"


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _file_digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _manifest(paths: list[Path]) -> dict[str, object]:
    files: dict[str, str] = {}
    for path in sorted(paths):
        try:
            name = path.relative_to(ROOT).as_posix()
        except ValueError:
            name = path.as_posix()
        files[name] = _file_digest(path)
    return {
        "files": files,
        "sha256": hashlib.sha256(_canonical(files).encode("utf-8")).hexdigest(),
    }


def _evidence(case_files: list[Path], reference: Path) -> dict[str, object]:
    python_sources = sorted((ROOT / "src" / "kctx" / "semantics").glob("*.py"))
    python_sources.extend((
        ROOT / "src" / "kctx" / "domain" / "ids.py",
        ROOT / "src" / "kctx" / "errors.py",
        Path(__file__).resolve(),
        ROOT / "scripts" / "semantic_cases.py",
        ROOT / "scripts" / "semantic_mutations.py",
        ROOT / "tests" / "semantics" / "examples.py",
    ))
    lean_sources = sorted((ROOT / "formal" / "Kctx").glob("*.lean"))
    lean_sources.extend(ROOT / "formal" / name for name in (
        "Kctx.lean", "lean-toolchain", "lakefile.toml", "lake-manifest.json",
    ))
    return {
        "digest_algorithm": "sha256",
        "python_sources": _manifest(python_sources),
        "lean_sources": _manifest(lean_sources),
        "fixtures": _manifest(case_files),
        "reference": {
            "path": str(reference),
            "sha256": _file_digest(reference) if reference.is_file() else None,
        },
        "python_version": platform.python_version(),
    }


def _load_cases(case_files: list[Path]) -> list[dict[str, object]]:
    if not case_files:
        raise ValueError("no case files")
    requests: list[dict[str, object]] = []
    seen: set[str] = set()
    for path in case_files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                request = wire.loads_request(line)
                ident = _str(request["id"])
                _str(request["op"])
                if not ident:
                    raise ValueError("empty case id")
                if ident in seen:
                    raise ValueError(f"duplicate case id {ident!r}")
                seen.add(ident)
            except (KeyError, ValueError) as exc:
                raise ValueError(f"{path}:{number}: {exc}") from exc
            requests.append(request)
    if not requests:
        raise ValueError("no fixture scenarios")
    return requests


def _response_errors(
    requests: list[dict[str, object]],
    responses: list[dict[str, object]],
    host: str,
) -> list[str]:
    errors: list[str] = []
    if len(responses) != len(requests):
        errors.append(
            f"{host}: response count {len(responses)} != request count {len(requests)}"
        )
    seen: set[str] = set()
    for index, response in enumerate(responses):
        ident = response.get("id")
        expected_id: object = requests[index]["id"] if index < len(requests) else None
        if index < len(requests) and "raw_request" in requests[index]:
            expected_id = _object(requests[index]["expected_response"])["id"]
        if not isinstance(ident, str) or not ident and expected_id != "":
            errors.append(f"{host}: response {index} has invalid id")
        elif ident:
            if ident in seen:
                errors.append(f"{host}: duplicate response id {ident!r}")
            seen.add(ident)
        if index < len(requests) and ident != expected_id:
            errors.append(f"{host}: response {index} id {ident!r} != expected id {expected_id!r}")
        if type(response.get("ok")) is not bool:
            errors.append(f"{host}: response {index} has non-boolean success flag")
        if response.get("ok") is True and "result" not in response:
            errors.append(f"{host}: response {index} missing result")
        if response.get("ok") is False and "error" not in response:
            errors.append(f"{host}: response {index} missing error")
        if index < len(requests) and "expected_response" in requests[index]:
            expected = requests[index]["expected_response"]
            if _canonical(response) != _canonical(expected):
                errors.append(f"{host}: {ident!r} response differs from fixture expectation")
        elif index < len(requests) and "expected" in requests[index]:
            if response.get("ok") is not True or _canonical(response.get("result")) != _canonical(requests[index]["expected"]):
                errors.append(f"{host}: {ident!r} result differs from fixture expectation")
    return errors


def compare_responses(
    requests: list[dict[str, object]],
    python_responses: list[dict[str, object]],
    reference_responses: list[dict[str, object]],
) -> list[str]:
    """Fail closed on protocol defects before comparing corresponding results."""
    errors = _response_errors(requests, python_responses, "python")
    errors.extend(_response_errors(requests, reference_responses, "reference"))
    if errors:
        return errors
    for index, request in enumerate(requests):
        py = python_responses[index]
        lean = reference_responses[index]
        if _canonical(py) != _canonical(lean):
            errors.append(f"{request['id']}: lean={lean!r} python={py!r}")
    return errors


def run_conformance(cases_dir: Path, reference: Path, *, skip_lean: bool = False) -> dict[str, object]:
    errors: list[str] = []
    handshake: dict[str, object] = {
        "expected_version": SEMANTIC_VERSION,
        "reference_version": None,
        "result": "not-run",
    }
    coverage: dict[str, object] = {
        "fixture_scenarios": 0,
        "generated_scenarios": 0,
        "stateful_scenarios": 0,
        "qualification": "fixture-correspondence-only",
    }
    report: dict[str, object] = {
        "report_schema_version": 1,
        "semantic_version": SEMANTIC_VERSION,
        "result": "fail",
        "cases": 0,
        "mismatches": 0,
        "errors": errors,
        "handshake": handshake,
        "coverage": coverage,
        "evidence": {},
        "python_response_count": 0,
        "reference_response_count": 0,
    }
    try:
        case_files = sorted(cases_dir.glob("*.jsonl"))
        report["evidence"] = _evidence(case_files, reference)
        requests = _load_cases(case_files)
        coverage["fixture_scenarios"] = len(requests)
        if cases_dir.resolve() == DEFAULT_CASES.resolve():
            from scripts.semantic_cases import reviewed_cases, generated_cases, stateful_cases
            from scripts.semantic_mutations import mutation_campaign
            reviewed, generated, stateful = reviewed_cases(), generated_cases(), stateful_cases()
            requests.extend((*reviewed, *generated, *stateful))
            coverage["fixture_scenarios"] = len(requests) - len(generated) - len(stateful)
            coverage["generated_scenarios"] = len(generated)
            coverage["stateful_scenarios"] = len(stateful)
            coverage["qualification"] = "golden-generated-stateful-full-response"
            mutations = mutation_campaign()
            report["mutations"] = mutations
            if mutations["result"] != "pass":
                errors.append("production decision mutation campaign failed")
        report["cases"] = len(requests)
        python_responses: list[dict[str, object]] = []
        for request in requests:
            try:
                python_responses.append(python_handle(request))
            except Exception as exc:  # noqa: BLE001 - harness crashes are failures
                errors.append(f"python boundary crashed for {request['id']}: {exc}")
        report["python_response_count"] = len(python_responses)
        if skip_lean:
            errors.extend(_response_errors(requests, python_responses, "python"))
            report["result"] = "fail" if errors else "unqualified"
            handshake["result"] = "skipped"
            return report

        hello: list[dict[str, object]] = [{
            "schema_version": 2, "semantic_version": SEMANTIC_VERSION,
            "id": HANDSHAKE_ID, "op": "semantic_version",
        }]
        handshake_responses, error = run_lean(reference, [_canonical(hello[0])])
        if handshake_responses is None:
            errors.append(error)
            handshake["result"] = "fail"
            return report
        handshake_errors = _response_errors(hello, handshake_responses, "reference handshake")
        if handshake_errors:
            errors.extend(handshake_errors)
            handshake["result"] = "fail"
            return report
        version = handshake_responses[0]["result"]
        handshake["reference_version"] = version
        if version != SEMANTIC_VERSION:
            errors.append(f"semantic version mismatch: reference={version!r} python={SEMANTIC_VERSION!r}")
            handshake["result"] = "fail"
            return report
        handshake["result"] = "pass"

        reference_responses, error = run_lean(reference, [
            reference_line(request) for request in requests
        ])
        if reference_responses is None:
            errors.append(error)
            return report
        report["reference_response_count"] = len(reference_responses)
        errors.extend(compare_responses(requests, python_responses, reference_responses))
        report["result"] = "fail" if errors else "pass"
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    finally:
        report["mismatches"] = len(errors)
    return report


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--lean", default=str(DEFAULT_LEAN_BIN))
    ap.add_argument("--cases", default=str(DEFAULT_CASES))
    ap.add_argument("--skip-lean", action="store_true",
                    help="run Python only (exit 3 signals 'not qualified')")
    args = ap.parse_args()
    report = run_conformance(Path(args.cases), Path(args.lean), skip_lean=args.skip_lean)
    out_path = ROOT / "conformance-report.json"
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for error in _array(report["errors"]):
        print("FAIL", error)
    print(f"conformance: {report['result']} ({report['cases']} fixture scenarios, "
          f"{report['mismatches']} failures); report: {out_path}")
    if report["result"] == "unqualified":
        return 3
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
