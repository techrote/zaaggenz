import hashlib,importlib,json,math,tempfile,unittest
from dataclasses import replace
from unittest import mock
import numpy as np

from zaaggenz_analysis import *
from zaaggenz_analysis.stft import AnalysisError
from zaaggenz_qc import fixture


def asset(data,sr=48000,channels=1):
    raw=np.asarray(data,dtype='<f4').tobytes(order='C')
    return {'kind':'AudioAssetRef','version':'1.0.0','content_sha256':hashlib.sha256(raw).hexdigest(),'identity_domain':'pcm-f32le-interleaved-v1',
      'sample_rate_hz':sr,'channels':channels,'channel_layout':'mono' if channels==1 else 'stereo-lr','frame_count':len(data),'level_domain':'source','sample_policy':'unclamped_float'}

class STFTTests(unittest.TestCase):
    def test_canonical_identity_mono_stereo_and_short(self):
        cases=[fixture('bandlimited_noise',48000,.3,7).data,fixture('stereo_antiphase',48000,.3).data,np.array([.2,-.1,.5])]
        spec=resolution_specs(48000)['medium']
        for x in cases:
            with self.subTest(shape=np.asarray(x).shape):
                r=stft(x,48000,spec);y=istft(r);np.testing.assert_allclose(y,x,rtol=0,atol=3e-14)
    def test_silence_identity(self):
        x=np.zeros(1111);r=stft(x,48000,resolution_specs(48000)['medium']);np.testing.assert_array_equal(istft(r),x)
    def test_empty_is_bounded(self):
        x=np.zeros(0);r=stft(x,48000,resolution_specs(48000)['medium']);self.assertEqual(r.source_frames,0);self.assertEqual(len(istft(r)),0)
    def test_observation_cannot_resynthesize(self):
        r=stft(np.zeros(1000),48000,resolution_specs(48000)['long'])
        with self.assertRaises(AnalysisError):istft(r)
    def test_support_is_explicit_at_edges(self):
        r=stft(np.ones(10),48000,resolution_specs(48000)['short']);self.assertLess(r.supports[0,0],0);self.assertLess(r.valid_fraction[0],1);self.assertEqual(r.anchors[0],0)
    def test_periodic_hann_and_raw_units_are_frozen(self):
        s=resolution_specs(48000)['medium'];self.assertEqual(s.window,'hann-periodic-v1');self.assertEqual(s.scaling,'raw-rfft-v1');self.assertEqual(s.hop_samples,s.window_samples//4)

class ResourceBoundTests(unittest.TestCase):
    def test_supported_default_resolutions_remain_inside_resource_policy(self):
        for sr in (8000,12000,48000,192000):
            with self.subTest(sample_rate_hz=sr):
                specs=resolution_specs(sr);self.assertEqual(set(specs),{'short','medium','long'})
                for spec in specs.values():
                    self.assertLessEqual(spec.window_samples,MAX_STFT_WINDOW_SAMPLES)
                    self.assertLessEqual(spec.fft_samples,MAX_STFT_FFT_SAMPLES)
        self.assertEqual(resolution_specs(192000)['long'].window_samples,MAX_STFT_WINDOW_SAMPLES)

    def test_exact_resource_bound_is_accepted(self):
        spec=STFTSpec(MAX_STFT_WINDOW_SAMPLES,MAX_STFT_WINDOW_SAMPLES//2,MAX_STFT_FFT_SAMPLES)
        self.assertEqual(spec.window_samples,32768);self.assertEqual(spec.fft_samples,32768)

    def test_window_and_fft_limit_plus_one_even_value_are_rejected(self):
        with self.assertRaisesRegex(AnalysisError,'window exceeds'):
            STFTSpec(MAX_STFT_WINDOW_SAMPLES+2,1,MAX_STFT_WINDOW_SAMPLES+2)
        with self.assertRaisesRegex(AnalysisError,'FFT size exceeds'):
            STFTSpec(1024,256,MAX_STFT_FFT_SAMPLES+2)

    def test_pathological_custom_dimensions_fail_during_spec_admission(self):
        with self.assertRaises(AnalysisError):STFTSpec(2**20,1,2**20)
        with self.assertRaises(AnalysisError):STFTSpec(1024,1,2**30)

    def test_rejected_tampered_spec_reaches_no_padding_or_fft_allocation(self):
        module=importlib.import_module('zaaggenz_analysis.stft')
        spec=STFTSpec(256,64,256)
        object.__setattr__(spec,'fft_samples',MAX_STFT_FFT_SAMPLES+2)
        with mock.patch.object(module.np,'pad') as pad,mock.patch.object(module.np.fft,'rfft') as rfft:
            with self.assertRaisesRegex(AnalysisError,'FFT size exceeds'):module.stft(np.zeros(128),48000,spec)
            pad.assert_not_called();rfft.assert_not_called()

    def test_estimator_matches_execution_cardinality_and_channel_cost(self):
        spec=STFTSpec(256,64,512)
        mono=estimate_stft_resources(100,1,spec);stereo=estimate_stft_resources(100,2,spec)
        self.assertEqual(mono.policy,STFT_RESOURCE_POLICY)
        self.assertEqual((mono.frame_count,mono.padded_frames,mono.padding_extra_frames),(3,384,28))
        self.assertEqual(stereo.weighted_bytes,mono.weighted_bytes*2)
        self.assertEqual(stereo.spectra_bytes,mono.spectra_bytes*2)
        self.assertEqual(stereo.fft_point_count,mono.fft_point_count*2)
        result=stft(np.zeros(100),48000,spec);self.assertEqual(len(result.anchors),mono.frame_count)

    def test_estimator_handles_empty_and_short_sources_without_allocation(self):
        spec=STFTSpec(256,64,256)
        empty=estimate_stft_resources(0,1,spec);short=estimate_stft_resources(1,2,spec)
        self.assertEqual((empty.frame_count,empty.padded_frames),(1,256))
        self.assertEqual(short.frame_count,2);self.assertGreater(short.estimated_live_bytes,0)
        with self.assertRaises(AnalysisError):estimate_stft_resources(-1,1,spec)
        with self.assertRaises(AnalysisError):estimate_stft_resources(1,3,spec)

    def test_within_bound_custom_zero_padding_executes_without_mutation(self):
        spec=STFTSpec(256,64,512,role='observation');r=stft(np.arange(100,dtype=np.float64),48000,spec)
        self.assertEqual(r.spec,spec);self.assertEqual(r.spectra.shape[-1],257)

    def test_resource_policy_is_identity_neutral_for_existing_spec_metadata(self):
        spec=resolution_specs(48000)['medium']
        self.assertEqual(spec.metadata(),{'window_samples':2048,'hop_samples':512,'fft_samples':2048,
            'window':'hann-periodic-v1','padding':'half-window-zero-v1','scaling':'raw-rfft-v1','role':'canonical-resynthesis'})
        self.assertNotIn('resource_policy',spec.metadata())

class ResolutionTests(unittest.TestCase):
    def test_two_low_tones_need_long_support(self):
        sr=48000;t=np.arange(sr*2)/sr;x=np.sin(2*np.pi*48*t)+.8*np.sin(2*np.pi*55*t+.3);a=analyse_multiresolution(x,sr)
        def count(tl):
            f=min(tl.frames,key=lambda q:abs(q.anchor_sample-sr));return sum(35<=p<=80 for p in f.peaks_hz)
        self.assertLess(count(a['short']),2);self.assertGreaterEqual(count(a['long']),2)
        self.assertGreater(a['long'].stft_spec.window_samples,a['short'].stft_spec.window_samples*8)
    def test_transient_timing_is_not_claimed_at_long_resolution(self):
        a=analyse_multiresolution(fixture('impulse',48000,.5).data,48000)
        sw=a['short'].frames[len(a['short'].frames)//2].support_end_sample-a['short'].frames[len(a['short'].frames)//2].support_start_sample
        lw=a['long'].frames[len(a['long'].frames)//2].support_end_sample-a['long'].frames[len(a['long'].frames)//2].support_start_sample
        self.assertGreater(lw,sw*8)
    def test_silence_features_invalid_not_zero_frequency(self):
        a=analyse_multiresolution(np.zeros(1000),12000)
        for tl in a.values():
            for f in tl.frames:self.assertFalse(f.valid);self.assertIsNone(f.dominant_hz);self.assertIsNone(f.spectral_centroid_hz)
    def test_stereo_preserved_in_representation(self):
        x=fixture('stereo_antiphase',12000,.2).data;r=stft(x,12000,resolution_specs(12000)['medium']);self.assertEqual(r.channels,2);np.testing.assert_allclose(istft(r),x,atol=3e-14,rtol=0)

class CacheTests(unittest.TestCase):
    def test_key_invalidates_source_window_and_channels(self):
        x=np.arange(20.);a=asset(x);s=resolution_specs(48000)['medium'];k=analysis_key(a,s)
        b=dict(a);b['content_sha256']='1'*64;self.assertNotEqual(k,analysis_key(b,s))
        other=STFTSpec(s.window_samples*2,s.hop_samples*2,s.fft_samples*2,role='canonical-resynthesis');self.assertNotEqual(k,analysis_key(a,other))
        stereo=dict(a);stereo.update(channels=2,channel_layout='stereo-lr');self.assertNotEqual(k,analysis_key(stereo,s))
    def test_lru_bound(self):
        c=AnalysisCache(2);c.put('1'*64,1);c.put('2'*64,2);self.assertEqual(c.get('1'*64),1);c.put('3'*64,3);self.assertIsNone(c.get('2'*64));self.assertEqual(len(c),2)

class TimelineTests(unittest.TestCase):
    def test_interval_overlap_vs_anchor(self):
        tl=analyse_multiresolution(fixture('sine',12000,.2).data,12000)['short'];o=select_interval(tl,100,200,'overlap');a=select_interval(tl,100,200,'anchor');self.assertGreaterEqual(len(o),len(a))
    def test_landmark_resampling(self):
        tl=analyse_multiresolution(fixture('sine',12000,.5).data,12000)['short'];ann={'segments':[{'id':'x','asset_id':'a','start_sample':4800,'end_sample':9600,'label':'turn','section_function':'variation','source':'manual','confidence':.8}]}
        rows=overlay_landmarks(tl,ann,'a',48000);self.assertEqual(rows[0]['start_sample'],1200);self.assertEqual(rows[0]['end_sample'],2400);self.assertTrue(rows[0]['frame_indices'])
    def test_bad_interval(self):
        tl=analyse_multiresolution(np.zeros(1),12000)['short']
        with self.assertRaises(AnalysisError):select_interval(tl,5,5)

if __name__=='__main__':unittest.main(verbosity=2)
