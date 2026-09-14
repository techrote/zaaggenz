"""Boundary and canonical-identity acceptance; no optimiser quality thresholds."""
import dataclasses
import json
import unittest
import numpy as np

from zaaggenz_contracts import ContractError, digest
from zaaggenz_inverse.contracts import *
from zaaggenz_inverse.render import AudioBuffer, GraphRenderer, execution_identity
from zaaggenz_inverse.objectives import ObjectivePlan, AXES
from zaaggenz_inverse.validation import GatePolicy
from zaaggenz_inverse.fixtures import make_fixture


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = make_fixture('nonidentifiable-gains')

    def test_round_trip_and_defensive_ownership(self):
        r = self.case.request
        self.assertEqual(SearchRequest.from_json(r.to_json()).sha256, r.sha256)
        d = r.to_dict(); d['seed'] = '42'
        self.assertNotEqual(SearchRequest.from_dict(d).sha256, r.sha256)
        self.assertEqual(r.to_dict()['seed'], '24001')
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r._json = b'{}'

    def test_canonical_mapping_and_numeric_values(self):
        a = ParameterState.from_mapping({'b': 1., 'a': 0})
        b = ParameterState.from_mapping({'a': -0., 'b': 1})
        self.assertEqual(a.sha256, b.sha256)
        d = self.case.request.to_dict()
        self.assertEqual(digest(dict(reversed(list(d.items())))), self.case.request.sha256)
        grid = Grid((('b', (2, 0, 1)), ('a', (1, 0))))
        self.assertEqual(grid.point(0).to_dict(), {'a': 0, 'b': 0})
        self.assertEqual(grid.point(3).to_dict(), {'a': 1, 'b': 0})

    def test_parameter_types_and_domains(self):
        for value in (float('nan'), float('inf'), True, '1'):
            with self.subTest(value=value), self.assertRaises(ContractError):
                ParameterState.from_mapping({'gain': value})
        for lower, upper in ((2, 1), (False, 1), (0, float('inf'))):
            with self.assertRaises(ContractError): ParameterBound('gain', 'dB', lower, upper)
        b = ParameterBound('count', 'count', 1, 3, True)
        for bad in (.5, 1.5, 4):
            with self.assertRaises(ContractError): b.validate(bad)
        domain = ParameterDomain((b,))
        for values in ({'other': 2}, {'count': 2, 'extra': 0}):
            with self.assertRaises(ContractError): domain.validate(ParameterState.from_mapping(values))
        with self.assertRaises(ContractError): ParameterDomain((b, b))

    def test_grid_bounds_duplicates_and_budget(self):
        for axes in ((('a', (0, 0)),), (('a', (0,)), ('a', (1,))), (('a', tuple(range(129))),)):
            with self.assertRaises(ContractError): Grid(axes)
        with self.assertRaises(ContractError): Grid(tuple((f'x{i}', tuple(range(128))) for i in range(4)))
        with self.assertRaises(ContractError): Grid((('a', (-1, 1)),)).validate(ParameterDomain((ParameterBound('a', 'dB', 0, 1),)))
        for evaluations, retain in ((0, 1), (513, 1), (1, 2), (17, 17), (True, 1)):
            with self.assertRaises(ContractError): Budget(evaluations, retain)
        with self.assertRaises(ContractError): self.case.request.grid.point(9)

    def test_window_plan_is_disjoint_bounded_and_exact(self):
        a = Window('fit', 0, 64)
        for held in (Window('test', 63, 96), Window('fit', 64, 128)):
            with self.assertRaises(ContractError): WindowPlan((a,), (held,))
        with self.assertRaises(ContractError): Window('tiny', 0, 31)
        with self.assertRaises(ContractError): WindowPlan((a,), ())
        p = WindowPlan((a,), (Window('test', 64, 128),))
        with self.assertRaises(ContractError): p.validate_frames(127)
        d = a.to_dict(); d['support']['anchor_sample'] += 1
        with self.assertRaises(ContractError): Window.from_dict(d)

    def test_unknown_fields_versions_and_seed(self):
        for transform in (lambda d: d.update(extra=True), lambda d: d.update(version='2.0.0'),
                          lambda d: d.update(seed=1), lambda d: d.update(seed='01'),
                          lambda d: d.update(seed=str(2**64))):
            d = self.case.request.to_dict(); transform(d)
            with self.assertRaises(ContractError): SearchRequest.from_dict(d)
        with self.assertRaises(ContractError): SearchRequest.from_json('{"seed":1,"seed":2}')
        with self.assertRaises(ContractError): Snapshot({'x': float('nan')})

    def test_identity_binds_all_relevant_inputs(self):
        r = self.case.request; original = r.sha256
        variants = []
        for field in ('source', 'target'):
            d = r.to_dict(); d[field]['content_sha256'] = 'a' * 64; variants.append(d)
        d = r.to_dict(); d['domain']['bounds'][0]['lower'] -= 1; variants.append(d)
        d = r.to_dict(); d['seed'] = '9'; variants.append(d)
        d = r.to_dict(); d['stage']['id'] = 'next'; variants.append(d)
        d = r.to_dict(); d['budget']['evaluations'] = 8; d['budget']['retain'] = 8; variants.append(d)
        d = r.to_dict(); d['windows']['fitting'][0]['support']['start_sample'] = 32
        d['windows']['fitting'][0]['support']['anchor_sample'] = (32+2048-1)//2; variants.append(d)
        d = r.to_dict(); d['renderer']['version'] = '1.0.1'; variants.append(d)
        d = r.to_dict(); d['execution']['implementation_sha256'] = 'b'*64; variants.append(d)
        d = r.to_dict(); d['objectives']['metrics']['waveform']['weight'] = 2.; variants.append(d)
        for d in variants:
            with self.subTest(d=d): self.assertNotEqual(SearchRequest.from_dict(d).sha256, original)
        self.assertNotEqual(r.candidate_id(r.grid.point(0)), r.candidate_id(r.grid.point(1)))

    def test_parent_lineage_is_explicit(self):
        r = self.case.request
        stage = Stage('texture', r.sha256, (r.candidate_id(r.grid.point(0)),))
        self.assertEqual(Stage.from_dict(stage.to_dict()), stage)
        with self.assertRaises(ContractError): Stage(parent_candidate_ids=('a'*64,))
        d = r.to_dict(); d['stage'] = stage.to_dict()
        self.assertNotEqual(SearchRequest.from_dict(d).sha256, r.sha256)

    def test_pcm_identity_is_the_measured_f32_and_readonly(self):
        x = np.ones(128, dtype=np.float64)*.1
        a = AudioBuffer(x, 12000); b = AudioBuffer(x + 1e-12, 12000)
        self.assertEqual(a.asset.sha256, b.asset.sha256)
        self.assertEqual(a.pcm, b.pcm)
        x[:] = 0
        self.assertGreater(float(a.audio[0]), 0)
        with self.assertRaises(ValueError): a.audio[0] = 0
        for bad in (np.zeros(31), np.zeros((64,3)), np.full(64,np.nan), np.ones(64)*1e7, np.ones(64,dtype=complex)):
            with self.assertRaises(ContractError): AudioBuffer(bad, 12000)

    def test_existing_graph_roundtrip_and_registry_bounds(self):
        r = self.case.renderer
        copied = GraphRenderer.from_method(r.source, r.method)
        state = self.case.request.grid.point(2)
        self.assertEqual(r.render(state, '0').sha256, copied.render(state, '0').sha256)
        bad = r.method; bad['configuration']['recipe_sha256'] = '0'*64
        with self.assertRaises(ContractError): GraphRenderer.from_method(r.source, bad)
        domain = ParameterDomain(tuple(ParameterBound(b.name, 'wrong', b.lower, b.upper) for b in self.case.request.domain.bounds))
        with self.assertRaises(ContractError): r.validate_domain(domain)
        domain = ParameterDomain(tuple(ParameterBound(b.name, b.unit, -1000, 1000) for b in self.case.request.domain.bounds))
        with self.assertRaises(ContractError): r.validate_domain(domain)

    def test_objective_and_gate_contracts(self):
        for bad in ({'unknown': 1}, {'waveform': -1}, {'waveform': float('nan')}):
            with self.assertRaises(ContractError): ObjectivePlan(weights=bad)
        with self.assertRaises(ContractError): ObjectivePlan(weights={k: 0 for k in AXES})
        with self.assertRaises(ContractError): ObjectivePlan(scales={'level': 0})
        d = ObjectivePlan().to_dict(); d['level_policy'] = 'normalised'
        with self.assertRaises(ContractError): ObjectivePlan.from_dict(d)
        with self.assertRaises(ContractError): GatePolicy(silence_ratio=-1)
        d = GatePolicy().to_dict(); d['output_clipping'] = 'silently-clip'
        with self.assertRaises(ContractError): GatePolicy.from_dict(d)
        self.assertEqual(GatePolicy.from_dict(GatePolicy().to_dict()), GatePolicy())


if __name__ == '__main__': unittest.main()
