from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import hashlib,json,math,re
import numpy as np

METHOD_ID='zg.harmonic_comb_inspector.v1'
METHOD_VERSION='1.0.0'
HEX64=re.compile(r'^[0-9a-f]{64}$')
SLOTS=('A','B')

class InspectorError(ValueError):pass

def _finite(v,name):
    if type(v) not in (int,float) or type(v)is bool or not math.isfinite(float(v)):raise InspectorError(f'{name} must be finite')
    return float(v)

def canonical_sha256(value):
    try:data=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
    except (TypeError,ValueError) as exc:raise InspectorError('snapshot must be JSON serialisable') from exc
    return hashlib.sha256(data).hexdigest()

def pcm_sha256(audio):
    a=np.asarray(audio,dtype='<f4');return hashlib.sha256(a.tobytes()).hexdigest()

def _rms(audio):
    a=np.asarray(audio,dtype=np.float64);return float(np.sqrt(np.mean(a*a))) if len(a) else 0.

@dataclass(frozen=True)
class SlotIdentity:
    slot:str
    revision_id:str
    audio_sha256:str
    sample_rate_hz:int
    frame_count:int
    label:str
    rms:float
    peak:float
    def __post_init__(self):
        if self.slot not in SLOTS:raise InspectorError('slot must be A or B')
        if type(self.revision_id)is not str or not HEX64.fullmatch(self.revision_id):raise InspectorError('revision_id must be sha256')
        if type(self.audio_sha256)is not str or not HEX64.fullmatch(self.audio_sha256):raise InspectorError('audio_sha256 must be sha256')
        if type(self.sample_rate_hz)is not int or not 8000<=self.sample_rate_hz<=192000:raise InspectorError('sample rate out of range')
        if type(self.frame_count)is not int or self.frame_count<1:raise InspectorError('frame_count must be positive')
        if type(self.label)is not str or not self.label or len(self.label)>120:raise InspectorError('invalid slot label')
        object.__setattr__(self,'rms',_finite(self.rms,'rms'));object.__setattr__(self,'peak',_finite(self.peak,'peak'))
    def to_dict(self):return {'slot':self.slot,'revision_id':self.revision_id,'audio_sha256':self.audio_sha256,'sample_rate_hz':self.sample_rate_hz,'frame_count':self.frame_count,'label':self.label,'rms':self.rms,'peak':self.peak}


def slot_identity(slot,audio,sample_rate_hz,label,*,revision_seed=None):
    a=np.asarray(audio,dtype=np.float32)
    if a.ndim!=1 or len(a)<1 or not np.isfinite(a).all():raise InspectorError('finite mono audio required')
    audio_hash=pcm_sha256(a);seed={'domain':'zg.inspector.slot.v1','slot':slot,'audio_sha256':audio_hash,'sample_rate_hz':sample_rate_hz,'label':label,'revision_seed':revision_seed}
    return SlotIdentity(slot,canonical_sha256(seed),audio_hash,int(sample_rate_hz),len(a),label,_rms(a),float(np.max(np.abs(a),initial=0.)))

@dataclass(frozen=True)
class InspectorSnapshot:
    before:SlotIdentity
    after:SlotIdentity
    method:dict
    controls:dict
    stage_order:tuple[str,...]
    target_combs:tuple[dict,...]
    components:tuple[dict,...]
    remainder:tuple[dict,...]
    compatibility:tuple[dict,...]
    uncertainty:dict
    diagnostics:dict
    expert:dict
    version:str=METHOD_VERSION
    def __post_init__(self):
        if not isinstance(self.before,SlotIdentity) or not isinstance(self.after,SlotIdentity):raise InspectorError('two slot identities required')
        if self.before.slot!='A' or self.after.slot!='B':raise InspectorError('snapshot slots must be A then B')
        if self.before.sample_rate_hz!=self.after.sample_rate_hz:raise InspectorError('slot sample rates must match')
        order=tuple(self.stage_order)
        if not order or any(type(x)is not str or not x for x in order):raise InspectorError('stage order required')
        object.__setattr__(self,'stage_order',order)
        for name in ('method','controls','uncertainty','diagnostics','expert'):
            value=deepcopy(getattr(self,name));json.dumps(value,allow_nan=False);object.__setattr__(self,name,value)
        for name in ('target_combs','components','remainder','compatibility'):
            value=tuple(deepcopy(getattr(self,name)));json.dumps(value,allow_nan=False);object.__setattr__(self,name,value)
    def core_dict(self):
        return {'kind':'HarmonicCombInspectorSnapshot','version':self.version,'method':deepcopy(self.method),'before':self.before.to_dict(),'after':self.after.to_dict(),
                'controls':deepcopy(self.controls),'stage_order':list(self.stage_order),'target_combs':deepcopy(list(self.target_combs)),
                'components':deepcopy(list(self.components)),'remainder':deepcopy(list(self.remainder)),'compatibility':deepcopy(list(self.compatibility)),
                'uncertainty':deepcopy(self.uncertainty),'diagnostics':deepcopy(self.diagnostics),'expert':deepcopy(self.expert)}
    @property
    def snapshot_id(self):return canonical_sha256(self.core_dict())
    def to_dict(self):return {**self.core_dict(),'snapshot_id':self.snapshot_id}


