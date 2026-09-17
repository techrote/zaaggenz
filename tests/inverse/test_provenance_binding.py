"""Candidate v2 must bind every authoritative search/provenance claim to one envelope."""
from copy import deepcopy
from dataclasses import replace
import unittest

from zaaggenz_contracts import digest
from zaaggenz_inverse import Candidate, InverseError
from zaaggenz_inverse.fixtures import synthetic_fixture
from zaaggenz_inverse.laboratory import prepare_experiment
from zaaggenz_inverse.results import candidate_identity, search_identity


class PersistedProvenanceBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = synthetic_fixture('identifiable')
        cls.fit, _ = cls.fixture.experiment()
        cls.candidate = cls.fit.evaluate(cls.fixture.ground_truth_state)
        alternate_request = replace(cls.fixture.request, source_revision_id='0' * 64)
        cls.alternate_fit, _ = prepare_experiment(alternate_request, cls.fixture.target, cls.fixture.plan)
        cls.alternate_candidate = cls.alternate_fit.evaluate(cls.fixture.ground_truth_state)

    def assert_tamper_rejected(self, mutate):
        data = self.candidate.to_dict()
        mutate(data)
        with self.assertRaises(InverseError):
            Candidate.from_dict(data)

    def test_candidate_roundtrip_is_exact_and_binding_is_content_addressed(self):
        data = self.candidate.to_dict()
        restored = Candidate.from_dict(deepcopy(data))
        self.assertEqual(restored.sha256, self.candidate.sha256)
        binding = data['provenance']['search_binding']
        self.assertEqual(data['provenance']['search_binding_sha256'], digest(binding))
        self.assertEqual(data['search_id'], search_identity(binding))
        method = binding['method']
        historical_search_id = digest({'domain': 'zaaggenz.inverse-search-v1', 'request': binding['request'],
            'implementation_sha256': method['implementation_sha256'],
            'feature_method_sha256': method['feature_method_sha256'], 'fit_assets': binding['fit_assets']})
        self.assertEqual(data['search_id'], historical_search_id)

    def test_each_previously_syntax_only_provenance_field_is_bound(self):
        replacements = {
            'implementation_sha256': '1' * 64,
            'environment_sha256': '2' * 64,
            'source_revision_id': '3' * 64,
            'base_recipe_sha256': '4' * 64,
            'target_asset_sha256': '5' * 64,
        }
        for key, value in replacements.items():
            with self.subTest(key=key):
                self.assert_tamper_rejected(lambda d, k=key, v=value: d['provenance'].__setitem__(k, v))

    def test_method_binding_recomputes_implementation_and_render_engine_identities(self):
        for key in ('engine_sha256', 'render_engine_base_sha256', 'implementation_sha256',
                    'render_engine_sha256', 'feature_method_sha256'):
            with self.subTest(key=key):
                self.assert_tamper_rejected(
                    lambda d, k=key: d['provenance']['search_binding']['method'].__setitem__(k, '6' * 64))

    def test_environment_manifest_tamper_cannot_retain_old_candidate_identity(self):
        def mutate(data):
            data['provenance']['search_binding']['environment']['python'] = '0.0-forged'
            data['provenance']['environment_sha256'] = digest(data['provenance']['search_binding']['environment'])
            data['provenance']['search_binding_sha256'] = digest(data['provenance']['search_binding'])
        self.assert_tamper_rejected(mutate)

    def test_request_target_or_source_revision_tamper_cannot_retain_search_identity(self):
        def source(data):
            data['provenance']['search_binding']['request']['source_revision_id'] = '7' * 64
            data['provenance']['source_revision_id'] = '7' * 64
            data['provenance']['search_binding_sha256'] = digest(data['provenance']['search_binding'])
        self.assert_tamper_rejected(source)

        def target(data):
            other = self.alternate_candidate.to_dict()['provenance']['search_binding']['request']['target_asset']
            # The alternate revision intentionally uses the same PCM; forge a different valid content identity instead.
            other = deepcopy(other)
            other['content_sha256'] = '8' * 64
            data['provenance']['search_binding']['request']['target_asset'] = other
            data['provenance']['search_binding_sha256'] = digest(data['provenance']['search_binding'])
        self.assert_tamper_rejected(target)

    def test_provenance_block_swap_between_searches_is_rejected(self):
        data = self.candidate.to_dict()
        other = self.alternate_candidate.to_dict()
        data['provenance'] = deepcopy(other['provenance'])
        with self.assertRaises(InverseError):
            Candidate.from_dict(data)

    def test_same_recipe_under_different_project_revision_has_distinct_search_and_candidate_identity(self):
        self.assertEqual(self.candidate.recipe.sha256, self.alternate_candidate.recipe.sha256)
        self.assertNotEqual(self.candidate.to_dict()['search_id'], self.alternate_candidate.to_dict()['search_id'])
        self.assertNotEqual(self.candidate.id, self.alternate_candidate.id)
        self.assertEqual(self.candidate.to_dict()['provenance']['base_recipe_sha256'],
                         self.alternate_candidate.to_dict()['provenance']['base_recipe_sha256'])
        self.assertNotEqual(self.candidate.to_dict()['provenance']['source_revision_id'],
                            self.alternate_candidate.to_dict()['provenance']['source_revision_id'])

    def test_stage_and_parent_provenance_are_bound_to_search_request(self):
        self.assert_tamper_rejected(lambda d: d['provenance']['stage'].__setitem__('id', 'forged-stage'))
        self.assert_tamper_rejected(lambda d: d['provenance']['parents'].append('9' * 64))

    def test_fitting_asset_identity_is_bound_and_window_shape_is_revalidated(self):
        def tamper(data):
            binding = data['provenance']['search_binding']
            binding['fit_assets'][0]['content_sha256'] = 'a' * 64
            data['provenance']['search_binding_sha256'] = digest(binding)
        self.assert_tamper_rejected(tamper)

        def wrong_extent(data):
            binding = data['provenance']['search_binding']
            binding['fit_assets'][0]['frame_count'] += 1
            data['provenance']['search_binding_sha256'] = digest(binding)
        self.assert_tamper_rejected(wrong_extent)

    def test_candidate_identity_includes_search_binding_digest(self):
        data = self.candidate.to_dict()
        state = self.fixture.ground_truth_state
        expected = candidate_identity(data['search_id'], state, self.candidate.recipe,
                                      data['provenance']['search_binding_sha256'])
        self.assertEqual(data['candidate_id'], expected)

    def test_legacy_v1_candidate_fails_with_explicit_replay_migration(self):
        data = self.candidate.to_dict()
        data['version'] = '1.0.0'
        data['candidate_id'] = candidate_identity(data['search_id'], self.fixture.ground_truth_state,
                                                  self.candidate.recipe)
        data['provenance'].pop('search_binding')
        data['provenance'].pop('search_binding_sha256')
        with self.assertRaisesRegex(InverseError, 'legacy InverseCandidate 1.0.0.*replay/regenerate'):
            Candidate.from_dict(data)

    def test_canonical_mono_shape_keeps_complete_candidate_identity(self):
        fit, _ = prepare_experiment(self.fixture.request, self.fixture.target[:, None], self.fixture.plan)
        same = fit.evaluate(self.fixture.ground_truth_state)
        self.assertEqual(self.candidate.sha256, same.sha256)


if __name__ == '__main__':
    unittest.main()
