"""Qualification metadata cannot silently turn fixture presence into gate evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from qualification_common import Qualification, redacted


class QualificationProtocolTests(unittest.TestCase):

    def test_blocked_case_is_nonzero_and_no_gate_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            q = Qualification('unit-report', Path(directory))
            q.blocked('approved-enterprise-scratch', ['Q61'], 'No approved endpoint')
            self.assertEqual(q.finish(), 1)
            report = json.loads((Path(directory) / 'report.json').read_text())
            self.assertFalse(report['gate_pass'])
            self.assertFalse(report['executed_cases_passed'])
            self.assertEqual(report['cases'][0]['status'], 'blocked')

    def test_executed_success_is_not_whole_gate_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            q = Qualification('unit-report', Path(directory))
            q.case('one-explicit-assertion', [], lambda: {'asserted': 1 == 1})
            self.assertEqual(q.finish(), 0)
            self.assertFalse(q.report['gate_pass'])
            self.assertTrue(q.report['executed_cases_passed'])

    def test_credential_diagnostics_are_redacted(self):
        raw = {'argv': ['tool', '--token', 'private-token-value'],
               'stderr': 'https://user:password@example.invalid token=secret Authorization: Bearer hidden'}
        protected = redacted(raw)
        self.assertNotIn('private-token-value', json.dumps(protected))
        self.assertNotIn('user:password', json.dumps(protected))
        self.assertNotIn('=secret', json.dumps(protected))
        self.assertNotIn('Bearer hidden', json.dumps(protected))

    def test_missing_model_trials_cannot_be_imported_as_success(self):
        from evaluate_kctx import import_agent_receipts
        protocol_path = ROOT / 'fixtures' / 'qualification' / 'evaluation-v1.json'
        protocol = json.loads(protocol_path.read_text())
        identity = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipts = root / 'receipts.json'
            measurements = root / 'measurements.json'
            receipts.write_text(json.dumps({'schema_version':1,'protocol_sha256':identity,'trials':[]}))
            corpus_path = ROOT / 'fixtures' / 'qualification' / 'corpus-lock.json'
            corpus_lock = json.loads(corpus_path.read_text())
            measurements.write_text(json.dumps({'protocol_sha256':identity,'exported_trial_payloads':[],
                'corpus_version':corpus_lock['corpus_version'],
                'corpus_lock_sha256':hashlib.sha256(corpus_path.read_bytes()).hexdigest()}))
            q = Qualification('unit-import', root / 'report')
            with self.assertRaises(AssertionError):
                import_agent_receipts(q, protocol, receipts, measurements)
            self.assertFalse(q.report['gate_pass'])

    def test_historical_context_excludes_future_information(self):
        from evaluate_kctx import FACTS, require_historical_blindness
        task = {'change_family':'old-release','expected_context_paths':['old.md'],'selected_time':100}
        note = {'path':'old.md','revision':'old','content':FACTS['old-release']}
        require_historical_blindness(task,'old',[note])
        for leaked in (
            [{**note,'content':note['content']+' A later release at time 110 corrects enabled=true.'}],
            [{**note,'revision':'new'}],
            [note,{'path':'operations/later-correction.json','revision':'old','content':'{}'}],
            [note,{'path':'operations/capture.json','revision':'old','content':'{"observed_at":110}'}],
        ):
            with self.subTest(context=leaked), self.assertRaises(AssertionError):
                require_historical_blindness(task,'old',leaked)

    def test_prepatch_corpus_cannot_supply_blind_model_trials(self):
        from evaluate_kctx import import_agent_receipts
        protocol_path = ROOT / 'fixtures' / 'qualification' / 'evaluation-v1.json'
        protocol = json.loads(protocol_path.read_text())
        identity = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipts, measurements = root/'receipts.json', root/'measurements.json'
            receipts.write_text(json.dumps({'schema_version':1,'protocol_sha256':identity,'trials':[]}))
            measurements.write_text(json.dumps({'protocol_sha256':identity,'exported_trial_payloads':[]}))
            with self.assertRaisesRegex(AssertionError,'pre-correction'):
                import_agent_receipts(Qualification('unit-import',root/'report'),protocol,receipts,measurements)


if __name__ == '__main__':
    unittest.main()
