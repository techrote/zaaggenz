from __future__ import annotations
import math,sys,unittest
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'app'))

from zaaggenz_contracts.legacy import adapt_parameters,freeze_legacy
from zaaggenz_harmony import *
from zaaggenz_tuning import fixture_pack,tuning_to_spec,tuning_from_spec


def legacy_tuning(sr=12000,bpm=200.):
    p=adapt_parameters('synth',{'sr':sr,'bpm':float(bpm),'beats':1,'f0_hz':48.});d=freeze_legacy(p).to_dict();return p,d['time_map'],d['tuning']

def triad(root=0,sid='triad',bass=None):
    return SonoritySpec(sid,root,(SonorityTone('root',degree_offset=0),SonorityTone('third',degree_offset=4),SonorityTone('fifth',degree_offset=7)),bass_tone_id=bass)

def three_voices(**kw):
    voices=(VoiceSpec('body','body',36,85,55,max_leap_cents=1800),VoiceSpec('aux','aux',70,145,100,max_leap_cents=1800),VoiceSpec('lead','synthline',105,230,155,max_leap_cents=1800))
    return VoicingConstraints(voices,**kw)

def four_voices(sub_policy='moving'):
    sub=VoiceSpec('sub','sub',22,60,36,max_leap_cents=1600,anchor_policy=sub_policy)
    voices=(sub,VoiceSpec('body','body',36,85,55,max_leap_cents=1800),VoiceSpec('aux','aux',70,145,100,max_leap_cents=1800),VoiceSpec('lead','synthline',105,230,155,max_leap_cents=1800))
    return VoicingConstraints(voices)

class ModelTests(unittest.TestCase):
    def test_tone_requires_exactly_one_coordinate(self):
        with self.assertRaises(HarmonyError):SonorityTone('bad')
        with self.assertRaises(HarmonyError):SonorityTone('bad',degree_offset=0,ratio=1.)
    def test_voice_order_and_explicit_candidate_bound(self):
        with self.assertRaises(HarmonyError):VoicingConstraints((VoiceSpec('hi','aux',100,300,200),VoiceSpec('lo','body',30,100,60)))
        self.assertEqual(three_voices(candidate_cap_per_voice=37).candidate_cap_per_voice,37)
    def test_cost_domains_are_not_collapsed(self):
        _,_,tu=legacy_tuning();r=solve_progression(tu,[triad(0),triad(5,'next')],three_voices())
        for f in r.frames:
            self.assertIsNone(f.costs.acoustic_fit_cost);self.assertIsNone(f.costs.grammar_cost);self.assertGreaterEqual(f.costs.voice_leading_cost,0)
        self.assertEqual(r.to_dict()['cost_domains']['voice_leading'],'optimised here')

class VoiceLeadingTests(unittest.TestCase):
    def setUp(self):self.p,self.tm,self.tu=legacy_tuning();self.t=tuning_from_spec(self.tu)
    def test_deterministic_non_crossing_ranges_required_tones(self):
        c=three_voices(min_spacing_cents=30);a=solve_progression(self.tu,[triad(0),triad(5,'b'),triad(0,'c')],c);b=solve_progression(self.tu,[triad(0),triad(5,'b'),triad(0,'c')],c)
        self.assertEqual(a.sha256,b.sha256)
        for frame in a.frames:
            self.assertEqual({v.tone_id for v in frame.voices},{'root','third','fifth'})
            self.assertTrue(all(x.frequency_hz<y.frequency_hz for x,y in zip(frame.voices,frame.voices[1:])))
            for v,spec in zip(frame.voices,c.voices):self.assertTrue(spec.min_hz<=v.frequency_hz<=spec.max_hz)
        for before,after in zip(a.frames,a.frames[1:]):
            for x,y,spec in zip(before.voices,after.voices,c.voices):self.assertLessEqual(abs(1200*math.log2(y.frequency_hz/x.frequency_hz)),spec.max_leap_cents+1e-8)
    def test_explicit_inversion_applies_to_lowest_moving_voice(self):
        frame=solve_voicing(self.tu,triad(0,bass='third'),three_voices());self.assertEqual(frame.voices[0].tone_id,'third')
    def test_hold_first_low_anchor_is_stable_while_other_voices_cover_new_sonority(self):
        r=solve_progression(self.tu,[triad(0,'a'),triad(5,'b'),triad(7,'c')],four_voices('hold-first'))
        held=[f.voices[0].frequency_hz for f in r.frames];self.assertTrue(all(abs(x-held[0])<1e-12 for x in held))
        for frame in r.frames[1:]:self.assertTrue({'root','third','fifth'}<={v.tone_id for v in frame.voices[1:]})
        self.assertTrue(any(abs(a.frequency_hz-b.frequency_hz)>1e-6 for a,b in zip(r.frames[0].voices[1:],r.frames[1].voices[1:])))
    def test_moving_bass_is_not_secretly_pedal_locked(self):
        r=solve_progression(self.tu,[triad(0,'a'),triad(5,'b'),triad(9,'c')],four_voices('moving'));bass=[f.voices[0].frequency_hz for f in r.frames]
        self.assertGreater(max(bass)-min(bass),1.)
    def test_fixed_hz_anchor_and_inversion_affect_different_voice(self):
        voices=(VoiceSpec('sub','sub',20,60,34,max_leap_cents=1200,anchor_policy='fixed-hz',fixed_hz=32.),*three_voices().voices)
        c=VoicingConstraints(voices);f=solve_voicing(self.tu,triad(0,bass='fifth'),c)
        self.assertEqual(f.voices[0].tone_id,'__fixed__');self.assertAlmostEqual(f.voices[0].frequency_hz,32,12);self.assertEqual(f.voices[1].tone_id,'fifth')
    def test_all_anchored_voices_cannot_fake_required_tone_coverage(self):
        voices=(VoiceSpec('a','sub',20,60,30,anchor_policy='fixed-hz',fixed_hz=24),VoiceSpec('b','body',61,120,80,anchor_policy='fixed-hz',fixed_hz=72),VoiceSpec('c','aux',121,240,160,anchor_policy='fixed-hz',fixed_hz=144))
        with self.assertRaises(HarmonyError):solve_voicing(self.tu,triad(0),VoicingConstraints(voices))
    def test_impossible_spacing_fails_closed(self):
        with self.assertRaises(HarmonyError):solve_voicing(self.tu,triad(0),three_voices(min_spacing_cents=1800))
    def test_chromatic_approach_is_degree_motion_not_inferred_chord_label(self):
        r=solve_progression(self.tu,[triad(0,'home'),triad(1,'approach'),triad(0,'return')],three_voices());self.assertEqual([f.root_degree for f in r.frames],[0,1,0]);self.assertGreater(r.total_voice_leading_cost,0)
        self.assertNotIn('chord',str(r.to_dict()).lower())
    def test_optional_colour_tone_may_be_omitted(self):
        s=SonoritySpec('colour',0,(SonorityTone('root',degree_offset=0),SonorityTone('fifth',degree_offset=7),SonorityTone('colour',degree_offset=14,required=False)))
        f=solve_voicing(self.tu,s,three_voices());self.assertTrue({'root','fifth'}<={v.tone_id for v in f.voices})

