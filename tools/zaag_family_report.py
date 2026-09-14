"""Generate ZG-022 engineering/audition evidence. Acoustic descriptors are never preference scores."""
from __future__ import annotations
import argparse,json,math,platform,sys,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from zaaggenz_zaag import (LOCKED_BLOOM,FAMILIES,candidates,contrasts,registry_payload,registry_sha256,
    render_family_source,example_manifests,render_arrangement,build_owner_audition_pack)

def _descriptor(audio,sr,f0=48.):
    x=np.asarray(audio,dtype=np.float64);w=np.hanning(len(x));p=np.abs(np.fft.rfft(x*w))**2+1e-30;freq=np.fft.rfftfreq(len(x),1./sr);total=float(np.sum(p));flat=float(np.exp(np.mean(np.log(p)))/np.mean(p));centroid=float(np.sum(freq*p)/total)
    mask=np.zeros(len(p),dtype=bool)
    n=1
    while n*f0<sr/2:
        mask|=np.abs(freq-n*f0)<=max(3.,f0*.035);n+=1
    harmonic=float(np.sum(p[mask])/total)
    return {'spectral_flatness':flat,'spectral_centroid_hz':centroid,'harmonic_band_power_fraction':harmonic,
            'interpretation':'engineering descriptor only; not preference, bounce or usefulness'}
def _wav(path,audio,sr):
    a=np.asarray(audio,dtype=np.float32);peak=float(np.max(np.abs(a),initial=0.));scale=32767./max(1.,peak);pcm=np.clip(np.rint(a*scale),-32768,32767).astype('<i2')
    path.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(path),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(sr);f.writeframes(pcm.tobytes())

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--sample-rate',type=int,default=12000);p.add_argument('--audition-dir',type=Path);p.add_argument('--skip-long',action='store_true');args=p.parse_args();sr=args.sample_rate
    suite=json.loads((ROOT/'examples/zg022_zaag_family_examples.json').read_text());baseline=json.loads((ROOT/'baseline/V1_2_1_CONTRACT.json').read_text())
    source_rows=[];hashes=[]
    for recipe in FAMILIES:
        rendered=render_family_source(recipe,sr);hashes.append(rendered.diagnostics['output_pcm_sha256']);source_rows.append({'id':recipe.id,'classification':recipe.classification,'recipe_sha256':recipe.sha256,'render':rendered.diagnostics,'descriptors':_descriptor(rendered.audio,sr,float(rendered.source_params['f0_hz'])),'documentation':{'useful_pitch_range_hz':list(recipe.useful_pitch_range_hz),'tuning_guidance':recipe.tuning_guidance,'phase_policy':recipe.expert.phase_policy,'tail_policy':recipe.expert.tail_policy,'quality_cost':recipe.expert.quality_cost,'limitations':list(recipe.limitations)}})
    arrangements=[]
    manifests=example_manifests(sr)
    for manifest in manifests:
        if args.skip_long and manifest.bars>4:arrangements.append({'id':manifest.id,'manifest_sha256':manifest.sha256,'bars':manifest.bars,'skipped_audio_at_this_evidence_tier':True});continue
        render=render_arrangement(manifest);arrangements.append({'id':manifest.id,'manifest_sha256':manifest.sha256,'bars':manifest.bars,'render':render.diagnostics})
        if args.audition_dir:_wav(args.audition_dir/f'{manifest.id}.wav',render.audio,sr)
    pack=build_owner_audition_pack(sr,-14.)
    if args.audition_dir:
        for item in pack.items:_wav(args.audition_dir/f'{item.family_id}.wav',pack.audio[item.id],sr)
        (args.audition_dir/'audition-manifest.json').write_text(json.dumps(pack.manifest,indent=2)+'\n')
    expected_candidates=suite['registry_expectation']['candidate_ids'];expected_contrasts=suite['registry_expectation']['contrast_ids']
    report={'scope':'ZG-022 deterministic engineering evidence and owner-audition preparation; no preference result is inferred','platform':platform.platform(),'python':sys.version,'sample_rate_hz':sr,
      'protected_anchor':LOCKED_BLOOM.to_dict(),'baseline_contract_anchor_hash':baseline['preset_contracts']['locked_bloom_canonical_json_sha256'],
      'registry_sha256':registry_sha256(),'registry':registry_payload(),'sources':source_rows,'arrangements':arrangements,'audition_manifest':pack.manifest,
      'example_suite':suite,'default_change':None,'owner_audition_completed':False,
      'preference_boundary':'flatness, clipping, harmonic concentration, roughness and other acoustic descriptors are descriptive only; owner ratings decide creative usefulness'}
    failures=[]
    if LOCKED_BLOOM.canonical_json_sha256!=baseline['preset_contracts']['locked_bloom_canonical_json_sha256']:failures.append('locked_bloom anchor changed')
    if [x.id for x in candidates()]!=expected_candidates:failures.append('candidate registry differs from frozen example suite')
    if [x.id for x in contrasts()]!=expected_contrasts:failures.append('contrast registry differs from frozen example suite')
    if len(set(hashes))!=len(FAMILIES):failures.append('family renders were not distinct')
    if any(x.approved_default for x in FAMILIES) or registry_payload()['new_default'] is not None:failures.append('new default was approved without owner decision')
    if [x.bars for x in manifests]!=[1,4,16]:failures.append('example manifest durations changed')
    if len(manifests[1].events)!=32 or len(manifests[2].events)!=64:failures.append('arranged event counts changed')
    if pack.manifest['status']!='pending-owner' or pack.manifest['owner_decisions']:failures.append('audition was falsely marked decided')
    if any(not np.isfinite([row['descriptors']['spectral_flatness'],row['descriptors']['spectral_centroid_hz'],row['descriptors']['harmonic_band_power_fraction']]).all() for row in source_rows):failures.append('nonfinite source descriptor')
    report['acceptance_failures']=failures;args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'sample_rate_hz':sr,'families':len(FAMILIES),'candidates':len(candidates()),'contrasts':len(contrasts()),'arrangements':[x['id'] for x in arrangements],'audition_status':pack.manifest['status'],'failures':failures},indent=2))
    if failures:raise SystemExit('ZG-022 evidence failed: '+'; '.join(failures))
if __name__=='__main__':main()
