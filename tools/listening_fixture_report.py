"""Generate immutable 48 kHz listening stimuli, matching diagnostics and trial manifests."""
from __future__ import annotations
import argparse,hashlib,json,sys
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_listening import ListeningService,make_trial
from zaaggenz_timeline import TimelineDocument,default_document
from zaaggenz_timeline.service import TimelineService


def document(name,degree,gain,sr):
    d=default_document(sr).to_dict();d['name']=name;d['end_beat']='4/1';d['notes']=[
        {'id':'n-0','beat':'0/1','duration_beats':'1/1','degree':degree,'detune_cents':0.,'gain_db':gain,'muted':False,'roll_density':0},
        {'id':'n-1','beat':'2/1','duration_beats':'1/2','degree':degree+2,'detune_cents':0.,'gain_db':gain-3.,'muted':False,'roll_density':4}]
    d['clips']=[];d['next_id']=2;return TimelineDocument(d).to_dict()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--artifact-dir',type=Path,required=True);p.add_argument('--sample-rate',type=int,default=48000);a=p.parse_args();a.artifact_dir.mkdir(parents=True,exist_ok=True)
    timeline=TimelineService();service=ListeningService(timeline)
    try:
        configs=[('anchor',0,-18.),('upper',4,-12.),('contrast',7,-15.)];stimuli=[]
        for name,degree,gain in configs:
            doc=document(name,degree,gain,a.sample_rate);(a.artifact_dir/f'{name}.zgtimeline.json').write_text(json.dumps(doc,indent=2)+'\n')
            job=timeline.submit(doc,name=name);state=timeline.scheduler.wait(job['job_id'],30)
            if state.state!='completed':raise RuntimeError(state.error or state.state)
            stimuli.append(service.freeze_job(job['job_id'],name))
        ids=[s['id'] for s in stimuli];matched=service.match(ids,peak_ceiling_dbfs=-3.)
        rms=[r['matched_rms_dbfs'] for r in matched]
        if max(rms)-min(rms)>1e-4 or any(r['sample_peak_headroom_db']<2.999 for r in matched):raise RuntimeError('level matching invariant failed')
        # Trial manifests consume the strict immutable matching contract. Human-facing
        # file names/hashes are report evidence and must not be injected into those rows.
        ab=make_trial('A/B fixture','ab',matched[:2],seed='101',endpoints=('liking','sound_quality'))
        abx=make_trial('ABX fixture','abx',matched[:2],seed='102',endpoints=('source_identity',))
        multi=make_trial('Multi fixture','multi',matched,seed='103',endpoints=('groove','liking'))
        if make_trial('A/B fixture','ab',matched[:2],seed='101',endpoints=('liking','sound_quality')).to_dict()!=ab.to_dict():raise RuntimeError('trial randomisation is not reproducible')
        files=[]
        for row in matched:
            wav=service.audio.wav(row['playback_sha256']);name=next(s['name'] for s in stimuli if s['id']==row['stimulus_id']);path=a.artifact_dir/(name+'-matched.wav');path.write_bytes(wav)
            files.append({'stimulus_id':row['stimulus_id'],'playback_sha256':row['playback_sha256'],'wav_file':path.name,'wav_sha256':hashlib.sha256(wav).hexdigest()})
        report={'method':'zg015-listening-fixture-v1','sample_rate_hz':a.sample_rate,'stimuli':stimuli,'matching':deepcopy(matched),'playback_files':files,
                'trials':{'ab':ab.to_dict(),'abx':abx.to_dict(),'multi':multi.to_dict()},
                'claims':{'participant_data':False,'preference_claimed':False,'perceptual_loudness_match_claimed':False,'true_peak_measured':False,'silent_regeneration_allowed':False},
                'note':'Generated source-derived engineering fixtures; no participant ratings or owner listening approval.'}
        a.out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps({'checks':'passed','stimuli':len(stimuli),'trials':3,'sample_rate_hz':a.sample_rate}))
    finally:timeline.close()
if __name__=='__main__':main()
