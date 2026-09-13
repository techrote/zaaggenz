"""Local immutable listening material and trial/result registry."""
from __future__ import annotations
from copy import deepcopy
from zaaggenz_jobs import RenderArtifact,JobError
from .model import TrialManifest,TrialResult,Stimulus,ListeningError
from .stimulus import ListeningAudioStore
from .trial import make_trial,make_result,public_trial,INSTRUCTIONS

class ListeningService:
    def __init__(self,timeline_service):
        self.timeline=timeline_service;self.audio=ListeningAudioStore();self.trials={};self.results={}
    def freeze_job(self,job_id,name,start_frame=0,end_frame=None):
        try:artifact=self.timeline.scheduler.result(job_id)
        except JobError as e:raise ListeningError(str(e)) from e
        if not isinstance(artifact,RenderArtifact):raise ListeningError('completed render job required')
        stimulus=self.audio.add_artifact(name,artifact,start_frame=start_frame,end_frame=end_frame)
        return stimulus.to_dict()
    def match(self,stimulus_ids,target_rms_dbfs=None,peak_ceiling_dbfs=-3.):return self.audio.match(stimulus_ids,target_rms_dbfs=target_rms_dbfs,peak_ceiling_dbfs=peak_ceiling_dbfs)
    def create_trial(self,title,design,matched_stimuli,seed='0',endpoints=('liking','sound_quality'),instruction_template=None):
        trial=make_trial(title,design,matched_stimuli,seed=seed,endpoints=endpoints,instruction_template=instruction_template);self.trials[trial.to_dict()['id']]=trial;return public_trial(trial)
    def manifest(self,trial_id):
        if trial_id not in self.trials:raise ListeningError('unknown trial')
        return self.trials[trial_id]
    def submit(self,trial_id,payload):
        trial=self.manifest(trial_id);result=make_result(trial,**payload);self.results.setdefault(trial_id,[]).append(result);return {'result':result.to_dict(),'result_sha256':result.sha256}
    def export_bundle(self,trial_id):
        trial=self.manifest(trial_id);td=trial.to_dict();stimuli=[self.audio.stimulus(row['stimulus_id']).to_dict() for row in td['matched_stimuli']]
        return {'format':'zaaggenz-listening-bundle','version':'1.0.0','stimuli':stimuli,'manifest':td,'results':[r.to_dict() for r in self.results.get(trial_id,[])]}
    def reopen_bundle(self,bundle):
        if type(bundle)is not dict or set(bundle)!={'format','version','stimuli','manifest','results'} or bundle['format']!='zaaggenz-listening-bundle' or bundle['version']!='1.0.0':raise ListeningError('invalid listening bundle')
        trial=TrialManifest(bundle['manifest']);stimuli=[Stimulus(s) for s in bundle['stimuli']]
        if {s.to_dict()['id'] for s in stimuli}!={r['stimulus_id'] for r in trial.to_dict()['matched_stimuli']}:raise ListeningError('bundle stimulus provenance does not match trial')
        for row in trial.to_dict()['matched_stimuli']:
            if not self.audio.has_playback(row['playback_sha256']):raise ListeningError('bundle playback bytes are missing; silent regeneration is forbidden')
        results=[TrialResult(r,trial) for r in bundle['results']];tid=trial.to_dict()['id'];self.trials[tid]=trial;self.results[tid]=results;return {'trial':public_trial(trial),'results':[r.to_dict() for r in results]}
    @property
    def templates(self):return deepcopy(INSTRUCTIONS)
