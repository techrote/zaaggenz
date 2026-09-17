import copy
import unittest

from tools.inverse_validation_transition import (
    apply_validation_transition,
    validate_validation_transitions,
)


OLD = '1' * 64
NEW = '2' * 64
STATE_PATH = '/fixtures/0/candidates/0/holdout/validation/0/state'
GATES_PATH = '/fixtures/0/candidates/0/holdout/validation/0/triggered_gates'


def projection(state='accepted', gates=None):
    if gates is None:
        gates = []
    return {'fixtures': [{'candidates': [{'holdout': {'validation': [
        {'state': state, 'triggered_gates': list(gates), 'allowed_gates': []}
    ]}}]}]}


def document(changes=None):
    if changes is None:
        changes = [
            {'path': STATE_PATH, 'from': 'accepted', 'to': 'rejected'},
            {'path': GATES_PATH, 'from': [], 'to': ['transient_loss']},
        ]
    return {
        'kind': 'InverseFoundationValidationTransitions',
        'version': '1.0.0',
        'transitions': [{
            'from_implementation_sha256': OLD,
            'to_implementation_sha256': NEW,
            'issue': 87,
            'stable_id': 'ZG-024',
            'reason': 'reviewed test migration',
            'changes': changes,
        }],
    }


class ValidationTransitionTests(unittest.TestCase):
    def test_exact_path_and_values_align_only_disposable_comparison_copy(self):
        expected = projection()
        actual = projection('rejected', ['transient_loss'])
        transitions = validate_validation_transitions(document())
        aligned, failures, accepted = apply_validation_transition(
            actual, expected, expected_impl=OLD, actual_impl=NEW,
            transitions=transitions, implementation_transition_reviewed=True)
        self.assertEqual(failures, [])
        self.assertEqual(accepted, 2)
        self.assertEqual(aligned, expected)
        self.assertEqual(actual, projection('rejected', ['transient_loss']))

    def test_validation_migration_requires_independent_implementation_review(self):
        expected = projection()
        actual = projection('rejected', ['transient_loss'])
        transitions = validate_validation_transitions(document())
        _, failures, accepted = apply_validation_transition(
            actual, expected, expected_impl=OLD, actual_impl=NEW,
            transitions=transitions, implementation_transition_reviewed=False)
        self.assertIn('/validation-transition: implementation transition is not independently reviewed', failures)
        self.assertEqual(accepted, 2)

    def test_wrong_predecessor_or_successor_value_fails_closed(self):
        transitions = validate_validation_transitions(document())
        wrong_actual = projection('accepted', ['transient_loss'])
        _, failures, accepted = apply_validation_transition(
            wrong_actual, projection(), expected_impl=OLD, actual_impl=NEW,
            transitions=transitions, implementation_transition_reviewed=True)
        self.assertTrue(any('successor value mismatch' in failure for failure in failures))
        self.assertEqual(accepted, 1)
        wrong_expected = projection('rejected', [])
        _, failures, accepted = apply_validation_transition(
            projection('rejected', ['transient_loss']), wrong_expected,
            expected_impl=OLD, actual_impl=NEW, transitions=transitions,
            implementation_transition_reviewed=True)
        self.assertTrue(any('predecessor value mismatch' in failure for failure in failures))
        self.assertEqual(accepted, 1)

    def test_unrelated_identity_pair_gets_no_migration(self):
        actual = projection('rejected', ['transient_loss'])
        aligned, failures, accepted = apply_validation_transition(
            actual, projection(), expected_impl='3' * 64, actual_impl=NEW,
            transitions=validate_validation_transitions(document()),
            implementation_transition_reviewed=True)
        self.assertIs(aligned, actual)
        self.assertEqual(failures, [])
        self.assertEqual(accepted, 0)

    def test_scope_wildcards_duplicates_and_ambiguous_gate_lists_are_rejected(self):
        invalid_paths = [
            '/fixtures/0/candidates/0/holdout/score',
            '/fixtures/*/candidates/0/holdout/validation/0/state',
            '/fixtures/0/candidates/0/holdout/validation/0/allowed_gates',
        ]
        for path in invalid_paths:
            with self.subTest(path=path):
                bad = document([{'path': path, 'from': 'accepted', 'to': 'rejected'}])
                with self.assertRaises(ValueError):
                    validate_validation_transitions(bad)
        duplicate = document([
            {'path': STATE_PATH, 'from': 'accepted', 'to': 'rejected'},
            {'path': STATE_PATH, 'from': 'accepted', 'to': 'rejected'},
        ])
        with self.assertRaises(ValueError):
            validate_validation_transitions(duplicate)
        duplicate_gates = document([
            {'path': GATES_PATH, 'from': [], 'to': ['transient_loss', 'transient_loss']},
        ])
        with self.assertRaises(ValueError):
            validate_validation_transitions(duplicate_gates)


if __name__ == '__main__':
    unittest.main()
