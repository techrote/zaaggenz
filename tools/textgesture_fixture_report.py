"""Generate 48 kHz text-gesture preview/bundle/render evidence from original synthetic dictionaries."""
from __future__ import annotations
import argparse,hashlib,json,math,platform,sys
from pathlib import Path
import numpy as np
from scipy.io import wavfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_melody import render_phrase
from zaaggenz_textgesture import starter_registry,make_bundle,TextGestureBundle,make_render_recipe,parse_text,format_text,semantic_ast

TEXT='bu[d=1/2] ~1/4 | budu[n=4,c=25] budubu[n=8] @return[d=1/2]'
MODIFIED='bu[d=1/2,p=4,b=0.9,n=4] ~1/4 | budu[n=2,p=-1,b=0.35] budubu[n=6] @return[d=1/2]'

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--artifact-dir',type=Path,required=True);p.add_argument('--sample-rate',type=int,default=48000);args=p.parse_args();args.artifact_dir.mkdir(parents=True,exist_ok=True)
    registry=starter_registry();conditions=[('soft-same-text',TEXT,'local-soft'),('bright-same-text',TEXT,'local-bright'),('soft-modified-text',MODIFIED,'local-soft')]
    rows=[];audio=[]
    for name,text,dictionary_id in conditions:
        bundle=make_bundle(text,registry,dictionary_id,sample_rate=args.sample_rate);reopened=TextGestureBundle.from_json(json.dumps(bundle.to_dict()));compilation=reopened.compilation
        if reopened.sha256!=bundle.sha256 or compilation.sha256!=bundle.compilation.sha256:raise RuntimeError('bundle roundtrip identity mismatch')
        recipe=make_render_recipe(compilation);result=render_phrase(recipe);x=result.mix.astype(np.float32,copy=True)
        if not np.isfinite(x).all() or np.max(np.abs(x),initial=0)<=0:raise RuntimeError(f'{name}: invalid generated audio')
        canonical=format_text(parse_text(text));semantic=semantic_ast(parse_text(canonical));first=compilation.preview['events'][0]
        (args.artifact_dir/f'{name}.bundle.json').write_text(json.dumps(bundle.to_dict(),indent=2,sort_keys=True)+'\n',encoding='utf-8')
        (args.artifact_dir/f'{name}.preview.json').write_text(json.dumps(compilation.preview,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        (args.artifact_dir/f'{name}.gesture.json').write_text(json.dumps(compilation.gesture.to_dict(),indent=2,sort_keys=True)+'\n',encoding='utf-8')
        (args.artifact_dir/f'{name}.timeline.json').write_text(json.dumps(compilation.timeline.to_dict(),indent=2,sort_keys=True)+'\n',encoding='utf-8')
        rows.append({'name':name,'dictionary_id':dictionary_id,'text':text,'canonical_text':canonical,'semantic_ast':semantic,'bundle_sha256':bundle.sha256,
                     'compilation_sha256':compilation.sha256,'gesture_sha256':compilation.gesture.sha256,'phrase_sha256':compilation.phrase.sha256,
                     'timeline_revision_id':compilation.timeline.revision_id,'first_event_degree':first['degree'],'first_event_brightness_fraction':first['brightness_fraction'],
                     'active_tuning_id':compilation.preview['active_tuning_id'],'base_degree':compilation.preview['base_degree'],'event_count':len(compilation.preview['events']),
                     'group_count':len(compilation.preview['groups']),'samples':len(x),'duration_seconds':len(x)/args.sample_rate,
                     'raw_rms':float(np.sqrt(np.mean(x.astype(np.float64)**2))),'raw_peak':float(np.max(np.abs(x))),
                     'raw_pcm_sha256':hashlib.sha256(x.tobytes()).hexdigest(),'clipped_fraction':result.diagnostics['clipped_fraction']})
        audio.append(x)
    if rows[0]['text']!=rows[1]['text'] or rows[0]['canonical_text']!=rows[1]['canonical_text']:raise RuntimeError('same-text dictionary control lost text identity')
    if rows[0]['first_event_degree']==rows[1]['first_event_degree'] or rows[0]['first_event_brightness_fraction']==rows[1]['first_event_brightness_fraction']:raise RuntimeError('dictionary identity did not change same-token mapping')
    if rows[0]['dictionary_id']!=rows[2]['dictionary_id'] or rows[0]['text']==rows[2]['text']:raise RuntimeError('explicit text-modifier control is malformed')
    target=min([10**(-24/20)]+[r['raw_rms']*10**(-3/20)/r['raw_peak'] for r in rows])
    for row,x in zip(rows,audio):
        gain=target/row['raw_rms'];matched=(x.astype(np.float64)*gain).astype(np.float32);path=args.artifact_dir/f'{row["name"]}-matched.wav';wavfile.write(path,args.sample_rate,matched)
        row.update(matching_gain_db=20*math.log10(gain),matched_rms=float(np.sqrt(np.mean(matched.astype(np.float64)**2))),matched_peak=float(np.max(np.abs(matched))),wav=path.name,wav_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    report={'method':'zg031-textgesture-fixtures-v1','sample_rate_hz':args.sample_rate,'python':sys.version,'platform':platform.platform(),'numpy':np.__version__,
            'registry_sha256':registry.sha256,'scope':'original synthetic project-local mnemonic dictionaries; no phonetic universal, speech-recognition or owner-listening claim',
            'matching':{'method':'whole-file RMS playback-only gain with common -3 dBFS sample-peak ceiling','perceptual_loudness_match_claimed':False,'true_peak_measured':False},'conditions':rows}
    args.out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8');print(json.dumps({'checks':'passed','conditions':len(rows),'sample_rate_hz':args.sample_rate}))
if __name__=='__main__':main()
