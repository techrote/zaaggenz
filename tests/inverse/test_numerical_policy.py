"""Regress the rich-fixture association instability exposed by Windows CI."""
from copy import deepcopy
import unittest

import numpy as np

from zaaggenz_components import ComponentTrackerSpec
from zaaggenz_components.tracker import _candidate_frames, _track
from zaaggenz_inverse.contracts import InverseError
from zaaggenz_inverse.fixtures import make_fixture
from zaaggenz_inverse.objectives import ObjectivePlan, FeatureStore
from zaaggenz_inverse.render import execution_identity


class NumericalPolicyTests(unittest.TestCase):
    def test_component_policy_is_explicit_roundtrippable_and_identity_relevant(self):
        stable = ObjectivePlan()
        legacy = ObjectivePlan(component_spec=ComponentTrackerSpec())
        self.assertEqual(stable.to_dict()['components']['assignment_cost_policy'], 'integer-microcent-v1')
        self.assertEqual(ObjectivePlan.from_dict(stable.to_dict()), stable)
        self.assertEqual(ObjectivePlan.from_dict(legacy.to_dict()), legacy)
        self.assertNotEqual(stable.sha256, legacy.sha256)
        with self.assertRaises(InverseError):
            ObjectivePlan(component_spec=ComponentTrackerSpec(max_tracks=64))

    def test_component_policy_cannot_reuse_legacy_features(self):
        f = make_fixture('nonidentifiable-gains')
        store = FeatureStore(execution_identity())
        source = f.renderer.source
        store.measure(source, ObjectivePlan())
        store.measure(source, ObjectivePlan(component_spec=ComponentTrackerSpec()))
        self.assertEqual(store.misses, 2)
        store.measure(source, ObjectivePlan())
        self.assertEqual(store.hits, 1)

    def test_portable_comparison_rejects_changed_experiment_without_relaxing_metrics(self):
        from tools.inverse_foundation_report import compare_reports
        from pathlib import Path
        import json
        # The committed calibration also serves as a comparison-contract fixture;
        # no expensive search is needed to test metadata and metric tampering.
        path = Path(__file__).resolve().parents[2] / 'examples/zg024a_inverse_baseline.json'
        expected = json.loads(path.read_text(encoding='utf-8'))
        compare_reports(expected, expected)
        for field in ('seed', 'budget', 'domain', 'grid', 'windows', 'method', 'objectives', 'validation'):
            changed = deepcopy(expected)
            changed['core']['fixtures'][0]['request'][field] = None
            with self.subTest(field=field), self.assertRaises(AssertionError):
                compare_reports(changed, expected)
        changed = deepcopy(expected)
        changed['core']['fixtures'][0]['retained'][0]['fit']['vector'][0] += .01
        with self.assertRaises(AssertionError):
            compare_reports(changed, expected)

    def test_rich_fixture_tracks_stable_under_sub_microcent_perturbations(self):
        f = make_fixture('rich-nonlinear-48k')
        spec = ComponentTrackerSpec(assignment_cost_policy='integer-microcent-v1')
        for grid_index in (16, 20, 17):
            output = f.renderer.render(f.request.grid.point(grid_index), '24001').output.audio[:8192, None]
            _, frames, _ = _candidate_frames(output, 48000, spec)
            def association(rows):
                return [[(r['frame'], round(r['frequency_hz'], 5)) for r in t['rows']]
                        for t in _track(deepcopy(rows), spec)]
            expected = association(frames)
            for seed in range(10):
                altered = deepcopy(frames)
                rng = np.random.default_rng(seed)
                for frame in altered:
                    for row in frame:
                        row['frequency_hz'] += 1e-10 * rng.normal()
                with self.subTest(grid_index=grid_index, perturbation_seed=seed):
                    self.assertEqual(association(altered), expected)


if __name__ == '__main__':
    unittest.main()
