from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import numpy as np
from zaaggenz_contracts import Contract,validate
from zaaggenz_melody import NoteMode,MelodicRenderSpec,make_melodic_recipe,render_phrase
from .model import HarmonyError,ProgressionResult
from .events import voice_phrase_plans

@dataclass(frozen=True)
class HarmonyAudition:
    mix:np.ndarray
    voice_stems:dict
    recipes:dict
    diagnostics:dict
    def __post_init__(self):
        mix=np.asarray(self.mix,dtype=np.float32);mix.setflags(write=False);object.__setattr__(self,'mix',mix)
        stems={}
        for k,v in self.voice_stems.items():a=np.asarray(v,dtype=np.float32);a.setflags(write=False);stems[k]=a
        object.__setattr__(self,'voice_stems',stems);object.__setattr__(self,'recipes',dict(self.recipes));object.__setattr__(self,'diagnostics',deepcopy(self.diagnostics))

def _pad(x,n):
    a=np.asarray(x,dtype=np.float32);return a if len(a)>=n else np.pad(a,(0,n-len(a)))

def audition_progression(progression,synth_params,time_map,tuning,frame_beats,duration_beats,*,gain_db=-18.,quality='standard',tail_mode='truncate',render_spec=None):
    """Render each stable voice through ZG-008's source-derived path for inspection.

    This is a diagnostic audition, not the final BODY/AUX/SUB routing promised by
    ZG-029. Every voice is rendered as a separate SYNTHLINE recipe so voice
    identity and tuning can be heard without pretending current legacy layers
    already implement harmony-aware persistent roles.
    """
    if not isinstance(progression,ProgressionResult):raise HarmonyError('ProgressionResult required')
    tu=tuning.to_dict() if isinstance(tuning,Contract) else deepcopy(tuning)
    try:validate(tu,'TuningSpec')
    except Exception as exc:raise HarmonyError('valid TuningSpec required for audition') from exc
    if tu['id']!=progression.tuning_id:raise HarmonyError('audition tuning does not match progression tuning')
    spec=render_spec or MelodicRenderSpec(mode=NoteMode.SOURCE_DERIVED)
    if not isinstance(spec,MelodicRenderSpec) or spec.mode is not NoteMode.SOURCE_DERIVED:raise HarmonyError('harmony audition is source-derived only')
    plans=voice_phrase_plans(progression,frame_beats,duration_beats,gain_db=gain_db);stems={};recipes={};render_diags={}
    for voice_id,plan in plans.items():
        recipe=make_melodic_recipe(synth_params,time_map,tu,plan,mode=NoteMode.SOURCE_DERIVED,tail_mode=tail_mode,quality=quality,master_gain_db=0.)
        result=render_phrase(recipe,spec);stems[voice_id]=np.asarray(result.mix,dtype=np.float32);recipes[voice_id]=recipe;render_diags[voice_id]=result.diagnostics
    n=max((len(v) for v in stems.values()),default=0);mix=np.zeros(n,dtype=np.float64)
    for v in stems.values():mix+=_pad(v,n).astype(np.float64)
    peak=float(np.max(np.abs(mix),initial=0.));atten=1. if peak<=.98 else .98/peak;mix=np.asarray(mix*atten,dtype=np.float32)
    diagnostics={'mode':'source-derived-per-voice-diagnostic','voice_count':len(stems),'voice_ids':list(stems),'peak_before_common_attenuation':peak,'common_attenuation':atten,
                 'routing_limit':'roles are preserved in the progression/events but auditioned as separate SYNTHLINE recipes; layer-role integration belongs to ZG-029','voice_renders':render_diags}
    return HarmonyAudition(mix,stems,recipes,diagnostics)
