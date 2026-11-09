"""MBR-004 source-critical diagnostic oracles; no product threshold or UI changes."""
from pathlib import Path
import struct
import sys
import unittest

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'app'))
sys.path.insert(0,str(ROOT/'tools'))
from zg242_spectral_portability_trace import (
    capture_document,compare_trace,pcm_identity,delta_metrics,
    _support_extent,TRACE_VERSION,decode_float32_wav,
    _numerical_tensor,_first_tensor_delta,compare_subledger,_tracker_taps)


class PortabilityTraceTests(unittest.TestCase):
    def _document(self):
        from zaaggenz_timeline.model import default_document,TimelineDocument
        from zaaggenz_project.project import Project
        from zaaggenz_contracts.rack import empty_rack,with_rack
        original=default_document(sample_rate=12000).to_dict()
        p=Project.from_document(original['project'])
        data=empty_rack(p.head_recipe).to_dict()
        data['bands'][1]['inserts']=[{
            'id':'insert.lowmid.gain','type_id':'zg.gain',
            'version':'1.0.0','bypass':False,'wet':1.,'automation':[],
            'params':{'gain_db':6.}}]
        p.commit(with_rack(p.head_recipe,data))
        original.update(project=p.to_document(),end_beat='4/1',
            notes=[{'id':'n-1','beat':'0/1','duration_beats':'1/1','degree':0,
                    'detune_cents':0,'gain_db':-18,'muted':False,'roll_density':0}])
        return TimelineDocument(original).to_dict()

    def test_strict_ieee_float_wav_without_extra_dependencies(self):
        values=np.array([0.,-.25,.5],dtype='<f4')
        data=values.tobytes()
        fmt=struct.pack('<HHIIHH',3,1,48000,192000,4,32)
        chunks=b'fmt '+struct.pack('<I',len(fmt))+fmt+b'data'+struct.pack('<I',len(data))+data
        raw=b'RIFF'+struct.pack('<I',len(chunks)+4)+b'WAVE'+chunks
        actual,rate=decode_float32_wav(raw)
        self.assertEqual(rate,48000)
        np.testing.assert_array_equal(actual,values)
        with self.assertRaisesRegex(ValueError,'header'):
            decode_float32_wav(b'NOT'+raw[3:])
        with self.assertRaisesRegex(ValueError,'length'):
            decode_float32_wav(raw[:-1])
        with self.assertRaisesRegex(ValueError,'non-IEEE'):
            decode_float32_wav(raw.replace(b'\x03\x00\x01\x00',b'\x01\x00\x01\x00',1))
        with self.assertRaisesRegex(ValueError,'non-finite'):
            decode_float32_wav(raw.replace(data,np.array([np.nan,-.25,.5],dtype='<f4').tobytes()))

    def test_pcm_digest_and_fail_closed_dimensions(self):
        v=np.array([0.,-.25,.5],dtype='<f4')
        self.assertEqual(pcm_identity(v)['shape'],[3])
        self.assertEqual(delta_metrics(v,v)['nonzero_samples'],0)
        with self.assertRaisesRegex(ValueError,'dimensions'):
            delta_metrics(v,v[:1])
        with self.assertRaisesRegex(ValueError,'non-finite'):
            pcm_identity(np.array([np.nan]))

    def test_unsupported_foreign_recipe_is_not_compared(self):
        t={'document_revision_id':'a','compiled_recipe_sha256':'b','rack_sonic_sha256':'c',
           'sample_rate_hz':48000,'spectral':[],'stages':[],
           'source_pre_rack':{'f32le_sha256':'x'},'rack_output':{'f32le_sha256':'x'},
           'final_pcm':{'f32le_sha256':'x'}}
        self.assertTrue(compare_trace(t,t)['source_pcm_equal'])
        with self.assertRaisesRegex(ValueError,'mismatched'):
            compare_trace(t,{**t,'rack_sonic_sha256':'foreign'})
        self.assertEqual(_support_extent({'decisions':[]}),None)


    def test_binary_subledger_hex_and_source_binding(self):
        a=np.zeros((2,1,3),dtype=np.float64);b=a.copy()
        b[0,0,1]=np.nextafter(0.,1.)
        d=_first_tensor_delta(_numerical_tensor(a),_numerical_tensor(b))
        self.assertEqual(d['frame'],0)
        self.assertEqual(d['index'],[0,1])
        self.assertEqual(d['ubuntu_hex'],'0x0.0p+0')
        self.assertEqual(d['windows_hex'],float(b[0,0,1]).hex())
        self.assertIsNone(_first_tensor_delta(_numerical_tensor(a),_numerical_tensor(a)))
        with self.assertRaisesRegex(ValueError,'non-finite'):
            _numerical_tensor(np.array([[np.nan]]))
        x=np.zeros((1,1,3),dtype=np.complex128)
        y=x.copy();y[0,0,1]=1j*np.nextafter(0.,1.)
        stft={'input':{'shape':[2],'f64le_sha256':'same'},'spec':{},
              'sample_rate_hz':48000,'anchors':[0],'supports':[[-1,1]],
              'valid_fraction':['0x1.0p+0'],'weighted':_numerical_tensor(a[:1,:,:2]),
              'rfft':_numerical_tensor(x)}
        u={'analysis_input':stft['input'],'subledger':{'stft':stft,'candidates':[],'assignments':[]}}
        w={'analysis_input':stft['input'],'subledger':{'stft':{**stft,'rfft':_numerical_tensor(y)},
             'candidates':[],'assignments':[]}}
        result=compare_subledger(u,w)
        self.assertEqual(result['first_boundary'],'stft-native-rfft-output')
        self.assertEqual(result['first_numeric_difference']['index'],[0,1])
        self.assertEqual(result['first_numeric_difference']['component'],'imag')
        self.assertEqual(compare_subledger(u,{**w,'analysis_input':
            {'shape':[2],'f64le_sha256':'foreign'}})['first_boundary'],
            'different-f64-analysis-input')

    def test_live_tracker_taps_restore_native_functions(self):
        from contextlib import ExitStack
        from zaaggenz_components import tracker as tr
        source=np.sin(2*np.pi*440*np.arange(2400)/12000).astype(np.float32)*.05
        uninstrumented=tr.analyse_components(source,12000)
        fft=np.fft.rfft;stft=tr.stft
        active=[{'stft':None,'candidates':[],'assignments':[],'transient':None}]
        with ExitStack() as stack:
            _tracker_taps(stack,active)
            instrumented=tr.analyse_components(source,12000)
        self.assertIs(np.fft.rfft,fft)
        self.assertIs(tr.stft,stft)
        self.assertEqual(uninstrumented.bundle.to_dict(),instrumented.bundle.to_dict())
        self.assertEqual(uninstrumented.diagnostics,instrumented.diagnostics)
        self.assertTrue(active[0]['stft']['rfft']['frame_sha256'])
        self.assertIsNotNone(active[0]['transient'])

    def test_real_saved_rack_is_unchanged_by_read_only_trace(self):
        from zaaggenz_timeline.model import TimelineDocument,compile_recipe
        from zaaggenz_melody.render import render_phrase
        from zaaggenz_spectral import rack_executor as rx
        document=self._document()
        direct=render_phrase(compile_recipe(TimelineDocument(document))).mix
        original=rx.execute_rack
        report=capture_document(document,expected_pcm=direct)
        self.assertIs(rx.execute_rack,original)
        self.assertEqual(report['trace_version'],TRACE_VERSION)
        self.assertEqual(report['original_export_comparison']['nonzero_samples'],0)
        self.assertEqual(report['sample_rate_hz'],12000)
        self.assertEqual(report['projection']['independent_routed_vs_production']['nonzero_samples'],0)
        self.assertEqual(report['stages'][0]['stage'],'gain')
        self.assertEqual(report['bands'][0]['index'],1)
        self.assertGreater(report['stages'][0]['delta']['rms_fs'],0.)
        self.assertEqual(report['spectral'],[])
        self.assertTrue(compare_trace(report,report)['stages'][0]['output_pcm_equal'])


if __name__=='__main__':
    unittest.main()
