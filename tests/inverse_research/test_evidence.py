import json
from pathlib import Path
import unittest

from research.zg024b import METHODS, CORE_NAMES, SEARCH_SEEDS

ROOT = Path(__file__).resolve().parents[2]
CAL = ROOT / 'examples' / 'zg024b_strategy_calibration_transient_v4.json'
LEGACY_CAL = ROOT / 'examples' / 'zg024b_strategy_calibration.json'


class EvidenceCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(CAL.read_text(encoding='utf-8'))
        cls.legacy = json.loads(LEGACY_CAL.read_text(encoding='utf-8'))

    def test_design_is_the_preregistered_matrix(self):
        d = self.data['design']
        self.assertEqual(tuple(d['methods']), METHODS)
        self.assertEqual(tuple(d['core_fixtures']), CORE_NAMES)
        self.assertEqual(tuple(d['search_seeds']), SEARCH_SEEDS)
        self.assertEqual(d['portable_tolerances'], {'absolute': 1e-7, 'relative': 1e-5})
        self.assertEqual(len(self.data['fixture_results']), len(METHODS) * len(CORE_NAMES))

    def test_each_fixture_method_preserves_all_three_seed_outcomes(self):
        expected = {(fixture, method) for fixture in CORE_NAMES for method in METHODS}
        actual = {(row['fixture'], row['method_id']) for row in self.data['fixture_results']}
        self.assertEqual(actual, expected)
        for row in self.data['fixture_results']:
            for key in ('best_fit_by_seed', 'best_holdout_by_seed', 'eligible_by_seed',
                        'pareto_by_seed', 'parameter_error_by_seed', 'manifold_error_by_seed'):
                self.assertEqual(len(row[key]), len(SEARCH_SEEDS))

    def test_holdout_sentinel_remains_fit_indistinguishable_and_audit_bad(self):
        sentinel = self.data['holdout_sentinel']
        self.assertEqual({x['method_id'] for x in sentinel}, set(METHODS))
        for row in sentinel:
            self.assertEqual(row['best_fit_score'], 0.0)
            self.assertGreater(row['best_holdout_score'], 1.27)
            self.assertTrue(row['overfit_warning'])
            self.assertEqual(row['pareto_candidates'], 9)

    def test_calibration_records_no_final_optimizer_selection(self):
        encoded = json.dumps(self.data, sort_keys=True).lower()
        self.assertNotIn('selected_optimizer', encoded)
        self.assertNotIn('production_optimizer', encoded)
        self.assertIn('full per-component candidate/lineage evidence remains in ci artifacts',
                      self.data['note'].lower())

    def test_grid_envelope_missing_results_remain_explicit_not_fake_scores(self):
        grid_envelope = next(x for x in self.data['fixture_results']
                             if x['fixture'] == 'offgrid-envelope' and x['method_id'] == 'zg024b.grid-prefix.v1')
        self.assertEqual(grid_envelope['best_fit_by_seed'], [None, None, None])
        self.assertEqual(grid_envelope['eligible_by_seed'], [0, 0, 0])

    def test_transient_v4_strategy_calibration_is_versioned_not_rewritten(self):
        self.assertNotEqual(self.data, self.legacy)
        legacy_coordinate = next(x for x in self.legacy['fixture_results']
                                 if x['fixture'] == 'offgrid-envelope'
                                 and x['method_id'] == 'zg024b.coordinate-refine.v1')
        current_coordinate = next(x for x in self.data['fixture_results']
                                  if x['fixture'] == 'offgrid-envelope'
                                  and x['method_id'] == 'zg024b.coordinate-refine.v1')
        self.assertEqual(legacy_coordinate['eligible_by_seed'], [0, 5, 1])
        self.assertEqual(current_coordinate['eligible_by_seed'], [3, 0, 0])
        self.assertEqual(self.legacy['design'], self.data['design'])


if __name__ == '__main__':
    unittest.main()
