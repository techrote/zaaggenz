"""Actual recovered engine equality, including complete synthline/bass/stem paths."""
from dataclasses import asdict, replace
import hashlib
import unittest
import numpy as np
from zaaggenz_contracts import Contract, ContractError
from zaaggenz_contracts.legacy import adapt_parameters, freeze_legacy, thaw_legacy, legacy_object
from zaaggenz_contracts.registry import legacy_catalogue
from uptempo_harmony.synth import PRESETS, KickParams, synthesize_one, synthesize_loop
from uptempo_harmony.reversebass import REVERSEBASS_PRESETS, ReverseBassParams, synthesize_reversebass_arrangement
from uptempo_harmony.multiband import SCULPT_PRESETS, SpectralSculptParams, process_spectral_sculpt
from uptempo_harmony.arrangement import ArrangementSpec, make_arrangement_template, synthesize_arrangement
from webapp import apply_master_gain


class LegacyTests(unittest.TestCase):
    def test_frozen_defaults_match_source(self):
        for family,cls in [('synth',KickParams),('reversebass',ReverseBassParams),('sculpt',SpectralSculptParams),('arrangement',ArrangementSpec)]:
            self.assertEqual(legacy_catalogue()[family]['defaults'],asdict(cls()))
    def test_all_synth_presets_actual_audio(self):
        for name,p in PRESETS.items():
            with self.subTest(preset=name):
                q=legacy_object('synth',p.to_dict());self.assertEqual(q,p)
                a,_=synthesize_one(p);b,_=synthesize_one(q)
                np.testing.assert_array_equal(a,b)
    def test_all_reversebass_presets_values(self):
        for name,p in REVERSEBASS_PRESETS.items():
            with self.subTest(preset=name):self.assertEqual(p,legacy_object('reversebass',p.to_dict()))
    def test_all_sculpt_presets_actual_audio(self):
        x=np.random.default_rng(24).normal(0,.1,12000).astype(np.float32)
        for name,p in SCULPT_PRESETS.items():
            with self.subTest(preset=name):
                q=legacy_object('sculpt',p.to_dict());self.assertEqual(p,q)
                a=process_spectral_sculpt(x,12000,p);b=process_spectral_sculpt(x,12000,q)
                np.testing.assert_array_equal(a,b)
    def test_full_render_paths(self):
        for sr in (12000,48000):
            base=replace(PRESETS['locked_bloom'],sr=sr,beats=1)
            rb=REVERSEBASS_PRESETS['layered_reverse']
            spec=make_arrangement_template('escalate',bpm=200,bars=2,seed=1337)
            for mode in ('synth','arrange','arrange_bass','bass'):
                with self.subTest(sr=sr,mode=mode):
                    recipe=freeze_legacy(base.to_dict(),mode=mode,arrangement=spec.to_dict() if mode!='synth' else None,
                        reversebass=rb.to_dict() if mode in ('arrange_bass','bass') else None,
                        sculpt=SCULPT_PRESETS['transparent'].to_dict(),master_gain_db=-6)
                    p=thaw_legacy(recipe)
                    if mode=='synth': a=synthesize_loop(base);b=synthesize_loop(p['synth'])
                    elif mode=='arrange':
                        a,_,_=synthesize_arrangement(base,spec);b,_,_=synthesize_arrangement(p['synth'],p['arrangement'])
                    else:
                        a,_,sa=synthesize_reversebass_arrangement(base,spec,rb)
                        b,_,sb=synthesize_reversebass_arrangement(p['synth'],p['arrangement'],p['reversebass'])
                        for stem in ('synthline','body','aux','sub','kick','bass','mix'):
                            np.testing.assert_array_equal(sa[stem],sb[stem])
                        self.assertGreater(float(np.std(sb['synthline'])),0)
                    np.testing.assert_array_equal(a,b)
                    shaped=process_spectral_sculpt(b,sr,p['sculpt'])
                    np.testing.assert_array_equal(shaped,b)
                    before,_=apply_master_gain(a,{'master_gain_db':-6})
                    after,_=apply_master_gain(shaped,{'master_gain_db':p['master_gain_db']})
                    np.testing.assert_array_equal(before,after)
    def test_unknown_parameter_not_ignored(self):
        with self.assertRaises(ContractError):adapt_parameters('synth',{'typo_drive_db':20})
    def test_out_of_bounds_not_clamped(self):
        with self.assertRaises(ContractError):adapt_parameters('synth',{'bpm':0})
    def test_bad_section_type(self):
        with self.assertRaises(ContractError):adapt_parameters('arrangement',{'sections':None})
    def test_derived_fields_verified(self):
        d=make_arrangement_template('escalate',bars=2).to_dict();d['duration_s']+=1
        with self.assertRaises(ContractError):adapt_parameters('arrangement',d)
    def test_partial_presets_defaults_are_explicit(self):
        p=adapt_parameters('synth',{'f0_hz':50})
        self.assertEqual(p,replace(KickParams(),f0_hz=50).to_dict())
    def test_unused_new_intent_is_not_dropped(self):
        d=freeze_legacy(PRESETS['locked_bloom'].to_dict()).to_dict();d['tuning']['reference_hz']=49
        with self.assertRaises(ContractError):thaw_legacy(Contract(d))
    def test_tempo_change_requires_new_consumer(self):
        d=freeze_legacy({}).to_dict();d['time_map']['tempo_segments'].append(dict(beat='8/1',bpm='210/1'))
        with self.assertRaises(ContractError):thaw_legacy(Contract(d))
    def test_source_is_not_mutated(self):
        before=PRESETS['locked_bloom'].to_dict();p=thaw_legacy(freeze_legacy(before));p['synth'].drive_db=32
        self.assertEqual(before,PRESETS['locked_bloom'].to_dict())
    def test_scalar_boolean_misuse(self):
        with self.assertRaises(ContractError):adapt_parameters('synth',{'drive_db':True})
    def test_integer_spelling(self):
        self.assertIs(type(legacy_object('synth',{'harmonic_count':49.0}).harmonic_count),int)

if __name__=='__main__':unittest.main(verbosity=2)
