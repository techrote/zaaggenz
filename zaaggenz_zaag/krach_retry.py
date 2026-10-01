"""ZG-022/#232 v2 audition: coherent sources, local distortion, unshaped low body.

The v1 Krach recipes and all owner-approved presets are historical inputs, not
mutated or automatically promoted. These four new IDs are audition-only.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, replace
from pathlib import Path
import hashlib
import json
import math
import re

import numpy as np
from scipy import signal

from zaaggenz_contracts.legacy import adapt_parameters, legacy_object
from .model import ZaagFamilyError, canonical_sha256
from .registry import family

REVISION = "zg022-krach-retry-232-v2"
SOURCE_METHOD = "zg.krach-coherent-body-surface.v2"
OVERSAMPLE = 4


@dataclass(frozen=True)
class RetryRecipe:
    id: str
    label: str
    parent_id: str
    mechanism: str
    body_gain: float
    surface_gain: float
    motion: float
    drive: float
    cutoff_hz: float
    sweep_semitones: float
    classification: str = "krach-candidate"

    def __post_init__(self):
        if type(self.id) is not str or not re.fullmatch(r"zaag\.krach-v2-[a-z0-9-]{1,40}", self.id):
            raise ZaagFamilyError("versioned retry ID required")
        if type(self.label) is not str or not re.fullmatch(r"[A-Za-z0-9 -]{1,64}", self.label):
            raise ZaagFamilyError("bounded filename-safe label required")
        if self.parent_id not in ("zaag.split-maul", "zaag.upper-chop", "zaag.formant-snarl", "zaag.bloom-bark"):
            raise ZaagFamilyError("declared approved source substrate required")
        if self.mechanism not in ("pressure", "bounce", "vowel", "motor"):
            raise ZaagFamilyError("unknown retry mechanism")
        bounds = {"body_gain": (0., 3.), "surface_gain": (0., 3.),
                  "motion": (0., 1.), "drive": (1., 8.),
                  "cutoff_hz": (1500., 5500.), "sweep_semitones": (-4., 0.)}
        for key, (lo, hi) in bounds.items():
            value = getattr(self, key)
            if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
                raise ZaagFamilyError(f"{key} must be finite in [{lo}, {hi}]")
        if self.classification != "krach-candidate":
            raise ZaagFamilyError("retry recipes cannot self-approve")

    def to_dict(self):
        return {"revision": REVISION, **asdict(self),
                "parent_recipe_sha256": family(self.parent_id).sha256}

    @property
    def sha256(self):
        return canonical_sha256(self.to_dict())


RECIPES = (
    RetryRecipe("zaag.krach-v2-pressure", "Pressure Roll", "zaag.split-maul", "pressure", 1.20, 1.20, .75, 4.5, 2600., -1.8),
    RetryRecipe("zaag.krach-v2-bounce", "Rubber Bounce", "zaag.upper-chop", "bounce", 1.10, 1.50, .90, 4.5, 3800., -1.4),
    RetryRecipe("zaag.krach-v2-throat", "Throat Motor", "zaag.formant-snarl", "vowel", 1.35, 1.05, .85, 5.0, 3600., -2.2),
    RetryRecipe("zaag.krach-v2-steel", "Rounded Steel", "zaag.bloom-bark", "motor", .90, 1.50, .80, 5.5, 4600., -1.1),
)


def retry_candidates():
    return RECIPES


def _finite_number(value, name, lo, hi):
    if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
        raise ZaagFamilyError(f"{name} must be finite in [{lo}, {hi}]")
    return float(value)


def _filter(x, sr, hz, kind="lowpass", order=3):
    sos = signal.butter(order, hz, btype=kind, fs=sr, output="sos")
    return signal.sosfilt(sos, x)


def _band(x, sr, lo, hi):
    return _filter(x, sr, [lo, hi], "bandpass", 2)


def _resonance(x, sr, hz, q=1.7):
    b, a = signal.iirpeak(hz, q, fs=sr)
    return signal.lfilter(b, a, x)


def _edges(x, sr, attack_ms=2., release_ms=8.):
    y = np.asarray(x, dtype=np.float64).copy()
    for is_start, ms in ((True, attack_ms), (False, release_ms)):
        n = min(len(y)//2, max(2, round(sr * ms / 1000.)))
        ramp = .5 - .5 * np.cos(np.linspace(0., np.pi, n))
        if is_start:
            y[:n] *= ramp
        else:
            y[-n:] *= ramp[::-1]
    return y


def render_retry_source(recipe: RetryRecipe, sample_rate_hz=48000, *, bpm=190.):
    """Return finite mono float32 PCM and an explicit source identity manifest.

    Four-times oversampling surrounds the *whole* nonlinear source/character
    path. Rate-dependent antialiasing is separate from the authored tone cutoff.
    No waveform/peak/RMS gain matching is done after the authored source mix.
    """
    if not isinstance(recipe, RetryRecipe):
        raise ZaagFamilyError("RetryRecipe required")
    if type(sample_rate_hz) is not int or sample_rate_hz not in (12000, 48000):
        raise ZaagFamilyError("retry output rate must be 12000 or 48000 Hz")
    bpm = _finite_number(bpm, "bpm", 60., 260.)
    parent = family(recipe.parent_id)
    # Use the accepted family's recovered-source substrate, not its rendered WAV
    # and not a reconstructed protected preset. Remove stochastic texture at its
    # origin instead of covering it with a final dark EQ.
    overrides = {**parent.synth_overrides,
        "sr": sample_rate_hz, "bpm": bpm, "beats": 1, "beat_fill": .985,
        "noise_level": 0., "roughness": 0., "pitch_jitter_cents": 0.,
        "harmonic_lock_cents": 0., "transient_click": 0.,
        "harmonic_count": 49, "harmonic_decay": .69,
        "harmonic_tilt_db_per_oct": -.6, "odd_even_ratio": 1.95,
        "sweep_semitones": recipe.sweep_semitones, "sweep_tau_ms": 45.,
        "input_trim_db": -4., "drive_db": 13., "shaper_mix": .92,
        "hard_clip_mix": .30, "hard_clip_level": .78, "hard_clip_makeup": 0.,
        "wavefold": .65, "preemphasis": .025, "asymmetry": .10,
        "attack_ms": 2.5, "decay_ms": 430., "sustain": .10,
        "post_hp_hz": 22., "post_lp_hz": 15000., "peak": .90}
    params = adapt_parameters("synth", overrides)
    high_sr = sample_rate_hz * OVERSAMPLE
    high_params = replace(legacy_object("synth", params), sr=high_sr)
    from uptempo_harmony.synth import synthesize_one
    base, debug = synthesize_one(high_params)
    x = base.astype(np.float64)
    t = np.arange(len(x), dtype=np.float64) / high_sr
    beats = t * bpm / 60.
    phase = 2. * np.pi * np.cumsum(debug["f0"]) / high_sr
    body = _filter(x, high_sr, 280.)
    surface = _filter(x, high_sr, 190., "highpass")
    m = recipe.motion
    if recipe.mechanism == "pressure":
        # Smooth fold-depth bloom changes harmonic structure, without adding
        # independent high-frequency/noise oscillators to the low body.
        swell = .5 - .5 * np.cos(2. * np.pi * beats)
        folded = np.sin((2.0 + 2.1 * m * swell) * x)
        throat = _resonance(folded, high_sr, 520., 1.4)
        shaped = np.tanh(recipe.drive * (.60 * surface + .50 * folded + 1.1 * throat))
        shaped *= .78 + .22 * swell
    elif recipe.mechanism == "bounce":
        # Rounded dual-rate modulation replaces sample-discontinuous gates.
        roll = .5 + .5 * np.sin(2. * np.pi * beats * 4. - .6)
        chatter = .5 + .5 * np.sin(2. * np.pi * beats * 8. + .3)
        mid = _band(surface, high_sr, 240., 1700.)
        top = _band(surface, high_sr, 1500., 3800.)
        z = mid * (1. - .78*m + .78*m*roll) + .60 * top * (1. - .88*m + .88*m*chatter)
        shaped = .72*np.tanh(recipe.drive*z) + .28*np.sin(3.2*z)
    elif recipe.mechanism == "vowel":
        # Broad, moving formants fed from the same coherent source. They do not
        # claim physiological vocal modelling or reference-chain recovery.
        cross = .5 - .5 * np.cos(2.*np.pi*beats)
        a = _resonance(surface, high_sr, 430., 1.6)
        b = _resonance(surface, high_sr, 1250., 1.8)
        c = _resonance(surface, high_sr, 2200., 1.5)
        z = .42*surface + 2.8*m*((1.-cross)*a + cross*b) + .30*c
        shaped = .70*np.tanh(recipe.drive*z) + .30*np.sin(3.6*z)
    else:
        # Pitch-synchronous sidebands and soft rhythmic articulation; no free
        # running ring oscillator, sample hold, bitcrusher, or air boost.
        roll = .5 + .5*np.sin(2.*np.pi*beats*8.)
        locked_ring = np.sin(3.*phase + .6*m*np.sin(2.*np.pi*beats))
        z = surface*(.85 + .28*m*locked_ring)
        shaped = .70*np.tanh(recipe.drive*z) + .30*np.sin(4.5*z)
        shaped *= 1. - .65*m + .65*m*roll
    shaped = _filter(shaped, high_sr, 240., "highpass")
    shaped = _filter(shaped, high_sr, recipe.cutoff_hz, order=4)
    # Crucial ordering: no clipping/bitcrush/tanh of the reunited low+surface.
    mix = recipe.body_gain*body + recipe.surface_gain*shaped
    sustain = (1. - np.exp(-t/.0025)) * (.75 + .25*np.exp(-t/.28))
    mix *= sustain
    audio = signal.resample_poly(mix, 1, OVERSAMPLE, window=("kaiser", 10.))
    n = round(sample_rate_hz*60./bpm*.985)
    audio = _edges(audio[:n], sample_rate_hz).astype(np.float32)
    if len(audio) != n or not np.isfinite(audio).all():
        raise ZaagFamilyError("invalid retry source output")
    info = {"method": SOURCE_METHOD, "revision": REVISION, "recipe": recipe.to_dict(),
        "recipe_sha256": recipe.sha256, "source_parameters": params,
        "sample_rate_hz": sample_rate_hz, "oversampling": OVERSAMPLE,
        "internal_rate_hz": high_sr, "samples": len(audio),
        "source_pcm_sha256": hashlib.sha256(audio.astype("<f4").tobytes()).hexdigest(),
        "peak": float(np.max(np.abs(audio))),
        "rms": float(np.sqrt(np.mean(audio.astype(np.float64)**2))),
        "output_normalization": "none", "source_internal_peak_policy": "recovered source peak=0.90 before authored body/surface split",
        "boundary_envelope_ms": {"attack": 2., "release": 8.},
        "status": "pending-owner", "production_promoted": False}
    return audio, info


def _level_match(audio, target_dbfs=-14., peak_limit=.92):
    """One linear gain for an entire item; never clip/limit/compress it."""
    x = np.asarray(audio, dtype=np.float64)
    if x.ndim != 1 or not len(x) or not np.isfinite(x).all():
        raise ZaagFamilyError("nonempty finite mono audio required")
    rms = float(np.sqrt(np.mean(x*x)))
    peak = float(np.max(np.abs(x)))
    if rms <= 1e-12 or peak <= 1e-12:
        raise ZaagFamilyError("silent item cannot be an audition candidate")
    gain = min(10.**(target_dbfs/20.)/rms, peak_limit/peak)
    y = (x*gain).astype(np.float32)
    return y, {"gain_db": 20.*math.log10(gain), "target_rms_dbfs": target_dbfs,
               "achieved_rms_dbfs": 20.*math.log10(float(np.sqrt(np.mean(y.astype(float)**2)))),
               "peak": float(np.max(np.abs(y))), "processing": "one constant gain; no compression or limiter"}


def render_retry_phrase(source, sr=48000, *, bpm=190., melodic=False, bars=8):
    """Use the source-preserving pitch engine and explicit sampler note gates.

    Root loops have one source hit per beat, not overlapping half-beat hits.
    Melody uses the earlier audition's eight-note pattern and explicit six-ms
    release gates. No time-varying source mutation or random seed changes.
    """
    from zaaggenz_melody.pitch import pitch_shift_static
    if type(sr) is not int or sr not in (12000, 48000):
        raise ZaagFamilyError("unsupported phrase sample rate")
    bpm = _finite_number(bpm, "bpm", 60., 260.)
    if type(bars) is not int or not 1 <= bars <= 16 or type(melodic) is not bool:
        raise ZaagFamilyError("bars must be integer 1..16 and melodic must be bool")
    source = np.asarray(source)
    if source.ndim != 1 or not 64 <= len(source) <= sr or not np.isfinite(source).all():
        raise ZaagFamilyError("finite mono source with 64..sample-rate frames required")
    spb = sr*60./bpm
    out = np.zeros(round(bars*4*spb), dtype=np.float64)
    per_beat = 2 if melodic else 1
    degrees = (0, 3, 5, 7, 5, 3, -2, 0)
    cache = {0: np.asarray(source, dtype=np.float32)}
    for i in range(bars*4*per_beat):
        degree = degrees[i % 8] if melodic else 0
        if degree not in cache:
            cache[degree] = pitch_shift_static(source, 2.**(degree/12.), fft_size=2048)
        start, end = round(i*spb/per_beat), round((i+1)*spb/per_beat)
        n = min(len(cache[degree]), end-start)
        wave = _edges(cache[degree][:n], sr, 1.5, 6.)
        gain = (1., .94, .98, .94)[i % 4]
        out[start:start+n] += wave*gain
    return out.astype(np.float32)


def _filter_performance(audio, sr):
    """Presentation-only dark-to-open crossfade; raw loop is also exported."""
    x = np.asarray(audio, dtype=np.float64)
    low = _filter(x, sr, 160.)
    dark = _filter(x, sr, 500.)
    open_ = _filter(x, sr, 4400.)
    u = np.linspace(0., 1., len(x), endpoint=False)
    sweep = np.sin(np.pi*u)**2
    return _edges(low + (1.-sweep)*(dark-low) + sweep*(open_-low), sr).astype(np.float32)


def _write_pcm24(path, audio, sr):
    import wave
    x = np.asarray(audio, dtype=np.float64)
    if x.ndim != 1 or not np.isfinite(x).all() or np.max(np.abs(x), initial=0.) >= 1.:
        raise ZaagFamilyError("finite mono sub-full-scale WAV required")
    integers = np.rint(x * 8388607).astype("<i4")
    raw = integers.view(np.uint8).reshape(-1, 4)[:, :3].copy().tobytes()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(3)
        handle.setframerate(sr)
        handle.writeframes(raw)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_retry_pack(destination, sample_rate_hz=48000, *, bpm=190.):
    """Export four candidates, a quick comparison and a local HTML player."""
    import html
    from .registry import PRODUCTION_PRESET_IDS
    if type(sample_rate_hz) is not int or sample_rate_hz not in (12000, 48000):
        raise ZaagFamilyError("pack sample rate must be 12000 or 48000 Hz")
    bpm = _finite_number(bpm, "bpm", 60., 260.)
    out = Path(destination)
    if out.exists() and any(out.iterdir()):
        raise ZaagFamilyError("use an empty pack destination; never overwrite an audition")
    out.mkdir(parents=True, exist_ok=True)
    entries, medley, cards = [], [], []
    now = 0.
    for index, recipe in enumerate(RECIPES, 1):
        source, info = render_retry_source(recipe, sample_rate_hz, bpm=bpm)
        root = render_retry_phrase(source, sample_rate_hz, bpm=bpm, bars=8)
        melody = render_retry_phrase(source, sample_rate_hz, bpm=bpm, melodic=True, bars=4)
        folder = f"{index:02d}_" + recipe.label.lower().replace(" ", "-")
        choices = (("01_source.wav", "Source", source),
                   ("02_root-loop.wav", "Unprocessed 8-bar root loop", root),
                   ("03_melody.wav", "4-bar melodic demo", melody),
                   ("04_filter-performance.wav", "Presentation-only filter sweep", _filter_performance(root, sample_rate_hz)))
        exports = []
        for filename, label, audio in choices:
            matched, level = _level_match(audio)
            rel = folder + "/" + filename
            sha = _write_pcm24(out / rel, matched, sample_rate_hz)
            exports.append({"path": rel, "label": label, "sha256": sha,
                            "duration_s": len(audio)/sample_rate_hz, "matching": level})
        matched_root, _ = _level_match(root)
        # Four bars per candidate, with an audible gap and exact cue positions.
        excerpt = matched_root[:round(16*sample_rate_hz*60./bpm)]
        info["comparison_start_s"] = now
        now += len(excerpt)/sample_rate_hz + .75
        medley.extend((excerpt, np.zeros(round(.75*sample_rate_hz), dtype=np.float32)))
        info["exports"] = exports
        entries.append(info)
        players = "".join(f'<label>{html.escape(e["label"])}<audio controls preload="none" loop src="{html.escape(e["path"])}"></audio></label>' for e in exports)
        cards.append(f'<section><h2>{index:02d} / {html.escape(recipe.label)}</h2>{players}</section>')
    comparison = np.concatenate(medley[:-1])
    comparison_name = "00_START_HERE_four-candidate-comparison.wav"
    comparison_sha = _write_pcm24(out / comparison_name, comparison, sample_rate_hz)
    report = {"revision": REVISION, "sample_rate_hz": sample_rate_hz, "bpm": bpm,
        "pcm_format": "24-bit signed PCM WAV, mono", "owner_status": "pending-owner",
        "previous_pack_disposition": "all four v1 Krach candidates rejected: scratchy and nasty in a bad way",
        "production_default": "locked_bloom", "production_presets_unchanged": list(PRODUCTION_PRESET_IDS),
        "renderer_file_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "dependencies": {"numpy": np.__version__, "scipy": __import__("scipy").__version__},
        "comparison": {"path": comparison_name, "sha256": comparison_sha, "duration_s": len(comparison)/sample_rate_hz},
        "source_ownership": "new original synthesis; no reference recording audio copied or embedded",
        "note_policy": "source-derived pitch_shift_static; explicit 1.5-ms attack and 6-ms sampler release; no tail overlap",
        "ratings": ["bounce", "melodic_identity", "source_character", "usefulness"],
        "rating_scale": [1, 7], "owner_decisions": [], "candidates": entries}
    (out / "manifest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")
    cues = "\n".join(f'- {e["comparison_start_s"]:.2f}s: {e["recipe"]["label"]}' for e in entries)
    readme = f'''# ZaagGenZ — Krach retry v2

Start with `{comparison_name}`, then the unprocessed root loops. Or extract this
ZIP and open `listen.html`. The browser player works locally without a server.
All audio is {sample_rate_hz} Hz, mono, 24-bit PCM, at {bpm:g} BPM.

## Comparison cues
{cues}

## Four new designs
Pressure Roll: heavy rounded body, slowly changing folded harmonics.
Rubber Bounce: coherent body with soft-edged, two-rate midrange pulses.
Throat Motor: broad moving vowel resonances, not broadband scratching.
Rounded Steel: pitch-locked motor texture, inspired by the approved Upper Chop's
repeatability rather than the rejected Air Teeth's high-band emphasis.

Each folder contains source, dry repeated-root loop, melodic demo and a separate
filter-performance example. The filter sweep is audition presentation only;
it is NOT baked into the source sound. Root loops are deliberately one hit per
beat. The melody uses the same eight-note pattern for all four candidates,
source-derived pitch shifting, and explicit short sampler release gates.

These are newly synthesized attempts, not low-passed copies of the rejected
pack. Broadband noise, random transient clicks, detuned partial attacks,
unsynchronised ring oscillators and sample-hold/bitcrushing are absent. The
source and character stage run at four times the output rate before filtered
decimation. The low body is mixed back AFTER surface distortion. Every file
uses a single constant matching gain: no master compressor, limiter or clipping.

All four remain audition-only. No quality claim follows from the diagnostics;
owner listening determines whether the retry is actually an improvement.
The six previously approved presets and locked_bloom are not modified.

Optional feedback: KEEP / MODIFY / REJECT for each, with what still sounds wrong.
The prior four 1–7 endpoints remain available, but scores are not required.

## Reproduction
In the ZaagGenZ checkout, with its authenticated source materialized and declared
NumPy/SciPy dependencies installed:
`PYTHONPATH=app:. python -m zaaggenz_zaag.krach_retry --out NEW_EMPTY_FOLDER`
On Windows set PYTHONPATH to `app;.` before running the Python command.
The exact renderer source and regression tests are supplied in `reproduction/`.
Place them at their matching paths in the checkout. `manifest.json` records
recipes, source settings, method, environment, sample rate and WAV hashes.
'''
    (out / "README.md").write_text(readme, encoding="utf-8")
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ZaagGenZ / Krach v2</title>
<style>body{margin:0 auto;padding:32px 24px;max-width:980px;background:#15171b;color:#eee;font:17px/1.5 system-ui,sans-serif}h1{font-size:36px;margin:4px 0 12px}p{max-width:78ch;color:#bac0c9}section{border-top:1px solid #444;padding:20px 0}h2{margin:0 0 15px;font-size:24px}label{display:block;margin:12px 0;font-size:14px;color:#ccd3df}audio{display:block;width:100%;margin:5px 0 16px}a{color:#a5d4ff}.tag{font-size:13px;letter-spacing:.12em;color:#9ba4b3}button{font:inherit;padding:8px 18px;background:#30353e;color:white;border:1px solid #666;border-radius:5px;cursor:pointer}</style>
<div class="tag">ZAAGGENZ / OWNER AUDITION / VERSION 2</div><h1>Weight and movement. Less scratch.</h1><p>Four replacement attempts. Start with the comparison, then use the raw root loops. These are not approved production presets.</p>
<button onclick="document.querySelectorAll('audio').forEach(a=>a.pause())">Stop all</button><section><h2>Start here / all four</h2><audio controls preload="metadata" src="''' + comparison_name + '''"></audio><p>Pressure Roll → Rubber Bounce → Throat Motor → Rounded Steel</p></section>''' + "".join(cards) + '''<p>Loops repeat automatically. The filter-performance clips add presentation-only processing. No reference recordings are included. No network connection is used.</p><script>document.querySelectorAll('audio').forEach(a=>a.addEventListener('play',()=>document.querySelectorAll('audio').forEach(b=>{if(a!==b)b.pause()})));</script></html>'''
    (out / "listen.html").write_text(page, encoding="utf-8")
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument("--bpm", type=float, default=190.)
    args = parser.parse_args()
    result = build_retry_pack(args.out, args.sample_rate, bpm=args.bpm)
    print(json.dumps({"revision": result["revision"], "candidates": len(result["candidates"]),
                      "sample_rate_hz": result["sample_rate_hz"], "status": result["owner_status"]}))


if __name__ == "__main__":
    main()
