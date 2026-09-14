from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import numpy as np
from zaaggenz_contracts import Contract,validate
from .chordness_model import ChordnessError
from .chordness_request import ChordnessRequest

@dataclass(frozen=True)
class ChordnessFrameDecision:
    track_id:str;frame_index:int;anchor_sample:int;source_hz:float;realised_hz:float
    source_amplitude:float;realised_amplitude:float;correction_cents:float;gain_db:float
    confidence:float;decision:str;reason:str;template_id:str|None;tooth_index:int|None
    target_hz:float|None;assignment_distance_cents:float|None;occupancy:int|None;capacity:int|None
    phase_correction_radians:float
    def to_dict(self):
        return dict(track_id=self.track_id,frame_index=self.frame_index,anchor_sample=self.anchor_sample,
                    source_hz=self.source_hz,realised_hz=self.realised_hz,source_amplitude=self.source_amplitude,
                    realised_amplitude=self.realised_amplitude,correction_cents=self.correction_cents,gain_db=self.gain_db,
                    confidence=self.confidence,decision=self.decision,reason=self.reason,template_id=self.template_id,
                    tooth_index=self.tooth_index,target_hz=self.target_hz,assignment_distance_cents=self.assignment_distance_cents,
                    occupancy=self.occupancy,capacity=self.capacity,phase_correction_radians=self.phase_correction_radians)

@dataclass(frozen=True)
class ChordnessResult:
    request:ChordnessRequest
    selected_template_ids:tuple[str,...]
    bundle:Contract
    source:np.ndarray
    audio:np.ndarray
    sinusoidal:np.ndarray
    transient:np.ndarray
    residual:np.ndarray
    decisions:tuple[ChordnessFrameDecision,...]
    candidate_evaluations:tuple[dict,...]
    occupancy:tuple[dict,...]
    descriptor_before:dict|None
    descriptor_after:dict|None
    objective_before:dict|None
    objective_after:dict|None
    diagnostics:dict
    def __post_init__(self):
        if not isinstance(self.request,ChordnessRequest):raise ChordnessError('ChordnessRequest required')
        if not isinstance(self.bundle,Contract):raise ChordnessError('PartialTrackBundle required')
        validate(self.bundle.to_dict(),'PartialTrackBundle')
        shape=np.asarray(self.source).shape
        for name in ('source','audio','sinusoidal','transient','residual'):
            a=np.asarray(getattr(self,name))
            if a.shape!=shape or not np.isfinite(a).all():raise ChordnessError(name+' invalid')
            a.setflags(write=False)
        object.__setattr__(self,'selected_template_ids',tuple(self.selected_template_ids))
        object.__setattr__(self,'decisions',tuple(self.decisions));object.__setattr__(self,'candidate_evaluations',tuple(deepcopy(self.candidate_evaluations)))
        object.__setattr__(self,'occupancy',tuple(deepcopy(self.occupancy)));object.__setattr__(self,'diagnostics',deepcopy(self.diagnostics))
    @property
    def inspection(self):
        return {'method':{'id':'zg.multi_comb_chordness.v1','version':'1.0.0'},'request':self.request.to_dict(),
                'selected_template_ids':list(self.selected_template_ids),'candidate_evaluations':deepcopy(list(self.candidate_evaluations)),
                'occupancy':deepcopy(list(self.occupancy)),'frames':[x.to_dict() for x in self.decisions],
                'descriptor_before':deepcopy(self.descriptor_before),'descriptor_after':deepcopy(self.descriptor_after),
                'objective_before':deepcopy(self.objective_before),'objective_after':deepcopy(self.objective_after),
                'diagnostics':deepcopy(self.diagnostics)}
