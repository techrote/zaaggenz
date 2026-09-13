from __future__ import annotations
import hashlib,math,unittest
import numpy as np
from scipy import signal
from zaaggenz_contracts import validate
from zaaggenz_components import *

SR=12000

def tone(f,duration=1.0,amp=.6,phase=.3):
    t=np.arange(round(SR*duration))/SR;return (amp*np.cos(2*np.pi*f*t+phase)).astype(np.float32)
def longest(result):
    tracks=result.bundle.to_dict()['tracks'];return max(tracks,key=lambda x:len(x['frames'])) if tracks else None

def circular_pi_distance(a,b):
    d=abs(((a-b+math.pi)%(2*math.pi))-math.pi);return abs(d-math.pi)

class ComponentTests(unittest.TestCase):
    def test_clean_tone_frequency_amplitude_and_contract(self):
        r=analyse_components(tone(440),SR);validate(r.bundle.to_dict(),'PartialTrackBundle');tr=longest(r);self.assertIsNotNone(tr)
        rows=tr['frames'];self.assertLess(np.median([abs(x['frequency_hz']-440) for x in rows]),1.5)
        self.assertTrue(.45<np.median([x['amplitudes'][0] for x in rows])<.75)
        self.assertGreater(r.diagnostics['transform_frames'],0)
        self.assertLessEqual(r.diagnostics['tracks'],2,'a stationary clean tone must not produce a forest of sidelobe trajectories')
    def test_linear_chirp_measured_error(self):
        n=round(SR*1.5);t=np.arange(n)/SR;x=signal.chirp(t,300,t[-1],600,method='linear').astype(np.float32)
        r=analyse_components(x,SR);tr=longest(r);self.assertIsNotNone(tr)
        errors=[]
        for row in tr['frames']:
            truth=300+(600-300)*(row['support']['anchor_sample']/SR)/t[-1];errors.append(abs(row['frequency_hz']-truth))
        self.assertLess(np.median(errors),6.)
        # A rapidly moving ridge may be conservatively marked unknown when local
        # time-frequency support cannot distinguish motion from a close doublet.
        # ZG-013 must measure the trajectory accurately; it must not overrule
        # uncertainty merely to make the component transform-eligible.
        self.assertGreater(len(tr['frames']),20)
    def test_amplitude_modulation_is_observed(self):
        n=SR;t=np.arange(n)/SR;truth=.5*(1+.45*np.sin(2*np.pi*3*t));x=(truth*np.cos(2*np.pi*440*t+.2)).astype(np.float32)
        r=analyse_components(x,SR);tr=longest(r);rows=tr['frames'];anchors=np.array([q['support']['anchor_sample'] for q in rows]);amps=np.array([q['amplitudes'][0] for q in rows])
        target=truth[anchors];self.assertGreater(np.corrcoef(amps,target)[0,1],.85)
    def test_crossing_marks_transform_uncertainty(self):
        n=round(SR*1.4);t=np.arange(n)/SR
        a=signal.chirp(t,280,t[-1],620);b=signal.chirp(t,620,t[-1],280,phi=80);x=(.35*a+.35*b).astype(np.float32)
        r=analyse_components(x,SR);bundle=r.bundle.to_dict();self.assertGreaterEqual(len(bundle['tracks']),2)
        preserves=sum(f['action']=='preserve' for tr in bundle['tracks'] for f in tr['frames'])
        self.assertGreater(preserves,0);self.assertGreaterEqual(r.diagnostics['ambiguous_tracks'],1)
    def test_noise_can_abstain(self):
        x=np.random.default_rng(4).normal(0,.2,SR).astype(np.float32);r=analyse_components(x,SR)
        self.assertEqual(r.diagnostics['transform_frames'],0);self.assertGreater(r.diagnostics['abstained_frames'],0)
    def test_transient_is_owned_and_reconstruction_is_separate_from_bypass(self):
        x=tone(330);mid=len(x)//2;x[mid]+=1.0;r=analyse_components(x,SR)
        self.assertEqual(r.transient_mask[mid],1);self.assertGreater(abs(float(r.transient[mid])),.5)
        self.assertLess(r.diagnostics['reconstruction_rms_error'],1e-6)
        bypass=exact_bypass(x);self.assertTrue(np.array_equal(bypass,x.astype(np.float32)))
        self.assertFalse(np.array_equal(r.reconstruction.astype(np.float32),bypass),'analysis reconstruction is evaluated separately from exact bypass')
    def test_stereo_antiphase_keeps_independent_channel_phase(self):
        x=tone(440,phase=.1);st=np.column_stack((x,-x));r=analyse_components(st,SR);tr=longest(r);self.assertIsNotNone(tr)
        rows=tr['frames'];diff=[]
        for q in rows:diff.append(circular_pi_distance(q['phases_radians'][0],q['phases_radians'][1]))
        self.assertLess(np.median(diff),.15);self.assertEqual(r.bundle.to_dict()['channel_policy'],'shared-frequency-independent-channel-coefficients')
    def test_remainder_assets_match_actual_arrays(self):
        r=analyse_components(tone(220),SR);d=r.bundle.to_dict()
        for key,array in [('residual_asset',r.residual),('transient_asset',r.transient)]:
            payload=np.asarray(array,dtype='<f4').tobytes();self.assertEqual(d[key]['content_sha256'],hashlib.sha256(payload).hexdigest())
    def test_short_signal_abstains_without_fake_zero_hz(self):
        r=analyse_components(np.zeros(100,dtype=np.float32),SR);d=r.bundle.to_dict();self.assertEqual(d['tracks'],[]);validate(d,'PartialTrackBundle')
    def test_empty_signal_contract(self):
        r=analyse_components(np.zeros(0,dtype=np.float32),SR);self.assertEqual(r.bundle.to_dict()['tracks'],[]);self.assertEqual(len(r.source),0)
    def test_nonfinite_rejected(self):
        x=tone(440);x[3]=np.nan
        with self.assertRaises(ComponentError):analyse_components(x,SR)
    def test_invalid_spec_rejected(self):
        with self.assertRaises(ComponentError):ComponentTrackerSpec(max_flatness=2)

if __name__=='__main__':unittest.main(verbosity=2)
