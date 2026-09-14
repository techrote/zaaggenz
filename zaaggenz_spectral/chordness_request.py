from __future__ import annotations
from dataclasses import dataclass
from .chordness_model import (ChordnessError,ChordnessCoefficients,CombTemplate,MODES,SELECTION_MODES,_bound)

@dataclass(frozen=True)
class ChordnessRequest:
    templates:tuple[CombTemplate,...]
    mode:str='off'
    selection_mode:str='manual'
    selected_template_ids:tuple[str,...]=()
    max_selected_templates:int=1
    retune_amount:float=1.
    reweight_amount:float=1.
    min_confidence:float=.55
    tolerance_cents:float=35.
    max_assignment_cents:float=1200.
    max_displacement_cents:float=350.
    max_correction_slew_cents_per_second:float=1800.
    max_gain_db:float=6.
    max_gain_slew_db_per_second:float=24.
    preserve_ambiguous:bool=True
    coefficients:ChordnessCoefficients=ChordnessCoefficients()
    def __post_init__(self):
        templates=tuple(self.templates)
        if not 1<=len(templates)<=32 or any(not isinstance(x,CombTemplate) for x in templates):raise ChordnessError('1..32 CombTemplate values required')
        ids=[x.id for x in templates]
        if len(ids)!=len(set(ids)):raise ChordnessError('duplicate comb id')
        if self.mode not in MODES:raise ChordnessError('invalid chordness mode')
        if self.selection_mode not in SELECTION_MODES:raise ChordnessError('invalid selection mode')
        selected=tuple(self.selected_template_ids)
        if len(selected)!=len(set(selected)) or any(x not in ids for x in selected):raise ChordnessError('selected template id is invalid')
        if self.selection_mode=='manual' and self.mode!='off' and not selected:raise ChordnessError('manual active mode requires selected_template_ids')
        if type(self.max_selected_templates)is not int or not 1<=self.max_selected_templates<=len(templates):raise ChordnessError('invalid max_selected_templates')
        if len(selected)>self.max_selected_templates:raise ChordnessError('too many manually selected templates')
        for name in ('retune_amount','reweight_amount','min_confidence'):
            object.__setattr__(self,name,_bound(getattr(self,name),name,0.,1.))
        object.__setattr__(self,'tolerance_cents',_bound(self.tolerance_cents,'tolerance_cents',1.,600.))
        assign=_bound(self.max_assignment_cents,'max_assignment_cents',1.,4800.)
        disp=_bound(self.max_displacement_cents,'max_displacement_cents',1.,2400.)
        if disp>assign:raise ChordnessError('max_displacement_cents cannot exceed max_assignment_cents')
        object.__setattr__(self,'max_assignment_cents',assign);object.__setattr__(self,'max_displacement_cents',disp)
        object.__setattr__(self,'max_correction_slew_cents_per_second',_bound(self.max_correction_slew_cents_per_second,'max_correction_slew_cents_per_second',1.,20000.))
        object.__setattr__(self,'max_gain_db',_bound(self.max_gain_db,'max_gain_db',0.,36.))
        object.__setattr__(self,'max_gain_slew_db_per_second',_bound(self.max_gain_slew_db_per_second,'max_gain_slew_db_per_second',.01,240.))
        if type(self.preserve_ambiguous)is not bool:raise ChordnessError('preserve_ambiguous must be bool')
        if not isinstance(self.coefficients,ChordnessCoefficients):raise ChordnessError('ChordnessCoefficients required')
        object.__setattr__(self,'templates',templates);object.__setattr__(self,'selected_template_ids',selected)
    def to_dict(self):
        return {'kind':'ChordnessRequest','version':'1.0.0','mode':self.mode,'selection_mode':self.selection_mode,
                'templates':[x.to_dict() for x in self.templates],'selected_template_ids':list(self.selected_template_ids),
                'max_selected_templates':self.max_selected_templates,'retune_amount':self.retune_amount,'reweight_amount':self.reweight_amount,
                'min_confidence':self.min_confidence,'tolerance_cents':self.tolerance_cents,'max_assignment_cents':self.max_assignment_cents,
                'max_displacement_cents':self.max_displacement_cents,'max_correction_slew_cents_per_second':self.max_correction_slew_cents_per_second,
                'max_gain_db':self.max_gain_db,'max_gain_slew_db_per_second':self.max_gain_slew_db_per_second,
                'preserve_ambiguous':self.preserve_ambiguous,'coefficients':self.coefficients.to_dict()}
