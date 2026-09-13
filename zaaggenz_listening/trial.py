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

def make_trial(title,design,matched_stimuli,*,seed='0',endpoints=('liking','sound_quality'),instruction_template=None,comfortable_level_prompt=True,rest_prompt_seconds=30):
    if design not in ('ab','abx','multi'):raise ListeningError('invalid design')
    try:seed_value(seed)
    except ValueError as e:raise ListeningError(str(e)) from e
    if instruction_template is None:instruction_template={'ab':'neutral-ab','abx':'neutral-abx','multi':'neutral-multi'}[design]
    if instruction_template not in INSTRUCTIONS:raise ListeningError('unknown neutral instruction template')
    rows=deepcopy(matched_stimuli);sids=[r['stimulus_id'] for r in rows];order=_shuffle(sids,seed,'order')
    truth=None
    if design=='abx':truth=('A','B')[_draw(seed,'abx.truth',2)]
    payload={'format':'zaaggenz-listening-trial','version':VERSION,'title':title,'design':design,'seed':seed,'instruction_template':instruction_template,'instructions':INSTRUCTIONS[instruction_template],'matched_stimuli':rows,'presentation_order':order,'abx_truth':truth,'endpoints':list(endpoints),'comfortable_level_prompt':bool(comfortable_level_prompt),'rest_prompt_seconds':rest_prompt_seconds}
    payload['id']=digest({'domain':'zaaggenz.listening-trial-v1','manifest':payload})
    return TrialManifest(payload)

def public_trial(manifest):
    if not isinstance(manifest,TrialManifest):raise ListeningError('TrialManifest required')
    d=manifest.to_dict();truth=d.pop('abx_truth');d['abx_truth']=None if d['design']=='abx' else truth
    d['labels']={sid:chr(ord('A')+i) for i,sid in enumerate(d['presentation_order'])}
    return d

def make_result(manifest,*,status='completed',choice=None,ratings=None,confidence=None,effort=None,comfortable_level=None,replay_counts=None,x_replay_count=0,annotations=None,note=''):
    if not isinstance(manifest,TrialManifest):raise ListeningError('TrialManifest required')
    m=manifest.to_dict();counts={sid:0 for sid in m['presentation_order']} if replay_counts is None else replay_counts
    correct=(choice==m['abx_truth']) if status=='completed' and m['design']=='abx' else None
    doc={'format':'zaaggenz-listening-result','version':VERSION,'trial_id':m['id'],'status':status,'presentation_order':m['presentation_order'],'choice':choice,'abx_correct':correct,'ratings':{} if ratings is None else ratings,'confidence':confidence,'effort':effort,'comfortable_level':comfortable_level,'replay_counts':counts,'x_replay_count':x_replay_count,'annotations':[] if annotations is None else annotations,'note':note}
    return TrialResult(doc,manifest)
