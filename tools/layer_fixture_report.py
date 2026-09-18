from __future__ import annotations
import argparse, hashlib, json, sys, wave
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_contracts.legacy import adapt_parameters,freeze_legacy
from zaaggenz_harmony import SonoritySpec,SonorityTone,VoiceSpec,VoicingConstraints,solve_progression
from zaaggenz_layers import LayerGeneratorSpec,LayerRuntimeSpec,render_coordinated_layers
from zaaggenz_melody import make_melodic_recipe,make_phrase_plan,note_event

def _sha(a):return hashlib.sha256(np.asarray(a,dtype='<f4').tobytes()).hexdigest()
def _sonority(root,name):return SonoritySpec(name,root,(SonorityTone('root',degree_offset=0),SonorityTone('third',degree_offset=4),SonorityTone('fifth',degree_offset=7)))
def _render(policy,sr):
    p=adapt_parameters('synth',{'sr':sr,'bpm':180.,'beats':1,'f0_hz':48.});base=freeze_legacy(p).to_dict();tu=base['tuning'];tm=base['time_map']
    phrase=make_phrase_plan(tu['id'],[note_event('source-lead','0/1','1/1',tu['id'],12,gain_db=-20.)],start_beat='0/1',end_beat='2/1',bass_role='pedal' if policy=='hold-first' else 'moving')
    recipe=make_melodic_recipe(p,tm,tu,phrase,quality='standard',tail_mode='truncate',master_gain_db=-6.)
    voices=VoicingConstraints((VoiceSpec('sub','sub',20,60,34,anchor_policy=policy),VoiceSpec('body','body',36,90,56),VoiceSpec('aux','aux',70,150,102),VoiceSpec('lead','synthline',105,240,160)))
    progression=solve_progression(tu,[_sonority(0,'home'),_sonority(5,'turn')],voices)
    spec=LayerRuntimeSpec(tuple(LayerGeneratorSpec(role,'sine',-30.,round(.01*sr),round(.02*sr),.125) for role in ('body','aux','sub')))
    return recipe,progression,render_coordinated_layers(recipe,progression,['0/1','1/1'],'1/1',spec)
def _wav(path,audio,sr):
    x=np.asarray(audio,dtype=np.float64);pcm=np.round(np.clip(x,-1.,1.)*32767.).astype('<i2')
    with wave.open(str(path),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(sr);f.writeframes(pcm.tobytes())
def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('--out',default='zg029-layer-fixtures.json');ap.add_argument('--audio-dir',default='zg029-layer-listening');ap.add_argument('--sample-rate',type=int,default=12000);ns=ap.parse_args(argv)
    if not 8000<=ns.sample_rate<=48000:raise SystemExit('sample rate must be 8000..48000')
    outdir=Path(ns.audio_dir);outdir.mkdir(parents=True,exist_ok=True);cases=[]
    for name,policy in (('fixed-pedal','hold-first'),('moving-root','moving')):
        recipe,progression,result=_render(policy,ns.sample_rate);path=outdir/f'{name}.wav';_wav(path,result.mix,ns.sample_rate)
        sub=[next(v.frequency_hz for v in frame.voices if v.voice_id=='sub') for frame in progression.frames]
        cases.append({'id':name,'recipe_sha256':recipe.sha256,'progression_sha256':progression.sha256,'mix_pcm_f32le_sha256':_sha(result.mix),'stem_pcm_f32le_sha256':result.diagnostics['stem_sha256'],'sub_targets_hz':sub,'state_sha256':result.state.sha256,'listening_copy':str(path),'listening_copy_policy':'PCM16 clipped transport copy; canonical evidence is float32 hash'})
    report={'format':'zaaggenz-zg029-owner-audition','version':'1.0.0','sample_rate_hz':ns.sample_rate,'cases':cases,'notes':['Explicit generator gains/glides/releases are fixture intent, not product defaults.','Fixed-pedal and moving-root examples share source and final-master policy; only declared bass ownership differs.']}
    Path(ns.out).write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8');return 0
if __name__=='__main__':raise SystemExit(main())
