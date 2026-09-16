from __future__ import annotations
import json,math,unittest
import numpy as np
from scipy import signal
from zaaggenz_components import analyse_components
from zaaggenz_contracts import validate
from zaaggenz_jobs import JobScheduler,JobState
from zaaggenz_tuning import fixture_pack,tuning_to_spec
from zaaggenz_spectral import *

SR=12000

def tone(f,duration=1.,amp=.55,phase=.23):
    t=np.arange(round(SR*duration),dtype=np.float64)/SR
    return (amp*np.cos(2*np.pi*f*t+phase)).astype(np.float32)

def spec12():return tuning_to_spec(fixture_pack()['12tet-a440'])

def request(**kwargs):
    values=dict(tuning_spec=spec12(),voices=(LatticeVoice(0,(1.,),'a440'),),
                min_hz=100.,max_hz=1200.,max_displacement_cents=180.,
                max_correction_slew_cents_per_second=1200.)
    values.update(kwargs);return SpectralRetuneRequest(**values)

def phase_difference(row):
    a,b=row['phases_radians'];return ((b-a+math.pi)%(2*math.pi))-math.pi

def one_tooth_segments(count):
    voice=(LatticeVoice(0,(1.,),'bounded'),)
    return tuple(LatticeSegment(i+1,voice,f's{i}') for i in range(count))

def full_voice_set():
    ratios=tuple(float(i) for i in range(1,129))
    return tuple(LatticeVoice(0,ratios,f'v{i}') for i in range(32))