def remainder_timeline(audio,sample_rate_hz,*,bins=80):
    a=np.asarray(audio,dtype=np.float64)
    if a.ndim!=1 or not np.isfinite(a).all():raise InspectorError('finite mono remainder required')
    count=max(1,min(int(bins),len(a)));edges=np.linspace(0,len(a),count+1,dtype=int);rows=[]
    for i in range(count):
        chunk=a[edges[i]:edges[i+1]];rms=_rms(chunk);rows.append({'anchor_sample':int((edges[i]+edges[i+1])//2),'time_seconds':float((edges[i]+edges[i+1])*.5/sample_rate_hz),
                                                               'rms':rms,'rms_dbfs':float(20*math.log10(max(rms,1e-12)))})
    return tuple(rows)


def compatibility_rows(curve):
    try:points=curve.points
    except Exception as exc:raise InspectorError('DissonanceCurve-like value required') from exc
    return tuple({'interval_cents':float(p.interval_cents),'value':None if p.value is None else float(p.value),'confidence':float(p.confidence),'validity':str(p.validity)} for p in points)


def _classify(decision,confidence,threshold,changed):
    if confidence<threshold or decision in ('uncertain','abstain'):return 'uncertain'
    return 'moved' if changed else 'unaffected'


def snapshot_from_chordness(result,before_audio,after_audio,sample_rate_hz,*,controls,compatibility=(),revision_seed=None):
    try:request=result.request;frames=result.decisions;residual=result.residual;inspection=result.inspection
    except Exception as exc:raise InspectorError('ChordnessResult-like value required') from exc
    before=slot_identity('A',before_audio,sample_rate_hz,'Before · source',revision_seed=revision_seed)
    after=slot_identity('B',after_audio,sample_rate_hz,'After · explicit transform',revision_seed={'source_revision':before.revision_id,'request':request.to_dict()})
    templates=[]
    selected=set(result.selected_template_ids)
    for template in request.templates:
        templates.append({'id':template.id,'label':template.label or template.id,'teeth_hz':list(template.teeth_hz),'tooth_capacity':template.tooth_capacity,'selected':template.id in selected,'source':deepcopy(template.source)})
    components=[];reasons={};classes={'moved':0,'unaffected':0,'uncertain':0}
    for row in frames:
        changed=abs(float(row.correction_cents))>1e-9 or abs(float(row.gain_db))>1e-9
        cls=_classify(row.decision,float(row.confidence),float(request.min_confidence),changed);classes[cls]+=1;reasons[row.reason]=reasons.get(row.reason,0)+1
        components.append({'track_id':row.track_id,'frame_index':row.frame_index,'anchor_sample':row.anchor_sample,'time_seconds':row.anchor_sample/sample_rate_hz,
                           'estimated_hz':float(row.source_hz),'requested_hz':None if row.target_hz is None else float(row.target_hz),'realised_hz':float(row.realised_hz),
                           'source_amplitude':float(row.source_amplitude),'realised_amplitude':float(row.realised_amplitude),'correction_cents':float(row.correction_cents),
                           'gain_db':float(row.gain_db),'confidence':float(row.confidence),'assignment_confidence':None if row.assignment_confidence is None else float(row.assignment_confidence),
                           'template_id':row.template_id,'tooth_index':row.tooth_index,'assignment_distance_cents':row.assignment_distance_cents,
                           'decision':row.decision,'reason':row.reason,'classification':cls})
    uncertainty={'confidence_threshold':float(request.min_confidence),'counts':classes,'reasons':reasons,
                 'policy':'confidence masking is visual disclosure only; uncertain components are never relabelled as certain'}
    method={'id':METHOD_ID,'version':METHOD_VERSION,'transform':inspection['method']}
    diagnostics={'source_frame_count':len(components),'selected_template_ids':list(result.selected_template_ids),'identity_path':bool(result.diagnostics.get('identity_path',False)),
                 'transient_unchanged':bool(result.diagnostics.get('transient_unchanged',False)),'residual_unchanged':bool(result.diagnostics.get('residual_unchanged',False)),
                 'requested_estimated_realised_labels_distinct':True,'normalization':'none'}
    expert={'request':request.to_dict(),'descriptor_before':deepcopy(result.descriptor_before),'descriptor_after':deepcopy(result.descriptor_after),
            'objective_before':deepcopy(result.objective_before),'objective_after':deepcopy(result.objective_after),'candidate_evaluations':deepcopy(list(result.candidate_evaluations)),
            'occupancy':deepcopy(list(result.occupancy)),'interpretation':'inspection metadata is descriptive; analysis never implies preference or auto-application'}
    return InspectorSnapshot(before,after,method,deepcopy(controls),('component-analysis','multi-comb-chordness:'+request.mode),tuple(templates),tuple(components),
                             remainder_timeline(residual,sample_rate_hz),tuple(compatibility),uncertainty,diagnostics,expert)
