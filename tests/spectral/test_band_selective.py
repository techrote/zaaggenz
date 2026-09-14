from __future__ import annotations
import unittest
import numpy as np
from zaaggenz_dsp import BitcrushSpec,CompressionSpec,split_bands
from zaaggenz_spectral import (BandSelectiveRequest,BandSlotSpec,ChordnessRequest,CombTemplate,LatticeVoice,
                               SpectralRetuneRequest,process_band_selective)
from zaaggenz_tuning import fixture_pack,tuning_to_spec

SR=12000
CROSS=(105.,520.,3600.)

def tone(f,duration=.8,amp=.4,phase=.13):
    t=np.arange(round(SR*duration),dtype=np.float64)/SR
    return (amp*np.cos(2*np.pi*f*t+phase)).astype(np.float32)

def rms(x):
    a=np.asarray(x,dtype=np.float64);return float(np.sqrt(np.mean(a*a)))

def retune880():
    return SpectralRetuneRequest(tuning_spec=tuning_to_spec(fixture_pack()['12tet-a440']),voices=(LatticeVoice(12,(1.,),'880'),),
        min_confidence=.35,min_hz=600.,max_hz=1600.,max_displacement_cents=120.,max_correction_slew_cents_per_second=3000.)

class BandSelectiveTests(unittest.TestCase):
    def test_identity_slot_controls_are_exact(self):
        x=tone(60.,amp=.45)+tone(1000.,amp=.2)
        slot=BandSlotSpec(gain_db=0.,compression=CompressionSpec(threshold_db=-40.,ratio=1.,makeup_db=0.,wet=1.),bitcrush=BitcrushSpec(bit_depth=4,hold_samples=8,wet=0.))
        result=process_band_selective(x,SR,BandSelectiveRequest(CROSS,(None,None,slot,None)))
        np.testing.assert_array_equal(result.audio,x);self.assertTrue(result.diagnostics['identity_path'])

    def test_confined_highmid_bitcrush_preserves_sub_pocket_relative_to_selected_band(self):
        x=tone(60.,amp=.5)+tone(1000.,amp=.22)+tone(5000.,amp=.12)
        slot=BandSlotSpec(bitcrush=BitcrushSpec(bit_depth=4,hold_samples=5,wet=1.))
        result=process_band_selective(x,SR,BandSelectiveRequest(CROSS,(None,None,slot,None),(True,True,True,True)))
        delta=np.asarray(result.audio)-x;bands=split_bands(delta,SR,CROSS);sub=rms(bands[0]);highmid=rms(bands[2])
        self.assertGreater(highmid,1e-4);self.assertLess(sub,highmid*.15)
        report=result.band_reports[2];self.assertTrue(report.selected);self.assertTrue(report.confine_delta)
        self.assertLess(report.leakage_rms_by_band[0],report.leakage_rms_by_band[2]*.15)

    def test_spectral_retune_runs_inside_selected_highmid_band(self):
        x=tone(60.,amp=.45)+tone(890.,amp=.28)
        slot=BandSlotSpec(spectral=retune880(),stage_order=('gain','spectral','compression','bitcrush'))
        result=process_band_selective(x,SR,BandSelectiveRequest(CROSS,(None,None,slot,None)))
        spectral=[row for row in result.slot_reports[2]['stages'] if row['stage']=='spectral'][0]
        self.assertGreater(spectral['diagnostics']['changed_frames'],0)
        delta=np.asarray(result.audio)-x;bands=split_bands(delta,SR,CROSS)
        self.assertGreater(rms(bands[2]),rms(bands[0])*5.)
        self.assertEqual(result.inspection['request']['slots'][2]['stage_order'],['gain','spectral','compression','bitcrush'])

    def test_chordness_reweight_is_available_as_band_spectral_slot(self):
        x=tone(1000.,amp=.28)
        comb=CombTemplate('target',(1000.,))
        request=ChordnessRequest((comb,),mode='reweight',selected_template_ids=('target',),max_selected_templates=1,min_confidence=.35,max_gain_db=4.,max_gain_slew_db_per_second=80.)
        slot=BandSlotSpec(spectral=request)
        result=process_band_selective(x,SR,BandSelectiveRequest(CROSS,(None,None,slot,None)))
        spectral=[row for row in result.slot_reports[2]['stages'] if row['stage']=='spectral'][0]
        self.assertEqual(spectral['diagnostics']['retuned_frames'],0);self.assertGreater(spectral['diagnostics']['reweighted_frames'],0)

    def test_recipe_persists_filter_order_latency_alias_and_spill_policy(self):
        slot=BandSlotSpec(gain_db=-2.,compression=CompressionSpec(threshold_db=-15.,ratio=3.,attack_ms=4.,release_ms=70.),
                          bitcrush=BitcrushSpec(bit_depth=6,hold_samples=3,wet=.5),spectral=retune880(),
                          stage_order=('compression','spectral','bitcrush','gain'))
        request=BandSelectiveRequest(CROSS,(None,None,slot,None),(True,True,False,True));recipe=request.to_dict(SR)
        self.assertEqual(recipe['slots'][2]['stage_order'],['compression','spectral','bitcrush','gain'])
        self.assertEqual(recipe['filter']['id'],'zg.butter4_sosfiltfilt_effect_delta.v1');self.assertEqual(recipe['filter']['declared_latency_samples'],0)
        self.assertIn('intentional unfiltered',recipe['slots'][2]['bitcrush']['alias_policy']);self.assertFalse(recipe['confine_delta'][2])
        self.assertEqual(recipe['output_policy']['normalization'],'none');self.assertEqual(recipe['output_policy']['master_gain_db'],0.)

if __name__=='__main__':unittest.main(verbosity=2)
