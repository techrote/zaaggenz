"""Versioned immutable listening stimuli, trial manifests and response records."""
from __future__ import annotations
from dataclasses import dataclass
import json, math, re
from zaaggenz_contracts import digest
from zaaggenz_contracts.model import check_json, loads, seed_value

VERSION='1.0.0'
HEX64=re.compile(r'[0-9a-f]{64}\Z')
ID=re.compile(r'[a-z][a-z0-9_.-]{0,63}\Z')
DESIGNS=('ab','abx','multi')
ENDPOINTS=('liking','sound_quality','groove','source_identity','sonority_fit','harshness','excitement','tension','urge_to_move','recognition','difficulty')
STATUS=('completed','aborted','missing')

class ListeningError(ValueError): pass

def exact(v,keys,name):
    if type(v)is not dict or set(v)!=set(keys):raise ListeningError(f'{name}: missing or unknown fields')
def text(v,name,maxlen=512):
    if type(v)is not str or not v.strip() or len(v)>maxlen or any(ord(c)<32 and c not in '\n\t' for c in v):raise ListeningError(f'{name}: nonempty bounded text required')
    return v
def identifier(v,name):
    if type(v)is not str or not ID.fullmatch(v):raise ListeningError(f'{name}: lowercase identifier required')
    return v
def sha(v,name):
    if type(v)is not str or not HEX64.fullmatch(v):raise ListeningError(f'{name}: lowercase SHA-256 required')
    return v
def integer(v,lo,hi,name):
    if type(v)is not int or not lo<=v<=hi:raise ListeningError(f'{name}: integer {lo}..{hi} required')
    return v
def finite(v,lo,hi,name):
    if type(v) not in (int,float) or type(v)is bool or not math.isfinite(float(v)) or not lo<=float(v)<=hi:raise ListeningError(f'{name}: finite {lo}..{hi} required')
    return float(v)

def validate_stimulus(d):
    exact(d,{'format','version','id','name','revision_id','recipe_sha256','product','cache_key','source_asset','excerpt','raw_pcm_sha256','sample_rate_hz','channels','frame_count','alignment'},'stimulus')
    if d['format']!='zaaggenz-listening-stimulus' or d['version']!=VERSION:raise ListeningError('unsupported listening stimulus format/version')
    sha(d['id'],'stimulus.id');text(d['name'],'stimulus.name',80)
    for k in ('revision_id','recipe_sha256','cache_key','raw_pcm_sha256'):sha(d[k],k)
    if d['product'] not in ('synth','arrange','arrange_bass','bass'):raise ListeningError('unsupported source product')
    a=d['source_asset'];exact(a,{'content_sha256','identity_domain','sample_rate_hz','channels','frame_count'},'source_asset');sha(a['content_sha256'],'source_asset.content_sha256')
    if a['identity_domain']!='pcm-f32le-interleaved-v1':raise ListeningError('listening materializer requires float32 PCM source')
    integer(d['sample_rate_hz'],8000,384000,'sample_rate_hz');integer(d['channels'],1,8,'channels');integer(d['frame_count'],1,384000*600,'frame_count')
    if (a['sample_rate_hz'],a['channels'])!=(d['sample_rate_hz'],d['channels']):raise ListeningError('source/excerpt channel or sample-rate mismatch')
    e=d['excerpt'];exact(e,{'start_frame','end_frame'},'excerpt');start=integer(e['start_frame'],0,a['frame_count']-1,'start_frame');end=integer(e['end_frame'],1,a['frame_count'],'end_frame')
    if start>=end or end-start!=d['frame_count']:raise ListeningError('excerpt bounds/frame count mismatch')
    if type(d['alignment']) is not dict:raise ListeningError('alignment metadata must be an object')

def validate_matched(row):
    exact(row,{'stimulus_id','playback_sha256','gain_db','source_rms_dbfs','source_sample_peak','target_rms_dbfs','matched_rms_dbfs','matched_sample_peak','sample_peak_headroom_db','method','true_peak_measured'},'matched stimulus')
    sha(row['stimulus_id'],'stimulus_id');sha(row['playback_sha256'],'playback_sha256')
    for k in ('gain_db','source_rms_dbfs','source_sample_peak','target_rms_dbfs','matched_rms_dbfs','matched_sample_peak','sample_peak_headroom_db'):finite(row[k],-240 if 'db' in k else 0,240 if 'db' in k else 4,k)
    if row['method']!='whole-file-rms-common-target-v1':raise ListeningError('unsupported matching method')
    if type(row['true_peak_measured']) is not bool or row['true_peak_measured']:raise ListeningError('this matcher declares sample peak, not true peak')

@dataclass(frozen=True,init=False)
class Stimulus:
    _json:str
    def __init__(self,d):
        try:check_json(d)
        except (ValueError,TypeError) as e:raise ListeningError(str(e)) from e
        validate_stimulus(d);object.__setattr__(self,'_json',json.dumps(d,sort_keys=True,separators=(',',':'),allow_nan=False))
    def to_dict(self):return loads(self._json)
    @property
    def sha256(self):return digest(self.to_dict())

