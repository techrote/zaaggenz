"""MBR-001 compatibility registration cannot relax the frozen comparison gate."""
from copy import deepcopy
from pathlib import Path
import unittest

from zaaggenz_contracts import digest
from tools.inverse_foundation_report import (
    compare_reports, read_json, validate_implementation_transitions,
)
from tools.inverse_validation_transition import validate_validation_transitions

ROOT = Path(__file__).resolve().parents[2]
SUCCESSOR = 'ae62e3d4a2faa405d0d5f6f1b6b7d79362118ec408634efa41ba1051d76b8aac'
PREDECESSOR = 'ff938e70ba2598d5f6f6f0bc305e01b580c373a8e5daca849e8d3f9392bee3a4'


def rehash(document):
    document['evidence_sha256'] = digest({k: v for k, v in document.items() if k != 'evidence_sha256'})


class MBR001TransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.implementations = validate_implementation_transitions(read_json(
            ROOT / 'examples/zg024a_implementation_transitions.json'))
        cls.validations = validate_validation_transitions(read_json(
            ROOT / 'examples/zg024a_validation_transitions.json'))
        cls.transition = next(r for r in cls.validations if r['to_implementation_sha256'] == SUCCESSOR)
        cls.expected = read_json(ROOT / 'examples/zg024a_inverse_calibration.json.gz')

    def successor_fixture(self):
        # Synthetic comparator fixture, not replacement evidence or a new render.
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
        return compare_reports(actual, self.expected, implementation_transitions=self.implementations,
                               validation_transitions=self.validations)

    def test_exact_identity_and_explicit_changed_paths(self):
        rows = [r for r in self.implementations if r['to_implementation_sha256'] == SUCCESSOR]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['from_implementation_sha256'], PREDECESSOR)
        self.assertEqual(row['issue'], 239)
        self.assertEqual(set(row['changed_paths']), {
            'zaaggenz_contracts/model.py', 'zaaggenz_contracts/rack.py',
            'zaaggenz_contracts/rack_schema.py', 'zaaggenz_contracts/schema.py',
            'zaaggenz_contracts/validation.py', 'zaaggenz_project/project.py',
            'zaaggenz_project/rack_state.py', 'zaaggenz_spectral/rack_adapter.py',
        })
        self.assertFalse(self.compare(self.successor_fixture()))

    def test_seven_validation_changes_are_exact_prior_carry_forward(self):
        previous = next(r for r in self.validations if r['to_implementation_sha256'] ==
                        '3d731d708e56611008532adaae091bb93d86f781935705623a344c2a887c1753')
        self.assertEqual(self.transition['changes'], previous['changes'])
        self.assertEqual(len(self.transition['changes']), 7)
        self.assertEqual(self.transition['from_implementation_sha256'], PREDECESSOR)

    def test_unlisted_successor_and_unreviewed_state_still_fail(self):
        actual = self.successor_fixture(); actual['implementation_sha256'] = '0' * 64; rehash(actual)
        self.assertTrue(any('unreviewed transition' in f for f in self.compare(actual)))
        actual = self.successor_fixture()
        actual['fixtures'][0]['candidates'][8]['holdout']['validation'][0]['state'] = 'accepted'
        rehash(actual)
        self.assertTrue(any('successor value mismatch' in f for f in self.compare(actual)))

    def test_numeric_or_recipe_drift_and_tampered_identity_still_fail(self):
        actual = self.successor_fixture()
        actual['fixtures'][0]['candidates'][0]['fit']['score'] += 1
        rehash(actual)
        self.assertTrue(any('numeric mismatch' in f for f in self.compare(actual)))
        actual = self.successor_fixture()
        actual['fixtures'][0]['candidates'][0]['recipe_sha256'] = '0' * 64
        rehash(actual)
        self.assertTrue(any('recipe_sha256' in f for f in self.compare(actual)))
        actual = self.successor_fixture(); actual['evidence_sha256'] = '0' * 64
        self.assertIn('actual: evidence identity mismatch', self.compare(actual))


if __name__ == '__main__':
    unittest.main()
