from __future__ import annotations

import argparse
import hashlib
import json
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

from zaaggenz_contracts.legacy import adapt_parameters, freeze_legacy
from zaaggenz_harmony import SonoritySpec, SonorityTone, VoiceSpec, VoicingConstraints, solve_progression
from zaaggenz_layers import (
    LayerGeneratorSpec,
    LayerPocketPlan,
    LayerRuntimeSpec,
    SidechainPocketSpec,
    render_coordinated_layers,
    render_coordinated_pockets,
)
from zaaggenz_melody import make_melodic_recipe, make_phrase_plan, note_event


def _sha(audio):
    return hashlib.sha256(np.asarray(audio, dtype="<f4").tobytes()).hexdigest()


def _rms(audio):
    a = np.asarray(audio, dtype=np.float64)
    return float(np.sqrt(np.mean(a * a))) if a.size else 0.0


def _wav(path, audio, sr):
    pcm = np.round(np.clip(np.asarray(audio, dtype=np.float64), -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm.tobytes())


def _sonority(root, name):
    return SonoritySpec(name, root, (
        SonorityTone("root", degree_offset=0),
        SonorityTone("third", degree_offset=4),
        SonorityTone("fifth", degree_offset=7),
    ))


def _render(sr):
    params = adapt_parameters("synth", {"sr": sr, "bpm": 180.0, "beats": 1, "f0_hz": 48.0})
    frozen = freeze_legacy(params).to_dict()
    tuning, time_map = frozen["tuning"], frozen["time_map"]
    phrase = make_phrase_plan(
        tuning["id"],
        [note_event("source-lead", "0/1", "1/1", tuning["id"], 12, gain_db=-18.0)],
        start_beat="0/1", end_beat="2/1", bass_role="pedal",
    )
    recipe = make_melodic_recipe(
        params, time_map, tuning, phrase, quality="standard", tail_mode="truncate", master_gain_db=-6.0,
    )
    voices = VoicingConstraints((
        VoiceSpec("sub", "sub", 20, 60, 34, anchor_policy="hold-first"),
        VoiceSpec("body", "body", 36, 90, 56),
        VoiceSpec("aux", "aux", 70, 150, 102),
        VoiceSpec("lead", "synthline", 105, 240, 160),
    ))
    progression = solve_progression(tuning, [_sonority(0, "home"), _sonority(5, "turn")], voices)
    runtime = LayerRuntimeSpec(tuple(
        LayerGeneratorSpec(role, "sine", -24.0, round(0.01 * sr), round(0.02 * sr), 0.125)
        for role in ("body", "aux", "sub")
    ))
    plan = LayerPocketPlan(
        (70.0, 600.0, 2500.0),
        sidechains=(SidechainPocketSpec(
            "body", "synthline", "lowmid", threshold_dbfs=-42.0,
            attack_samples=round(0.002 * sr), release_samples=round(0.025 * sr),
            lookahead_samples=round(0.003 * sr), max_attenuation_db=9.0,
        ),),
    )
    baseline = render_coordinated_layers(recipe, progression, ["0/1", "1/1"], "1/1", runtime)
    pocket = render_coordinated_pockets(recipe, progression, ["0/1", "1/1"], "1/1", runtime, plan)
    return recipe, progression, baseline, pocket, plan


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="zg030-pocket-fixtures.json")
    parser.add_argument("--audio-dir", default="zg030-pocket-listening")
    parser.add_argument("--sample-rate", type=int, default=12000)
    args = parser.parse_args(argv)
    if not 8000 <= args.sample_rate <= 48000:
        raise SystemExit("sample rate must be 8000..48000")

    outdir = Path(args.audio_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    recipe, progression, baseline, pocket, plan = _render(args.sample_rate)
    baseline_path = outdir / "matched-baseline.wav"
    pocket_path = outdir / "matched-body-yields-to-synthline.wav"
    _wav(baseline_path, baseline.mix, args.sample_rate)
    _wav(pocket_path, pocket.mix, args.sample_rate)

    operation = pocket.diagnostics["pockets"]["operations"][0]
    report = {
        "format": "zaaggenz-zg030-pocket-audition",
        "version": "1.0.0",
        "sample_rate_hz": args.sample_rate,
        "recipe_sha256": recipe.sha256,
        "progression_sha256": progression.sha256,
        "pocket_plan_sha256": plan.sha256,
        "matched_controls": {
            "same_recipe": True,
            "same_progression": True,
            "same_runtime_state": baseline.state.to_dict() == pocket.state.to_dict(),
            "same_synthline_pcm": _sha(baseline.stems["synthline"]) == _sha(pocket.stems["synthline"]),
            "same_exciter_pcm": _sha(baseline.stems["exciter"]) == _sha(pocket.stems["exciter"]),
            "same_sub_pcm": _sha(baseline.stems["sub"]) == _sha(pocket.stems["sub"]),
            "master_owner": pocket.diagnostics["final_master_owner"],
            "normalization": pocket.diagnostics["normalization"],
            "makeup_gain_db": pocket.diagnostics["pockets"]["makeup_gain_db"],
        },
        "baseline": {
            "mix_pcm_f32le_sha256": _sha(baseline.mix),
            "mix_rms": _rms(baseline.mix),
            "body_pcm_f32le_sha256": _sha(baseline.stems["body"]),
            "sub_pcm_f32le_sha256": _sha(baseline.stems["sub"]),
            "listening_copy": str(baseline_path),
        },
        "pocket": {
            "mix_pcm_f32le_sha256": _sha(pocket.mix),
            "mix_rms": _rms(pocket.mix),
            "body_pcm_f32le_sha256": _sha(pocket.stems["body"]),
            "sub_pcm_f32le_sha256": _sha(pocket.stems["sub"]),
            "observed_max_attenuation_db": operation["observed_max_attenuation_db"],
            "active_samples": operation["active_samples"],
            "band_delta": operation["band_delta"],
            "listening_copy": str(pocket_path),
        },
        "listening_copy_policy": "PCM16 clipped transport copies; canonical evidence is float32 hash",
        "interpretation": [
            "The pair is for level-aware owner audition; it is not a preference result.",
            "No proxy score selected the pocket or its controls.",
            "SYNTHLINE and SUB are intentionally retained byte-for-byte across the pair; BODY alone yields in the declared band/time envelope.",
        ],
    }
    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
