"""Generate deterministic ZG-032 capture/abstention evidence without private recordings."""
from __future__ import annotations
import argparse, hashlib, json, sys, io
from pathlib import Path
import numpy as np
from scipy.io import wavfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_melody import render_phrase
from zaaggenz_textgesture import starter_registry
from zaaggenz_vocal import (analyse_vocal,make_edit,update_segment,compile_edit,mark_source_discarded,
                            make_render_recipe,decode_wav_bytes)

def silence(sr,d): return np.zeros(round(sr*d),np.float32)
def tone(sr,f,d,a=.28):
    t=np.arange(round(sr*d),dtype=np.float64)/sr
    return (a*np.sin(2*np.pi*f*t)+.06*np.sin(4*np.pi*f*t)).astype(np.float32)
def noise(sr,d,a=.18,seed=43): return np.random.default_rng(seed).normal(0,a,round(sr*d)).astype(np.float32)
def fixture(sr): return np.concatenate([silence(sr,.10),tone(sr,122,.32),silence(sr,.08),noise(sr,.25),silence(sr,.08),tone(sr,151,.32),silence(sr,.10)])
def expected(sr): return [(round(sr*.10),122.),(round(sr*(.10+.32+.08)),None),(round(sr*(.10+.32+.08+.25+.08)),151.)]
def pcm_hash(x): return hashlib.sha256(np.asarray(x,dtype='<f4').tobytes()).hexdigest()

def analyse_condition(label,x,sr,origin,outdir):
    analysis=analyse_vocal(x,sr,origin=origin);d=analysis.to_dict();truth=expected(sr)
    if len(d['segments'])!=3: raise RuntimeError(f'{label}: expected 3 regions, got {len(d["segments"])}')
    timing=[];pitch=[]
    for row,(want_sample,want_pitch) in zip(d['segments'],truth):
        timing.append(abs(row['start_sample']-want_sample)/sr)
        if want_pitch is None:
            if row['pitch_hz'] is not None or row['voicing']=='voiced': raise RuntimeError(f'{label}: unvoiced region forced to pitch')
            pitch.append(None)
        else:
            if row['pitch_hz'] is None: raise RuntimeError(f'{label}: voiced region abstained unexpectedly')
            pitch.append(abs(row['pitch_hz']-want_pitch))
    if max(timing)>.04 or max(v for v in pitch if v is not None)>3.: raise RuntimeError(f'{label}: error tolerance exceeded')
    registry=starter_registry();edit=make_edit(analysis,registry,'local-soft');compiled=compile_edit(edit,registry);events=compiled.phrase.to_dict()['events']
    if events[1]['pitch'] is not None: raise RuntimeError(f'{label}: unvoiced region did not compile as rest')
    recipe=make_render_recipe(compiled);render=render_phrase(recipe)
    if not np.isfinite(render.mix).all() or np.max(np.abs(render.mix))<=0 or render.diagnostics['clipped_fraction']!=0: raise RuntimeError(f'{label}: invalid source-derived preview')
    manual=update_segment(edit,'vocal-001',pitch_mode='manual',manual_pitch_hz=136.,manual_offset_samples=17,manual_brightness_hz=1900.)
    corrected=compile_edit(manual,registry)
    if corrected.phrase.to_dict()['events'][1]['pitch'] is None: raise RuntimeError(f'{label}: explicit manual pitch did not create a note')
    discarded=compile_edit(mark_source_discarded(manual),registry)
    if corrected.phrase.to_dict()!=discarded.phrase.to_dict() or corrected.timeline.to_dict()!=discarded.timeline.to_dict(): raise RuntimeError(f'{label}: source discard changed compiled music')
    raw_path=outdir/f'{label}-input.wav';wavfile.write(raw_path,sr,np.asarray(x,dtype=np.float32))
    render_path=outdir/f'{label}-preview.wav';wavfile.write(render_path,sr,np.asarray(render.mix,dtype=np.float32))
    return {'label':label,'origin':origin,'source_sha256':d['source']['content_sha256'],'analysis_sha256':analysis.sha256,
            'voicing':[s['voicing'] for s in d['segments']], 'pitch_hz':[s['pitch_hz'] for s in d['segments']],
            'pitch_confidence':[s['pitch_confidence'] for s in d['segments']], 'brightness_confidence':[s['brightness_confidence'] for s in d['segments']],
            'timing_error_seconds':timing,'pitch_error_hz':pitch,'default_event_kinds':['note' if e['pitch'] is not None else 'rest' for e in events],
            'manual_correction':corrected.preview['events'][1], 'discard_preserves_phrase_and_timeline':True,
            'render_samples':len(render.mix),'render_clipped_fraction':render.diagnostics['clipped_fraction'],
            'input_wav_sha256':hashlib.sha256(raw_path.read_bytes()).hexdigest(),'preview_wav_sha256':hashlib.sha256(render_path.read_bytes()).hexdigest(),
            'raw_preview_pcm_sha256':pcm_hash(render.mix)}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--artifact-dir',type=Path,required=True);p.add_argument('--sample-rate',type=int,default=48000);a=p.parse_args()
    a.artifact_dir.mkdir(parents=True,exist_ok=True);x=fixture(a.sample_rate)
    b=io.BytesIO();wavfile.write(b,a.sample_rate,np.asarray(np.clip(x,-1,1)*32767,dtype=np.int16));sr,recorded=decode_wav_bytes(b.getvalue())
    rows=[analyse_condition('clean-synthetic',x,a.sample_rate,'generated-fixture',a.artifact_dir),analyse_condition('pcm16-recording-path',recorded,sr,'local-recording',a.artifact_dir)]
    report={'method':'zg032-vocal-fixture-v1','sample_rate_hz':a.sample_rate,'conditions':rows,
            'claims':{'human_recording_in_ci':False,'recording_path_exercised':True,'pitch_abstention_required':True,'microphone_required_for_normal_compose':False,'private_pcm_committed':False},
            'note':'CI recording-path fixture is deterministic synthetic PCM16, not a human recording. Human capture uses the same local path and is optional.'}
    a.out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print(json.dumps({'checks':'passed','conditions':len(rows),'sample_rate_hz':a.sample_rate}))
if __name__=='__main__':main()