class SpectralRetuneTests(unittest.TestCase):
    def test_explicit_harmonic_and_inharmonic_teeth(self):
        r=request(voices=(LatticeVoice(0,(1.,math.sqrt(2),2.03),'inharmonic'),))
        teeth=build_target_lattice(r)
        self.assertEqual(len(teeth),3)
        self.assertAlmostEqual(teeth[0].frequency_hz,440.,places=8)
        self.assertAlmostEqual(teeth[1].frequency_hz,440.*math.sqrt(2),places=8)
        self.assertAlmostEqual(teeth[2].frequency_hz,440.*2.03,places=8)
        self.assertEqual(r.to_dict()['voices'][0]['label'],'inharmonic')

    def test_amount_zero_uses_exact_identity_path(self):
        x=tone(445.);analysis=analyse_components(x,SR)
        result=retune_components(analysis,request(amount=0.))
        self.assertTrue(np.array_equal(result.audio,analysis.source))
        self.assertTrue(result.diagnostics['identity_path'])
        self.assertEqual(result.diagnostics['changed_frames'],0)
        self.assertTrue(all(d.reason=='amount-zero-exact-bypass' for d in result.plan.decisions))
        validate(result.bundle.to_dict(),'PartialTrackBundle')

    def test_isolated_component_reaches_explicit_target(self):
        analysis=analyse_components(tone(445.),SR);result=retune_components(analysis,request())
        changed=[d for d in result.plan.decisions if d.decision=='transform']
        self.assertGreater(len(changed),10)
        self.assertLess(np.median([abs(cents_distance(d.realised_hz,440.)) for d in changed]),.25)
        self.assertTrue(all(d.requested_hz==440. for d in changed))
        self.assertFalse(result.diagnostics['identity_path'])

    def test_scheduled_target_change_obeys_correction_slew(self):
        change=SR//2
        req=request(segments=(LatticeSegment(change,(LatticeVoice(1,(1.,),'next-degree'),),'raise'),),
                    max_correction_slew_cents_per_second=240.)
        result=retune_components(analyse_components(tone(443.,1.2),SR),req)
        rows=[d for d in result.plan.decisions if d.decision=='transform']
        self.assertIn(0,{d.target_segment for d in rows});self.assertIn(1,{d.target_segment for d in rows})
        after=[d for d in rows if d.anchor_sample>=change]
        self.assertTrue(after);self.assertAlmostEqual(after[-1].requested_hz,fixture_pack()['12tet-a440'].frequency(1),places=8)
        for a,b in zip(rows,rows[1:]):
            if a.track_id!=b.track_id:continue
            dt=(b.anchor_sample-a.anchor_sample)/SR
            self.assertLessEqual(abs(b.correction_cents-a.correction_cents),240.*dt+1e-7)
        self.assertEqual(result.inspection['target_starts'],[0,change])

    def test_crossing_uncertainty_is_not_forced_through_retune(self):
        n=round(SR*1.4);t=np.arange(n)/SR
        x=(.35*signal.chirp(t,280,t[-1],620)+.35*signal.chirp(t,620,t[-1],280,phi=80)).astype(np.float32)
        analysis=analyse_components(x,SR);src=analysis.bundle.to_dict();result=retune_components(analysis,request(voices=(LatticeVoice(-7,(1.,2.,3.,4.,5.,6.),'broad'),),min_hz=180.,max_hz=1500.,max_displacement_cents=500.))
        uncertain={tr['id'] for tr in src['tracks'] if tr['continuity']!='continuous'}
        self.assertTrue(uncertain)
        relevant=[d for d in result.plan.decisions if d.track_id in uncertain]
        self.assertTrue(relevant);self.assertTrue(all(d.decision=='preserve' for d in relevant))

    def test_transient_and_residual_are_bit_identical(self):
        x=tone(445.);x[len(x)//2]+=1.
        analysis=analyse_components(x,SR);result=retune_components(analysis,request())
        self.assertTrue(np.array_equal(result.transient,analysis.transient))
        self.assertTrue(np.array_equal(result.residual,analysis.residual))
        self.assertTrue(result.diagnostics['transient_unchanged']);self.assertTrue(result.diagnostics['residual_unchanged'])

    def test_stereo_phase_relation_survives_shared_phase_correction(self):
        mono=tone(445.,phase=.11);analysis=analyse_components(np.column_stack((mono,-mono)),SR)
        source=analysis.bundle.to_dict();result=retune_components(analysis,request());dest=result.bundle.to_dict()
        src_tracks={t['id']:t for t in source['tracks']};checked=0
        for track in dest['tracks']:
            original=src_tracks[track['id']]
            for a,b in zip(original['frames'],track['frames']):
                if abs(b['frequency_hz']-a['frequency_hz'])<1e-8:continue
                before=phase_difference(a);after=phase_difference(b)
                delta=((after-before+math.pi)%(2*math.pi))-math.pi
                self.assertLess(abs(delta),1e-9);checked+=1
        self.assertGreater(checked,5)
        self.assertEqual(result.diagnostics['stereo_phase_policy'],'shared-correction-per-track')

    def test_bounded_render_job_returns_same_typed_result(self):
        analysis=analyse_components(tone(445.,.6),SR);req=request();scheduler=JobScheduler()
        try:
            jid=submit_retune_job(scheduler,'a'*64,analysis,req)
            snap=scheduler.snapshot(jid)
            self.assertEqual(snap.estimated_memory_bytes,estimate_retune_memory_bytes(analysis,req))
            self.assertGreater(snap.estimated_memory_bytes,estimate_retune_memory_bytes(analysis))
            snap=scheduler.wait(jid,timeout=10.)
            self.assertEqual(snap.state,JobState.COMPLETED.value)
            result=scheduler.result(jid);self.assertIsInstance(result,SpectralRetuneResult)
            self.assertGreater(result.diagnostics['changed_frames'],0)
        finally:scheduler.shutdown(cancel=True)

    def test_invalid_segment_order_is_rejected(self):
        with self.assertRaises(SpectralRetuneError):
            request(segments=(LatticeSegment(500,(LatticeVoice(0,(1.,)),)),LatticeSegment(400,(LatticeVoice(1,(1.,)),))))

    def test_exact_segment_bound_is_accepted_and_one_over_rejected_before_tuning(self):
        req=request(segments=one_tooth_segments(MAX_RETUNE_SEGMENTS))
        counts=retune_request_work_counts(req)
        self.assertEqual(counts['segments'],MAX_RETUNE_SEGMENTS)
        self.assertEqual(counts['target_segments'],MAX_RETUNE_SEGMENTS+1)
        self.assertEqual(len(build_target_schedule(req)),MAX_RETUNE_SEGMENTS+1)
        with self.assertRaisesRegex(SpectralRetuneError,'segments exceeds bounded maximum'):
            SpectralRetuneRequest(tuning_spec={},voices=(LatticeVoice(0,(1.,)),),
                                  segments=one_tooth_segments(MAX_RETUNE_SEGMENTS+1))

    def test_candidate_tooth_budget_accepts_exact_maximum_and_rejects_one_over(self):
        voices=full_voice_set()
        exact_segments=tuple(LatticeSegment(i+1,voices,f'full-{i}') for i in range(7))
        req=request(voices=voices,segments=exact_segments,max_hz=60000.)
        self.assertEqual(retune_request_work_counts(req)['candidate_teeth'],MAX_RETUNE_CANDIDATE_TEETH)
        schedule=build_target_schedule(req)
        teeth=tuple(tooth for _,_,segment_teeth in schedule for tooth in segment_teeth)
        self.assertEqual(len(teeth),MAX_RETUNE_CANDIDATE_TEETH)
        plan=SpectralRetunePlan(req,teeth,(),tuple(item[0] for item in schedule))
        payload=plan.inspection()
        self.assertEqual(len(payload['teeth']),MAX_RETUNE_CANDIDATE_TEETH)
        self.assertLess(len(json.dumps(payload,separators=(',',':')).encode('utf-8')),16*1024*1024)
        over=exact_segments+(LatticeSegment(8,(LatticeVoice(0,(1.,),'one-over'),),'one-over'),)
        with self.assertRaisesRegex(SpectralRetuneError,'candidate count .* exceeds bounded maximum'):
            request(voices=voices,segments=over,max_hz=60000.)

    def test_in_band_filtering_cannot_bypass_raw_candidate_budget(self):
        ratios=tuple(float(i) for i in range(1,129));voices=tuple(LatticeVoice(0,ratios,f'v{i}') for i in range(32))
        exact=tuple(LatticeSegment(i+1,voices) for i in range(7))
        # Only the 440 Hz tooth in each voice is in band; resource admission still
        # accounts the complete declared lattice before tuning/filter work.
        req=request(voices=voices,segments=exact,min_hz=430.,max_hz=450.)
        schedule=build_target_schedule(req)
        self.assertEqual(retune_request_work_counts(req)['candidate_teeth'],MAX_RETUNE_CANDIDATE_TEETH)
        self.assertEqual(sum(len(teeth) for _,_,teeth in schedule),8*32)
        with self.assertRaisesRegex(SpectralRetuneError,'candidate count .* exceeds bounded maximum'):
            request(voices=voices,segments=exact+(LatticeSegment(8,(LatticeVoice(0,(1000.,)),)),),
                    min_hz=430.,max_hz=450.)

    def test_segment_with_no_in_band_teeth_still_fails_explicitly(self):
        req=request(segments=(LatticeSegment(1,(LatticeVoice(0,(100.,),'out-of-band'),)),))
        with self.assertRaisesRegex(SpectralRetuneError,'target lattice has no teeth'):
            build_target_schedule(req)

    def test_schedule_construction_checks_cancellation_inside_large_lattice(self):
        voices=full_voice_set();req=request(voices=voices,max_hz=60000.)
        calls=[]
        class StopSchedule(RuntimeError):pass
        def checkpoint():
            calls.append(len(calls))
            if len(calls)==3:raise StopSchedule('cancelled during target construction')
        with self.assertRaises(StopSchedule):build_target_schedule(req,checkpoint=checkpoint)
        self.assertEqual(len(calls),3)

if __name__=='__main__':unittest.main(verbosity=2)
