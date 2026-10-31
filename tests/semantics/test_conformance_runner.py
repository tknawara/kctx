"""The conformance harness compares complete production boundary responses."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import conformance_check as runner


def request(ident: str) -> dict[str, object]:
    return {"schema_version": 2, "semantic_version": runner.SEMANTIC_VERSION,
            "id": ident, "op": "semantic_version"}


def response(ident: str, result: object = True) -> dict[str, object]:
    return {"id": ident, "ok": True, "result": result}


class ResponseProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.requests = [request("first"), request("second")]
        self.responses = [response("first"), response("second")]

    def test_complete_responses_match(self) -> None:
        self.assertEqual(runner.compare_responses(self.requests, self.responses, self.responses), [])

    def test_counts_ids_types_and_extra_fields_are_checked(self) -> None:
        alternatives = [[], self.responses[:1], self.responses + [response("extra")],
                        list(reversed(self.responses)), [response("first"), response("first")],
                        [response("first", 1), response("second")],
                        [{**response("first"), "extra": True}, response("second")],
                        [{"id": "first", "ok": 1, "result": True}, response("second")],
                        [{"id": "first", "ok": True}, response("second")]]
        for replies in alternatives:
            with self.subTest(replies=replies):
                self.assertTrue(runner.compare_responses(self.requests, self.responses, replies))

    def test_invalid_case_requires_independent_expected_error(self) -> None:
        error: dict[str, object] = {"id": "first", "ok": False, "error": "invalid_request"}
        self.requests[0]["expected_response"] = error
        replies = [error, self.responses[1]]
        self.assertEqual(runner.compare_responses(self.requests, replies, replies), [])
        wrong = [{**error, "error": "other"}, self.responses[1]]
        self.assertTrue(runner.compare_responses(self.requests, wrong, wrong))

    def test_agreement_cannot_override_golden(self) -> None:
        self.requests[0]["expected"] = False
        self.assertTrue(runner.compare_responses(self.requests, self.responses, self.responses))


class RunnerEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cases = self.root / "cases"
        self.cases.mkdir()
        self.fixture = self.cases / "cases.jsonl"
        self.fixture.write_text(json.dumps(request("fixture-version")) + "\n", encoding="utf-8")
        self.reference = self.root / "reference"
        self.reference.write_bytes(b"retained executable identity")

    def test_handshake_precedes_cases(self) -> None:
        hello = [response(runner.HANDSHAKE_ID, runner.SEMANTIC_VERSION)]
        replies = [response("fixture-version", runner.SEMANTIC_VERSION)]
        with patch.object(runner, "run_lean", side_effect=[(hello, ""), (replies, "")]) as run:
            report = runner.run_conformance(self.cases, self.reference)
        self.assertEqual(report["result"], "pass", report)
        envelope = json.loads(run.call_args_list[0].args[1][0])
        self.assertEqual(envelope["schema_version"], 2)
        self.assertEqual(envelope["semantic_version"], runner.SEMANTIC_VERSION)
        self.assertEqual(run.call_count, 2)
        self.assertTrue(report["evidence"])

    def test_fixture_expectations_are_not_sent_to_hosts(self) -> None:
        fixture = {**request("fixture-version"), "expected": runner.SEMANTIC_VERSION}
        self.fixture.write_text(json.dumps(fixture) + "\n", encoding="utf-8")
        with patch.object(runner, "run_lean", side_effect=[
            ([response(runner.HANDSHAKE_ID, runner.SEMANTIC_VERSION)], ""),
            ([response("fixture-version", runner.SEMANTIC_VERSION)], ""),
        ]) as run:
            report = runner.run_conformance(self.cases, self.reference)
        self.assertEqual(report["result"], "pass", report)
        self.assertNotIn("expected", json.loads(run.call_args_list[1].args[1][0]))

    def test_version_mismatch_stops_before_cases(self) -> None:
        with patch.object(runner, "run_lean", return_value=(
            [response(runner.HANDSHAKE_ID, "wrong")], ""
        )) as run:
            report = runner.run_conformance(self.cases, self.reference)
        self.assertEqual(report["result"], "fail")
        self.assertEqual(run.call_count, 1)

    def test_missing_reference_fails_and_skip_is_unqualified(self) -> None:
        self.assertEqual(runner.run_conformance(self.cases, self.root / "missing")["result"], "fail")
        self.assertEqual(runner.run_conformance(self.cases, self.reference, skip_lean=True)["result"], "unqualified")

    def test_duplicate_fixture_ids_fail_before_reference(self) -> None:
        self.fixture.write_text(self.fixture.read_text(encoding="utf-8") * 2, encoding="utf-8")
        with patch.object(runner, "run_lean") as run:
            report = runner.run_conformance(self.cases, self.reference)
        self.assertEqual(report["result"], "fail")
        run.assert_not_called()
