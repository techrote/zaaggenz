from __future__ import annotations
import copy,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_listening import ListeningError,TrialResult,make_result,make_trial


def matched(stimulus_hex,playback_hex):
    return {'stimulus_id':stimulus_hex*64,'playback_sha256':playback_hex*64,'gain_db':0.,'source_rms_dbfs':-18.,'source_sample_peak':.2,
            'target_rms_dbfs':-18.,'matched_rms_dbfs':-18.,'matched_sample_peak':.2,'sample_peak_headroom_db':13.9794,
            'method':'whole-file-rms-common-target-v1','true_peak_measured':False}


class ResultSemanticTests(unittest.TestCase):
    def setUp(self):
        self.rows=[matched('a','c'),matched('b','d')]
        self.meta={r['stimulus_id']:{'sample_rate_hz':8000,'frame_count':8000} for r in self.rows}

    def _trial(self,design='ab'):
        return make_trial(design.upper(),design,self.rows,seed='7',endpoints=('liking','groove'))

    def test_ab_and_multi_choice_is_null_or_exact_presented_stimulus_id(self):
        ab=self._trial('ab');valid=ab.to_dict()['presentation_order'][0]
        self.assertIsNone(make_result(ab,ratings={'liking':50}).to_dict()['choice'])
        self.assertEqual(make_result(ab,choice=valid,ratings={'liking':50}).to_dict()['choice'],valid)
        with self.assertRaisesRegex(ListeningError,'presented stimulus'):make_result(ab,choice='not-a-stimulus',ratings={'liking':50})
        multi=make_trial('Multi','multi',self.rows,seed='8',endpoints=('liking',))
        with self.assertRaisesRegex(ListeningError,'presented stimulus'):make_result(multi,choice='arbitrary',ratings={'liking':50})

    def test_abx_completed_requires_label_and_scoring_stays_manifest_bound(self):
        trial=self._trial('abx');truth=trial.to_dict()['abx_truth']
        result=make_result(trial,choice=truth,ratings={'liking':50})
        self.assertTrue(result.to_dict()['abx_correct'])
        with self.assertRaisesRegex(ListeningError,'completed ABX'):make_result(trial,choice=None,ratings={'liking':50})
        with self.assertRaisesRegex(ListeningError,'ABX choice'):make_result(trial,choice=self.rows[0]['stimulus_id'],ratings={'liking':50})

    def test_annotation_target_must_belong_to_trial(self):
        trial=self._trial();sid=trial.to_dict()['presentation_order'][0]
        ann={'stimulus_id':'f'*64,'time_seconds':.5,'label':'attack','note':''}
        with self.assertRaisesRegex(ListeningError,'presented by this trial'):
            make_result(trial,status='aborted',annotations=[ann],stimulus_metadata=self.meta)
        good={**ann,'stimulus_id':sid}
        self.assertEqual(make_result(trial,status='aborted',annotations=[good],stimulus_metadata=self.meta).to_dict()['annotations'][0]['stimulus_id'],sid)

    def test_annotation_time_uses_exact_stimulus_presentation_clock(self):
        trial=self._trial();sid=trial.to_dict()['presentation_order'][0]
        def ann(t):return {'stimulus_id':sid,'time_seconds':t,'label':'attack','note':''}
        for t in (0.,.999,1.0):make_result(trial,status='aborted',annotations=[ann(t)],stimulus_metadata=self.meta)
        with self.assertRaisesRegex(ListeningError,'exceeds referenced stimulus duration'):
            make_result(trial,status='aborted',annotations=[ann(1.000001)],stimulus_metadata=self.meta)
        # Frozen 1.0 manifests do not contain duration; low-level historical
        # construction remains structurally compatible when timing context is absent.
        make_result(trial,status='aborted',annotations=[ann(.5)])

    def test_missing_status_cannot_fabricate_substantive_observations(self):
        trial=self._trial();order=trial.to_dict()['presentation_order'];zero={sid:0 for sid in order}
        base=make_result(trial,status='missing',note='participant unavailable')
        self.assertEqual(base.to_dict()['note'],'participant unavailable')
        cases=[
            {'choice':order[0]}, {'ratings':{'liking':1}}, {'confidence':1}, {'effort':1}, {'comfortable_level':1},
            {'replay_counts':{order[0]:1,order[1]:0}},
            {'annotations':[{'stimulus_id':order[0],'time_seconds':0.,'label':'x','note':''}],'stimulus_metadata':self.meta},
        ]
        for extra in cases:
            with self.subTest(extra=extra),self.assertRaisesRegex(ListeningError,'missing result'):
                make_result(trial,status='missing',replay_counts=extra.pop('replay_counts',zero),**extra)

    def test_aborted_status_preserves_partial_but_semantically_valid_observations(self):
        trial=self._trial();sid=trial.to_dict()['presentation_order'][0];counts={x:0 for x in trial.to_dict()['presentation_order']};counts[sid]=2
        result=make_result(trial,status='aborted',choice=sid,ratings={'groove':22},effort=81,replay_counts=counts,
                           annotations=[{'stimulus_id':sid,'time_seconds':1.0,'label':'tail','note':'stopped here'}],stimulus_metadata=self.meta)
        self.assertEqual(result.to_dict()['status'],'aborted');self.assertEqual(result.to_dict()['choice'],sid);self.assertIsNone(result.to_dict()['abx_correct'])

    def test_persisted_result_revalidation_rejects_manifest_and_semantic_tampering(self):
        trial=self._trial();sid=trial.to_dict()['presentation_order'][0]
        result=make_result(trial,choice=sid,ratings={'liking':50})
        self.assertEqual(TrialResult(result.to_dict(),trial).sha256,result.sha256)
        forged=result.to_dict();forged['choice']='e'*64
        with self.assertRaisesRegex(ListeningError,'presented stimulus'):TrialResult(forged,trial)
        annotated=result.to_dict();annotated['status']='aborted';annotated['choice']=None;annotated['ratings']={};annotated['annotations']=[{'stimulus_id':sid,'time_seconds':2.,'label':'late','note':''}]
        with self.assertRaisesRegex(ListeningError,'exceeds referenced stimulus duration'):TrialResult(annotated,trial,stimulus_metadata=self.meta)


if __name__=='__main__':unittest.main()
