from __future__ import annotations
import unittest
import numpy as np
from zaaggenz_components import analyse_components
from zaaggenz_jobs import JobScheduler,JobState
from zaaggenz_spectral import (ChordnessRequest,CombTemplate,apply_chordness,cents_distance,
                               submit_chordness_job)

SR=12000

def tone(f,duration=1.,amp=.45,phase=.2):
    t=np.arange(round(SR*duration),dtype=np.float64)/SR
    return (amp*np.cos(2*np.pi*f*t+phase)).astype(np.float32)

def mix(*freqs):
    return sum((tone(f,amp=.28,phase=.17+i*.31) for i,f in enumerate(freqs)),np.zeros(SR,dtype=np.float32))

def req(templates,**kwargs):
    values=dict(mode='retune',selected_template_ids=tuple(x.id for x in templates),max_selected_templates=len(templates),
                min_confidence=.4,max_assignment_cents=180.,max_displacement_cents=100.,max_correction_slew_cents_per_second=2400.)
    values.update(kwargs);return ChordnessRequest(tuple(templates),**values)

class ChordnessEngineTests(unittest.TestCase):
    def test_off_state_is_exact_pcm_identity(self):
        x=tone(445.);analysis=analyse_components(x,SR)
        result=apply_chordness(analysis,ChordnessRequest((CombTemplate('a',(440.,)),),mode='off'))
        self.assertTrue(np.array_equal(result.audio,x));self.assertTrue(result.diagnostics['identity_path'])
        self.assertEqual(result.diagnostics['changed_frames'],0);self.assertEqual(result.selected_template_ids,())

    def test_reweight_only_changes_amplitudes_not_frequency_or_phase(self):
        analysis=analyse_components(tone(445.),SR);template=CombTemplate('a',(440.,))
        result=apply_chordness(analysis,req((template,),mode='reweight',max_gain_db=6.,max_gain_slew_db_per_second=60.))
        src=analysis.bundle.to_dict();dst=result.bundle.to_dict();changed_amp=0
        self.assertGreater(result.diagnostics['reweighted_frames'],0);self.assertEqual(result.diagnostics['retuned_frames'],0)
        for a,b in zip(src['tracks'],dst['tracks']):
            for x,y in zip(a['frames'],b['frames']):
                self.assertEqual(x['frequency_hz'],y['frequency_hz']);self.assertEqual(x['phases_radians'],y['phases_radians'])
                changed_amp+=x['amplitudes']!=y['amplitudes']
        self.assertGreater(changed_amp,0)

    def test_two_simultaneous_combs_receive_capacity_bounded_assignments(self):
        templates=(CombTemplate('low',(440.,),1),CombTemplate('high',(660.,),1))
        result=apply_chordness(analyse_components(mix(445.,665.),SR),req(templates))
        active=[d for d in result.decisions if d.decision!='preserve']
        self.assertGreater(len(active),10);self.assertEqual({'low','high'},{d.template_id for d in active})
        self.assertTrue(all(x['occupancy']<=x['capacity'] for x in result.occupancy))
        before=np.median([d.assignment_distance_cents for d in active if d.assignment_distance_cents is not None])
        after=np.median([abs(cents_distance(d.realised_hz,d.target_hz)) for d in active if d.target_hz is not None])
        self.assertLess(after,before)

    def test_hybrid_improves_declared_comb_fit_on_detuned_mixture(self):
        templates=(CombTemplate('a',(440.,),1),CombTemplate('b',(660.,),1))
        result=apply_chordness(analyse_components(mix(445.,665.),SR),req(templates,mode='hybrid',max_gain_db=4.,max_gain_slew_db_per_second=60.))
        self.assertGreater(result.diagnostics['retuned_frames'],0);self.assertGreater(result.diagnostics['reweighted_frames'],0)
        self.assertGreater(result.diagnostics['target_comb_fit_after'],result.diagnostics['target_comb_fit_before'])
        self.assertIsNotNone(result.objective_before);self.assertIsNotNone(result.objective_after)

    def test_descriptor_selection_prefers_matching_visible_candidate(self):
        analysis=analyse_components(tone(443.),SR);good=CombTemplate('good',(440.,));bad=CombTemplate('bad',(700.,))
        request=ChordnessRequest((good,bad),mode='retune',selection_mode='descriptor',max_selected_templates=1,
                                 min_confidence=.4,max_assignment_cents=300.,max_displacement_cents=150.)
        result=apply_chordness(analysis,request)
        self.assertEqual(result.selected_template_ids,('good',))
        evaluations={x['template_id']:x for x in result.candidate_evaluations}
        self.assertGreater(evaluations['good']['selection_terms']['configured_score'],evaluations['bad']['selection_terms']['configured_score'])
        self.assertIn('not preference or pleasure',evaluations['good']['selection_terms']['interpretation'])

    def test_arbitrary_local_inharmonic_targets_need_no_twelve_tet(self):
        templates=(CombTemplate('local.a',(437.2,701.3)),CombTemplate('local.b',(523.7,1003.7)))
        result=apply_chordness(analyse_components(mix(442.,706.),SR),req(templates,max_assignment_cents=220.,max_displacement_cents=160.))
        targets={d.target_hz for d in result.decisions if d.decision!='preserve'}
        self.assertTrue(437.2 in targets and 701.3 in targets)

    def test_transient_and_residual_ownership_remains_unchanged(self):
        x=tone(445.);x[len(x)//2]+=1.;analysis=analyse_components(x,SR);template=CombTemplate('a',(440.,))
        result=apply_chordness(analysis,req((template,),mode='hybrid'))
        self.assertTrue(np.array_equal(result.transient,analysis.transient));self.assertTrue(np.array_equal(result.residual,analysis.residual))

    def test_inspection_exposes_assignments_descriptors_and_objective_terms(self):
        template=CombTemplate('a',(440.,));result=apply_chordness(analyse_components(tone(445.),SR),req((template,),mode='hybrid'))
        payload=result.inspection
        self.assertEqual(payload['request']['templates'][0]['id'],'a');self.assertTrue(payload['frames'])
        self.assertIn('target_comb_fit',payload['descriptor_before']['target']);self.assertIn('roughness',payload['objective_after']['terms'])
        self.assertIn('configured engineering objective',payload['objective_after']['interpretation'])

    def test_bounded_render_job_completes(self):
        analysis=analyse_components(tone(445.,.6),SR);template=CombTemplate('a',(440.,));scheduler=JobScheduler()
        try:
            jid=submit_chordness_job(scheduler,'b'*64,analysis,req((template,),mode='hybrid'))
            snap=scheduler.wait(jid,timeout=10.);self.assertEqual(snap.state,JobState.COMPLETED.value)
            result=scheduler.result(jid);self.assertGreater(result.diagnostics['changed_frames'],0)
        finally:scheduler.shutdown(cancel=True)

if __name__=='__main__':unittest.main(verbosity=2)
