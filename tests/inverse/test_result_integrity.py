"""Persistence boundaries must not turn forged measurements into successful candidates."""
from copy import deepcopy
import unittest
from zaaggenz_contracts import digest
from zaaggenz_inverse import Candidate, InverseError, ParameterState
from zaaggenz_inverse.fixtures import synthetic_fixture
from zaaggenz_inverse.results import candidate_identity
from zaaggenz_inverse.legacy import provenance


class ResultIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = synthetic_fixture('identifiable')
        fit, _ = cls.fixture.experiment()
        cls.candidate = fit.evaluate(cls.fixture.ground_truth_state)

    def test_scaled_value_cannot_be_forged(self):
        d = self.candidate.to_dict()
        d['fit']['objectives']['pareto_axes'][0]['scaled_value'] = 10.
        with self.assertRaises(InverseError): Candidate.from_dict(d)

    def test_scalar_score_cannot_be_forged(self):
        d = self.candidate.to_dict()
        d['fit']['objectives']['score'] = .1
        with self.assertRaises(InverseError): Candidate.from_dict(d)

    def test_aggregate_cannot_disagree_with_window_measurements(self):
        d = self.candidate.to_dict()
        d['fit']['windows'][0]['measurements']['components'][0]['value'] = .1
        with self.assertRaises(InverseError): Candidate.from_dict(d)

    def test_feature_provenance_cannot_be_forged(self):
        d = self.candidate.to_dict()
        d['provenance']['feature_sha256'] = '0'*64
        with self.assertRaises(InverseError): Candidate.from_dict(d)

    def test_candidate_identity_alone_is_not_enough_to_bind_editable_state(self):
        d = self.candidate.to_dict()
        state = ParameterState((('/source/params/decay_ms', 180.), ('/source/params/f0_hz', 72.)))
        d['parameters'] = state.to_dict()
        d['candidate_id'] = candidate_identity(d['search_id'], state, self.candidate.recipe)
        with self.assertRaises(InverseError): Candidate.from_dict(d)

    def test_canonical_mono_shape_has_identical_results(self):
        f = self.fixture
        from zaaggenz_inverse.laboratory import prepare_experiment
        fit, _ = prepare_experiment(f.request, f.target[:, None], f.plan)
        same = fit.evaluate(f.ground_truth_state)
        self.assertEqual(self.candidate.sha256, same.sha256)

    def test_recovered_baseline_provenance_is_exact_and_untouched(self):
        record = provenance()
        self.assertEqual(record['original_archive_sha256'], '90be319a4660a637077df935a8ebcbd1bb4c3a629e28e2f6d4bfe62d88dfe8a8')
        self.assertEqual(len(record['profiles']['quick']), 11)
        self.assertEqual(len(record['profiles']['balanced']), 21)
        self.assertEqual(record['method']['workers'], 1)
        self.assertFalse(record['method']['polish'])
        self.assertEqual(digest(record), digest(deepcopy(record)))


if __name__ == '__main__': unittest.main()
