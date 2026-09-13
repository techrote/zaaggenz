"""Generate matched directionality fixtures from the protected source."""
from __future__ import annotations
import argparse,hashlib,json,math,platform,sys
from pathlib import Path
import numpy as np
from scipy.io import wavfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_gesture import rise_turn_return,vary_surface,reverse_direction,compile_gesture_recipe
from zaaggenz_melody import render_phrase

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--audio-dir',type=Path,required=True);p.add_argument('--sample-rate',type=int,default=48000);args=p.parse_args();args.audio_dir.mkdir(parents=True,exist_ok=True)
    base=rise_turn_return();surface=vary_surface(base,'42',1.,axes=('pitch_cents','brightness_hz'),source_family='surface-b');opposite=reverse_direction(base,('pitch_cents','brightness_hz'),source_family='opposite-direction')
    plans=[('baseline',base,'reference authored direction'),('same-direction-different-surface',surface,'same signs/turn/landing; warped interior control timing'),('similar-surface-opposite-direction',opposite,'same timing/density/duration/gain/landing; pitch+brightness signs reversed')]
    rows=[];audio=[]
    for name,plan,description in plans:
        bundle=compile_gesture_recipe(plan,sample_rate=args.sample_rate);result=render_phrase(bundle.recipe);x=result.mix.astype(np.float32,copy=True)
        events=bundle.compilation.phrase.to_dict()['events'];path=args.audio_dir/f'{name}.plan.json';path.write_text(json.dumps(plan.to_dict(),indent=2,sort_keys=True)+'\n',encoding='utf-8')
        (args.audio_dir/f'{name}.automation.json').write_text(json.dumps(bundle.compilation.automation,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        (args.audio_dir/f'{name}.trace.json').write_text(json.dumps(list(bundle.compilation.trace),indent=2,sort_keys=True)+'\n',encoding='utf-8')
        rows.append({'name':name,'description':description,'plan_sha256':plan.sha256,'compilation_sha256':bundle.compilation.sha256,'recipe_sha256':bundle.recipe.sha256,
                     'source_family':plan.to_dict()['source_family'],'event_count':len(events),'event_signature':[(e['beat'],e['duration_beats'],e['gain_db']) for e in events],
                     'landing':plan.to_dict()['landing'],'pitch_directions':[s['direction'] for s in next(t for t in plan.to_dict()['trajectories'] if t['axis']=='pitch_cents')['segments']],
                     'brightness_directions':[s['direction'] for s in next(t for t in plan.to_dict()['trajectories'] if t['axis']=='brightness_hz')['segments']],
                     'raw_rms':float(np.sqrt(np.mean(x.astype(np.float64)**2))),'raw_peak':float(np.max(np.abs(x))),
                     'raw_pcm_sha256':hashlib.sha256(x.tobytes()).hexdigest(),'samples':len(x),'clipped_fraction':result.diagnostics['clipped_fraction']})
        audio.append(x)
    if not (rows[0]['event_signature']==rows[1]['event_signature']==rows[2]['event_signature']):raise RuntimeError('matched timing/duration/gain inventory changed')
    if not (rows[0]['landing']==rows[1]['landing']==rows[2]['landing']):raise RuntimeError('terminal landing changed')
    if rows[0]['pitch_directions']!=rows[1]['pitch_directions'] or rows[0]['pitch_directions']==rows[2]['pitch_directions']:raise RuntimeError('direction controls are not isolated')
    target=min([10**(-24/20)]+[r['raw_rms']*10**(-3/20)/r['raw_peak'] for r in rows])
    for row,x in zip(rows,audio):
        gain=target/row['raw_rms'];matched=(x.astype(np.float64)*gain).astype(np.float32);wav=args.audio_dir/f'{row["name"]}-matched.wav';wavfile.write(wav,args.sample_rate,matched)
        row.update(matching_gain_db=20*math.log10(gain),matched_rms=float(np.sqrt(np.mean(matched.astype(np.float64)**2))),matched_peak=float(np.max(np.abs(matched))),wav=wav.name,wav_sha256=hashlib.sha256(wav.read_bytes()).hexdigest())
    report={'method':'zg027-directionality-fixtures-v1','sample_rate_hz':args.sample_rate,'python':sys.version,'platform':platform.platform(),'numpy':np.__version__,
            'scope':'original source-derived matched controls; deferred timbral rows are recorded but not silently applied; no owner listening/preference claim',
            'matching':{'method':'whole-file RMS playback-only gain with common -3 dBFS sample-peak ceiling','perceptual_loudness_match_claimed':False,'true_peak_measured':False},'examples':rows}
    args.out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8');print(json.dumps({'checks':'passed','examples':len(rows),'sample_rate_hz':args.sample_rate}))
if __name__=='__main__':main()
