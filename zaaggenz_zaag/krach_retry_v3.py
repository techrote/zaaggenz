"""ZG-022/#232 v3 audition. No formants; broad harmonic surface; restrained riff.

Additive experiment: no accepted renderer, preset, default or v2 file is changed.
Run with --out NEW_EMPTY_DIRECTORY to produce the owner-listening pack.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, replace
from fractions import Fraction
from pathlib import Path
import hashlib
import html
import json
import math
import wave

import numpy as np
from scipy import signal
from zaaggenz_contracts.legacy import adapt_parameters, legacy_object
from .model import ZaagFamilyError, canonical_sha256
from .registry import family, PRODUCTION_PRESET_IDS

REVISION = "zg022-krach-retry-232-v3"
METHOD = "zg.krach-open-harmonics.v3"
OVERSAMPLE = 4
BANDS = ((20, 120), (120, 300), (300, 1000), (1000, 3000), (3000, 7000), (7000, 18000))


@dataclass(frozen=True)
class Recipe:
    id: str
    label: str
    parent: str
    style: int
    body: float
    surface: float
    upper: float

    def __post_init__(self):
        if type(self.style) is not int or self.style not in range(4):
            raise ZaagFamilyError("known v3 style required")
        if self.id != ("zaag.krach-v3-open", "zaag.krach-v3-pulse", "zaag.krach-v3-weight", "zaag.krach-v3-edge")[self.style]:
            raise ZaagFamilyError("versioned v3 identity/style mismatch")
        if self.parent not in PRODUCTION_PRESET_IDS or not self.label.isascii() or not self.label.isalpha():
            raise ZaagFamilyError("accepted substrate and plain label required")
        for value in (self.body, self.surface, self.upper):
            finite(value, "source gain", 0., 2.)

    def payload(self):
        return {**asdict(self), "revision": REVISION, "classification": "krach-candidate",
                "parent_recipe_sha256": family(self.parent).sha256}


def finite(value, name, lo, hi):
    if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
        raise ZaagFamilyError(f"{name} must be finite in [{lo}, {hi}]")
    return float(value)


def rate_bpm(sr, bpm):
    if type(sr) is not int or sr not in (12000, 48000):
        raise ZaagFamilyError("sample rate must be 12000 or 48000")
    return finite(bpm, "bpm", 60., 260.)


RECIPES = (
    Recipe("zaag.krach-v3-open", "Open", "zaag.bloom-bark", 0, 1.10, .85, .145),
    Recipe("zaag.krach-v3-pulse", "Pulse", "zaag.upper-chop", 1, 1.00, 1.25, .185),
    Recipe("zaag.krach-v3-weight", "Weight", "zaag.split-maul", 2, 1.25, .93, .125),
    Recipe("zaag.krach-v3-edge", "Edge", "zaag.harmonic-rip", 3, 1.05, 1.20, .190),
)


def lowpass(x, sr, hz):
    # Matched zero-phase branches avoid crossover phase cancellation. No Q peaks.
    return signal.sosfiltfilt(signal.butter(2, hz, fs=sr, output="sos"), x)


def edges(x, sr, attack_ms=1.2, release_ms=6.):
    y = np.asarray(x, dtype=np.float64).copy()
    for start, ms in ((True, attack_ms), (False, release_ms)):
        n = min(len(y)//2, max(2, round(sr*ms/1000.)))
        ramp = .5 - .5*np.cos(np.linspace(0., np.pi, n))
        if start:
            y[:n] *= ramp
        else:
            y[-n:] *= ramp[::-1]
    return y


def render_source(recipe, sr=48000, *, bpm=190.):
    if not isinstance(recipe, Recipe):
        raise ZaagFamilyError("v3 Recipe required")
    bpm = rate_bpm(sr, bpm)
    k = recipe.style
    params = adapt_parameters("synth", {**family(recipe.parent).synth_overrides,
        "sr": sr, "bpm": bpm, "beats": 1, "beat_fill": .97,
        "noise_level": 0., "roughness": 0., "pitch_jitter_cents": 0., "harmonic_lock_cents": 0., "transient_click": 0.,
        "harmonic_count": (64, 60, 72, 68)[k], "harmonic_decay": (.66, .60, .60, .58)[k],
        "odd_even_ratio": (1.08, 1.18, .94, 1.04)[k], "harmonic_tilt_db_per_oct": -.12,
        "sweep_semitones": (-1.2, -.75, -1.5, -.6)[k], "sweep_tau_ms": 36.,
        "input_trim_db": -6., "drive_db": (14., 17., 16., 18.)[k], "shaper_mix": .78,
        "asymmetry": (.17, .13, .22, .10)[k], "hard_clip_mix": .12,
        "wavefold": (.28, .36, .42, .24)[k], "preemphasis": .06,
        "attack_ms": 1.5, "decay_ms": 360., "sustain": .06,
        "post_hp_hz": 18., "post_lp_hz": 16500., "peak": .90})
    from uptempo_harmony.synth import synthesize_one
    high_sr = sr*OVERSAMPLE
    x, debug = synthesize_one(replace(legacy_object("synth", params), sr=high_sr))
    x = np.asarray(x, dtype=np.float64)
    t = np.arange(len(x))/high_sr
    beats = t*bpm/60.
    body = lowpass(x, high_sr, 160.)
    z = x-body
    if k == 0:
        drive = 2.5 + .5*(1.-np.cos(2.*np.pi*beats))
        surface = .65*np.tanh(drive*z) + .35*z
    elif k == 1:
        gate = .25 + .75*(.5+.5*np.sin(2.*np.pi*beats*8.-.45))
        slow = .7 + .3*(.5+.5*np.sin(2.*np.pi*beats*2.))
        surface = (.74*np.tanh(3.*z)+.26*z)*(.25+.75*gate)*slow
    elif k == 2:
        move = .5-.5*np.cos(2.*np.pi*beats*2.)
        bias = .14+.22*move
        surface = .7*(np.tanh((2.4+1.4*move)*z+bias)-np.tanh(bias))+.3*z
    else:
        gate = .4+.6*(.5+.5*np.sin(2.*np.pi*beats*6.+.35))
        surface = (.58*np.tanh(3.4*z)+.24*np.sin((3.+1.3*np.sin(2.*np.pi*beats))*z)+.18*z)*gate
    surface -= lowpass(surface, high_sr, 160.)
    mid = lowpass(surface, high_sr, 1700.)-lowpass(surface, high_sr, 330.)
    surface = lowpass(surface-.40*mid, high_sr, 10000.)
    # Broad, integer-locked partials, including even harmonics. Randomness is
    # confined to fixed oscillator phases, not noise samples or pitch jitter.
    phase = 2.*np.pi*np.cumsum(debug["f0"], dtype=np.float64)/high_sr
    harmonics = np.arange(12, 193, dtype=float)
    weights = harmonics**(-.32)*np.exp(-(harmonics*params["f0_hz"]/8000.)**2)
    offsets = np.random.default_rng(7911+k).uniform(0., 2.*np.pi, len(harmonics))
    upper = np.zeros(len(x), dtype=np.float64)
    for harmonic, weight, offset in zip(harmonics, weights, offsets):
        upper += weight*np.sin(harmonic*phase+offset)
    upper /= np.sqrt(.5*np.sum(weights**2))  # analytic oscillator-bank gain
    upper *= .7+.3*np.exp(-t/.22)
    if k == 1:
        upper *= .25+.75*(.5+.5*np.sin(2.*np.pi*beats*8.-.45))
    elif k == 2:
        upper *= .75+.25*np.sin(2.*np.pi*beats*2.)
    elif k == 3:
        upper *= .5+.5*(.5+.5*np.sin(2.*np.pi*beats*6.+.35))
    mix = (recipe.body*body+recipe.surface*surface+recipe.upper*upper)*(.8+.2*np.exp(-t/.23))
    n = round(sr*60./bpm*.97)
    audio = signal.resample_poly(mix, 1, OVERSAMPLE, window=("kaiser", 10.))[:n]
    audio = edges(audio, sr).astype(np.float32)
    if len(audio) != n or not np.isfinite(audio).all():
        raise ZaagFamilyError("invalid v3 source output")
    info = {"method": METHOD, "recipe": recipe.payload(), "source_parameters": params,
            "recipe_sha256": canonical_sha256(recipe.payload()), "sample_rate_hz": sr,
            "internal_sample_rate_hz": high_sr, "partial_phase_seed": 7911+k,
            "harmonic_bank": {"first": 12, "last": 192, "weight_exponent": -.32, "rolloff_hz": 8000.},
            "source_pcm_sha256": hashlib.sha256(audio.astype("<f4").tobytes()).hexdigest(),
            "normalization": "none after authored mix; recovered substrate peak=0.90",
            "formant_resonators": False, "whole_mix_grit": False, "production_promoted": False}
    return audio, info


# Four-bar ostinato: root pedal, silence, pickups, one lower-fourth excursion.
# Semitones relative to the source. No ascending scale or arpeggio.
RIFF = (
    (0., .90, 0, 1.), (1., .78, 0, .93), (2., .90, 0, 1.), (3., .48, 0, .93), (3.75, .19, -1, .75),
    (4., .90, 0, 1.), (5., .62, 0, .93), (5.75, .20, 0, .65), (6., .90, 0, 1.), (7., .55, -1, .94), (7.75, .19, -1, .67),
    (8., .90, 0, 1.), (9., .90, 0, .96), (10., .65, 0, 1.), (11., .80, -5, .94),
    (12., .90, 0, 1.), (13., .48, 0, .94), (13.75, .19, 0, .68), (14., .60, 0, 1.), (15.5, .30, -1, .90),
)


def render_phrase(source, sr=48000, *, bpm=190., riff=False, bars=8):
    bpm = rate_bpm(sr, bpm)
    if type(bars) is not int or bars not in (4, 8) or type(riff) is not bool:
        raise ZaagFamilyError("bars must be 4 or 8; riff must be boolean")
    x = np.asarray(source, dtype=np.float64)
    if x.ndim != 1 or not 64 <= len(x) <= sr or not np.isfinite(x).all():
        raise ZaagFamilyError("bounded finite mono source required")
    score = [(i, .97, 0, (1., .94, .99, .94)[i % 4]) for i in range(bars*4)]
    if riff:
        score = [(at+16*rep, duration, degree, gain) for rep in range(bars//4) for at, duration, degree, gain in RIFF]
    out = np.zeros(round(bars*4*sr*60./bpm), dtype=np.float64)
    cache, ratios = {0: x}, {0: [1, 1]}
    for at, duration, degree, gain in score:
        if degree not in cache:
            q = Fraction(2.**(-degree/12.)).limit_denominator(2048)
            cache[degree] = signal.resample_poly(x, q.numerator, q.denominator, window=("kaiser", 10.))
            ratios[degree] = [q.numerator, q.denominator]
        start = round(at*sr*60./bpm)
        n = min(len(cache[degree]), round((at+duration)*sr*60./bpm)-start, len(out)-start)
        out[start:start+n] += edges(cache[degree][:n], sr, 1.2, 6.)*gain
    return out.astype(np.float32), {"events": score, "sampler_length_ratios": ratios,
        "pitch_method": "polyphase sampler transposition; duration changes explicitly; no phase vocoder",
        "note_attack_ms": 1.2, "note_release_ms": 6., "tail_overlap": False}


def match(audio, target=-14., peak_limit=.90):
    finite(target, "target dBFS", -30., -6.)
    finite(peak_limit, "peak limit", .1, .98)
    x = np.asarray(audio, dtype=np.float64)
    if x.ndim != 1 or not len(x) or not np.isfinite(x).all():
        raise ZaagFamilyError("finite mono audio required")
    rms, peak = float(np.sqrt(np.mean(x*x))), float(np.max(np.abs(x)))
    if rms <= 1e-12:
        raise ZaagFamilyError("silent audition source")
    gain = min(10.**(target/20.)/rms, peak_limit/peak)
    return (x*gain).astype(np.float32), {"gain": gain, "target_rms_dbfs": target,
        "achieved_rms_dbfs": 20.*math.log10(rms*gain), "peak": peak*gain,
        "processing": "one scalar per complete item; no clipping, compression or limiting"}


def write_wav(path, audio, sr):
    rate_bpm(sr, 190.)
    x = np.asarray(audio, dtype=np.float64)
    if x.ndim != 1 or not len(x) or not np.isfinite(x).all() or np.max(np.abs(x)) >= 1.:
        raise ZaagFamilyError("finite sub-full-scale mono PCM required")
    data = np.rint(x*8388607).astype("<i4").view(np.uint8).reshape(-1, 4)[:, :3].copy().tobytes()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(3); handle.setframerate(sr); handle.writeframes(data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_pack(destination, sr=48000, *, bpm=190.):
    bpm = rate_bpm(sr, bpm)
    out = Path(destination)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ZaagFamilyError("empty destination required; do not overwrite auditions")
    out.mkdir(parents=True, exist_ok=True)
    candidates, files, cards = [], [], []
    comparisons = {"tone": [], "riff": []}
    cues = {"tone": [], "riff": []}
    elapsed = {"tone": 0., "riff": 0.}
    for index, recipe in enumerate(RECIPES, 1):
        source, info = render_source(recipe, sr, bpm=bpm)
        root, root_score = render_phrase(source, sr, bpm=bpm)
        riff, riff_score = render_phrase(source, sr, bpm=bpm, riff=True)
        folder = f"{index:02d}_{recipe.label.lower()}"
        exports = []
        for name, label, audio in (("01_source.wav", "Source hit", source), ("02_root-loop.wav", "Raw root loop", root), ("03_riff.wav", "New riff", riff)):
            matched, level = match(audio)
            rel = folder+"/"+name
            sha = write_wav(out/rel, matched, sr)
            row = {"path": rel, "label": label, "sha256": sha, "frames": len(matched), "matching": level}
            files.append(row); exports.append(row)
            key = {"02_root-loop.wav": "tone", "03_riff.wav": "riff"}.get(name)
            if key:
                excerpt = matched[:round((8 if key == "tone" else 16)*sr*60./bpm)]
                cues[key].append({"label": recipe.label, "start_s": elapsed[key]})
                elapsed[key] += len(excerpt)/sr+.5
                comparisons[key].extend((excerpt, np.zeros(round(sr*.5), dtype=np.float32)))
        info.update(exports=exports, root_score=root_score, riff_score=riff_score)
        candidates.append(info)
        players = "".join(f'<label>{e["label"]}<audio controls preload="none" loop src="{html.escape(e["path"])}"></audio></label>' for e in exports)
        cards.append(f'<section><h2>{index:02d} / {recipe.label}</h2>{players}</section>')
    for key, name in (("tone", "00_tone-comparison.wav"), ("riff", "00_riff-comparison.wav")):
        audio = np.concatenate(comparisons[key][:-1])
        files.append({"path": name, "sha256": write_wav(out/name, audio, sr), "frames": len(audio), "cues": cues[key]})
    manifest = {"revision": REVISION, "method": METHOD, "sample_rate_hz": sr, "bpm": bpm,
        "format": "mono PCM24 WAV", "owner_status": "pending-owner", "production_promoted": False,
        "previous_feedback": "v2 too nasal / blocked ears; previous melody cheesy",
        "default_unchanged": "locked_bloom", "production_presets_unchanged": list(PRODUCTION_PRESET_IDS),
        "renderer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "numpy": np.__version__, "scipy": __import__("scipy").__version__,
        "no_private_recording_audio_included": True, "files": files, "candidates": candidates}
    (out/"manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    (out/"README.txt").write_text(
        "ZaagGenZ / Krach v3 / owner audition\n\nOpen listen.html locally, or play the two comparison WAVs.\n"
        "Order: Open, Pulse, Weight, Edge. Each has a source hit, eight-bar raw root loop and eight-bar riff.\n"
        "No fixed formant resonators, extra noise samples, bitcrushing or final whole-mix saturation.\n"
        "The top is restored using broad root-locked harmonics, not an EQ boost of the old WAVs.\n"
        "The riff uses a root pedal, rests, pickups, semitone falls and a single five-semitone descent per four bars.\n"
        "Sampler transposition changes duration; short release gates are explicit. No added effects hide the source.\n"
        "Level matching is a single constant gain per file, not a perceptual-loudness guarantee. Start at modest volume.\n"
        "These are unapproved experiments, not replacement production presets. Listening decides quality.\n"
        "Reproduce in an authenticated ZaagGenZ checkout with declared dependencies:\n"
        "python -m zaaggenz_zaag.krach_retry_v3 --out NEW_EMPTY_DIRECTORY\n"
        "Set PYTHONPATH=app:. on POSIX, or app;. on Windows. Source/tests are in reproduction/.\n", encoding="utf-8")
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ZaagGenZ / Krach v3</title>
<style>body{margin:0 auto;padding:28px 22px;max-width:960px;background:#13171c;color:#edf0f5;font:16px/1.5 system-ui}h1{font-size:32px;margin:6px 0}h2{font-size:21px}p{color:#b5bdc9}section{border-top:1px solid #46505b;padding:14px 0}label{display:block;font-size:14px;margin:12px 0}audio{display:block;width:100%;margin-top:7px}button{font:inherit;padding:9px 20px;background:#333c49;color:white;border:1px solid #697588;border-radius:5px;cursor:pointer}.tag{font-size:12px;letter-spacing:.12em;color:#abb4c2}</style>
<div class="tag">ZAAGGENZ / OWNER AUDITION / V3</div><h1>Open tone. New riff.</h1><p>No vowel-resonance stages. Broader harmonics, less mid emphasis. A sparse root-led riff instead of the ascending melody. All four are pending your verdict.</p>
<button id="stop">Stop all</button><section><h2>Tone comparison</h2><audio controls src="00_tone-comparison.wav" preload="metadata"></audio><p>Open → Pulse → Weight → Edge</p><h2>Riff comparison</h2><audio controls src="00_riff-comparison.wav" preload="none"></audio><p>The same riff and tempo for all four sounds.</p></section>''' + "".join(cards) + '''<p>Raw examples only; no presentation EQ. Individual examples loop automatically. Local files only, no network.</p><script>const tracks=[...document.querySelectorAll('audio')];tracks.forEach(a=>a.addEventListener('play',()=>tracks.forEach(b=>{if(a!==b)b.pause()})));document.querySelector('#stop').onclick=()=>tracks.forEach(a=>a.pause());</script></html>'''
    (out/"listen.html").write_text(page, encoding="utf-8")
    return manifest


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument("--bpm", type=float, default=190.)
    args = parser.parse_args()
    report = build_pack(args.out, args.sample_rate, bpm=args.bpm)
    print(json.dumps({"revision": report["revision"], "files": len(report["files"]), "status": report["owner_status"]}))


if __name__ == "__main__":
    main()
