from __future__ import annotations
from .chordness_model import ChordnessError,CombTemplate,_finite

def harmonic_comb(id,root_hz,*,harmonics=8,max_hz=12000.,tooth_capacity=1,label=''):
    root=_finite(root_hz,'root_hz')
    if root<=0:raise ChordnessError('root_hz must be positive')
    max_hz=_finite(max_hz,'max_hz')
    if max_hz<=root:raise ChordnessError('max_hz must exceed root_hz')
    if type(harmonics)is not int or not 1<=harmonics<=64:raise ChordnessError('harmonics must be integer 1..64')
    teeth=tuple(root*n for n in range(1,harmonics+1) if root*n<max_hz)
    if not teeth:raise ChordnessError('harmonic comb has no teeth below max_hz')
    return CombTemplate(id,teeth,tooth_capacity,label,{'kind':'harmonic','root_hz':root,'harmonics':harmonics})

def templates_from_voicing_frame(frame,*,harmonics=8,max_hz=12000.,tooth_capacity=1):
    try:roots=tuple(float(x) for x in frame.fundamental_targets_hz);sonority=str(frame.sonority_id)
    except Exception as exc:raise ChordnessError('VoicingFrame-like value required') from exc
    if not roots:raise ChordnessError('voicing frame has no fundamental targets')
    return tuple(harmonic_comb(f'{sonority}.v{i}',root,harmonics=harmonics,max_hz=max_hz,
                               tooth_capacity=tooth_capacity,label=f'{sonority} fundamental {i}')
                 for i,root in enumerate(roots))
