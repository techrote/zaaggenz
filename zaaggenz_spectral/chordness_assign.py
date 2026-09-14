from __future__ import annotations
import math
import numpy as np
from .chordness_descriptors import usable_teeth
from .chordness_model import ChordnessError
from .chordness_request import ChordnessRequest
from .lattice import cents_distance

def _amp(row):
    a=np.asarray(row['amplitudes'],dtype=np.float64)
    return float(np.sqrt(np.mean(a*a)))

def preserve_reason(track,row,request):
    if row.get('action')!='transform':return 'component-policy-preserve'
    if float(row.get('confidence',0.))<request.min_confidence:return 'low-confidence'
    if request.preserve_ambiguous and track.get('continuity')!='continuous':return 'ambiguous-or-reanchored-track'
    return None

def target_slots(templates,sample_rate_hz):
    slots=[]
    for template in templates:
        for i,hz in enumerate(usable_teeth(template,sample_rate_hz)):
            slots.append({'template_id':template.id,'tooth_index':i,'target_hz':float(hz),'capacity':template.tooth_capacity})
    if not slots:raise ChordnessError('selected combs contain no usable target teeth')
    return tuple(slots)

def assign_components(bundle,templates,request):
    if not isinstance(request,ChordnessRequest):raise ChordnessError('ChordnessRequest required')
    source=bundle.to_dict() if hasattr(bundle,'to_dict') else bundle;sr=source['asset']['sample_rate_hz'];slots=target_slots(templates,sr)
    groups={};preserved={}
    for ti,track in enumerate(source['tracks']):
        for fi,row in enumerate(track['frames']):
            key=(ti,fi);reason=preserve_reason(track,row,request)
            if reason is not None:preserved[key]=reason;continue
            anchor=int(row['support']['anchor_sample']);groups.setdefault(anchor,[]).append((ti,fi,track,row))
    assignments={};occupancy_rows=[]
    for anchor in sorted(groups):
        occupancy={(x['template_id'],x['tooth_index']):0 for x in slots}
        rows=sorted(groups[anchor],key=lambda x:(-_amp(x[3])*float(x[3]['confidence']),x[2]['id'],x[1]))
        for ti,fi,track,row in rows:
            f=float(row['frequency_hz']);ranked=[]
            for slot in slots:
                key=(slot['template_id'],slot['tooth_index'])
                if occupancy[key]>=slot['capacity']:continue
                distance=abs(cents_distance(slot['target_hz'],f))
                ranked.append((distance,slot['template_id'],slot['tooth_index'],slot))
            ranked.sort(key=lambda x:(x[0],x[1],x[2]))
            if not ranked or ranked[0][0]>request.max_assignment_cents:
                preserved[(ti,fi)]='no-capacity-or-target-within-assignment';continue
            distance,_,_,slot=ranked[0];key=(slot['template_id'],slot['tooth_index']);occupancy[key]+=1
            assignments[(ti,fi)]={**slot,'distance_cents':float(distance),'occupancy':occupancy[key],
                                  'anchor_sample':anchor,'track_id':track['id'],'frame_index':fi}
        for slot in slots:
            key=(slot['template_id'],slot['tooth_index']);used=occupancy[key]
            occupancy_rows.append({'anchor_sample':anchor,'template_id':slot['template_id'],'tooth_index':slot['tooth_index'],
                                   'target_hz':slot['target_hz'],'occupancy':used,'capacity':slot['capacity']})
    return assignments,preserved,tuple(occupancy_rows)
