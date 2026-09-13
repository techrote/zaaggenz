"""Generate full-rate controlled linked-violation/recovery evidence from the protected source."""
from __future__ import annotations
import argparse,hashlib,json,math,platform,sys
from pathlib import Path
import numpy as np
from scipy.io import wavfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_linked import linked_fakeout_return,compile_linked_recipe
from zaaggenz_melody import render_phrase
NAMES=('baseline','violation-only','recovery-only','both-linked','both-unrelated')
def write(path,obj):path.write_text(json.dumps(obj,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def signature(bundle):return [(e['beat'],e['duration_beats'],e['gain_db'],e['source_id']) for e in bundle.expansion.phrase.to_dict()['events']]
def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',required=True,type=Path);ap.add_argument('--audio-dir',required=True,type=Path);ap.add_argument('--sample-rate',type=int,default=48000);args=ap.parse_args();args.audio_dir.mkdir(parents=True,exist_ok=True);plan=linked_fakeout_return();rows=[];audio=[];base_sig=None;base_source=None;base_return=None;base_anchor=None
 for name in NAMES:
  bundle=compile_linked_recipe(plan,name,sample_rate=args.sample_rate,quality='standard',tail_mode='truncate');result=render_phrase(bundle.recipe);x=np.asarray(result.mix,dtype=np.float32)
  sig=signature(bundle);source=bundle.recipe.to_dict()['source'];ret=bundle.expansion.phrase.to_dict()['events'][-1];anchor=list(bundle.expansion.anchor_trace)
  if base_sig is None:base_sig,base_source,base_return,base_anchor=sig,source,ret,anchor
  else:assert sig==base_sig and source==base_source and ret==base_return and anchor==base_anchor
  bridge=[r for r in bundle.expansion.trace if r['phase']=='bridge'];dist=[r['distance_to_return_cents'] for r in bridge]
  if name in ('recovery-only','both-linked'):assert all(b<a for a,b in zip(dist,dist[1:]))
  if name=='both-unrelated':assert not all(b<a for a,b in zip(dist,dist[1:]))
  write(args.audio_dir/f'{name}.trace.json',list(bundle.expansion.trace));write(args.audio_dir/f'{name}.automation.json',list(bundle.expansion.automation));write(args.audio_dir/f'{name}.timeline.json',bundle.timeline.to_dict())
  rms=float(np.sqrt(np.mean(x.astype(np.float64)**2)));peak=float(np.max(np.abs(x)))
  rows.append({'name':name,'variant':bundle.expansion.variant.to_dict(),'model_state':bundle.expansion.model_state,'expansion_sha256':bundle.expansion.sha256,'recipe_sha256':bundle.recipe.sha256,'timeline_revision':bundle.timeline.revision_id,'samples':len(x),'duration_seconds':len(x)/args.sample_rate,'event_signature':sig,'return_event':ret,'anchor_beats':[r['beat'] for r in anchor],'bridge_distance_to_return_cents':dist,'bridge_link_progress':[r['link_progress'] for r in bridge],'active_transforms':[r['kind'] for r in bundle.expansion.automation if r['active']],'raw_rms':rms,'raw_peak':peak,'raw_pcm_sha256':hashlib.sha256(x.tobytes()).hexdigest(),'clipped_fraction':result.diagnostics['clipped_fraction']});audio.append(x)
 target=min([10**(-24/20)]+[r['raw_rms']*10**(-3/20)/r['raw_peak'] for r in rows])
 for row,x in zip(rows,audio):
  gain=target/row['raw_rms'];matched=(x.astype(np.float64)*gain).astype(np.float32);wav=args.audio_dir/(row['name']+'-matched.wav');wavfile.write(wav,args.sample_rate,matched);row.update(matching_gain_db=20*math.log10(gain),matched_rms=float(np.sqrt(np.mean(matched.astype(np.float64)**2))),matched_peak=float(np.max(np.abs(matched))),matched_headroom_db=-20*math.log10(float(np.max(np.abs(matched)))),wav=wav.name,wav_sha256=hashlib.sha256(wav.read_bytes()).hexdigest())
 report={'method':'zg028-linked-return-fixtures-v1','scope':'controlled source-derived compositional evidence; no listener or biochemical inference','python':sys.version,'platform':platform.platform(),'sample_rate_hz':args.sample_rate,'plan_sha256':plan.sha256,'matching':{'method':'whole-file RMS playback-only gain with common -3 dBFS sample-peak ceiling','target_rms':target,'perceptual_loudness_match_claimed':False,'true_peak_measured':False},'invariants':{'source_identity_equal':True,'duration_timing_gain_signature_equal':True,'final_destination_equal':True,'slow_anchor_equal':True,'linked_bridge_monotonic_convergence':True,'unrelated_bridge_not_monotonic':True,'deferred_dsp_applied':False},'conditions':rows}
 args.out.parent.mkdir(parents=True,exist_ok=True);write(args.out,report);print(json.dumps({'checks':'passed','conditions':len(rows),'out':str(args.out)}))
if __name__=='__main__':main()
