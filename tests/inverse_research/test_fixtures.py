import unittest
import numpy as np

from zaaggenz_inverse.search import grid_levels
from research.zg024b import CORE_NAMES, SEARCH_SEEDS, research_fixture


class ResearchFixtureTests(unittest.TestCase):
    def test_core_truth_is_deliberately_off_five_level_grid(self):
        for name in CORE_NAMES:
            fixture = research_fixture(name, seed='24')
            truth = dict(fixture.ground_truth_state.values)
            levels = grid_levels(fixture.request)
            with self.subTest(name=name):
                self.assertTrue(any(truth[axis.path] not in values
                                    for axis, values in zip(fixture.domain.axes, levels)))

    def test_search_seed_changes_search_identity_not_target_pcm(self):
        for name in CORE_NAMES:
            a = research_fixture(name, seed=SEARCH_SEEDS[0])
            b = research_fixture(name, seed=SEARCH_SEEDS[1])
            with self.subTest(name=name):
                np.testing.assert_array_equal(a.target, b.target)
                self.assertEqual(a.request.target_asset.to_dict(), b.request.target_asset.to_dict())
                self.assertNotEqual(a.request.sha256, b.request.sha256)

    def test_budgets_are_predeclared_and_grid_has_room(self):
        for name in CORE_NAMES:
            fixture = research_fixture(name, seed='24')
            size = 1
            for values in grid_levels(fixture.request):
                size *= len(values)
            with self.subTest(name=name):
                self.assertGreaterEqual(size, fixture.budget.max_evaluations)
                self.assertIn(fixture.budget.max_evaluations, (16, 24))

    def test_unknown_seed_and_fixture_fail_closed(self):
        with self.assertRaises(ValueError):
            research_fixture('offgrid-envelope', seed='25')
        with self.assertRaises(ValueError):
            research_fixture('not-a-fixture', seed='24')


if __name__ == '__main__':
    unittest.main()
