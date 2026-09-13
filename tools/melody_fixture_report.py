"""Generate deterministic ZG-008 musical construction evidence and level-matched listening files."""
from __future__ import annotations
import argparse,json,math,platform,sys
from pathlib import Path
import numpy as np
from scipy.io import wavfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'app'))

from zaaggenz_contracts.legacy import adapt_parameters,freeze_legacy,envelope,legacy_object
from zaaggenz_melody import *

def rms(x):
    a=np.asarray(x,dtype=np.float64);return float(np.sqrt(np.mean(a*a))) if a.size else 0.
def match_pair(a,b):
    ra,rb=rms(a),rms(b);gain=1. if rb<=1e-20 else ra/rb;db=20*math.log10(max(gain,1e-30));bm=np.asarray(b,dtype=np.float64)*gain
    peak=max(float(np.max(np.abs(a),initial=0)),float(np.max(np.abs(bm),initial=0)));common=1. if peak<=.98 else .98/peak
    return (np.asarray(a,dtype=np.float32)*common,(bm*common).astype(np.float32),db,20*math.log10(common) if common<1 else 0.)
def make_recipe(params,tm,tu,events,gestures=(),*,mode=NoteMode.SOURCE_DERIVED,end='1/1'):
    phrase=make_phrase_plan(tu['id'],events,end_beat=end,gestures=gestures)
    return make_melodic_recipe(params,tm,tu,phrase,mode=mode,quality='high')
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--audio-dir',type=Path,required=True);p.add_argument('--sample-rate',type=int,default=12000);a=p.parse_args()
    params=adapt_parameters('synth',{'sr':a.sample_rate,'bpm':200.,'beats':1,'f0_hz':48.});base=freeze_legacy(params).to_dict();tm=base['time_map'];tu=base['tuning']
    root=note_event('root','0/1','1/1',tu['id'],0);neutral=render_phrase(make_recipe(params,tm,tu,[root]))
    from uptempo_harmony.synth import synthesize_one
    direct=np.asarray(synthesize_one(legacy_object('synth',params))[0],dtype=np.float32);neutral_prefix=neutral.stems['synthline'][:len(direct)]
    degree=7;note=note_event('n','0/1','1/1',tu['id'],degree)
    src=render_phrase(make_recipe(params,tm,tu,[note],mode=NoteMode.SOURCE_DERIVED),MelodicRenderSpec(mode=NoteMode.SOURCE_DERIVED))
    target=render_phrase(make_recipe(params,tm,tu,[note],mode=NoteMode.TARGET_NOTE),MelodicRenderSpec(mode=NoteMode.TARGET_NOTE))
    aa,bb,match_db,common_db=match_pair(src.mix,target.mix);a.audio_dir.mkdir(parents=True,exist_ok=True);wavfile.write(a.audio_dir/'A-source-derived.wav',a.sample_rate,aa);wavfile.write(a.audio_dir/'B-target-note-matched.wav',a.sample_rate,bb)
    glide_g=envelope('GestureSpec',id='rise',duration_beats='1/1',curves=[dict(axis='pitch_cents',unit='cents',interpolation='linear',points=[dict(beat='0/1',value=0.),dict(beat='1/1',value=1200.)])])
    glide=render_phrase(make_recipe(params,tm,tu,[note_event('g','0/1','1/1',tu['id'],0,gesture_id='rise')],[glide_g]));wavfile.write(a.audio_dir/'glide-octave.wav',a.sample_rate,glide.mix)
    roll_g=envelope('GestureSpec',id='roll',duration_beats='1/1',curves=[dict(axis='density_per_beat',unit='events/beat',interpolation='step',points=[dict(beat='0/1',value=8.),dict(beat='1/1',value=8.)])])
    roll=render_phrase(make_recipe(params,tm,tu,[note_event('r','0/1','1/1',tu['id'],0,gesture_id='roll')],[roll_g]));wavfile.write(a.audio_dir/'roll-8-per-beat.wav',a.sample_rate,roll.mix)
    report={'scope':'deterministic generated-source construction evidence; listening files make no quality claim','platform':platform.platform(),'python':sys.version,'sample_rate_hz':a.sample_rate,
      'neutral':{'direct_samples':len(direct),'prefix_bit_identical':bool(np.array_equal(direct,neutral_prefix)),'source_rms':rms(direct),'render_rms':rms(neutral_prefix)},
      'ab_listening':{'A':'source-derived degree 7','B':'target-note degree 7, RMS matched to A','B_matching_gain_db':match_db,'common_headroom_gain_db':common_db,'A_rms':rms(aa),'B_rms':rms(bb)},
      'glide':glide.events[0],'roll':roll.events[0]}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
