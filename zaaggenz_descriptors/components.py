from __future__ import annotations
from copy import deepcopy
import math
import numpy as np
from zaaggenz_contracts import Contract,validate
from .model import DescriptorError,observation

def _bundle(value):
    d=value.to_dict() if isinstance(value,Contract) else deepcopy(value)
    try:validate(d,'PartialTrackBundle')
    except Exception as exc:raise DescriptorError('valid PartialTrackBundle required') from exc
    return d

def _support(bundle,support):
    if support is not None:return deepcopy(support)
    n=bundle['asset']['frame_count'];return dict(start_sample=0,end_sample=max(1,n),anchor_sample=max(0,(n-1)//2),padding='none')

def _amp(frame):
    a=np.asarray(frame['amplitudes'],dtype=np.float64)
    return float(np.sqrt(np.mean(a*a)))

def _snapshot_components(bundle,support,component_cap=64):
    if type(component_cap)is not int or not 1<=component_cap<=256:raise DescriptorError('component_cap must be integer 1..256')
    anchor=support['anchor_sample'];start=support['start_sample'];end=support['end_sample'];rows=[]
    for track in bundle['tracks']:
        frames=[f for f in track['frames'] if start<=f['support']['anchor_sample']<end]
        if not frames:continue
        frame=min(frames,key=lambda f:abs(f['support']['anchor_sample']-anchor))
        amp=_amp(frame);conf=float(frame['confidence'])
        if amp<=0:continue
        rows.append(dict(track_id=track['id'],frequency_hz=float(frame['frequency_hz']),amplitude=amp,confidence=conf,
                         weight=amp*conf,continuity=track['continuity'],frame_anchor_sample=frame['support']['anchor_sample']))
    rows.sort(key=lambda r:(r['weight'],r['amplitude']),reverse=True)
    return rows[:component_cap],len(rows)

def _weighted_mean(values,weights):
    v=np.asarray(values,dtype=np.float64);w=np.asarray(weights,dtype=np.float64);den=float(w.sum())
    return None if den<=1e-30 else float(np.dot(v,w)/den)

def _confidence(components):
    amps=[c['amplitude'] for c in components];return _weighted_mean([c['confidence'] for c in components],amps) or 0.

def _cents_ratio(r):return 1200.*math.log2(r)

def harmonicity_observation(partials,f0_hz,*,support=None,component_cap=64,tolerance_cents=35.):
    b=_bundle(partials);s=_support(b,support);components,total=_snapshot_components(b,s,component_cap)
    if type(f0_hz) not in (int,float) or type(f0_hz)is bool or not math.isfinite(float(f0_hz)) or f0_hz<=0:raise DescriptorError('positive finite f0_hz required')
    if not 1<=float(tolerance_cents)<=600:raise DescriptorError('harmonicity tolerance must be 1..600 cents')
    if not components:
        return observation('harmonicity_comb_fit',None,s,validity='abstained',confidence=0.,role='estimate',details={'reason':'no-components','f0_hz':float(f0_hz)})
    scores=[];weights=[];mismatches=[]
    for c in components:
        n=max(1,int(round(c['frequency_hz']/float(f0_hz))));target=n*float(f0_hz);m=abs(_cents_ratio(c['frequency_hz']/target))
        scores.append(math.exp(-.5*(m/float(tolerance_cents))**2));weights.append(c['weight']);mismatches.append(m)
    score=_weighted_mean(scores,weights);conf=_confidence(components)
    details={'f0_hz':float(f0_hz),'tolerance_cents':float(tolerance_cents),'component_cap':component_cap,'components_used':len(components),
             'components_available':total,'weighted_mean_abs_mismatch_cents':_weighted_mean(mismatches,weights),'snapshot':'nearest frame to support anchor'}
    return observation('harmonicity_comb_fit',score,s,confidence=conf,role='estimate',details=details)

def roughness_observation(partials,*,support=None,component_cap=64):
    b=_bundle(partials);s=_support(b,support);components,total=_snapshot_components(b,s,component_cap)
    if not components:
        return observation('roughness_pairwise',None,s,validity='abstained',confidence=0.,role='estimate',details={'reason':'no-components'})
    if len(components)==1:
        return observation('roughness_pairwise',0.,s,confidence=_confidence(components),role='estimate',details={'components_used':1,'components_available':total,'level_policy':'relative amplitude; global gain invariant','pair_kernel':'Sethares-style normalized pair kernel'})
    a=3.5;bcoef=5.75;xmax=math.log(bcoef/a)/(bcoef-a);kernel_max=math.exp(-a*xmax)-math.exp(-bcoef*xmax)
    values=[];weights=[]
    for i in range(len(components)):
        c1=components[i]
        for j in range(i+1,len(components)):
            c2=components[j];f1,f2=c1['frequency_hz'],c2['frequency_hz'];df=abs(f2-f1);scale=.24/(.021*min(f1,f2)+19.)
            raw=math.exp(-a*scale*df)-math.exp(-bcoef*scale*df);values.append(max(0.,min(1.,raw/kernel_max)))
            weights.append(c1['weight']*c2['weight'])
    value=_weighted_mean(values,weights)
    if value is None:value=0.
    details={'components_used':len(components),'components_available':total,'component_cap':component_cap,
             'level_policy':'pair weights use relative amplitude*confidence; global gain cancels','bandwidth_model':'0.24/(0.021*f_low+19)','kernel':'exp(-3.5*x)-exp(-5.75*x), normalized to unit maximum','absolute_loudness_model':False}
    return observation('roughness_pairwise',value,s,confidence=_confidence(components),role='estimate',details=details)

def target_comb_observations(partials,target_hz,*,support=None,component_cap=64,tolerance_cents=35.):
    b=_bundle(partials);s=_support(b,support);components,total=_snapshot_components(b,s,component_cap);sr=b['asset']['sample_rate_hz']
    try:targets=tuple(float(x) for x in target_hz)
    except Exception as exc:raise DescriptorError('target_hz must be a finite sequence') from exc
    if not 1<=len(targets)<=128 or any(not math.isfinite(x) or x<=0 or x>=sr/2 for x in targets) or any(a>=b for a,b in zip(targets,targets[1:])):raise DescriptorError('target comb must contain 1..128 strictly increasing positive frequencies below Nyquist')
    if not 1<=float(tolerance_cents)<=600:raise DescriptorError('target-comb tolerance must be 1..600 cents')
    common={'target_count':len(targets),'target_min_hz':targets[0],'target_max_hz':targets[-1],'tolerance_cents':float(tolerance_cents),'component_cap':component_cap,'components_available':total}
    density=observation('target_comb_density',float(len(targets)),s,role='measurement',details=common)
    if not components:
        d={**common,'reason':'no-components'}
        return [observation('target_comb_coverage',None,s,validity='abstained',confidence=0.,role='estimate',details=d),
                observation('target_comb_precision',None,s,validity='abstained',confidence=0.,role='estimate',details=d),
                observation('target_comb_fit',None,s,validity='abstained',confidence=0.,role='estimate',details=d),
                observation('target_comb_mismatch_cents',None,s,validity='abstained',confidence=0.,role='estimate',details=d),density]
    weights=[c['weight'] for c in components];coverage_scores=[];mismatches=[]
    for c in components:
        m=min(abs(_cents_ratio(c['frequency_hz']/t)) for t in targets);mismatches.append(m);coverage_scores.append(math.exp(-.5*(m/float(tolerance_cents))**2))
    coverage=_weighted_mean(coverage_scores,weights) or 0.;mismatch=min(4800.,_weighted_mean(mismatches,weights) or 4800.)
    precision_scores=[]
    for t in targets:
        m=min(abs(_cents_ratio(t/c['frequency_hz'])) for c in components);precision_scores.append(math.exp(-.5*(m/float(tolerance_cents))**2))
    precision=float(np.mean(precision_scores));balanced=0. if coverage+precision<=1e-30 else 2*coverage*precision/(coverage+precision);conf=_confidence(components)
    coverage_details={**common,'components_used':len(components),'density_bias':'adding target teeth can only improve or preserve this source-to-target coverage term; inspect precision/balanced fit too'}
    precision_details={**common,'components_used':len(components),'definition':'equal-weight target-to-source tooth support'}
    balanced_details={**common,'components_used':len(components),'definition':'harmonic mean of source coverage and target precision'}
    mismatch_details={**common,'components_used':len(components),'definition':'amplitude*confidence-weighted source-to-nearest-target absolute cents'}
    return [observation('target_comb_coverage',coverage,s,confidence=conf,role='estimate',details=coverage_details),
            observation('target_comb_precision',precision,s,confidence=conf,role='estimate',details=precision_details),
            observation('target_comb_fit',balanced,s,confidence=conf,role='estimate',details=balanced_details),
            observation('target_comb_mismatch_cents',mismatch,s,confidence=conf,role='estimate',details=mismatch_details),density]

def component_observations(partials,*,f0_hz=None,target_hz=None,support=None,component_cap=64,tolerance_cents=35.):
    out=[roughness_observation(partials,support=support,component_cap=component_cap)]
    if f0_hz is not None:out.append(harmonicity_observation(partials,f0_hz,support=support,component_cap=component_cap,tolerance_cents=tolerance_cents))
    else:
        b=_bundle(partials);s=_support(b,support);out.append(observation('harmonicity_comb_fit',None,s,validity='unknown',confidence=0.,role='estimate',details={'reason':'no-f0-candidate'}))
    if target_hz is not None:out.extend(target_comb_observations(partials,target_hz,support=support,component_cap=component_cap,tolerance_cents=tolerance_cents))
    return out
