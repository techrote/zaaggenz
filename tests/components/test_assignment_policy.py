"""Opt-in deterministic assignment without changing recovered/default semantics."""
import unittest

import numpy as np
from scipy.optimize import linear_sum_assignment

from zaaggenz_components import ComponentError, ComponentTrackerSpec
from zaaggenz_components.tracker import _assignment_cost


class AssignmentPolicyTests(unittest.TestCase):
    def test_legacy_default_preserves_costs_and_metadata(self):
        spec = ComponentTrackerSpec()
        self.assertEqual(spec.assignment_cost_policy, 'legacy-float-v1')
        self.assertNotIn('assignment_cost_policy', spec.metadata())
        cost = np.array([[100., 200.]])
        self.assertIs(_assignment_cost(cost, spec.assignment_cost_policy), cost)

    def test_explicit_policy_roundtrip_and_invalid_policy(self):
        spec = ComponentTrackerSpec(assignment_cost_policy='integer-microcent-v1')
        self.assertEqual(ComponentTrackerSpec(**spec.metadata()), spec)
        with self.assertRaises(ComponentError):
            ComponentTrackerSpec(assignment_cost_policy='unregistered')

    def test_integer_microcents_not_an_epsilon_added_to_objective(self):
        c = np.array([[.0000004, .0000006], [1., 2.]])
        np.testing.assert_array_equal(_assignment_cost(c, 'integer-microcent-v1'),
                                      [[0., 1.], [1000000., 2000000.]])
        np.testing.assert_array_equal(c, [[.0000004, .0000006], [1., 2.]])

    def test_log_distance_assignment_ties_are_stable_not_libm_dependent(self):
        # For all candidates above all predicted frequencies, total L1 log
        # distance is equal for every permutation. Last-bit roundoff used to
        # change the selected trajectory, not just a metric's last digit.
        costs = [np.array([[100., 300.], [200., 400. + d]]) for d in (-1e-12, 1e-12)]
        legacy = [tuple(linear_sum_assignment(c)[1]) for c in costs]
        stable = [tuple(linear_sum_assignment(_assignment_cost(c, 'integer-microcent-v1'))[1]) for c in costs]
        self.assertNotEqual(*legacy)
        self.assertEqual(*stable)

    def test_invalid_and_nonexact_cost_arithmetic_fails_closed(self):
        for value in (float('nan'), float('inf'), -1., 1e20):
            with self.subTest(value=value), self.assertRaises(ComponentError):
                _assignment_cost(np.array([[value]]), 'integer-microcent-v1')
        with self.assertRaises(ComponentError):
            _assignment_cost(np.array([[1.]]), 'unknown')


if __name__ == '__main__':
    unittest.main()
