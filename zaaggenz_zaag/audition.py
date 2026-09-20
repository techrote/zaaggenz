from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import hashlib,math
import numpy as np
from .model import ZaagFamilyError,canonical_sha256
from .registry import FAMILIES,LOCKED_BLOOM,family
from .render import render_family_source

ENDPOINTS=('bounce','melodic_identity','source_character','usefulness')

@dataclass(frozen=True)
class AuditionItem:
    id:str
    family_id:str
    classification:str
    gain_db:float
    achieved_rms_dbfs:float
    peak:float
    pcm_sha256:str
    def to_dict(self):return deepcopy(self.__dict__)

@dataclass(frozen=True)
class AuditionPack:
    sample_rate_hz:int
    target_rms_dbfs:float
    audio:dict[str,np.ndarray]
    items:tuple[AuditionItem,...]
    manifest:dict
    def __post_init__(self):
        frozen={}
        for k,v in self.audio.items():
            a=np.asarray(v,dtype=np.float32);a.setflags(write=False);frozen[k]=a
        object.__setattr__(self,'audio',frozen);object.__setattr__(self,'items',tuple(self.items));object.__setattr__(self,'manifest',deepcopy(self.manifest))

def _rms(a):return float(np.sqrt(np.mean(np.asarray(a,dtype=np.float64)**2))) if len(a) else 0.
def _db(v):return 20*math.log10(max(float(v),1e-15))
def _match(audio,target_dbfs,peak_limit=.98):
    x=np.asarray(audio,dtype=np.float64);current=_db(_rms(x));desired=float(target_dbfs)-current;scale=10**(desired/20.);peak=float(np.max(np.abs(x),initial=0.))*scale
    if peak>peak_limit and peak>0:scale*=peak_limit/peak
    y=x*scale;return np.asarray(y,dtype=np.float32),20*math.log10(max(scale,1e-15))
def deterministic_order(ids,seed='zg022-owner-audition-v1'):
    return tuple(sorted(ids,key=lambda x:hashlib.sha256((seed+'\0'+x).encode()).hexdigest()))

def build_owner_audition_pack(sample_rate_hz=48000,target_rms_dbfs=-14.):
    if sample_rate_hz not in (12000,48000):raise ZaagFamilyError('audition sample rate must be 12k or 48k')
    if not -30<=target_rms_dbfs<=-6:raise ZaagFamilyError('audition target outside safe engineering range')
    audio={};items=[]
    for recipe in FAMILIES:
        raw=render_family_source(recipe,sample_rate_hz,beats=1).audio;matched,gain=_match(raw,target_rms_dbfs);key=recipe.id;audio[key]=matched
        items.append(AuditionItem(key,recipe.id,recipe.classification,gain,_db(_rms(matched)),float(np.max(np.abs(matched),initial=0.)),hashlib.sha256(matched.astype('<f4').tobytes()).hexdigest()))
    order=deterministic_order(tuple(audio))
    manifest={'kind':'ZaagOwnerAuditionPack','version':'1.1.0','status':'pending-owner','audition_revision':'zg022-brutal-family-redesign-229-v1','sample_rate_hz':sample_rate_hz,
              'target_rms_dbfs':float(target_rms_dbfs),'matching':'whole-item RMS target with peak-safe gain reduction only; no compression or normalization',
              'protected_anchor':LOCKED_BLOOM.to_dict(),'anchor_audio_included':False,
              'anchor_note':'locked_bloom remains available in the recovered product; this generated pack does not rebuild it from remembered parameters.',
              'order':list(order),'items':[x.to_dict() for x in items],'candidate_intents':{r.id:r.intent for r in FAMILIES if r.classification=='candidate'},
              'companion_files_note':'Evidence tooling emits one-bar melodic demos for every candidate in addition to these matched one-beat source items.',
              'endpoints':[{'id':x,'scale':[1,7]} for x in ENDPOINTS],
              'questions':['Rate bounce separately from melodic identity.','Rate recognisable source character separately from usefulness.','Optional free-text reason for reject/keep.'],
              'decision_policy':'No acoustic descriptor or aggregate score changes defaults. Explicit owner approval is required.',
              'owner_decisions':[],'rejected_variants_retained_as_evidence':True}
    manifest['manifest_sha256']=canonical_sha256(manifest)
    return AuditionPack(sample_rate_hz,float(target_rms_dbfs),audio,tuple(items),manifest)
