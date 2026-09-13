"""Generate deterministic ZG-014 synthetic calibration evidence; no perceptual-quality claim."""
from __future__ import annotations
import argparse,json,platform,sys
from copy import deepcopy
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from zaaggenz_contracts import Contract
from zaaggenz_descriptors import *

def partials(freqs,amps=None,conf=None,sr=12000,frames=4096):
    amps=[1.]*len(freqs) if amps is None else amps;conf=[1.]*len(freqs) if conf is None else conf;asset=pcm_asset(np.zeros(frames,dtype=np.float32),sr);s=dict(start_sample=1536,end_sample=2560,anchor_sample=2048,padding='none');tracks=[]
    for i,(f,a,c) in enumerate(zip(freqs,amps,conf)):
        tracks.append(dict(id=f'p{i}',segment_id=f's{i}',continuity='continuous',frames=[dict(support=deepcopy(s),frequency_hz=float(f),amplitudes=[float(a)],phases_radians=[0.],confidence=float(c),action='transform')]))
    return Contract(dict(kind='PartialTrackBundle',version='1.0.0',asset=asset,method=dict(id='zg014.synthetic.source-known',version='1',configuration={}),phase_convention='cosine-at-anchor-radians-v1',channel_policy='shared-frequency-independent-channel-coefficients',data_origin='source_known',tracks=tracks,residual_asset=None,transient_asset=None,remainder_policy='additive-owned-remainders-v1'))

def simple(obs):return dict(value=obs.value,validity=obs.validity,confidence=obs.confidence,details=obs.details)
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--sample-rate',type=int,default=12000);a=p.parse_args();sr=a.sample_rate;t=np.arange(2*sr)/sr
    audio={}
    for hz in (55.,220.,880.):
        x=np.sin(2*np.pi*hz*t).astype(np.float32);d={o.metric:o for o in periodicity_observations(x,sr,min_f0_hz=30,max_f0_hz=1200)};audio[f'sine_{int(hz)}']=dict(f0=simple(d['f0_candidate_hz']),periodicity=simple(d['periodicity_peak']),occupancy=simple(occupancy_observation(x,sr)))
    noise=np.random.default_rng(20260913).normal(0,.3,len(t)).astype(np.float32);silence=np.zeros(len(t),dtype=np.float32);dc=np.ones(len(t),dtype=np.float32)*.25
    for name,x in [('noise',noise),('silence',silence),('constant_dc',dc)]:
        d={o.metric:o for o in periodicity_observations(x,sr)};audio[name]=dict(f0=simple(d['f0_candidate_hz']),periodicity=simple(d['periodicity_peak']),occupancy=simple(occupancy_observation(x,sr)))
    env=1+.45*np.sin(2*np.pi*4*t);am=(env*np.sin(2*np.pi*440*t)).astype(np.float32);ed={o.metric:o for o in envelope_observations(am,sr)};audio['am_4hz']=dict(modulation_hz=simple(ed['envelope_modulation_hz']),modulation_depth=simple(ed['envelope_modulation_depth']))
    base=(np.sin(2*np.pi*220*t)+.2*np.sin(2*np.pi*440*t)).astype(np.float32);audio['level_sensitivity']={}
    for gain in (1.,.1,.01):
        d={o.metric:o for o in periodicity_observations(base*gain,sr)};audio['level_sensitivity'][str(gain)]=dict(periodicity=d['periodicity_peak'].value,occupancy=occupancy_observation(base*gain,sr).value,rms=rms_observation(base*gain).value)
    clean=partials([200,400,600,800]);cluster=partials([200,220,400,420,600,620,800,820]);inharm=partials([205,389,743,1301]);off=partials([130])
    component={
      'harmonic_clean':simple(harmonicity_observation(clean,200)),'roughness_clean':simple(roughness_observation(clean)),
      'harmonic_clustered_exact_20hz_grid':simple(harmonicity_observation(cluster,20)),'roughness_clustered':simple(roughness_observation(cluster)),
      'harmonic_inharmonic':simple(harmonicity_observation(inharm,200)),'roughness_inharmonic':simple(roughness_observation(inharm)),
      'tolerance_sensitivity':{str(c):harmonicity_observation(inharm,200,tolerance_cents=c).value for c in (20.,35.,70.,140.)}}
    sparse={o.metric:o for o in target_comb_observations(off,[100,200])};dense={o.metric:o for o in target_comb_observations(off,[100,125,150,175,200])}
    comb={'sparse':{k:simple(v) for k,v in sparse.items()},'dense':{k:simple(v) for k,v in dense.items()}}
    report={'scope':'synthetic deterministic descriptor calibration; no preference, pleasure or biochemical inference','platform':platform.platform(),'python':sys.version,'sample_rate_hz':sr,'audio_controls':audio,'component_controls':component,'target_comb_density_probe':comb,'registry':descriptor_catalogue()}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8');print(json.dumps(report,indent=2,sort_keys=True))
if __name__=='__main__':main()
