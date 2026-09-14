from __future__ import annotations
import unittest
import numpy as np
from zaaggenz_jobs import JobScheduler,JobState
from zaaggenz_spectral import (LatticeVoice,NonlinearStageSpec,PlacementRequest,SpectralRetuneRequest,
                               run_family,run_placement,submit_placement_family_job)
from zaaggenz_tuning import fixture_pack,tuning_to_spec

SR=12000

def tone(f,duration=.8,amp=.52,phase=.17):
    t=np.arange(round(SR*duration),dtype=np.float64)/SR
    return (amp*np.cos(2*np.pi*f*t+phase)).astype(np.float32)

def spectral(amount=1.):
    return SpectralRetuneRequest(tuning_spec=tuning_to_spec(fixture_pack()['12tet-a440']),voices=(LatticeVoice(0,(1.,),'a440'),),
                                 amount=amount,min_confidence=.4,min_hz=100.,max_hz=2000.,max_displacement_cents=180.,
                                 max_correction_slew_cents_per_second=2400.)

def stages(mix=1.,factor=2,mode='antialiased'):
    return (NonlinearStageSpec('tanh',mode,factor,drive_db=15.,mix=mix),
            NonlinearStageSpec('hard_clip',mode,factor,threshold=.58,mix=mix))

class PlacementTests(unittest.TestCase):
    def test_family_order_is_explicit_and_only_spectral_position_changes(self):
        a,b=stages();rows={p:PlacementRequest(spectral(),p,a,b).to_dict() for p in ('pre','inter','post')}
        self.assertEqual(rows['pre']['order'],['spectral','stage_a','stage_b']);self.assertEqual(rows['inter']['order'],['stage_a','spectral','stage_b']);self.assertEqual(rows['post']['order'],['stage_a','stage_b','spectral'])
        for p in rows:
            self.assertEqual(rows[p]['stage_a'],rows['pre']['stage_a']);self.assertEqual(rows[p]['stage_b'],rows['pre']['stage_b'])
            self.assertEqual(rows[p]['output_policy']['normalization'],'none');self.assertEqual(rows[p]['output_policy']['master_gain_db'],0.)

    def test_placement_family_is_deterministic_and_order_changes_output(self):
        x=tone(445.);a,b=stages();first=run_family(x,SR,spectral(),a,b);second=run_family(x,SR,spectral(),a,b)
        for p in first:np.testing.assert_array_equal(first[p].audio,second[p].audio)
        self.assertGreater(np.max(np.abs(first['pre'].audio-first['post'].audio)),1e-5);self.assertGreater(np.max(np.abs(first['inter'].audio-first['post'].audio)),1e-5)
        for result in first.values():
            self.assertEqual(result.audio.shape,x.shape);self.assertTrue(np.isfinite(result.audio).all());self.assertEqual(result.diagnostics['normalization'],'none');self.assertEqual(result.diagnostics['master_gain_db'],0.)

    def test_full_identity_aligns_all_variants_in_latency_and_gain(self):
        x=tone(445.);a,b=stages(mix=0.,factor=4);family=run_family(x,SR,spectral(amount=0.),a,b)
        for result in family.values():
            np.testing.assert_array_equal(result.audio,x);self.assertTrue(result.diagnostics['identity_path']);self.assertEqual(result.diagnostics['declared_latency_samples'],0);self.assertEqual(len(result.audio),len(x))

    def test_legacy_alias_mode_remains_a_separate_one_x_option(self):
        a,b=stages(factor=1,mode='legacy');result=run_placement(tone(445.),SR,PlacementRequest(spectral(),'inter',a,b));spec=result.request.to_dict()
        self.assertEqual(spec['stage_a']['type_id'],'core.tanh.v1');self.assertEqual(spec['stage_b']['type_id'],'core.hard_clip.v1');self.assertEqual(spec['stage_a']['filter']['id'],'legacy-direct-1x')

    def test_inspection_persists_graph_nodes_and_spectral_decisions(self):
        a,b=stages();result=run_placement(tone(445.),SR,PlacementRequest(spectral(),'pre',a,b));payload=result.inspection
        self.assertEqual(payload['request']['placement'],'pre');self.assertEqual(len(payload['graph_nodes']),2);self.assertEqual(payload['graph_nodes'][0]['type_id'],'core.tanh_aa.v1');self.assertTrue(payload['spectral']['frames']);self.assertIn('post-spectral',result.taps);self.assertIn('output',result.taps)

    def test_bounded_family_job_returns_all_three_variants(self):
        x=tone(445.,duration=.45);a,b=stages();scheduler=JobScheduler()
        try:
            jid=submit_placement_family_job(scheduler,'c'*64,x,SR,spectral(),a,b);snap=scheduler.wait(jid,timeout=15.)
            self.assertEqual(snap.state,JobState.COMPLETED.value);result=scheduler.result(jid);self.assertEqual(set(result),{'pre','inter','post'})
            self.assertTrue(all(v.audio.shape==x.shape for v in result.values()))
        finally:scheduler.shutdown(cancel=True)

if __name__=='__main__':unittest.main(verbosity=2)
