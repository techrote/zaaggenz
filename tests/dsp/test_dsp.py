from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys,unittest
import numpy as np
from scipy import signal

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_contracts.legacy import envelope,freeze_legacy
from zaaggenz_dsp import *
from zaaggenz_dsp.graph import GraphError
from zaaggenz_dsp.multiband import BandError
from uptempo_harmony.synth import PRESETS,synthesize_one,synthesize_loop
from uptempo_harmony.arrangement import make_arrangement_template,synthesize_arrangement
from uptempo_harmony.reversebass import REVERSEBASS_PRESETS,synthesize_reversebass_arrangement
from uptempo_harmony.multiband import SCULPT_PRESETS,process_spectral_sculpt
from webapp import apply_master_gain


def node(id,type_id,input='source',params=None,automation=None):
    from zaaggenz_contracts.registry import node_definition
    d=node_definition(type_id);p={k:v['default'] for k,v in d['parameters'].items()};p.update(params or {})
    return envelope('DSPNodeSpec',id=id,type_id=type_id,inputs=[input],channels=1,params=p,state_policy=d['state'],phase_policy='source-derived',latency_samples=d['latency'],lookahead_samples=d['lookahead'],bypass=d['bypass'],automation=automation or [])

class GraphTests(unittest.TestCase):
    def setUp(self):
        t=np.arange(12000)/12000;self.x=(.4*np.sin(2*np.pi*97*t)+.15*np.sin(2*np.pi*1100*t)).astype(np.float32)
    def test_empty_graph_identity(self):np.testing.assert_array_equal(execute_graph(self.x,12000,[],'source').output,self.x)
    def test_zero_gain_identity(self):np.testing.assert_array_equal(execute_graph(self.x,12000,[node('g','core.gain.v1')],'g').output,self.x)
    def test_node_order_is_audible_math_not_commutative(self):
        a=[node('clip','core.hard_clip.v1',params={'threshold':.2,'mix':1}),node('gain','core.gain.v1','clip',{'gain_db':12})]
        b=[node('gain','core.gain.v1',params={'gain_db':12}),node('clip','core.hard_clip.v1','gain',{'threshold':.2,'mix':1})]
        ya=execute_graph(self.x,12000,a,'gain').output;yb=execute_graph(self.x,12000,b,'clip').output;self.assertGreater(np.max(np.abs(ya-yb)),.1)
    def test_linear_automation_deterministic(self):
        lane=[{'parameter':'gain_db','unit':'dB','interpolation':'linear','points':[{'sample':0,'value':-12.},{'sample':11999,'value':0.}]}]
        n=node('g','core.gain.v1',params={'gain_db':-12},automation=lane);a=execute_graph(self.x,12000,[n],'g').output;b=execute_graph(self.x,12000,[n],'g').output;np.testing.assert_array_equal(a,b);self.assertLess(abs(a[0]),abs(a[-2])+1)
    def test_nonautomatable_rejected_before_processing(self):
        n=node('m','core.multiband_gain.v1');n['automation']=[{'parameter':'sub_gain_db','unit':'dB','interpolation':'linear','points':[{'sample':0,'value':0.},{'sample':2,'value':1.}]}]
        with self.assertRaises(GraphError):execute_graph(self.x,12000,[n],'m')
    def test_channel_mismatch(self):
        n=node('g','core.gain.v1');n['channels']=2
        with self.assertRaises(GraphError):execute_graph(self.x,12000,[n],'g')
    def test_cycle_rejected(self):
        a=node('a','core.gain.v1','b');b=node('b','core.gain.v1','a')
        with self.assertRaises(GraphError):execute_graph(self.x,12000,[a,b],'a')
    def test_output_error_policy(self):
        with self.assertRaises(GraphError):apply_output_policy(self.x*5,{'master_gain_db':0,'clipping':'error'})
    def test_unbounded_float_preserves_finite_over_full_scale(self):
        x=np.asarray([1.25,-3.5,0.0],dtype=np.float64);out,diag=apply_output_policy(x,{'master_gain_db':0,'clipping':'unbounded_float'})
        np.testing.assert_array_equal(out,x.astype(np.float32));self.assertEqual(out.dtype,np.float32);self.assertEqual(diag['output_peak'],3.5)
    def test_unbounded_float_exact_float32_range_boundary(self):
        m=np.float64(np.finfo(np.float32).max);out,_=apply_output_policy(np.asarray([m,-m]),{'master_gain_db':0,'clipping':'unbounded_float'})
        self.assertTrue(np.isfinite(out).all());self.assertEqual(float(out[0]),float(np.finfo(np.float32).max))
        with self.assertRaisesRegex(GraphError,'finite float32 range'):
            apply_output_policy(np.asarray([m*1.0000001]),{'master_gain_db':0,'clipping':'unbounded_float'})
    def test_contract_valid_gain_chain_cannot_publish_float32_inf(self):
        nodes=[];previous='source'
        for i in range(40):
            key=f'g{i}';nodes.append(node(key,'core.gain.v1',previous,{'gain_db':24}));previous=key
        y=execute_graph(np.asarray([1.0],dtype=np.float64),48000,nodes,previous,capture_taps=False).output
        self.assertTrue(np.isfinite(y).all());self.assertGreater(float(abs(y[0])),float(np.finfo(np.float32).max))
        with self.assertRaisesRegex(GraphError,'finite float32 range'):
            apply_output_policy(y,{'master_gain_db':0,'clipping':'unbounded_float'})
    def test_master_overflow_fails_before_clipping_can_hide_it(self):
        x=np.asarray([np.finfo(np.float64).max],dtype=np.float64)
        for policy in ('clip_at_full_scale','error','unbounded_float'):
            with self.subTest(policy=policy),self.assertRaisesRegex(GraphError,'non-finite output'):
                apply_output_policy(x,{'master_gain_db':24,'clipping':policy})
    def test_unbounded_float_stereo_remains_finite_and_unclamped(self):
        x=np.asarray([[2.0,-2.0],[5.25,-7.5]],dtype=np.float64);out,_=apply_output_policy(x,{'master_gain_db':0,'clipping':'unbounded_float'})
        np.testing.assert_array_equal(out,x.astype(np.float32));self.assertTrue(np.isfinite(out).all())

