"""Local immutable listening material and trial/result registry."""
from __future__ import annotations
from copy import deepcopy
import secrets
from zaaggenz_contracts import digest
from zaaggenz_jobs import RenderArtifact,JobError
from .model import TrialManifest,TrialResult,Stimulus,ListeningError
from .stimulus import ListeningAudioStore
from .trial import make_trial,make_participant_trial,make_result,public_trial,public_result,INSTRUCTIONS

class ListeningService:
    def __init__(self,timeline_service):
        self.timeline=timeline_service;self.audio=ListeningAudioStore();self.trials={};self.results={};self._participant_to_trusted={};self._trusted_to_participant={}
    def freeze_job(self,job_id,name,start_frame=0,end_frame=None):
        try:artifact=self.timeline.artifact(job_id)
        except JobError as e:raise ListeningError(str(e)) from e
        if not isinstance(artifact,RenderArtifact):raise ListeningError('completed render job required')
        stimulus=self.audio.add_artifact(name,artifact,start_frame=start_frame,end_frame=end_frame)
        return stimulus.to_dict()
    def match(self,stimulus_ids,target_rms_dbfs=None,peak_ceiling_dbfs=-3.):return self.audio.match(stimulus_ids,target_rms_dbfs=target_rms_dbfs,peak_ceiling_dbfs=peak_ceiling_dbfs)
    @staticmethod
    def _stimulus_metadata(stimuli):
        rows={}
        for stimulus in stimuli:
            if not isinstance(stimulus,Stimulus):raise ListeningError('Stimulus required for result timing validation')
            d=stimulus.to_dict();rows[d['id']]={'sample_rate_hz':d['sample_rate_hz'],'frame_count':d['frame_count']}
        return rows
    def _trial_stimulus_metadata(self,trial):
        td=trial.to_dict();return self._stimulus_metadata([self.audio.stimulus(row['stimulus_id']) for row in td['matched_stimuli']])
    def _register_trial(self,trial,participant_id=None):
        if not isinstance(trial,TrialManifest):raise ListeningError('TrialManifest required')
        tid=trial.to_dict()['id'];self.trials[tid]=trial
        if tid in self._trusted_to_participant:pid=self._trusted_to_participant[tid]
        else:
            pid=secrets.token_hex(32) if participant_id is None else participant_id
            if type(pid)is not str or len(pid)!=64 or any(c not in '0123456789abcdef' for c in pid):raise ListeningError('participant trial ID must be lowercase SHA-256')
            if pid in self._participant_to_trusted and self._participant_to_trusted[pid]!=tid:raise ListeningError('participant trial ID collision')
            self._participant_to_trusted[pid]=tid;self._trusted_to_participant[tid]=pid
        return public_trial(trial,pid)
    def create_trial(self,title,design,matched_stimuli,seed='0',endpoints=('liking','sound_quality'),instruction_template=None):
        """Trusted/programmatic deterministic construction used by offline evidence and tests."""
        return self._register_trial(make_trial(title,design,matched_stimuli,seed=seed,endpoints=endpoints,instruction_template=instruction_template))
    def create_participant_trial(self,title,design,matched_stimuli,seed='0',endpoints=('liking','sound_quality'),instruction_template=None):
        """HTTP participant construction: ordering may use the visible seed; ABX truth never does."""
        hidden=None if design!='abx' else secrets.choice(('A','B'))
        trial=make_participant_trial(title,design,matched_stimuli,seed=seed,endpoints=endpoints,instruction_template=instruction_template,hidden_abx_truth=hidden)
        return self._register_trial(trial)
    def _trusted_id(self,trial_id,*,participant_only=False):
        if trial_id in self._participant_to_trusted:return self._participant_to_trusted[trial_id]
        if not participant_only and trial_id in self.trials:return trial_id
        raise ListeningError('unknown trial')
    def participant_manifest(self,participant_id):
        return self.trials[self._trusted_id(participant_id,participant_only=True)]
    def manifest(self,trial_id):
        return self.trials[self._trusted_id(trial_id)]
    def submit(self,trial_id,payload):
        tid=self._trusted_id(trial_id);trial=self.trials[tid];result=make_result(trial,stimulus_metadata=self._trial_stimulus_metadata(trial),**payload);self.results.setdefault(tid,[]).append(result);return {'result':result.to_dict(),'result_sha256':result.sha256}
    def submit_participant(self,participant_id,payload):
        """One terminal participant response per public trial; retakes require a new trial."""
        tid=self._trusted_id(participant_id,participant_only=True);trial=self.trials[tid]
        if self.results.get(tid):raise ListeningError('participant trial already has a terminal result; create a new trial for a retake')
        result=make_result(trial,stimulus_metadata=self._trial_stimulus_metadata(trial),**payload);self.results.setdefault(tid,[]).append(result);view=public_result(result,participant_id)
        return {'result':view,'result_sha256':digest({'domain':'zaaggenz.listening-participant-result-v1','result':view})}
    def export_bundle(self,trial_id):
        """Trusted archival export. Never expose this through participant capability."""
        tid=self._trusted_id(trial_id);trial=self.trials[tid];td=trial.to_dict();stimuli=[self.audio.stimulus(row['stimulus_id']).to_dict() for row in td['matched_stimuli']]
        return {'format':'zaaggenz-listening-bundle','version':'1.0.0','stimuli':stimuli,'manifest':td,'results':[r.to_dict() for r in self.results.get(tid,[])]}
    def export_participant_bundle(self,participant_id):
        """Participant-safe export: no seed, trusted trial ID, ABX truth or correctness oracle."""
        tid=self._trusted_id(participant_id,participant_only=True);trial=self.trials[tid];td=trial.to_dict();stimuli=[self.audio.stimulus(row['stimulus_id']).to_dict() for row in td['matched_stimuli']]
        return {'format':'zaaggenz-listening-participant-bundle','version':'1.0.0','role':'participant','stimuli':stimuli,
                'trial':public_trial(trial,participant_id),'results':[public_result(r,participant_id) for r in self.results.get(tid,[])]}
    def reopen_bundle(self,bundle):
        if type(bundle)is not dict or set(bundle)!={'format','version','stimuli','manifest','results'} or bundle['format']!='zaaggenz-listening-bundle' or bundle['version']!='1.0.0':raise ListeningError('invalid trusted listening bundle')
        trial=TrialManifest(bundle['manifest']);stimuli=[Stimulus(s) for s in bundle['stimuli']]
        if {s.to_dict()['id'] for s in stimuli}!={r['stimulus_id'] for r in trial.to_dict()['matched_stimuli']}:raise ListeningError('bundle stimulus provenance does not match trial')
        for row in trial.to_dict()['matched_stimuli']:
            if not self.audio.has_playback(row['playback_sha256']):raise ListeningError('bundle playback bytes are missing; silent regeneration is forbidden')
        metadata=self._stimulus_metadata(stimuli);results=[TrialResult(r,trial,stimulus_metadata=metadata) for r in bundle['results']];tid=trial.to_dict()['id'];public=self._register_trial(trial);self.results[tid]=results;return {'trial':public,'results':[r.to_dict() for r in results]}
    @property
    def templates(self):return deepcopy(INSTRUCTIONS)
