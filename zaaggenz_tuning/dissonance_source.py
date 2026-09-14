from __future__ import annotations
import math
from zaaggenz_contracts import Contract
from .dissonance_model import DissonanceError,TimbreSpectrum

def _rms(values):
    return math.sqrt(sum(float(x)*float(x) for x in values)/max(len(values),1))

def spectrum_from_partial_bundle(bundle,anchor_sample,*,id='component-window',max_components=32,max_anchor_distance_samples=None):
    if isinstance(bundle,Contract):data=bundle.to_dict()
    elif isinstance(bundle,dict):data=bundle
    else:raise DissonanceError('PartialTrackBundle Contract/mapping required')
    if data.get('kind')!='PartialTrackBundle':raise DissonanceError('PartialTrackBundle required')
    if type(anchor_sample)is not int or anchor_sample<0:raise DissonanceError('anchor_sample must be a nonnegative integer')
    if type(max_components)is not int or not 1<=max_components<=64:raise DissonanceError('max_components must be 1..64')
    if max_anchor_distance_samples is not None and (type(max_anchor_distance_samples)is not int or max_anchor_distance_samples<0):raise DissonanceError('invalid max anchor distance')
    rows=[]
    for track in data.get('tracks',[]):
        frames=track.get('frames',[])
        if not frames:continue
        frame=min(frames,key=lambda x:(abs(int(x['support']['anchor_sample'])-anchor_sample),int(x['support']['anchor_sample'])))
        distance=abs(int(frame['support']['anchor_sample'])-anchor_sample)
        if max_anchor_distance_samples is not None and distance>max_anchor_distance_samples:continue
        amp=_rms(frame['amplitudes']);confidence=float(frame['confidence'])
        if amp<=0:continue
        rows.append({'frequency_hz':float(frame['frequency_hz']),'amplitude':amp,'confidence':confidence,
                     'track_id':track['id'],'frame_anchor_sample':int(frame['support']['anchor_sample']),'distance_samples':distance,
                     'continuity':track.get('continuity'),'action':frame.get('action')})
    if not rows:raise DissonanceError('component window contains no usable partials')
    rows.sort(key=lambda x:(-(x['amplitude']*x['confidence']),x['frequency_hz'],x['track_id']));rows=rows[:max_components]
    energy=sum(x['amplitude'] for x in rows);confidence=sum(x['amplitude']*x['confidence'] for x in rows)/max(energy,1e-30)
    rows.sort(key=lambda x:(x['frequency_hz'],x['track_id']))
    source={'kind':'PartialTrackBundle-window','asset':data.get('asset',{}),'anchor_sample':anchor_sample,
            'max_anchor_distance_samples':max_anchor_distance_samples,'components':rows,
            'confidence_policy':'amplitude-weighted component confidence; amplitudes themselves are not confidence-scaled'}
    return TimbreSpectrum(id,tuple(x['frequency_hz'] for x in rows),tuple(x['amplitude'] for x in rows),confidence,source)

def harmonic_spectrum(id,root_hz,*,partials=8,amplitude_power=1.,stretch=1.,confidence=1.):
    root=float(root_hz)
    if not math.isfinite(root) or root<=0:raise DissonanceError('root_hz must be positive finite')
    if type(partials)is not int or not 1<=partials<=64:raise DissonanceError('partials must be 1..64')
    if not math.isfinite(float(amplitude_power)) or amplitude_power<=0:raise DissonanceError('amplitude_power must be positive')
    if not math.isfinite(float(stretch)) or stretch<=0:raise DissonanceError('stretch must be positive')
    frequencies=tuple(root*(n**float(stretch)) for n in range(1,partials+1));amplitudes=tuple(1./(n**float(amplitude_power)) for n in range(1,partials+1))
    return TimbreSpectrum(id,frequencies,amplitudes,confidence,{'kind':'synthetic-harmonic','root_hz':root,'partials':partials,'amplitude_power':float(amplitude_power),'stretch':float(stretch)})
