"""Four new source mechanisms around owner-approved Open. Open itself is frozen."""
from dataclasses import dataclass, asdict, replace
from pathlib import Path
import hashlib
import html
import json
import numpy as np
from scipy import signal
from zaaggenz_contracts.legacy import legacy_object
from . import krach_retry_v3 as v3
from .krach_presets import parameters, catalogue, recipe_for
from .model import ZaagFamilyError, canonical_sha256

REVISION = 'zg022-open-variations-v1'
PROFILES = ('drift', 'roll', 'fold', 'spread')
INTENTS = (
    'Slow exchange between broad harmonic groups; continuous body and no resonant sweep.',
    'Two rounded pressure surges per beat; the upper detail answers between them.',
    'A smooth fold blooms within the surface branch; low body never enters the extra shaper.',
    'Interleaved harmonic groups trade emphasis across the hit; no pitch detuning or noise.')


@dataclass(frozen=True)
class Variant:
    id: str
    label: str
    profile: str
    depth: float

    def __post_init__(self):
        if self.profile not in PROFILES or self.id != 'zaag.open-'+self.profile+'-v1':
            raise ZaagFamilyError('versioned Open variation/profile identity required')
        if self.label != self.profile.title():
            raise ZaagFamilyError('known plain label required')
        v3.finite(self.depth, 'depth', 0., 1.)

    def payload(self):
        return {**asdict(self), 'revision': REVISION, 'status': 'pending-owner',
                'parent_id': v3.RECIPES[0].id,
                'parent_recipe_sha256': canonical_sha256(v3.RECIPES[0].payload())}


VARIANTS = tuple(Variant('zaag.open-'+p+'-v1', p.title(), p, d)
                 for p, d in zip(PROFILES, (.95, .95, .85, .90)))


