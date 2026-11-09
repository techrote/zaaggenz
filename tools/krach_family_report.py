#!/usr/bin/env python3
"""Build #232 Krach audition evidence without redistributing private references."""
from __future__ import annotations
import argparse,hashlib,json,math,platform,sys,wave
from pathlib import Path
import numpy as np
from scipy import signal

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))

from zaaggenz_zaag import (LOCKED_BLOOM,krach_candidates,production_presets,product_preset_catalogue,
    render_family_source,build_krach_audition_pack,family_demo_manifest,krach_loop_manifest,render_arrangement)

BANDS=(('sub',20.,120.),('body',120.,500.),('mid',500.,2000.),('teeth',2000.,6000.),('air',6000.,10000.))

def _rms(audio):
    x=np.asarray(audio,dtype=np.float64)
    return float(np.sqrt(np.mean(x*x))) if x.size else 0.

def _db(v):return 20.*math.log10(max(float(v),1e-15))

def _match(audio,target=-14.,peak_limit=.98):
    x=np.asarray(audio,dtype=np.float64);scale=10**((float(target)-_db(_rms(x)))/20.)
    peak=float(np.max(np.abs(x),initial=0.))*scale
    if peak>peak_limit and peak>0:scale*=peak_limit/peak
    y=np.asarray(x*scale,dtype=np.float32)
    return y,{'target_rms_dbfs':float(target),'gain_db':_db(scale),'achieved_rms_dbfs':_db(_rms(y)),
              'peak':float(np.max(np.abs(y),initial=0.)),
              'float32_pcm_sha256':hashlib.sha256(y.astype('<f4').tobytes()).hexdigest()}

def _wav(path,audio,sr):
    x=np.asarray(audio,dtype=np.float32);peak=float(np.max(np.abs(x),initial=0.))
    if peak>1.000001:raise ValueError(f'audition WAV peak {peak:g} exceeds full scale')
    pcm=np.clip(np.rint(x*32767.),-32768,32767).astype('<i2')
    path.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(path),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(sr);f.writeframes(pcm.tobytes())

def _band_fractions(audio,sr):
    x=np.asarray(audio,dtype=np.float64)
    if not x.size:return {name:0. for name,_,_ in BANDS}
    window=np.hanning(len(x));s=np.fft.rfft(x*window);p=np.abs(s)**2;freq=np.fft.rfftfreq(len(x),1./sr)
    den=float(p[(freq>=20)&(freq<min(10000,sr/2))].sum())+1e-30
    return {name:float(p[(freq>=lo)&(freq<min(hi,sr/2))].sum()/den) for name,lo,hi in BANDS}

def _eq_motion(audio,sr,bpm=190.):
    """Audition-only broad EQ motion; never part of a preset render."""
    x=np.asarray(audio,dtype=np.float64)
    def lp(hz):
        sos=signal.butter(3,min(float(hz),.45*sr),fs=sr,output='sos')
        if len(x)<32:return signal.sosfilt(sos,x)
        return signal.sosfiltfilt(sos,x,padlen=min(len(x)-1,18))
    low=lp(650.);lowmid=lp(2400.);mid=lowmid-low;high=x-lowmid
    t=np.arange(len(x),dtype=np.float64)/sr;beats=t*bpm/60.
    mid_db=5.*np.sin(2*np.pi*beats/4.)
    high_db=7.*np.sin(2*np.pi*beats/2.+np.pi/3.)
    return np.asarray(low+mid*np.power(10.,mid_db/20.)+high*np.power(10.,high_db/20.),dtype=np.float32)

