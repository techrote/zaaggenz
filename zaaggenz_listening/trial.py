"""Deterministic randomised A/B, ABX and multi-example trials with separate endpoints."""
from __future__ import annotations
import hashlib,json
from copy import deepcopy
from zaaggenz_contracts import digest
from zaaggenz_contracts.model import seed_value
from .model import TrialManifest,TrialResult,ListeningError,VERSION,ENDPOINTS

INSTRUCTIONS={
 'neutral-ab':'Compare A and B at a comfortable level. Replay as needed. Rate only the requested endpoints; stop or rest if you become tired.',
 'neutral-abx':'Listen to A and B, then decide whether X is A or B. Accuracy is recorded separately from ratings, confidence and effort.',
 'neutral-multi':'Compare the examples in the presented order. Replay as needed and rate only the requested endpoints. There is no assumed preferred answer.'}

def _draw(seed,label,n):
    if n<1:raise ListeningError('empty choice')
    counter=0;limit=2**64-(2**64%n)
    while True:
        value=int.from_bytes(hashlib.sha256(f'zaaggenz.listening-choice-v1\0{seed}\0{label}\0{counter}'.encode()).digest()[:8],'big')
        if value<limit:return value%n
        counter+=1

def _shuffle(values,seed,label):
    out=list(values)
    for i in range(len(out)-1,0,-1):
        j=_draw(seed,f'{label}.{i}',i+1);out[i],out[j]=out[j],out[i]
    return out

def _make_trial(title,design,matched_stimuli,*,seed='0',endpoints=('liking','sound_quality'),instruction_template=None,comfortable_level_prompt=True,rest_prompt_seconds=30,hidden_abx_truth=None):
    if design not in ('ab','abx','multi'):raise ListeningError('invalid design')
    try:seed_value(seed)
    except ValueError as e:raise ListeningError(str(e)) from e
    if instruction_template is None:instruction_template={'ab':'neutral-ab','abx':'neutral-abx','multi':'neutral-multi'}[design]
    if instruction_template not in INSTRUCTIONS:raise ListeningError('unknown neutral instruction template')
    rows=deepcopy(matched_stimuli);sids=[r['stimulus_id'] for r in rows];order=_shuffle(sids,seed,'order')
    truth=None
    if design=='abx':
        truth=('A','B')[_draw(seed,'abx.truth',2)] if hidden_abx_truth is None else hidden_abx_truth
        if truth not in ('A','B'):raise ListeningError('hidden ABX truth must be A or B')
    elif hidden_abx_truth is not None:raise ListeningError('hidden ABX truth belongs only to ABX')
    payload={'format':'zaaggenz-listening-trial','version':VERSION,'title':title,'design':design,'seed':seed,'instruction_template':instruction_template,'instructions':INSTRUCTIONS[instruction_template],'matched_stimuli':rows,'presentation_order':order,'abx_truth':truth,'endpoints':list(endpoints),'comfortable_level_prompt':bool(comfortable_level_prompt),'rest_prompt_seconds':rest_prompt_seconds}
    payload['id']=digest({'domain':'zaaggenz.listening-trial-v1','manifest':payload})
    return TrialManifest(payload)

def make_trial(title,design,matched_stimuli,*,seed='0',endpoints=('liking','sound_quality'),instruction_template=None,comfortable_level_prompt=True,rest_prompt_seconds=30):
    """Trusted/offline deterministic constructor retained for evidence reproduction."""
    return _make_trial(title,design,matched_stimuli,seed=seed,endpoints=endpoints,instruction_template=instruction_template,comfortable_level_prompt=comfortable_level_prompt,rest_prompt_seconds=rest_prompt_seconds)

def make_participant_trial(title,design,matched_stimuli,*,seed='0',endpoints=('liking','sound_quality'),instruction_template=None,comfortable_level_prompt=True,rest_prompt_seconds=30,hidden_abx_truth=None):
    """Construct an HTTP participant trial whose ABX truth is not derived from participant-visible state."""
    if design=='abx' and hidden_abx_truth not in ('A','B'):raise ListeningError('server-held ABX truth required')
    return _make_trial(title,design,matched_stimuli,seed=seed,endpoints=endpoints,instruction_template=instruction_template,comfortable_level_prompt=comfortable_level_prompt,rest_prompt_seconds=rest_prompt_seconds,hidden_abx_truth=hidden_abx_truth)

def public_trial(manifest,participant_id=None):
    """Participant-safe projection: no seed, trusted manifest ID or ABX truth."""
    if not isinstance(manifest,TrialManifest):raise ListeningError('TrialManifest required')
    d=manifest.to_dict()
    p={'format':'zaaggenz-listening-participant-trial','version':'1.0.0','title':d['title'],'design':d['design'],
       'instruction_template':d['instruction_template'],'instructions':d['instructions'],'matched_stimuli':d['matched_stimuli'],
       'presentation_order':d['presentation_order'],'abx_truth':None,'endpoints':d['endpoints'],
       'comfortable_level_prompt':d['comfortable_level_prompt'],'rest_prompt_seconds':d['rest_prompt_seconds']}
    if participant_id is None:participant_id=digest({'domain':'zaaggenz.listening-participant-view-v1','trial':p})
    if type(participant_id)is not str or len(participant_id)!=64 or any(c not in '0123456789abcdef' for c in participant_id):raise ListeningError('participant trial ID must be lowercase SHA-256')
    p['id']=participant_id
    p['labels']={sid:chr(ord('A')+i) for i,sid in enumerate(d['presentation_order'])}
    return p

def public_result(result,participant_id):
    """Participant receipt preserves the response but withholds scoring and trusted identity."""
    if not isinstance(result,TrialResult):raise ListeningError('TrialResult required')
    d=result.to_dict();d['trial_id']=participant_id;d['abx_correct']=None
    return d

def make_result(manifest,*,status='completed',choice=None,ratings=None,confidence=None,effort=None,comfortable_level=None,replay_counts=None,x_replay_count=0,annotations=None,note=''):
    if not isinstance(manifest,TrialManifest):raise ListeningError('TrialManifest required')
    m=manifest.to_dict();counts={sid:0 for sid in m['presentation_order']} if replay_counts is None else replay_counts
    correct=(choice==m['abx_truth']) if status=='completed' and m['design']=='abx' else None
    doc={'format':'zaaggenz-listening-result','version':VERSION,'trial_id':m['id'],'status':status,'presentation_order':m['presentation_order'],'choice':choice,'abx_correct':correct,'ratings':{} if ratings is None else ratings,'confidence':confidence,'effort':effort,'comfortable_level':comfortable_level,'replay_counts':counts,'x_replay_count':x_replay_count,'annotations':[] if annotations is None else annotations,'note':note}
    return TrialResult(doc,manifest)