@dataclass(frozen=True,init=False)
class TrialManifest:
    _json:str
    def __init__(self,d):
        try:check_json(d)
        except (ValueError,TypeError) as e:raise ListeningError(str(e)) from e
        exact(d,{'format','version','id','title','design','seed','instruction_template','instructions','matched_stimuli','presentation_order','abx_truth','endpoints','comfortable_level_prompt','rest_prompt_seconds'},'trial manifest')
        if d['format']!='zaaggenz-listening-trial' or d['version']!=VERSION:raise ListeningError('unsupported trial manifest format/version')
        sha(d['id'],'trial.id');text(d['title'],'title',100)
        if d['design'] not in DESIGNS:raise ListeningError('invalid trial design')
        try:seed_value(d['seed'])
        except ValueError as e:raise ListeningError(str(e)) from e
        identifier(d['instruction_template'],'instruction_template');text(d['instructions'],'instructions',2048)
        rows=d['matched_stimuli']
        if type(rows)is not list or not 2<=len(rows)<=8:raise ListeningError('2..8 matched stimuli required')
        for r in rows:validate_matched(r)
        sids=[r['stimulus_id'] for r in rows]
        if len(set(sids))!=len(sids):raise ListeningError('duplicate stimulus in trial')
        order=d['presentation_order']
        if type(order)is not list or sorted(order)!=sorted(sids):raise ListeningError('presentation_order must be an exact permutation of stimulus IDs')
        if d['design'] in ('ab','abx') and len(rows)!=2:raise ListeningError('A/B and ABX require exactly two stimuli')
        truth=d['abx_truth']
        if d['design']=='abx':
            if truth not in ('A','B'):raise ListeningError('ABX truth must be A or B')
        elif truth is not None:raise ListeningError('ABX truth belongs only to ABX trials')
        eps=d['endpoints']
        if type(eps)is not list or not eps or len(set(eps))!=len(eps) or any(e not in ENDPOINTS for e in eps):raise ListeningError('invalid rating endpoints')
        if type(d['comfortable_level_prompt'])is not bool:raise ListeningError('comfortable_level_prompt must be boolean')
        integer(d['rest_prompt_seconds'],0,3600,'rest_prompt_seconds')
        payload={k:v for k,v in d.items() if k!='id'}
        expected=digest({'domain':'zaaggenz.listening-trial-v1','manifest':payload})
        if d['id']!=expected:raise ListeningError('trial id does not match manifest')
        object.__setattr__(self,'_json',json.dumps(d,sort_keys=True,separators=(',',':'),allow_nan=False))
    def to_dict(self):return loads(self._json)
    @property
    def sha256(self):return digest(self.to_dict())
    @classmethod
    def from_json(cls,text):return cls(loads(text))

@dataclass(frozen=True,init=False)
class TrialResult:
    _json:str
    def __init__(self,d,manifest=None):
        try:check_json(d)
        except (ValueError,TypeError) as e:raise ListeningError(str(e)) from e
        exact(d,{'format','version','trial_id','status','presentation_order','choice','abx_correct','ratings','confidence','effort','comfortable_level','replay_counts','x_replay_count','annotations','note'},'trial result')
        if d['format']!='zaaggenz-listening-result' or d['version']!=VERSION:raise ListeningError('unsupported result format/version')
        sha(d['trial_id'],'trial_id')
        if d['status'] not in STATUS:raise ListeningError('invalid result status')
        if type(d['presentation_order'])is not list or not all(type(x)is str for x in d['presentation_order']):raise ListeningError('presentation_order required')
        if d['choice'] is not None and type(d['choice'])is not str:raise ListeningError('choice must be string/null')
        if d['abx_correct'] is not None and type(d['abx_correct'])is not bool:raise ListeningError('abx_correct must be boolean/null')
        ratings=d['ratings']
        if type(ratings)is not dict or any(k not in ENDPOINTS for k in ratings):raise ListeningError('unknown rating endpoint')
        for v in ratings.values():finite(v,0,100,'rating')
        for k in ('confidence','effort','comfortable_level'):
            if d[k] is not None:finite(d[k],0,100,k)
        counts=d['replay_counts']
        if type(counts)is not dict or any(type(k)is not str for k in counts):raise ListeningError('replay_counts must be object')
        for v in counts.values():integer(v,0,10000,'replay count')
        integer(d['x_replay_count'],0,10000,'x_replay_count')
        ann=d['annotations']
        if type(ann)is not list or len(ann)>256:raise ListeningError('too many annotations')
        for a in ann:
            exact(a,{'stimulus_id','time_seconds','label','note'},'annotation');sha(a['stimulus_id'],'annotation stimulus');finite(a['time_seconds'],0,3600,'annotation time');text(a['label'],'annotation label',64)
            if type(a['note'])is not str or len(a['note'])>1000:raise ListeningError('annotation note too long')
        if type(d['note'])is not str or len(d['note'])>4000:raise ListeningError('result note too long')
        if manifest is not None:
            if not isinstance(manifest,TrialManifest):raise ListeningError('TrialManifest required')
            m=manifest.to_dict()
            if d['trial_id']!=m['id'] or d['presentation_order']!=m['presentation_order']:raise ListeningError('result trial/order mismatch')
            expected=set(m['presentation_order'])
            if set(counts)!=expected:raise ListeningError('replay counts must cover every presented stimulus')
            if set(ratings)-set(m['endpoints']):raise ListeningError('result rates undeclared endpoint')
            if m['design']!='abx' and d['x_replay_count']!=0:raise ListeningError('X replay count belongs only to ABX')
            if d['status']=='completed':
                if m['design']=='abx':
                    if d['choice'] not in ('A','B'):raise ListeningError('completed ABX requires A/B choice')
                    if d['abx_correct']!=(d['choice']==m['abx_truth']):raise ListeningError('ABX accuracy field is inconsistent')
                elif d['abx_correct'] is not None:raise ListeningError('ABX accuracy must stay separate/null outside ABX')
            elif d['abx_correct'] is not None:raise ListeningError('aborted/missing trial cannot claim ABX accuracy')
        object.__setattr__(self,'_json',json.dumps(d,sort_keys=True,separators=(',',':'),allow_nan=False))
    def to_dict(self):return loads(self._json)
    @property
    def sha256(self):return digest(self.to_dict())
