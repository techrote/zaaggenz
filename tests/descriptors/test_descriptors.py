from __future__ import annotations
from copy import deepcopy
import math,unittest
import numpy as np

from zaaggenz_contracts import Contract,validate
from zaaggenz_descriptors import *

SR=12000

def support(n=4096):return dict(start_sample=0,end_sample=n,anchor_sample=n//2,padding='none')

def partials(freqs,amps=None,conf=None,*,frames=4096,sr=SR,channels=1):
    freqs=list(freqs);amps=[1.]*len(freqs) if amps is None else list(amps);conf=[1.]*len(freqs) if conf is None else list(conf)
    x=np.zeros((frames,channels),dtype=np.float32) if channels>1 else np.zeros(frames,dtype=np.float32);asset=pcm_asset(x,sr);tracks=[]
    s=dict(start_sample=max(0,frames//2-512),end_sample=min(frames,frames//2+512),anchor_sample=frames//2,padding='none')
    for i,(f,a,c) in enumerate(zip(freqs,amps,conf)):
        tracks.append(dict(id=f'p{i}',segment_id=f's{i}',continuity='continuous',frames=[dict(support=deepcopy(s),frequency_hz=float(f),
            amplitudes=[float(a)]*channels,phases_radians=[0.]*channels,confidence=float(c),action='transform')]))
    d=dict(kind='PartialTrackBundle',version='1.0.0',asset=asset,method=dict(id='test.source-known',version='1',configuration={}),
           phase_convention='cosine-at-anchor-radians-v1',channel_policy='shared-frequency-independent-channel-coefficients',data_origin='source_known',
           tracks=tracks,residual_asset=None,transient_asset=None,remainder_policy='additive-owned-remainders-v1')
    return Contract(d)

def val(obs):return obs.value

class ModelTests(unittest.TestCase):
    def test_registry_is_evidence_labelled_not_hedonic(self):
        text=' '.join(str(x).lower() for row in descriptor_catalogue().values() for x in row.values())
        for forbidden in ('pleasure','dopamine','reward score','happiness','bliss'):
            self.assertNotIn(forbidden,text)
    def test_invalid_metric_and_metadata_fail(self):
        s=support()
        with self.assertRaises(DescriptorError):observation('not-a-metric',1,s)
        with self.assertRaises(DescriptorError):DescriptorObservation('rms','zg.rms.v1','1.0.0','Hz',1,'measurement','valid',None,s,{})
        with self.assertRaises(DescriptorError):DescriptorObservation('roughness_pairwise','zg.components.roughness.v1','1.0.0','ratio',2,'estimate','valid',1,s,{})
    def test_bundle_identity_is_deterministic_and_defensive(self):
        x=np.zeros(4096,dtype=np.float32);asset=pcm_asset(x,SR);o=rms_observation(x);b=DescriptorBundle(asset,(o,),configuration={'b':2,'a':1});h=b.sha256
        asset['frame_count']=1;self.assertEqual(h,b.sha256);self.assertEqual(h,DescriptorBundle(pcm_asset(x,SR),(o,),configuration={'a':1,'b':2}).sha256)
    def test_feature_projection_preserves_frozen_v1(self):
        x=np.sin(2*np.pi*220*np.arange(SR)/SR).astype(np.float32);r=analyse_descriptors(x,SR,target_hz=[220.,440.,660.])
        validate(r.feature_bundle,'FeatureBundle');names={o['feature'] for o in r.feature_bundle['observations']}
        self.assertTrue(names<={'rms','f0','roughness_score','chord_fit_score'});self.assertNotIn('periodicity_peak',names)
    def test_unknown_projection_uses_frozen_null_semantics(self):
        r=analyse_descriptors(np.zeros(SR,dtype=np.float32),SR)
        validate(r.feature_bundle,'FeatureBundle');f0=next(o for o in r.feature_bundle['observations'] if o['feature']=='f0')
        self.assertIsNone(f0['value']);self.assertIsNone(f0['confidence'])

class AudioTests(unittest.TestCase):
    def test_sine_periodicity_and_f0(self):
        t=np.arange(2*SR)/SR;x=np.sin(2*np.pi*220*t).astype(np.float32);rows=periodicity_observations(x,SR);d={o.metric:o for o in rows}
        self.assertEqual(d['f0_candidate_hz'].validity,'valid');self.assertLess(abs(d['f0_candidate_hz'].value-220),2.);self.assertGreater(d['periodicity_peak'].value,.8)
    def test_stereo_antiphase_does_not_cancel_analysis(self):
        t=np.arange(SR)/SR;x=np.sin(2*np.pi*330*t).astype(np.float32);st=np.column_stack((x,-x));d={o.metric:o for o in periodicity_observations(st,SR)}
        self.assertLess(abs(d['f0_candidate_hz'].value-330),3.);self.assertIn(d['f0_candidate_hz'].details['analysis_channel'],(0,1))
    def test_silence_and_constant_do_not_fabricate_pitch(self):
        for x in (np.zeros(SR),np.ones(SR)*.25):
            with self.subTest(kind=float(x[0])):
                d={o.metric:o for o in periodicity_observations(x,SR)};self.assertNotEqual(d['f0_candidate_hz'].validity,'valid');self.assertIsNone(d['f0_candidate_hz'].value)
    def test_am_envelope_frequency(self):
        t=np.arange(3*SR)/SR;env=1+.45*np.sin(2*np.pi*4*t);x=(env*np.sin(2*np.pi*440*t)).astype(np.float32);d={o.metric:o for o in envelope_observations(x,SR)}
        self.assertGreater(d['envelope_modulation_depth'].value,.15);self.assertLess(abs(d['envelope_modulation_hz'].value-4),.8)
    def test_spectral_occupancy_separates_tone_and_noise(self):
        t=np.arange(2*SR)/SR;tone=np.sin(2*np.pi*440*t);noise=np.random.default_rng(7).normal(size=len(t));a=occupancy_observation(tone,SR);b=occupancy_observation(noise,SR)
        self.assertLess(a.value,b.value);self.assertLess(a.value,.1);self.assertGreater(b.value,.4)
    def test_level_invariance_of_normalised_audio_descriptors(self):
        t=np.arange(2*SR)/SR;x=np.sin(2*np.pi*220*t)+.2*np.sin(2*np.pi*440*t)
        for fn in (lambda q:periodicity_observations(q,SR)[0],lambda q:occupancy_observation(q,SR)):
            self.assertAlmostEqual(fn(x).value,fn(x*.03).value,8)

class ComponentTests(unittest.TestCase):
    def test_harmonicity_and_roughness_can_move_independently(self):
        clean=partials([200,400,600,800]);clustered=partials([200,220,400,420,600,620,800,820]);inharm=partials([205,389,743,1301])
        h_clean=val(harmonicity_observation(clean,200));h_cluster=val(harmonicity_observation(clustered,20));h_inharm=val(harmonicity_observation(inharm,200))
        r_clean=val(roughness_observation(clean));r_cluster=val(roughness_observation(clustered));r_inharm=val(roughness_observation(inharm))
        self.assertGreater(h_clean,.95);self.assertGreater(h_cluster,.95);self.assertLess(h_inharm,.55)
        self.assertGreater(r_cluster,r_clean+.08);self.assertLess(r_inharm,r_cluster)
    def test_roughness_is_global_gain_invariant_but_confidence_weighted(self):
        a=roughness_observation(partials([400,420,800],[1,1,1],[1,1,1])).value;b=roughness_observation(partials([400,420,800],[.01,.01,.01],[1,1,1])).value
        self.assertAlmostEqual(a,b,12)
        low=harmonicity_observation(partials([200,400,607],[1,1,1],[1,1,.02]),200).value;high=harmonicity_observation(partials([200,400,607],[1,1,1],[1,1,1]),200).value
        self.assertGreater(low,high)
    def test_target_comb_density_bias_is_visible_not_hidden(self):
        p=partials([130]);sparse={o.metric:o for o in target_comb_observations(p,[100,200])};dense={o.metric:o for o in target_comb_observations(p,[100,125,150,175,200])}
        self.assertGreater(dense['target_comb_coverage'].value,sparse['target_comb_coverage'].value)
        self.assertLess(dense['target_comb_mismatch_cents'].value,sparse['target_comb_mismatch_cents'].value)
        self.assertEqual(dense['target_comb_density'].value,5);self.assertIn('density_bias',dense['target_comb_coverage'].details)
    def test_component_cap_and_bad_comb(self):
        p=partials(np.linspace(100,2000,80));o=roughness_observation(p,component_cap=16);self.assertEqual(o.details['components_used'],16);self.assertEqual(o.details['components_available'],80)
        with self.assertRaises(DescriptorError):target_comb_observations(p,[200,100])

class IntegrationTests(unittest.TestCase):
    def test_every_stored_metric_has_method_unit_support_and_validity(self):
        t=np.arange(SR)/SR;x=(.6*np.sin(2*np.pi*200*t)+.25*np.sin(2*np.pi*400*t)).astype(np.float32);r=analyse_descriptors(x,SR,target_hz=[200,400,600,800])
        cat=descriptor_catalogue()
        for o in r.descriptors.observations:
            with self.subTest(metric=o.metric):
                self.assertEqual(o.method_id,cat[o.metric]['method']);self.assertEqual(o.method_version,'1.0.0');self.assertEqual(o.unit,cat[o.metric]['unit']);self.assertIn(o.validity,VALIDITY if False else {'valid','unknown','abstained'});self.assertIn('anchor_sample',o.support)
    def test_explicit_f0_override_does_not_mutate_periodicity_measurement(self):
        t=np.arange(SR)/SR;x=np.sin(2*np.pi*220*t).astype(np.float32);r=analyse_descriptors(x,SR,f0_override_hz=110.)
        f0=r.descriptors.get('f0_candidate_hz')[0];h=r.descriptors.get('harmonicity_comb_fit')[0];self.assertLess(abs(f0.value-220),2.);self.assertEqual(r.descriptors.configuration['f0_source'],'explicit-analysis-override');self.assertAlmostEqual(h.details['f0_hz'],110.)
    def test_long_input_requires_explicit_excerpt(self):
        spec=DescriptorAnalysisSpec(max_samples=2048)
        with self.assertRaises(DescriptorError):analyse_descriptors(np.zeros(2049,dtype=np.float32),SR,spec=spec)
    def test_no_target_comb_does_not_invent_chord_fit(self):
        x=np.sin(2*np.pi*220*np.arange(SR)/SR).astype(np.float32);r=analyse_descriptors(x,SR);self.assertEqual(r.descriptors.get('target_comb_fit'),())
        self.assertNotIn('chord_fit_score',{o['feature'] for o in r.feature_bundle['observations']})

if __name__=='__main__':unittest.main(verbosity=2)
