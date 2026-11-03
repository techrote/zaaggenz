"""MBR-002 compatibility registration is exact and fail-closed."""
from copy import deepcopy
from pathlib import Path
import unittest

from zaaggenz_contracts import digest
from tools.inverse_foundation_report import (
    compare_reports, read_json, validate_implementation_transitions,
)
from tools.inverse_validation_transition import validate_validation_transitions

ROOT = Path(__file__).resolve().parents[2]
SUCCESSOR = '9da1f1f521292f0dd0e2ca444521260aa91301526d9798573289149736b33e6a'
PREDECESSOR = 'ff938e70ba2598d5f6f6f0bc305e01b580c373a8e5daca849e8d3f9392bee3a4'
PREVIOUS = 'f562faec6d279b090ff0da28b7c73fc24082d875e2fa3d9c87cc50d95072bcd3'
CHANGED_PATHS = [
    'zaaggenz_components/reconstruct.py',
    'zaaggenz_components/tracker.py',
    'zaaggenz_dsp/band_router.py',
    'zaaggenz_dsp/dynamics.py',
    'zaaggenz_jobs/scheduler.py',
    'zaaggenz_spectral/band_selective.py',
    'zaaggenz_spectral/chordness_engine.py',
    'zaaggenz_spectral/engine.py',
    'zaaggenz_spectral/rack_executor.py'
]


def rehash(document):
    document['evidence_sha256'] = digest({k: v for k, v in document.items() if k != 'evidence_sha256'})


class MBR002TransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.implementations = validate_implementation_transitions(read_json(
            ROOT / 'examples/zg024a_implementation_transitions.json'))
        cls.validations = validate_validation_transitions(read_json(
            ROOT / 'examples/zg024a_validation_transitions.json'))
        cls.transition = next(r for r in cls.validations
                              if r['to_implementation_sha256'] == SUCCESSOR)
        cls.expected = read_json(ROOT / 'examples/zg024a_inverse_calibration.json.gz')

    def successor_fixture(self):
        # Synthetic comparator fixture only; real evidence is the platform CI pair.
        actual = deepcopy(self.expected)
        actual['implementation_sha256'] = SUCCESSOR
        for change in self.transition['changes']:
            tokens = change['path'].split('/')[1:]
            parent = actual
            for token in tokens[:-1]:
                parent = parent[int(token)] if isinstance(parent, list) else parent[token]
            self.assertEqual(parent[tokens[-1]], change['from'])
            parent[tokens[-1]] = deepcopy(change['to'])
        rehash(actual)
        return actual

    def compare(self, actual):
        return compare_reports(actual, self.expected,
                               implementation_transitions=self.implementations,
                               validation_transitions=self.validations)

    def test_exact_identity_issue_and_manifest_paths(self):
        rows = [r for r in self.implementations
                if r['to_implementation_sha256'] == SUCCESSOR]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['from_implementation_sha256'], PREDECESSOR)
        self.assertEqual(row['issue'], 240)
        self.assertEqual(row['stable_id'], 'ZG-021')
        self.assertEqual(row['changed_paths'], CHANGED_PATHS)
        self.assertFalse(self.compare(self.successor_fixture()))

    def test_seven_validation_changes_are_exact_nyq_carry_forward(self):
        previous = next(r for r in self.validations
                        if r['to_implementation_sha256'] == PREVIOUS)
        self.assertEqual(self.transition['changes'], previous['changes'])
        self.assertEqual(len(self.transition['changes']), 7)
        self.assertEqual(self.transition['from_implementation_sha256'], PREDECESSOR)
        self.assertEqual(self.transition['issue'], 240)

    def test_unlisted_successor_and_unreviewed_state_still_fail(self):
        actual = self.successor_fixture()
        actual['implementation_sha256'] = '0' * 64
        rehash(actual)
        self.assertTrue(any('unreviewed transition' in f for f in self.compare(actual)))
        actual = self.successor_fixture()
        actual['fixtures'][0]['candidates'][8]['holdout']['validation'][0]['state'] = 'accepted'
        rehash(actual)
        self.assertTrue(any('successor value mismatch' in f for f in self.compare(actual)))

    def test_numeric_recipe_and_evidence_drift_still_fail(self):
        actual = self.successor_fixture()
        actual['fixtures'][0]['candidates'][0]['fit']['score'] += 1
        rehash(actual)
        self.assertTrue(any('numeric mismatch' in f for f in self.compare(actual)))
        actual = self.successor_fixture()
        actual['fixtures'][0]['candidates'][0]['recipe_sha256'] = '0' * 64
        rehash(actual)
        self.assertTrue(any('recipe_sha256' in f for f in self.compare(actual)))
        actual = self.successor_fixture()
        actual['evidence_sha256'] = '0' * 64
        self.assertIn('actual: evidence identity mismatch', self.compare(actual))

    def test_accepted_nyq_predecessor_rows_remain_unique(self):
        self.assertEqual(sum(r['to_implementation_sha256'] == PREVIOUS
                             for r in self.implementations), 1)
        self.assertEqual(sum(r['to_implementation_sha256'] == PREVIOUS
                             for r in self.validations), 1)
        self.assertEqual(self.implementations[-1]['to_implementation_sha256'], SUCCESSOR)
        self.assertEqual(self.validations[-1]['to_implementation_sha256'], SUCCESSOR)


if __name__ == '__main__':
    unittest.main()
