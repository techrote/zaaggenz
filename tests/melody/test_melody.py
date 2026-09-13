from __future__ import annotations
from copy import deepcopy
from fractions import Fraction
import math,sys,unittest
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'app'))

from zaaggenz_contracts.legacy import adapt_parameters,freeze_legacy,legacy_object,envelope
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_jobs import JobScheduler,SchedulerLimits,JobClass,RenderArtifact,JobCancelled
from zaaggenz_melody import *
from zaaggenz_tuning import fixture_pack,tuning_to_spec


def rat(q):return f'{q.numerator}/{q.denominator}'

def gesture(gid,axis,unit,points,*,duration='1/1',interpolation='linear'):
    return envelope('GestureSpec',id=gid,duration_beats=duration,curves=[dict(axis=axis,unit=unit,interpolation=interpolation,
        points=[dict(beat=b,value=float(v)) for b,v in points])])

class MelodyTests(unittest.TestCase):
    def base(self,*,sr=12000,bpm=200.):
        p=adapt_parameters('synth',{'sr':sr,'bpm':float(bpm),'beats':1,'f0_hz':48.})
        d=freeze_legacy(p).to_dict();return p,deepcopy(d['time_map']),deepcopy(d['tuning'])
    def recipe(self,events,*,gestures=(),end='1/1',p=None,tm=None,tu=None,mode=NoteMode.SOURCE_DERIVED,tail='preserve',quality='standard',master=0.):
        if p is None:p,tm0,tu0=self.base();tm=tm or tm0;tu=tu or tu0
        phrase=make_phrase_plan(tu['id'],events,start_beat='0/1',end_beat=end,gestures=gestures)
        return make_melodic_recipe(p,tm,tu,phrase,mode=mode,tail_mode=tail,quality=quality,master_gain_db=master)
    def test_neutral_source_path_is_exact_legacy_source_prefix(self):
        p,tm,tu=self.base();ev=note_event('n','0/1','1/1',tu['id'],0);recipe=self.recipe([ev],p=p,tm=tm,tu=tu)
        result=render_phrase(recipe,MelodicRenderSpec(mode=NoteMode.SOURCE_DERIVED))
        from uptempo_harmony.synth import synthesize_one
        source=np.asarray(synthesize_one(legacy_object('synth',p))[0],dtype=np.float32)
        self.assertTrue(np.array_equal(result.stems['synthline'][:len(source)],source))
        self.assertTrue(np.array_equal(result.mix[:len(source)],source))
        self.assertEqual(np.count_nonzero(result.stems['exciter']),0)
        self.assertEqual(result.events[0]['pitch_ratio_start'],1.)
    def test_preserve_and_truncate_have_explicit_tail_semantics(self):
        p,tm,tu=self.base();ev=note_event('n','0/1','1/4',tu['id'],0)
        preserve=render_phrase(self.recipe([ev],end='1/1',p=p,tm=tm,tu=tu,tail='preserve'))
        truncate=render_phrase(self.recipe([ev],end='1/1',p=p,tm=tm,tu=tu,tail='truncate'))
        self.assertGreater(preserve.events[0]['output_samples'],preserve.events[0]['gate_samples'])
        self.assertEqual(truncate.events[0]['output_samples'],truncate.events[0]['gate_samples'])
    def test_static_transpose_has_expected_frequency_and_stereo_phase(self):
        sr=12000;t=np.arange(sr)/sr;x=np.sin(2*np.pi*220*t).astype(np.float32);st=np.column_stack((x,-x))
        self.assertTrue(np.array_equal(pitch_shift_static(st,1.),st))
        y=pitch_shift_static(st,1.5,fft_size=1024);f=np.fft.rfftfreq(len(y),1/sr);peak=f[np.argmax(np.abs(np.fft.rfft(y[:,0])))]
        self.assertLess(abs(peak-330),4.);self.assertLess(float(np.max(np.abs(y[:,0]+y[:,1]))),2e-4)
    def test_non_octave_and_negative_degree_targets_are_explicit(self):
        p,tm,_=self.base();tuning=fixture_pack()['synthetic-13ed3'];tu=tuning_to_spec(tuning)
        events=[note_event('lo','0/1','1/1',tu['id'],-13),note_event('hi','1/1','1/1',tu['id'],13)]
        r=render_phrase(self.recipe(events,end='2/1',p=p,tm=tm,tu=tu))
        self.assertAlmostEqual(r.events[0]['target_hz'],16.,10);self.assertAlmostEqual(r.events[1]['target_hz'],144.,10)
        bad=note_event('bad','0/1','1/1',tu['id'],-14)
        with self.assertRaises(MelodyError):render_phrase(self.recipe([bad],p=p,tm=tm,tu=tu))
    def test_rational_event_timing_has_no_accumulated_rounding_drift(self):
        p,tm,tu=self.base(sr=44100,bpm=199.7);tm['tempo_segments']=[dict(beat='0/1',bpm='1997/10'),dict(beat='2/1',bpm='240/1')]
        events=[]
        for i in range(48):
            q=Fraction(i,12);events.append(rest_event(f'r{i}',rat(q),'1/12'))
        recipe=self.recipe(events,end='4/1',p=p,tm=tm,tu=tu);result=render_phrase(recipe)
        for i,row in enumerate(result.events):
            q=Fraction(i,12);expected=beat_to_sample(tm,rat(q));end=beat_to_sample(tm,rat(q+Fraction(1,12)))
            self.assertEqual(row['onset_sample'],expected);self.assertEqual(row['gate_samples'],end-expected)
        self.assertEqual(result.diagnostics['rendered_samples'],beat_to_sample(tm,'4/1'))
    def test_glide_uses_pitch_gesture_and_preserves_tail(self):
        p,tm,tu=self.base();g=gesture('rise','pitch_cents','cents',[('0/1',0),('1/1',1200)])
        ev=note_event('n','0/1','1/1',tu['id'],0,gesture_id='rise');r=render_phrase(self.recipe([ev],gestures=[g],p=p,tm=tm,tu=tu))
        self.assertAlmostEqual(r.events[0]['pitch_ratio_start'],1.,6);self.assertGreater(r.events[0]['pitch_ratio_end'],1.75)
        self.assertGreater(r.events[0]['output_samples'],0)
    def test_rolls_are_short_source_derived_slices_not_full_rerenders(self):
        for bpm,density in ((20.,4),(360.,16)):
            with self.subTest(bpm=bpm):
                p,tm,tu=self.base(bpm=bpm);g=gesture('roll','density_per_beat','events/beat',[('0/1',density),('1/1',density)],interpolation='step')
                ev=note_event('n','0/1','1/1',tu['id'],0,gesture_id='roll');spec=MelodicRenderSpec(roll_slice_max_ms=120.)
                r=render_phrase(self.recipe([ev],gestures=[g],p=p,tm=tm,tu=tu),spec);row=r.events[0]
                self.assertEqual(row['roll_retriggers'],density-1);self.assertGreater(np.max(np.abs(r.stems['exciter'])),0)
                self.assertLessEqual(row['roll_slice_samples_max'],round(.120*p['sr']));self.assertLess(row['roll_slice_samples_max'],row['source_samples'])
                self.assertGreater(row['roll_interval_samples_min'],0)
    def test_density_curve_is_not_silently_collapsed(self):
        p,tm,tu=self.base();ev=lambda gid:note_event('n','0/1','1/1',tu['id'],0,gesture_id=gid)
        varying=gesture('vary','density_per_beat','events/beat',[('0/1',4),('1/1',8)])
        fractional=gesture('frac','density_per_beat','events/beat',[('0/1',3.5),('1/1',3.5)])
        for g in (varying,fractional):
            with self.subTest(g=g['id']),self.assertRaises(MelodyError):render_phrase(self.recipe([ev(g['id'])],gestures=[g],p=p,tm=tm,tu=tu))
    def test_unsupported_gesture_axis_fails_instead_of_disappearing(self):
        p,tm,tu=self.base();g=gesture('bright','brightness_hz','Hz',[('0/1',1000),('1/1',5000)]);ev=note_event('n','0/1','1/1',tu['id'],0,gesture_id='bright')
        with self.assertRaises(MelodyError):render_phrase(self.recipe([ev],gestures=[g],p=p,tm=tm,tu=tu))
    def test_source_derived_and_target_note_are_named_distinct_paths(self):
        p,tm,tu=self.base();ev=note_event('n','0/1','1/1',tu['id'],7)
        a=render_phrase(self.recipe([ev],p=p,tm=tm,tu=tu,mode=NoteMode.SOURCE_DERIVED),MelodicRenderSpec(mode=NoteMode.SOURCE_DERIVED))
        b=render_phrase(self.recipe([ev],p=p,tm=tm,tu=tu,mode=NoteMode.TARGET_NOTE),MelodicRenderSpec(mode=NoteMode.TARGET_NOTE))
        self.assertEqual(a.events[0]['mode'],'source-derived');self.assertEqual(b.events[0]['mode'],'target-note')
        self.assertGreater(a.events[0]['pitch_ratio_start'],1.4);self.assertEqual(b.events[0]['pitch_ratio_start'],1.)
        self.assertFalse(np.array_equal(a.mix,b.mix))
    def test_master_is_final_linear_gain_when_not_clipping(self):
        p,tm,tu=self.base();ev=note_event('n','0/1','1/1',tu['id'],0);r=render_phrase(self.recipe([ev],p=p,tm=tm,tu=tu,master=-6.))
        gain=10**(-6/20);self.assertTrue(np.allclose(r.mix,r.stems['pre_master']*gain,rtol=1e-6,atol=2e-7));self.assertEqual(r.diagnostics['clipped_fraction'],0.)
    def test_job_executor_binds_recipe_revision_audio_and_scopes(self):
        p,tm,tu=self.base();ev=note_event('n','0/1','1/1',tu['id'],0);recipe=self.recipe([ev],p=p,tm=tm,tu=tu);revision='a'*64
        limits=SchedulerLimits(interactive_workers=1,background_workers=1,max_queued_jobs=8,max_background_queued_jobs=4,max_history_jobs=32,
            max_memory_bytes=1_000_000,interactive_memory_reserve_bytes=200_000,max_job_memory_bytes=500_000,max_preview_memory_bytes=200_000,
            preview_cache_bytes=1_000_000,preview_cache_entries=4,numeric_threads=1)
        sched=JobScheduler(limits,apply_numeric_limit=False)
        try:
            ex=make_render_executor(recipe,MelodicRenderSpec(),revision);jid=sched.submit(JobClass.RENDER,revision,ex,estimated_memory_bytes=100_000);self.assertEqual(sched.wait(jid,5).state,'completed')
            art=sched.result(jid);self.assertIsInstance(art,RenderArtifact);self.assertEqual(art.revision_id,revision);self.assertEqual(art.recipe_sha256,recipe.sha256)
            self.assertEqual(art.asset['frame_count'],len(art.audio_bytes)//4);self.assertEqual(art.scopes['diagnostics']['recipe_sha256'],recipe.sha256)
        finally:sched.shutdown(cancel=True,timeout=2)
    def test_note_helpers_reject_lossy_degree_coercion(self):
        with self.assertRaises(MelodyError):note_event('n','0/1','1/1','legacy-12edo',1.5)
        with self.assertRaises(MelodyError):note_event('n','0/1','1/1','legacy-12edo',True)

if __name__=='__main__':unittest.main(verbosity=2)