def render_source(variant, sr=48000, *, bpm=190.):
    """Resynthesise Open's exact substrate; change only a named surface mechanism.

    A zero-depth variant reconstructs the approved Open PCM exactly. No opaque
    reference WAV, new source seed, Q peak, detuned oscillator or bitcrusher.
    """
    if not isinstance(variant, Variant):
        raise ZaagFamilyError('Variant required')
    bpm = v3.rate_bpm(sr, bpm)
    params = parameters(v3.RECIPES[0].id, sr, bpm)
    from uptempo_harmony.synth import synthesize_one
    high_sr = 4*sr
    x, debug = synthesize_one(replace(legacy_object('synth', params), sr=high_sr))
    x = np.asarray(x, dtype=np.float64)
    t = np.arange(len(x))/high_sr
    beat = t*bpm/60.
    body = v3.lowpass(x, high_sr, 160.)
    z = x-body
    swell = .5-.5*np.cos(2*np.pi*beat)
    drive = 2.5 + .5*(1.-np.cos(2.*np.pi*beat))
    base = .65*np.tanh(drive*z)+.35*z
    d = variant.depth
    if variant.profile == 'drift':
        # Broad complementary motion, never a narrow formant boost.
        lower = v3.lowpass(z, high_sr, 2100.)
        upper_z = z-lower
        travel = np.sin(2*np.pi*(beat-.15))
        moving = lower*(1.+.72*d*travel)+upper_z*(1.-.72*d*travel)
        surface = .65*np.tanh(drive*moving)+.35*moving
    elif variant.profile == 'roll':
        crest = (.5+.5*np.cos(4*np.pi*beat-.45))**2
        rounded = .36+.64*crest
        moving_drive = drive*(.86+.24*crest)
        rolled = (.65*np.tanh(moving_drive*z)+.35*z)*rounded
        surface = (1.-d)*base+d*rolled
    elif variant.profile == 'fold':
        amount = 2.6+3.2*swell
        folded = .78*np.sin(amount*z)+.22*z
        surface = (1.-.70*d)*base+.70*d*folded
    else:
        # The substrate stays open while three integer harmonic groups move.
        surface = base*(1.+.28*d*np.sin(2*np.pi*beat*3.))
    surface -= v3.lowpass(surface, high_sr, 160.)
    mid = v3.lowpass(surface, high_sr, 1700.)-v3.lowpass(surface, high_sr, 330.)
    surface = v3.lowpass(surface-.40*mid, high_sr, 10000.)
    phase = 2*np.pi*np.cumsum(debug['f0'], dtype=np.float64)/high_sr
    harmonics = np.arange(12,193,dtype=float)
    weights = harmonics**(-.32)*np.exp(-(harmonics*params['f0_hz']/8000.)**2)
    offsets = np.random.default_rng(7911).uniform(0.,2*np.pi,len(harmonics))
    upper = np.zeros(len(x), dtype=np.float64)
    for index, (h,w,offset) in enumerate(zip(harmonics,weights,offsets)):
        gain = 1.
        if variant.profile == 'drift':
            gain = 1.+.80*d*np.sin(2*np.pi*beat + np.log2(h/12.)*1.3)
        elif variant.profile == 'roll':
            gain = 1.-.55*d+.55*d*(.5+.5*np.sin(4*np.pi*beat+1.1))
        elif variant.profile == 'fold':
            gain = 1.+.22*d*swell*np.tanh((h-48.)/36.)
        elif variant.profile == 'spread':
            gain = 1.+.90*d*np.sin(2*np.pi*beat*2.+(index%3)*2*np.pi/3.)
        phase_motion = .55*d*np.sin(phase) if variant.profile == 'spread' else 0.
        upper += w*np.sin(h*phase+offset+phase_motion)*gain
    upper /= np.sqrt(.5*np.sum(weights**2))
    upper *= .7+.3*np.exp(-t/.22)
    anchor = v3.RECIPES[0]
    mix = (anchor.body*body+anchor.surface*surface+anchor.upper*upper)*(.8+.2*np.exp(-t/.23))
    n = round(sr*60./bpm*.97)
    audio = signal.resample_poly(mix,1,4,window=('kaiser',10.))[:n]
    audio = v3.edges(audio,sr).astype(np.float32)
    if len(audio)!=n or not np.isfinite(audio).all():
        raise ZaagFamilyError('invalid Open variation output')
    return audio, {'recipe':variant.payload(),'recipe_sha256':canonical_sha256(variant.payload()),
        'source_parameters':params,'sample_rate_hz':sr,'internal_sample_rate_hz':high_sr,
        'phase_seed':7911,'source_pcm_sha256':hashlib.sha256(audio.astype('<f4').tobytes()).hexdigest(),
        'low_body_unchanged':True,'whole_mix_distortion':False,'formant_resonators':False,
        'normalization':'none after authored mix; scalar listening gain recorded separately'}


