import copy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from zaaggenz_contracts import digest
from tools.inverse_foundation_report import (build_report, calibration_reference, compare_reports,
                                            read_json, write_json)


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch('tools.inverse_foundation_report.NAMES', ('holdout-step',)):
            cls.report, cls.full, cls.telemetry = build_report(include_legacy=False)
        cls.reference = calibration_reference(cls.report)

    def test_reference_preserves_identity_bounds_seeds_losses_and_holdouts(self):
        self.assertEqual(compare_reports(self.reference, self.reference), [])
        fixture = self.reference['fixtures'][0]
        self.assertEqual(fixture['seed'], '24')
        self.assertEqual(len(fixture['fixture_id']), 64)
        self.assertEqual(fixture['budget']['consumed_evaluations'], 3)
        self.assertEqual(fixture['domain']['axes'][0]['lower'], -6.)
        self.assertEqual(fixture['domain']['axes'][0]['upper'], 6.)
        self.assertEqual(len(fixture['candidates'][0]['fit']['losses']), 8)
        self.assertEqual(sum(c['overfit_warning'] for c in fixture['candidates']), 2)
        self.assertEqual(len(self.full[0]['audits']), 3)
        self.assertNotIn('total_seconds', self.report)
        self.assertGreater(self.telemetry['total_seconds'], 0.)

    def test_comparison_catches_modified_numeric_results_even_with_rehashed_envelope(self):
        changed = copy.deepcopy(self.reference)
        changed['fixtures'][0]['candidates'][0]['holdout']['score'] = 0.
        changed['evidence_sha256'] = digest({k:v for k,v in changed.items() if k != 'evidence_sha256'})
        differences = compare_reports(changed, self.reference)
        self.assertTrue(any('holdout/score' in d for d in differences))

    def test_comparison_catches_unrecorded_identity_tampering(self):
        changed = copy.deepcopy(self.reference)
        changed['fixtures'][0]['fixture_id'] = '0'*64
        self.assertIn('actual: evidence identity mismatch', compare_reports(changed, self.reference))

    def test_gzip_evidence_is_deterministic_and_roundtrips(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = (Path(directory)/n for n in ('a.json.gz','b.json.gz'))
            write_json(a,self.reference,compact=True); write_json(b,self.reference,compact=True)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            self.assertEqual(read_json(a),self.reference)


if __name__ == '__main__': unittest.main()
