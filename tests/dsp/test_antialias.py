from __future__ import annotations
import unittest
import numpy as np
from zaaggenz_contracts.legacy import envelope
from zaaggenz_contracts.registry import node_definition
from zaaggenz_dsp import execute_graph,filter_metadata,reference_error
from zaaggenz_dsp.graph import GraphError

SR=48000

def node(id,type_id,params):
    d=node_definition(type_id);base={k:v['default'] for k,v in d['parameters'].items()};base.update(params)
    return envelope('DSPNodeSpec',id=id,type_id=type_id,inputs=['source'],channels=1,params=base,
                    state_policy=d['state'],phase_policy='source-derived',latency_samples=d['latency'],
                    lookahead_samples=d['lookahead'],bypass=d['bypass'],automation=[])

class AntialiasNodeTests(unittest.TestCase):
    def setUp(self):
        t=np.arange(SR,dtype=np.float64)/SR;self.x=(.6*np.sin(2*np.pi*9000*t)).astype(np.float32)

    def test_registry_accepts_only_1_2_4(self):
        for factor in (1,2,4):
            y=execute_graph(self.x,SR,[node('aa','core.tanh_aa.v1',{'drive_db':18.,'mix':1.,'oversample':factor})],'aa').output
            self.assertEqual(y.shape,self.x.shape);self.assertTrue(np.isfinite(y).all())
        bad=node('aa','core.tanh_aa.v1',{'drive_db':18.,'mix':1.,'oversample':2});bad['params']['oversample']=3
        with self.assertRaises(GraphError):execute_graph(self.x,SR,[bad],'aa')

    def test_mix_zero_is_exact_identity_at_every_factor(self):
        for factor in (1,2,4):
            y=execute_graph(self.x,SR,[node('aa','core.tanh_aa.v1',{'drive_db':24.,'mix':0.,'oversample':factor})],'aa').output
            np.testing.assert_array_equal(y,self.x)

    def test_legacy_tanh_math_is_unchanged(self):
        y=execute_graph(self.x,SR,[node('legacy','core.tanh.v1',{'drive_db':18.,'mix':1.})],'legacy').output
        expected=np.tanh(self.x.astype(np.float64)*10**(18/20))
        np.testing.assert_array_equal(y,expected)

    def test_four_x_converges_toward_eight_x_reference(self):
        errors=reference_error(self.x,kind='tanh',drive_db=18.,mix=1.)
        self.assertLess(errors[4]['rms_error'],errors[2]['rms_error'])
        self.assertLess(errors[2]['rms_error'],errors[1]['rms_error'])
        self.assertLess(errors[4]['relative_rms_error'],.01)

    def test_filter_metadata_discloses_zero_phase_offline_alignment(self):
        meta=filter_metadata(4)
        self.assertEqual(meta['factor'],4);self.assertEqual(meta['declared_latency_samples'],0)
        self.assertEqual(meta['fir_taps'],129);self.assertIn('zero-phase',meta['alignment'])

if __name__=='__main__':unittest.main(verbosity=2)