def _corr(a,b):
    a=np.asarray(a,dtype=np.float64);b=np.asarray(b,dtype=np.float64);n=min(len(a),len(b))
    a=a[:n]-np.mean(a[:n]);b=b[:n]-np.mean(b[:n]);d=np.linalg.norm(a)*np.linalg.norm(b)
    return 0. if d==0 else abs(float(np.dot(a,b)/d))

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--sample-rate',type=int,default=12000)
    p.add_argument('--audition-dir',type=Path);args=p.parse_args();sr=args.sample_rate
    if sr not in (12000,48000):raise SystemExit('Krach evidence sample rate must be 12000 or 48000')
    refs=json.loads((ROOT/'references/krach_private_registry_v1.json').read_text(encoding='utf-8'))
    texture=json.loads((ROOT/'references/krach_texture_analysis_v1.json').read_text(encoding='utf-8'))
    pack=build_krach_audition_pack(sr,-14.)
    candidates=krach_candidates();sources={};rows=[];exports=[];loops={}
    for recipe in candidates:
        rendered=render_family_source(recipe,sr);sources[recipe.id]=rendered.audio
        demo=render_arrangement(family_demo_manifest(recipe.id,sr))
        loop=render_arrangement(krach_loop_manifest(recipe.id,sr));loops[recipe.id]=loop.audio
        rows.append({'id':recipe.id,'label':recipe.label,'recipe_sha256':recipe.sha256,
                     'character_profile':rendered.diagnostics['character_profile'],
                     'source_pcm_sha256':rendered.diagnostics['output_pcm_sha256'],
                     'source_peak':rendered.diagnostics['peak'],'source_rms':rendered.diagnostics['output_rms'],
                     'power_fraction':_band_fractions(rendered.audio,sr),
                     'useful_pitch_range_hz':list(recipe.useful_pitch_range_hz),
                     'tuning_guidance':recipe.tuning_guidance,'limitations':list(recipe.limitations)})
        if args.audition_dir:
            source_item=next(x for x in pack.items if x.family_id==recipe.id)
            _wav(args.audition_dir/f'{recipe.id}.wav',pack.audio[source_item.id],sr)
            dm,dmeta=_match(demo.audio);_wav(args.audition_dir/f'{recipe.id}--melodic-demo.wav',dm,sr)
            lm,lmeta=_match(loop.audio);_wav(args.audition_dir/f'{recipe.id}--repeated-root-loop.wav',lm,sr)
            eq=_eq_motion(loop.audio,sr,loop.manifest.bpm);eqm,emeta=_match(eq)
            _wav(args.audition_dir/f'{recipe.id}--repeated-root-loop--eq-motion.wav',eqm,sr)
            exports.extend([
                {'id':recipe.id,'kind':'source','family_id':recipe.id,'source_pcm_sha256':rendered.diagnostics['output_pcm_sha256'],
                 'presentation_processing':'none',**source_item.to_dict()},
                {'id':recipe.id+'--melodic-demo','kind':'melodic-demo','family_id':recipe.id,
                 'source_pcm_sha256':demo.diagnostics['pcm_sha256'],'presentation_processing':'level-match-only',**dmeta},
                {'id':recipe.id+'--repeated-root-loop','kind':'repeated-root-loop','family_id':recipe.id,
                 'source_pcm_sha256':loop.diagnostics['pcm_sha256'],'presentation_processing':'level-match-only',**lmeta},
                {'id':recipe.id+'--repeated-root-loop--eq-motion','kind':'repeated-root-loop-eq-motion','family_id':recipe.id,
                 'source_pcm_sha256':loop.diagnostics['pcm_sha256'],
                 'presentation_processing':'audition-only three-band moving EQ; not preset DSP',**emeta}])
    pairwise=[]
    ids=[x.id for x in candidates]
    for i,left in enumerate(ids):
        for right in ids[i+1:]:
            pairwise.append({'left':left,'right':right,'abs_normalized_waveform_correlation':_corr(sources[left],sources[right]),
                             'interpretation':'anti-degeneracy engineering check only'})
    maxcorr=max((x['abs_normalized_waveform_correlation'] for x in pairwise),default=0.)
    catalogue=product_preset_catalogue();product_ids={x['id'] for x in catalogue['presets']}
    profiles={x['character_profile'] for x in rows}
    failures=[]
    if len(candidates)!=4:failures.append('expected exactly four Krach candidates')
    if profiles!={'krach-black-mass','krach-dark-bounce','krach-mid-shred','krach-air-teeth'}:failures.append('Krach mechanism profile set changed')
    if product_ids & set(ids):failures.append('unapproved Krach candidate leaked into production preset catalogue')
    if catalogue['default']!='locked_bloom':failures.append('protected product default changed')
    if len(pack.items)!=4 or pack.manifest['status']!='pending-owner' or pack.manifest['owner_decisions']:failures.append('Krach audition pack is not an undecided four-candidate pack')
    if maxcorr>=.97:failures.append('Krach candidates are waveform-degenerate')
    if len({hashlib.sha256(np.asarray(x,dtype='<f4').tobytes()).hexdigest() for x in sources.values()})!=4:failures.append('Krach source renders are not distinct')
    report={'scope':'ZG-022 #232 Krach creative follow-up; descriptors guide candidate separation but never certify preference or authenticity',
            'platform':platform.platform(),'python':sys.version,'sample_rate_hz':sr,
            'private_reference_registry':refs,'reference_texture_analysis':texture,
            'protected_anchor':LOCKED_BLOOM.to_dict(),
            'existing_production_preset_ids':[x.id for x in production_presets()],
            'product_default':catalogue['default'],'krach_candidates':rows,
            'candidate_separation':{'pairwise':pairwise,'max_abs_normalized_waveform_correlation':maxcorr,'threshold':.97},
            'audition_manifest':pack.manifest,'listening_exports':exports,'owner_audition_completed':False,
            'acceptance_failures':failures}
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    if args.audition_dir:
        (args.audition_dir/'krach-audition-manifest.json').write_text(json.dumps(pack.manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        (args.audition_dir/'README.txt').write_text(
            'ZG-022 / #232 Krach owner audition\n\n'
            'For each of the four family IDs, listen to: source; melodic demo; repeated-root loop; then repeated-root-loop--eq-motion.\n'
            'The EQ-motion file is presentation-only processing and is NOT part of the preset mechanism.\n'
            'Rate bounce, melodic identity, source character and usefulness separately (1-7), then KEEP/REJECT with notes.\n'
            'No candidate is a production preset or default until explicit owner approval.\n',encoding='utf-8')
    print(json.dumps({'sample_rate_hz':sr,'krach_candidates':ids,'profiles':sorted(profiles),
                      'max_pairwise_abs_corr':maxcorr,'audition_status':pack.manifest['status'],'failures':failures},indent=2))
    if failures:raise SystemExit('ZG-022 #232 Krach evidence failed: '+'; '.join(failures))

if __name__=='__main__':main()
