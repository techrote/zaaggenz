"""Generate deterministic ZG-010 harmony/voice-leading evidence and a source-derived audition."""
from __future__ import annotations
import argparse,json,platform,sys
from pathlib import Path
import numpy as np
from scipy.io import wavfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'app'))
from zaaggenz_contracts.legacy import adapt_parameters,freeze_legacy
from zaaggenz_harmony import *
from zaaggenz_tuning import fixture_pack,tuning_to_spec

def triad(root,name,bass=None):return SonoritySpec(name,root,(SonorityTone('root',degree_offset=0),SonorityTone('third',degree_offset=4),SonorityTone('fifth',degree_offset=7)),bass_tone_id=bass)
def constraints(policy='moving'):
    return VoicingConstraints((VoiceSpec('sub','sub',22,60,36,max_leap_cents=1600,anchor_policy=policy),VoiceSpec('body','body',36,85,55,max_leap_cents=1800),VoiceSpec('aux','aux',70,145,100,max_leap_cents=1800),VoiceSpec('lead','synthline',105,230,155,max_leap_cents=1800)))
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--audio-dir',type=Path,required=True);p.add_argument('--sample-rate',type=int,default=12000);a=p.parse_args()
    params=adapt_parameters('synth',{'sr':a.sample_rate,'bpm':200.,'beats':1,'f0_hz':48.});base=freeze_legacy(params).to_dict();tm=base['time_map'];tu=base['tuning']
    moving=solve_progression(tu,[triad(0,'home'),triad(5,'subdominant'),triad(7,'dominant'),triad(0,'return')],constraints('moving'))
    held=solve_progression(tu,[triad(0,'home'),triad(5,'subdominant'),triad(7,'dominant'),triad(0,'return')],constraints('hold-first'))
    chromatic=solve_progression(tu,[triad(0,'home'),triad(1,'approach'),triad(0,'return')],VoicingConstraints(constraints().voices[1:]))
    t=fixture_pack()['synthetic-13ed3'];tritave=SonoritySpec('tritave-ratio',0,(SonorityTone('root',degree_offset=0),SonorityTone('d4',degree_offset=4),SonorityTone('ratio',ratio=3/2)))
    nonoct=solve_progression(tuning_to_spec(t),[tritave],VoicingConstraints((VoiceSpec('low','body',35,75,50),VoiceSpec('mid','aux',60,130,85),VoiceSpec('high','synthline',90,260,150))))
    dyad=lambda root,name:SonoritySpec(name,root,(SonorityTone('root',degree_offset=0),SonorityTone('fifth',degree_offset=7)))
    audition_prog=solve_progression(tu,[dyad(0,'a'),dyad(2,'b'),dyad(5,'c'),dyad(0,'d')],VoicingConstraints((VoiceSpec('body','body',36,90,55),VoiceSpec('lead','synthline',80,190,125))))
    audition=audition_progression(audition_prog,params,tm,tu,['0/1','1/2','1/1','3/2'],'1/2',gain_db=-24,quality='standard',tail_mode='truncate');a.audio_dir.mkdir(parents=True,exist_ok=True);wavfile.write(a.audio_dir/'source-derived-two-voice-progression.wav',a.sample_rate,audition.mix)
    report={'scope':'deterministic mathematical harmony/voice-leading fixtures and generated-source audition; no quality, cultural-authenticity or perceptual claim','platform':platform.platform(),'python':sys.version,'sample_rate_hz':a.sample_rate,
      'moving_bass':moving.to_dict(),'hold_first_low_anchor':held.to_dict(),'chromatic_approach_return':chromatic.to_dict(),'non_octave_ratio_fixture':nonoct.to_dict(),
      'audition':{'progression':audition_prog.to_dict(),'diagnostics':audition.diagnostics,'wav':'source-derived-two-voice-progression.wav'}}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8');print(json.dumps({'moving_cost':moving.total_voice_leading_cost,'held_sub_hz':[f.voices[0].frequency_hz for f in held.frames],'audition_samples':len(audition.mix),'out':str(a.out)},indent=2))
if __name__=='__main__':main()
