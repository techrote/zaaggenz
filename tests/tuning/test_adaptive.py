from __future__ import annotations
import unittest
from zaaggenz_jobs import JobScheduler,JobState
from zaaggenz_tuning import (AdaptiveState,AdaptiveTuningRequest,AdaptiveVoice,AdaptiveWeights,ab_recipe,
                             candidate_tuning_set,commit_proposal,harmonic_spectrum,propose_adaptive_tuning,
                             reject_proposal,submit_adaptive_tuning_job)

def voice(id,root_hz,nominal,*,role='voice',locked=False,confidence=1.):
    return AdaptiveVoice(id,nominal,harmonic_spectrum(id+'spec',root_hz,partials=8,confidence=confidence),role,locked)

def request(*,desired=0.,second_cents=705.,second_confidence=1.,max_total=30.,max_step=12.,min_sep=20.,pedal=False):
    root=voice('root',220.,0.,role='root');second=voice('upper',220.*2**(second_cents/1200.),second_cents,role='pedal' if pedal else 'voice',confidence=second_confidence)
    return AdaptiveTuningRequest((root,second),(0.,498.,702.,1200.),'root',desired_tension=desired,
        max_total_drift_cents=max_total,max_step_cents=max_step,search_step_cents=1.,min_separation_cents=min_sep,
        weights=AdaptiveWeights(tension=12.,voice_leading=.02,drift=.02,candidate_proximity=.1))

class AdaptiveTuningTests(unittest.TestCase):
    def test_low_tension_moves_detuned_fifth_toward_candidate_and_locks_root(self):
        proposal=propose_adaptive_tuning(request(desired=0.))
        self.assertEqual(proposal.status,'proposed');offsets=proposal.offset_mapping()
        self.assertEqual(offsets['root'],0.);self.assertLess(offsets['upper'],0.)
        self.assertLess(abs((705.+offsets['upper'])-702.),abs(705.-702.))
        self.assertLessEqual(abs(offsets['upper']),12.);self.assertTrue(proposal.to_dict()['manual_review_required'])

    def test_desired_tension_changes_proposal_without_muting_any_voice(self):
        low=propose_adaptive_tuning(request(desired=0.));high=propose_adaptive_tuning(request(desired=.2))
        self.assertNotEqual(low.offset_mapping()['upper'],high.offset_mapping()['upper'])
        self.assertLessEqual(abs(high.objective['predicted_tension']-.2),abs(low.objective['predicted_tension']-.2)+1e-12)
        before=[v.spectrum.amplitudes for v in high.request.voices];after=[v.spectrum.amplitudes for v in low.request.voices]
        self.assertEqual(before,after);self.assertEqual(high.request.to_dict()['amplitude_policy'],'immutable; adaptive tuning changes pitch only')

    def test_repeated_manual_commits_cannot_drift_beyond_absolute_bound(self):
        req=request(desired=.3,max_total=20.,max_step=5.);state=AdaptiveState()
        for _ in range(20):
            proposal=propose_adaptive_tuning(req,state);self.assertEqual(proposal.status,'proposed');state=commit_proposal(proposal)
            self.assertTrue(all(abs(v)<=20.+1e-9 for v in state.mapping().values()))
        self.assertEqual(state.mapping()['root'],0.);self.assertEqual(state.step_index,20)

    def test_reject_is_exact_state_noop(self):
        state=AdaptiveState((('upper',-2.),),4);proposal=propose_adaptive_tuning(request(),state)
        self.assertEqual(reject_proposal(proposal),state)

    def test_low_confidence_source_abstains(self):
        proposal=propose_adaptive_tuning(request(second_confidence=.2))
        self.assertEqual(proposal.status,'abstained');self.assertEqual(proposal.reason,'low-source-confidence');self.assertEqual(proposal.offset_mapping()['upper'],0.)

    def test_pedal_choice_is_explicitly_locked(self):
        proposal=propose_adaptive_tuning(request(pedal=True),AdaptiveState((('upper',4.),),1))
        self.assertEqual(proposal.offset_mapping()['upper'],4.);self.assertEqual(proposal.request.voices[1].role,'pedal')

    def test_minimum_separation_is_hard_constraint(self):
        req=request(second_cents=24.,desired=.4,max_total=10.,max_step=10.,min_sep=20.)
        proposal=propose_adaptive_tuning(req);self.assertEqual(proposal.status,'proposed')
        adjusted=dict(proposal.adjusted_cents);self.assertGreaterEqual(abs(adjusted['upper']-adjusted['root']),20.-1e-9)

    def test_ab_export_is_hashable_reproducible_and_manual(self):
        proposal=propose_adaptive_tuning(request());a=ab_recipe(proposal);b=ab_recipe(proposal)
        self.assertEqual(a,b);self.assertEqual(len(a['recipe_sha256']),64);self.assertTrue(a['controls']['manual_accept_reject'])
        self.assertTrue(candidate_tuning_set(proposal)['manual_review_required'])

    def test_analysis_job_returns_proposal(self):
        scheduler=JobScheduler()
        try:
            jid=submit_adaptive_tuning_job(scheduler,'d'*64,request());snap=scheduler.wait(jid,timeout=10.)
            self.assertEqual(snap.state,JobState.COMPLETED.value);self.assertEqual(scheduler.result(jid).status,'proposed')
        finally:scheduler.shutdown(cancel=True)

if __name__=='__main__':unittest.main(verbosity=2)