def build_pack(destination, sr=48000, *, bpm=190.):
    bpm = v3.rate_bpm(sr,bpm)
    out = Path(destination)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ZaagFamilyError('empty destination required; preserve previous auditions')
    out.mkdir(parents=True,exist_ok=True)
    files, items, cards = [], [], []
    comparisons = {'tone':[], 'riff':[]}
    cues = {'tone':[], 'riff':[]}
    times = {'tone':0., 'riff':0.}
    choices = [(v3.RECIPES[0], 'Open reference', 'reference')]+[(v,v.label,'candidate') for v in VARIANTS]
    for number,(recipe,label,status) in enumerate(choices):
        audio,info = v3.render_source(recipe,sr,bpm=bpm) if status=='reference' else render_source(recipe,sr,bpm=bpm)
        root,root_score = v3.render_phrase(audio,sr,bpm=bpm)
        riff,riff_score = v3.render_phrase(audio,sr,bpm=bpm,riff=True)
        folder = f'{number:02d}_{label.lower().replace(" ","_")}'
        entries=[]
        for name,pcm in (('source',audio),('root-loop',root),('riff',riff)):
            matched,level = v3.match(pcm)
            path = f'{folder}/{name}.wav'
            row = {'path':path,'sha256':v3.write_wav(out/path,matched,sr),'frames':len(matched),'matching':level}
            files.append(row);entries.append(row)
            if name!='source':
                key = 'tone' if name=='root-loop' else 'riff'
                length = round((8 if key=='tone' else 16)*sr*60./bpm)
                excerpt = matched[:length]
                cues[key].append({'label':label,'start_s':times[key]})
                times[key]+=len(excerpt)/sr+.5
                comparisons[key].extend([excerpt,np.zeros(round(.5*sr),dtype=np.float32)])
        info.update(status=status,exports=entries,root_score=root_score,riff_score=riff_score)
        items.append(info)
        description = 'Exact approved Open. Not a new candidate.' if status=='reference' else INTENTS[PROFILES.index(recipe.profile)]
        players=''.join(f'<label>{html.escape(Path(e["path"]).stem)}<audio controls loop preload="none" src="{e["path"]}"></audio></label>' for e in entries)
        cards.append(f'<section><h2>{number:02d} / {label}</h2><p>{description}</p>{players}</section>')
    for key in comparisons:
        joined = np.concatenate(comparisons[key][:-1])
        path='00_'+key+'-comparison.wav'
        files.append({'path':path,'sha256':v3.write_wav(out/path,joined,sr),'frames':len(joined),'cues':cues[key]})
    # Tier files contain immutable recipes, not claims that candidates are approved.
    presets=[]
    for entry in catalogue():
        recipe=recipe_for(entry['id'])
        record={**entry,'format':'zaaggenz-krach-preset-v1','recipe':recipe.payload(),
                'source_parameters':parameters(entry['id'],sr,bpm),'renderer':'zaaggenz_zaag.krach_retry_v3.render_source',
                'renderer_sha256':hashlib.sha256(Path(v3.__file__).read_bytes()).hexdigest()}
        path=out/'saved_presets'/entry['tier']/(recipe.label.lower()+'.json')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
        presets.append(record)
    manifest={'revision':REVISION,'sample_rate_hz':sr,'bpm':bpm,'files':files,'items':items,
        'approved_presets':presets,'new_candidates_approved':False,'default':'locked_bloom',
        'renderer_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'feedback_requested':'favourites and specific issues; no numerical scores required',
        'no_private_reference_recordings':True,'matching':'one scalar per complete file; no EQ or limiter'}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ZaagGenZ / Open variations</title><style>body{max-width:940px;margin:auto;padding:24px;background:#151a20;color:#e8edf2;font:16px/1.5 system-ui}h1{font-size:32px}p{color:#b9c5cf}section{border-top:1px solid #475563;padding:18px 0}label{display:block;margin:14px 0}audio{display:block;width:100%;margin-top:5px}button{font:inherit;padding:9px 20px;cursor:pointer}</style><h1>Open / four variations</h1><p>Open stays exactly as approved. Four new candidates explore different motion with the same source and low body. Same restrained riff; no presentation EQ.</p><button id="stop">Stop all</button><section><h2>Comparisons</h2><p>Open reference → Drift → Roll → Fold → Spread</p><label>Tone comparison<audio controls src="00_tone-comparison.wav"></audio></label><label>Riff comparison<audio controls src="00_riff-comparison.wav"></audio></label></section>'''+''.join(cards)+'''<p>Favourites and specific issues are enough. Candidates are not automatically promoted.</p><script>const all=[...document.querySelectorAll('audio')];all.forEach(a=>a.addEventListener('play',()=>all.forEach(b=>{if(a!==b)b.pause()})));document.querySelector('#stop').onclick=()=>all.forEach(a=>a.pause());</script></html>'''
    (out/'listen.html').write_text(page,encoding='utf-8')
    (out/'README.txt').write_text('Open variations / owner audition\n\nOpen listen.html after extracting this ZIP. Comparisons: Open, Drift, Roll, Fold, Spread.\nAll sounds are mono PCM24 at the manifest sample rate. Each has a source, eight-bar raw root loop and eight-bar riff.\nOpen is the exact approved reference, not a replacement. Pulse, Weight and Edge are retained unchanged as secondary presets.\nThe saved_presets files record that owner decision; new variations remain pending. No extra user-distortion is baked in.\nNo numeric ratings needed: name your favourites and any concrete issues.\nReproduce in the ZaagGenZ branch with: python -m zaaggenz_zaag.open_variations --out NEW_EMPTY_DIRECTORY\n',encoding='utf-8')
    return manifest


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--sample-rate',type=int,default=48000)
    args=p.parse_args()
    result=build_pack(args.out,args.sample_rate)
    print(json.dumps({'revision':REVISION,'wav_files':len(result['files'])}))