class TuningTests(unittest.TestCase):
    def test_non_octave_period_and_ratio_tone(self):
        t=fixture_pack()['synthetic-13ed3'];tu=tuning_to_spec(t);voices=(VoiceSpec('low','body',35,75,50),VoiceSpec('mid','aux',60,130,85),VoiceSpec('high','synthline',90,260,150));c=VoicingConstraints(voices)
        s=SonoritySpec('tritave-shape',0,(SonorityTone('root',degree_offset=0),SonorityTone('d4',degree_offset=4),SonorityTone('ratio',ratio=3/2)))
        f=solve_voicing(tu,s,c);self.assertEqual({v.tone_id for v in f.voices},{'root','d4','ratio'})
        ratio=next(v for v in f.voices if v.tone_id=='ratio');self.assertEqual(ratio.source_coordinate['kind'],'ratio')
        reconstructed=t.frequency(ratio.degree,ratio.detune_cents);self.assertAlmostEqual(reconstructed,ratio.frequency_hz,9)

class OutputTests(unittest.TestCase):
    def setUp(self):self.p,self.tm,self.tu=legacy_tuning();self.t=tuning_from_spec(self.tu);self.r=solve_progression(self.tu,[triad(0,'a'),triad(5,'b')],four_voices('hold-first'))
    def test_target_comb_is_bounded_sorted_and_contains_voice_fundamentals(self):
        f=self.r.frames[0];self.assertEqual(tuple(sorted(f.target_comb_hz)),f.target_comb_hz);self.assertLessEqual(len(f.target_comb_hz),four_voices().target_max_teeth)
        for fundamental in f.fundamental_targets_hz:self.assertTrue(any(abs(x-fundamental)<1e-9 for x in f.target_comb_hz))
    def test_events_preserve_stable_voice_ids_roles_and_exact_pitch_coordinates(self):
        events=progression_events(self.r,['0/1','1/1'],'1/1',gain_db={'sub':-20,'body':-18,'aux':-18,'lead':-18});self.assertEqual(len(events),8)
        for i,frame in enumerate(self.r.frames):
            by={e['id'].split('-')[0]:e for e in events if e['id'].endswith(f'-{i:04d}')}
            for voice in frame.voices:
                e=by[voice.voice_id];self.assertEqual(e['layer_role'],voice.role);self.assertAlmostEqual(self.t.frequency(e['pitch']['degree'],e['pitch']['detune_cents']),voice.frequency_hz,9)
    def test_voice_phrase_plans_are_audition_synthline_only(self):
        plans=voice_phrase_plans(self.r,['0/1','1/1'],'1/1',gain_db=-24)
        self.assertEqual(set(plans),{'sub','body','aux','lead'})
        for plan in plans.values():self.assertTrue(all(e['layer_role']=='synthline' for e in plan.to_dict()['events']))
    def test_source_preserving_multivoice_audition_keeps_separate_stems(self):
        # A two-voice dyad keeps this CI fixture light while exercising the real ZG-008 renderer.
        c=VoicingConstraints((VoiceSpec('body','body',36,90,55),VoiceSpec('lead','synthline',80,190,125)))
        s=lambda root,name:SonoritySpec(name,root,(SonorityTone('root',degree_offset=0),SonorityTone('fifth',degree_offset=7)))
        r=solve_progression(self.tu,[s(0,'a'),s(2,'b')],c);aud=audition_progression(r,self.p,self.tm,self.tu,['0/1','1/4'],'1/4',gain_db=-24,quality='standard',tail_mode='truncate')
        self.assertEqual(set(aud.voice_stems),{'body','lead'});self.assertGreater(len(aud.mix),0);self.assertLessEqual(float(np.max(np.abs(aud.mix),initial=0)),.981)
        self.assertEqual(aud.diagnostics['mode'],'source-derived-per-voice-diagnostic')
        for recipe in aud.recipes.values():self.assertEqual(recipe.to_dict()['phase_policy'],'source-derived')

if __name__=='__main__':unittest.main(verbosity=2)
