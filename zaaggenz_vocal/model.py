"""Versioned local-vocal analysis and correction state; raw capture audio is never embedded."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib, json, math, re
from zaaggenz_contracts import digest, validate
from zaaggenz_contracts.model import check_json, fraction, loads
from zaaggenz_contracts.music import beat_to_sample

VERSION='1.1.0'
LEGACY_VERSION='1.0.0'
SOURCE_IDENTITY_DOMAIN='zaaggenz-vocal-source-v1'
PCM_IDENTITY_DOMAIN='pcm-f32le-interleaved-v1'
_SHA=re.compile(r'[0-9a-f]{64}\Z')
_ID=re.compile(r'[a-z][a-z0-9_.-]{0,63}\Z')
_SOURCE_ID=re.compile(r'capture-v1-[0-9a-f]{64}\Z')

class VocalCaptureError(ValueError): pass

def exact(v,keys,name):
    if type(v)is not dict or set(v)!=set(keys):raise VocalCaptureError(f'{name}: missing or unknown fields')
def finite(v,lo,hi,name):
    if type(v) not in (int,float) or type(v)is bool or not math.isfinite(float(v)) or not lo<=float(v)<=hi:raise VocalCaptureError(f'{name}: finite {lo}..{hi} required')
    return float(v)
def integer(v,lo,hi,name):
    if type(v)is not int or not lo<=v<=hi:raise VocalCaptureError(f'{name}: integer {lo}..{hi} required')
    return v
def ident(v,name):
    if type(v)is not str or not _ID.fullmatch(v):raise VocalCaptureError(f'{name}: lowercase identifier required')
    return v

def source_identity_digest(content_sha256,sample_rate_hz,channels,frame_count):
    """Hash the complete interpretation metadata for canonical vocal PCM.

    Origin is deliberately excluded: local-import/local-recording/generated-fixture
    describes provenance, not how the PCM is interpreted.  The containing
    VocalAnalysis/VocalEdit digest still covers origin exactly.
    """
    if type(content_sha256)is not str or not _SHA.fullmatch(content_sha256):raise VocalCaptureError('source content hash required')
    integer(sample_rate_hz,8000,192000,'source.sample_rate_hz')
    integer(channels,1,2,'source.channels')
    integer(frame_count,1,192000*30,'source.frame_count')
    payload={'identity_domain':SOURCE_IDENTITY_DOMAIN,'pcm_domain':PCM_IDENTITY_DOMAIN,'content_sha256':content_sha256,
             'sample_rate_hz':sample_rate_hz,'channels':channels,'frame_count':frame_count}
    raw=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()

def make_source_identity(content_sha256,sample_rate_hz,channels,frame_count,origin):
    if origin not in ('local-recording','local-import','generated-fixture'):raise VocalCaptureError('unknown local source origin')
    sha=source_identity_digest(content_sha256,sample_rate_hz,channels,frame_count)
    return {'id':'capture-v1-'+sha,'content_sha256':content_sha256,'identity_domain':SOURCE_IDENTITY_DOMAIN,'pcm_domain':PCM_IDENTITY_DOMAIN,
            'sample_rate_hz':sample_rate_hz,'channels':channels,'frame_count':frame_count,'origin':origin}

def _source(v):
    exact(v,{'id','content_sha256','identity_domain','pcm_domain','sample_rate_hz','channels','frame_count','origin'},'source')
    if type(v['id'])is not str or not _SOURCE_ID.fullmatch(v['id']):raise VocalCaptureError('source.id must be a full capture-v1 SHA-256 identity')
    if v['identity_domain']!=SOURCE_IDENTITY_DOMAIN:raise VocalCaptureError('unsupported vocal source identity domain')
    if v['pcm_domain']!=PCM_IDENTITY_DOMAIN:raise VocalCaptureError('unsupported canonical PCM identity domain')
    if type(v['content_sha256'])is not str or not _SHA.fullmatch(v['content_sha256']):raise VocalCaptureError('source content hash required')
    integer(v['sample_rate_hz'],8000,192000,'source.sample_rate_hz');integer(v['channels'],1,2,'source.channels');integer(v['frame_count'],1,192000*30,'source.frame_count')
    if v['origin'] not in ('local-recording','local-import','generated-fixture'):raise VocalCaptureError('unknown local source origin')
    expected='capture-v1-'+source_identity_digest(v['content_sha256'],v['sample_rate_hz'],v['channels'],v['frame_count'])
    if v['id']!=expected:raise VocalCaptureError('source.id does not match canonical content/timing/channel identity')

def _segment(v,sr,frames,index):
    exact(v,{'id','start_sample','end_sample','onset_confidence','accent_db','rms_dbfs','voicing','pitch_hz','pitch_confidence','brightness_hz','brightness_confidence','spectral_flatness'},f'segment[{index}]')
    ident(v['id'],'segment.id');start=integer(v['start_sample'],0,frames-1,'segment.start_sample');end=integer(v['end_sample'],1,frames,'segment.end_sample')
    if start>=end:raise VocalCaptureError('segment start must precede end')
    finite(v['onset_confidence'],0,1,'onset_confidence');finite(v['accent_db'],-60,60,'accent_db');finite(v['rms_dbfs'],-180,24,'rms_dbfs')
    if v['voicing'] not in ('voiced','unvoiced','low-confidence'):raise VocalCaptureError('invalid voicing state')
    finite(v['pitch_confidence'],0,1,'pitch_confidence');finite(v['brightness_confidence'],0,1,'brightness_confidence');finite(v['spectral_flatness'],0,1,'spectral_flatness')
    if v['pitch_hz'] is not None:finite(v['pitch_hz'],30,min(1200,sr*.49),'pitch_hz')
    if v['brightness_hz'] is not None:finite(v['brightness_hz'],0,sr*.5,'brightness_hz')
    if v['voicing']!='voiced' and v['pitch_hz'] is not None:raise VocalCaptureError('unvoiced/low-confidence segment cannot carry a confident pitch estimate')

@dataclass(frozen=True,init=False)
class VocalAnalysis:
    _json:str
    def __init__(self,data):
        try:check_json(data)
        except (ValueError,TypeError) as exc:raise VocalCaptureError(str(exc)) from exc
        exact(data,{'format','version','source','method','segments','diagnostics'},'analysis')
        if data['format']!='zaaggenz-vocal-analysis':raise VocalCaptureError('unsupported vocal-analysis format')
        if data['version']==LEGACY_VERSION:raise VocalCaptureError('legacy vocal-analysis 1.0.0 uses truncated capture identity; reanalyse from retained source audio instead of reinterpreting it')
        if data['version']!=VERSION:raise VocalCaptureError('unsupported vocal-analysis format/version')
        _source(data['source']);method=data['method'];exact(method,{'id','version','frame_ms','hop_ms','pitch_min_hz','pitch_max_hz','voicing_threshold'},'method')
        if method['id']!='zg-vocal-contour-v1' or method['version']!='1.0.0':raise VocalCaptureError('unsupported vocal analysis method')
        finite(method['frame_ms'],10,100,'frame_ms');finite(method['hop_ms'],2,50,'hop_ms');finite(method['pitch_min_hz'],30,500,'pitch_min_hz');finite(method['pitch_max_hz'],80,1200,'pitch_max_hz');finite(method['voicing_threshold'],0,1,'voicing_threshold')
        if method['pitch_min_hz']>=method['pitch_max_hz']:raise VocalCaptureError('pitch range is empty')
        segs=data['segments']
        if type(segs)is not list or len(segs)>128:raise VocalCaptureError('segments must be a bounded list')
        ids=set();last=0
        for i,seg in enumerate(segs):
            _segment(seg,data['source']['sample_rate_hz'],data['source']['frame_count'],i)
            if seg['id'] in ids:raise VocalCaptureError('duplicate segment id')
            if i and seg['start_sample']<last:raise VocalCaptureError('segments must be ordered and non-overlapping')
            ids.add(seg['id']);last=seg['end_sample']
        diag=data['diagnostics'];exact(diag,{'active_threshold_dbfs','noise_floor_dbfs','peak_dbfs','frame_count','voiced_segments','unvoiced_segments','low_confidence_segments','shared_feature_method'},'diagnostics')
        for k in ('active_threshold_dbfs','noise_floor_dbfs','peak_dbfs'):finite(diag[k],-180,24,k)
        for k in ('frame_count','voiced_segments','unvoiced_segments','low_confidence_segments'):integer(diag[k],0,10_000,k)
        if diag['shared_feature_method']!='zg-multiresolution-features-v1':raise VocalCaptureError('shared feature method identity changed')
        object.__setattr__(self,'_json',json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False))
    def to_dict(self):return loads(self._json)
    @property
    def sha256(self):return digest(self.to_dict())
    @classmethod
    def from_json(cls,text):return cls(loads(text))

def _edit_segment(row,analysis_ids,sr):
    exact(row,{'segment_id','approved','aligned_beat','alignment_error_samples','manual_offset_samples','pitch_mode','manual_pitch_hz','manual_brightness_hz','token'},'edit segment')
    if row['segment_id'] not in analysis_ids:raise VocalCaptureError('edit references unknown analysis segment')
    if type(row['approved'])is not bool:raise VocalCaptureError('approved must be boolean')
    try:beat=fraction(row['aligned_beat'])
    except (ValueError,TypeError) as exc:raise VocalCaptureError(str(exc)) from exc
    if beat<0 or beat>256:raise VocalCaptureError('aligned beat outside supported timeline')
    integer(row['alignment_error_samples'],-2**53+1,2**53-1,'alignment_error_samples');integer(row['manual_offset_samples'],-sr,sr,'manual_offset_samples')
    if row['pitch_mode'] not in ('estimate','manual','unpitched'):raise VocalCaptureError('pitch_mode must be estimate/manual/unpitched')
    if row['manual_pitch_hz'] is not None:finite(row['manual_pitch_hz'],30,min(1200,sr*.49),'manual_pitch_hz')
    if row['pitch_mode']=='manual' and row['manual_pitch_hz'] is None:raise VocalCaptureError('manual pitch mode requires a pitch')
    if row['manual_brightness_hz'] is not None:finite(row['manual_brightness_hz'],0,sr*.5,'manual_brightness_hz')
    if type(row['token'])is not str or not re.fullmatch(r'[a-z][a-z0-9-]{0,31}',row['token']):raise VocalCaptureError('token must be a safe mnemonic token')

@dataclass(frozen=True,init=False)
class VocalEdit:
    _json:str
    def __init__(self,data):
        try:check_json(data)
        except (ValueError,TypeError) as exc:raise VocalCaptureError(str(exc)) from exc
        exact(data,{'format','version','analysis','dictionary_registry_sha256','dictionary_id','grid_beats','time_map','segments','source_disposition'},'edit')
        if data['format']!='zaaggenz-vocal-edit':raise VocalCaptureError('unsupported vocal-edit format')
        if data['version']==LEGACY_VERSION:raise VocalCaptureError('legacy vocal-edit 1.0.0 embeds truncated capture identity; reanalyse/recreate the edit from retained source audio')
        if data['version']!=VERSION:raise VocalCaptureError('unsupported vocal-edit format/version')
        analysis=VocalAnalysis(data['analysis']);sha=data['dictionary_registry_sha256']
        if type(sha)is not str or not _SHA.fullmatch(sha):raise VocalCaptureError('dictionary registry hash required')
        ident(data['dictionary_id'],'dictionary_id')
        try:grid=fraction(data['grid_beats'])
        except (ValueError,TypeError) as exc:raise VocalCaptureError(str(exc)) from exc
        if not 0<grid<=4:raise VocalCaptureError('grid must be in (0,4] quarter-note beats')
        validate(data['time_map'],'TimeMap')
        if data['time_map']['sample_rate_hz']!=analysis.to_dict()['source']['sample_rate_hz']:raise VocalCaptureError('capture and musical TimeMap sample rates must match')
        if data['source_disposition'] not in ('retained-session-local','discarded'):raise VocalCaptureError('unknown source disposition')
        rows=data['segments'];ids={s['id'] for s in analysis.to_dict()['segments']}
        if type(rows)is not list or len(rows)!=len(ids):raise VocalCaptureError('edit must contain exactly one row per analysis segment')
        seen=set();ad=analysis.to_dict();sr=ad['source']['sample_rate_hz'];segments={s['id']:s for s in ad['segments']}
        for row in rows:
            _edit_segment(row,ids,sr)
            if row['segment_id'] in seen:raise VocalCaptureError('duplicate edit segment')
            seen.add(row['segment_id'])
            expected=segments[row['segment_id']]['start_sample']-beat_to_sample(data['time_map'],row['aligned_beat'])
            if row['alignment_error_samples']!=expected:raise VocalCaptureError('alignment_error_samples does not match retained original timing')
        if seen!=ids:raise VocalCaptureError('edit does not cover every analysis segment')
        object.__setattr__(self,'_json',json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False))
    def to_dict(self):return loads(self._json)
    @property
    def sha256(self):return digest(self.to_dict())
    @classmethod
    def from_json(cls,text):return cls(loads(text))
