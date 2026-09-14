from dataclasses import replace
import json
import unittest
import numpy as np

from zaaggenz_contracts import Contract, digest
from zaaggenz_project import Project
from zaaggenz_inverse import *
from zaaggenz_inverse.fixtures import synthetic_fixture
from zaaggenz_inverse.recipes import apply_state, validate_domain, render_trace, implementation_manifest, engine_identity


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = synthetic_fixture('identifiable')
        cls.request = cls.fixture.request

    def test_request_round_trip_uses_existing_contracts(self):
        request = SearchRequest.from_dict(self.request.to_dict())
        self.assertEqual(request.sha256, self.request.sha256)
        self.assertIsInstance(request.base_recipe, Contract)
        self.assertIsInstance(request.target_asset, Contract)
        self.assertEqual(request.source_revision_id, Project(self.fixture.base_recipe).head)

    def test_all_small_contract_round_trips(self):
        f = self.fixture
        values = (f.domain.axes[0], f.domain, f.ground_truth_state, f.plan.fit[0], f.plan,
                  SearchStage(), f.budget, f.objective.terms[0], f.objective, ValidationPolicy(),
                  Checkpoint('a'*64, 'b'*64, 1, ('c'*64,)))
        for value in values:
            with self.subTest(type=type(value).__name__):
                rebuilt = type(value).from_dict(value.to_dict())
                self.assertEqual(value.sha256, rebuilt.sha256)

    def test_unknown_missing_and_future_fields_rejected(self):
        for variant in ('unknown', 'missing', 'version'):
            d = self.request.to_dict()
            if variant == 'unknown': d['magic_optimizer'] = True
            if variant == 'missing': del d['seed']
            if variant == 'version': d['version'] = '99.0.0'
            with self.subTest(variant=variant), self.assertRaises(InverseError):
                SearchRequest.from_dict(d)

    def test_bounds_are_explicit_finite_ordered_and_typed(self):
        for lo, hi in ((True, 1.), (float('nan'), 1.), (0., float('inf')), (2., 1.), ('0', 1)):
            with self.subTest(lo=lo, hi=hi), self.assertRaises(InverseError):
                ParameterAxis('/source/params/f0_hz', lo, hi, 'Hz')
        with self.assertRaises(InverseError): ParameterAxis('/x', .5, 2, 'count', 'integer')
        with self.assertRaises(InverseError): ParameterAxis('/x', 0, 1, '')
        with self.assertRaises(InverseError): ParameterAxis('/nodes/00/params/mix', 0, 1, 'ratio')

    def test_seed_is_existing_string_u64_convention(self):
        for seed in (24, '-1', str(2**64), '01', 'nan'):
            with self.subTest(seed=seed), self.assertRaises((InverseError, ValueError)):
                replace(self.request, seed=seed)
        self.assertEqual(replace(self.request, seed=str(2**64-1)).seed, str(2**64-1))

    def test_budget_rejects_unbounded_or_nonverified_work(self):
        for kwargs in ({'max_evaluations': 0}, {'max_evaluations': 257}, {'max_evaluations': True},
                       {'grid_points_per_axis': 1}, {'render_repeats': 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(InverseError): SearchBudget(**kwargs)

    def test_unknown_optimizer_is_not_silently_accepted(self):
        with self.assertRaises(InverseError): SearchStage(method_id='clever.v1')

    def test_window_overlap_including_fit_holdout_rejected(self):
        for plan in ((Window('a',0,100), Window('b',99,200)),
                     (Window('a',0,100), Window('a',100,200))):
            with self.assertRaises(InverseError): WindowPlan((plan[0],), (plan[1],), 300)
        with self.assertRaises(InverseError): Window('tiny',0,31)
        with self.assertRaises(InverseError): WindowPlan((Window('a',0,100),), (Window('b',100,400),), 300)
        with self.assertRaises(InverseError): WindowPlan((), (Window('b',100,200),), 300)

    def test_duplicate_parameter_paths_fail(self):
        a = self.fixture.domain.axes[0]
        with self.assertRaises(InverseError): ParameterDomain((a,a))
        with self.assertRaises(InverseError): ParameterState(((a.path,a.lower),(a.path,a.upper)))
        with self.assertRaises(InverseError): ParameterState(((a.path,float('inf')),))

    def test_registered_bounds_units_and_timeline_enforced(self):
        recipe = self.fixture.base_recipe
        for axis in (ParameterAxis('/source/params/f0_hz',1.,1e6,'Hz'),
                     ParameterAxis('/source/params/f0_hz',60.,80.,'ms'),
                     ParameterAxis('/source/params/beats',1,4,'count','integer')):
            with self.subTest(axis=axis), self.assertRaises(InverseError): validate_domain(recipe,ParameterDomain((axis,)))

    def test_state_bounds_and_missing_values_rejected_before_render(self):
        f = self.fixture
        values = list(f.ground_truth_state.values)
        values[0] = (values[0][0], 1e6)
        with self.assertRaises(InverseError): apply_state(f.base_recipe,f.domain,ParameterState(tuple(values)))
        with self.assertRaises(InverseError): apply_state(f.base_recipe,f.domain,ParameterState((values[1],)))

    def test_integer_state_and_endpoint_precision(self):
        f = synthetic_fixture('polarity-feature-conflict')
        with self.assertRaises(InverseError): f.domain.validate_state(ParameterState((('/source/params/harmonic_count',9.),)))
        for value in (7,11):
            f.domain.validate_state(ParameterState((('/source/params/harmonic_count',value),)))

    def test_source_f0_updates_existing_tuning_projection(self):
        recipe = apply_state(self.fixture.base_recipe,self.fixture.domain,self.fixture.ground_truth_state)
        self.assertEqual(recipe.to_dict()['tuning']['reference_hz'],72.)
        self.assertEqual(recipe.sha256,self.fixture.ground_truth_recipe.sha256)

    def test_registered_automation_binding(self):
        f = synthetic_fixture('holdout-step')
        patched = apply_state(f.base_recipe,f.domain,f.ground_truth_state)
        self.assertEqual(patched.sha256,f.ground_truth_recipe.sha256)

    def test_target_identity_and_frame_mismatch_fail_closed(self):
        f = self.fixture
        with self.assertRaises(InverseError): prepare_experiment(f.request,f.target*.5,f.plan)
        changed = f.base_recipe.to_dict();changed['source']['params']['beat_fill'] = .5
        # Rebuild through the authoritative source adapter, not a forged time projection.
        from zaaggenz_contracts.legacy import freeze_legacy
        short = freeze_legacy(changed['source']['params'])
        request = replace(f.request,base_recipe=short,source_revision_id=Project(short).head)
        with self.assertRaises(InverseError): prepare_experiment(request,f.target,f.plan)

    def test_unknown_descriptor_never_becomes_zero(self):
        with self.assertRaises(InverseError): ObjectiveTerm('pleasure')
        with self.assertRaises(InverseError): ObjectiveTerm('waveform',scale=0.)
        with self.assertRaises(InverseError): ObjectivePolicy((ObjectiveTerm('waveform',weight=0.),))
        with self.assertRaises(InverseError): ObjectivePolicy((ObjectiveTerm('roughness'),))

    def test_nonfinite_and_provenance_failures_cannot_be_allowed(self):
        for gate in ('non_finite','hidden_level_handling','invalid_shape','invalid_gain_provenance'):
            with self.subTest(gate=gate), self.assertRaises(InverseError): ValidationPolicy(allowed=(gate,))
        self.assertEqual(ValidationPolicy(allowed=('level_mismatch',)).allowed,('level_mismatch',))

    def test_contract_payloads_and_audio_are_immutable(self):
        d = self.request.to_dict(); d['base_recipe']['source']['params']['f0_hz'] = 100.
        self.assertEqual(self.request.base_recipe.to_dict()['source']['params']['f0_hz'],60.)
        with self.assertRaises(ValueError): self.fixture.target.setflags(write=True)
        fit,_ = self.fixture.experiment()
        with self.assertRaises(AttributeError): fit.request = replace(self.request,seed='7')
        with self.assertRaises(AttributeError): fit.features.root_hz = 999.
        with self.assertRaises(ValueError): fit._fit[0].setflags(write=True)
        manifest = implementation_manifest();manifest['source_files'].clear()
        self.assertTrue(implementation_manifest()['source_files'])

    def test_checkpoint_strict_envelope_and_duplicate_json(self):
        cp = Checkpoint('a'*64,'b'*64,1,('c'*64,))
        self.assertEqual(Checkpoint.from_json(json.dumps(cp.to_dict())).sha256,cp.sha256)
        with self.assertRaises(InverseError): Checkpoint('a'*64,'b'*64,2,('c'*64,))
        with self.assertRaises(InverseError): Checkpoint.from_json('{"kind":"Checkpoint","kind":"Checkpoint"}')
        d=cp.to_dict();d['version']='2.0.0'
        with self.assertRaises(InverseError): Checkpoint.from_dict(d)

if __name__=='__main__': unittest.main()