class BandTests(unittest.TestCase):
    def setUp(self):
        self.sr=48000;t=np.arange(self.sr)/self.sr;self.x=sum(.1*np.sin(2*np.pi*f*t+.1) for f in (70,260,900,2600,8000))
        self.cross=(105,520,3600)
    def test_split_reconstructs(self):np.testing.assert_allclose(sum(split_bands(self.x,self.sr,self.cross)),self.x,atol=2e-15,rtol=0)
    def test_zero_effect_does_not_even_filter_dry(self):np.testing.assert_array_equal(route_effect_deltas(self.x,self.sr,self.cross,[None]*4),self.x)
    def test_zero_band_gain_identity(self):np.testing.assert_array_equal(multiband_gain(self.x,self.sr,self.cross,[0,0,0,0]),self.x)
    def test_delta_confinement_reduces_outside_energy(self):
        processor=lambda b:np.tanh(8*b)
        y0=route_effect_deltas(self.x,self.sr,self.cross,[None,None,processor,None],False);y1=route_effect_deltas(self.x,self.sr,self.cross,[None,None,processor,None],True)
        f=np.fft.rfftfreq(len(self.x),1/self.sr);w=signal.windows.hann(len(self.x),sym=False);outside=(f<self.cross[1]/1.5)|(f>self.cross[2]*1.5)
        def frac(y):
            p=np.abs(np.fft.rfft((y-self.x)*w))**2;return p[outside].sum()/max(p.sum(),1e-30)
        self.assertLess(frac(y1),frac(y0)*.05)
    def test_bad_crossover(self):
        with self.assertRaises(BandError):multiband_gain(self.x,self.sr,(1000,500,3000),(1,0,0,0))

class LegacyAdapterTests(unittest.TestCase):
    def expected(self,base,spec,rb,sculpt,master,mode):
        if mode=='synth':raw=synthesize_loop(base) if base.beats>1 else synthesize_one(base)[0];stems={}
        elif mode=='arrange':raw,_,_=synthesize_arrangement(base,spec);stems={}
        else:raw,_,stems=synthesize_reversebass_arrangement(base,spec,rb)
        shaped=process_spectral_sculpt(raw,base.sr,sculpt);final,_=apply_master_gain(shaped,{'master_gain_db':master});return final,stems
    def test_graphify_preserves_legacy_pipeline_and_stems(self):
        for sr in (12000,48000):
            base=replace(PRESETS['locked_bloom'],sr=sr,beats=1);spec=make_arrangement_template('escalate',bpm=200,bars=2,seed=1337);rb=REVERSEBASS_PRESETS['layered_reverse'];sc=SCULPT_PRESETS['gentle_separation']
            modes=('synth','arrange_bass') if sr==48000 else ('synth','arrange','arrange_bass','bass')
            for mode in modes:
                with self.subTest(sr=sr,mode=mode):
                    recipe=freeze_legacy(base.to_dict(),mode=mode,arrangement=spec.to_dict() if mode!='synth' else None,reversebass=rb.to_dict() if mode in ('arrange_bass','bass') else None,sculpt=sc.to_dict(),master_gain_db=-6)
                    graph=graphify_legacy_recipe(recipe);result=render_recipe(graph);expected,stems=self.expected(base,spec,rb,sc,-6,mode);np.testing.assert_array_equal(result.audio,expected)
                    self.assertIn('legacy-source-post-internal-nonlinear',result.taps);self.assertIn('pre-master',result.taps);self.assertIn('post-master',result.taps)
                    if stems:
                        for k in ('synthline','body','aux','sub','kick','bass'):np.testing.assert_array_equal(result.stems[k],stems[k])
                        self.assertGreater(np.std(result.stems['synthline']),0)
    def test_graphified_sculpt_is_explicit_stage(self):
        base=replace(PRESETS['locked_bloom'],sr=12000,beats=1);r=graphify_legacy_recipe(freeze_legacy(base.to_dict(),sculpt=SCULPT_PRESETS['gentle_separation'].to_dict()));d=r.to_dict();self.assertEqual(d['nodes'][0]['type_id'],'legacy.sculpt.v1');self.assertEqual(d['output_node'],'legacy-sculpt');self.assertIsNone(d['sculpt'])
    def test_new_node_can_be_inserted_after_sculpt(self):
        base=replace(PRESETS['locked_bloom'],sr=12000,beats=1);r=graphify_legacy_recipe(freeze_legacy(base.to_dict(),sculpt=SCULPT_PRESETS['transparent'].to_dict())).to_dict();g=node('postgain','core.gain.v1','legacy-sculpt',{'gain_db':-3});r['nodes'].append(g);r['output_node']='postgain';result=render_recipe(r);self.assertEqual(result.graph_order,('legacy-sculpt','postgain'))

if __name__=='__main__':unittest.main(verbosity=2)
