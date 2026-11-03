"""NYQ-002 admits one source identity and seven historical validation deltas."""
from copy import deepcopy
import hashlib
from pathlib import Path
import unittest

from zaaggenz_contracts import digest
from tools.inverse_foundation_report import (
    compare_reports, read_json, validate_implementation_transitions,
)
from tools.inverse_validation_transition import validate_validation_transitions

ROOT = Path(__file__).resolve().parents[2]
SUCCESSOR = '9624e0bbfa30a34c17303573d7a48a46ee2f0ce3814dfdf209e2404a89ff8497'
PREDECESSOR = 'ff938e70ba2598d5f6f6f0bc305e01b580c373a8e5daca849e8d3f9392bee3a4'
PREVIOUS = '9da1f1f521292f0dd0e2ca444521260aa91301526d9798573289149736b33e6a'
CHANGED_PATHS = [
    'zaaggenz_contracts/nyquismic.py',
    'zaaggenz_contracts/nyquismic_clock.py',
    'zaaggenz_dsp/nyquismic.py',
]


def rehash(document):
    document['evidence_sha256'] = digest({k: v for k, v in document.items()
                                        if k != 'evidence_sha256'})


class NYQ002TransitionTests(unittest.TestCase):
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
        # Comparator fixture only. The actual Ubuntu/Windows reports recorded
        # in NYQ002_CI_RECONCILIATION.md establish the registration evidence.
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
        self.assertEqual(rows[0]['from_implementation_sha256'], PREDECESSOR)
        self.assertEqual(rows[0]['issue'], 251)
        self.assertEqual(rows[0]['stable_id'], 'ZG-016')
        self.assertEqual(rows[0]['changed_paths'], CHANGED_PATHS)
        self.assertFalse(self.compare(self.successor_fixture()))

    def test_seven_validation_changes_are_exact_mbr_carry_forward(self):
        previous = next(r for r in self.validations
                        if r['to_implementation_sha256'] == PREVIOUS)
        self.assertEqual(self.transition['changes'], previous['changes'])
        self.assertEqual(len(self.transition['changes']), 7)
        self.assertEqual(self.transition['from_implementation_sha256'], PREDECESSOR)
        self.assertEqual(self.transition['issue'], 251)
        self.assertEqual(self.transition['stable_id'], 'ZG-024')

    def test_registration_requires_both_exact_reviewed_rows(self):
        actual = self.successor_fixture()
        failures = compare_reports(actual, self.expected,
                                   implementation_transitions=self.implementations[:33],
                                   validation_transitions=self.validations[:8])
        expected_paths = ['/implementation_sha256'] + [c['path'] for c in self.transition['changes']]
        self.assertEqual([f.split(':')[0] for f in failures], expected_paths)
        failures = compare_reports(actual, self.expected,
                                   implementation_transitions=self.implementations[:33],
                                   validation_transitions=self.validations)
        self.assertIn('/validation-transition: implementation transition is not independently reviewed', failures)

    def test_unknown_identity_and_unreviewed_validation_still_fail(self):
        actual = self.successor_fixture()
        actual['implementation_sha256'] = '0' * 64
        rehash(actual)
        self.assertTrue(any('unreviewed transition' in f for f in self.compare(actual)))
        actual = self.successor_fixture()
        actual['fixtures'][0]['candidates'][8]['holdout']['validation'][0]['state'] = 'accepted'
        rehash(actual)
        self.assertTrue(any('successor value mismatch' in f for f in self.compare(actual)))

    def test_unrelated_portable_values_are_never_exempted(self):
        mutations = {
            'numeric score': lambda f: f['candidates'][0]['fit'].__setitem__('score', f['candidates'][0]['fit']['score'] + 1),
            'recipe': lambda f: f['candidates'][0].__setitem__('recipe_sha256', '0' * 64),
            'source definition': lambda f: f.__setitem__('definition_sha256', '0' * 64),
            'eligibility': lambda f: f['candidates'][0].__setitem__('eligible', not f['candidates'][0]['eligible']),
            'rank': lambda f: f['ranked_ordinals'].append(-1),
            'budget': lambda f: f['budget'].__setitem__('declared_evaluations', f['budget']['declared_evaluations'] + 1),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                actual = self.successor_fixture()
                mutate(actual['fixtures'][0])
                rehash(actual)
                self.assertTrue(self.compare(actual))

    def test_report_evidence_tamper_still_fails(self):
        actual = self.successor_fixture()
        actual['evidence_sha256'] = '0' * 64
        self.assertIn('actual: evidence identity mismatch', self.compare(actual))

    def test_accepted_prefixes_and_calibration_are_frozen(self):
        self.assertEqual(digest(self.implementations[:33]),
                         '85b4f1da52692f7a60560da6d7eaf97426cc25e54ad61bf0e1e63210fc7bf32f')
        self.assertEqual(digest(self.validations[:8]),
                         '024b8bc464e270dc1b960c4019101d6dcd3b0c256224f14c16533726a2834d18')
        self.assertEqual(self.implementations[33]['to_implementation_sha256'], SUCCESSOR)
        self.assertEqual(self.validations[8]['to_implementation_sha256'], SUCCESSOR)
        self.assertEqual(sum(r['to_implementation_sha256'] == SUCCESSOR for r in self.validations), 1)
        calibration = (ROOT / 'examples/zg024a_inverse_calibration.json.gz').read_bytes()
        self.assertEqual(hashlib.sha256(calibration).hexdigest(),
                         '4dfde21014b1863177db5416c0b285c0c2648f579d0d418f80f0afd8506d2761')


if __name__ == '__main__':
    unittest.main()
