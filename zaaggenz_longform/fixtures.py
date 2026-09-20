"""Deterministic original ZG-043 long-form fixtures; no reference audio or preference claim."""
from __future__ import annotations

from copy import deepcopy

from zaaggenz_contracts.legacy import envelope, freeze_legacy
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_grammar import starter_grammars
from zaaggenz_harmony import SonorityTone, VoiceSpec, VoicingConstraints
from zaaggenz_layers import (
    LayerGeneratorSpec,
    LayerPocketPlan,
    LayerRuntimeSpec,
    PocketAutomationPoint,
    StaticPocketSpec,
)
from zaaggenz_project import Project

from .model import LongformDocument


def _twelve_edo():
    return envelope(
        "TuningSpec",
        id="twelve-edo-a1",
        reference_hz=55.0,
        reference_degree=0,
        period_ratio=2.0,
        degree_ratios=[2.0 ** (index / 12.0) for index in range(12)],
        keyboard=None,
    )


def _thirteen_ed3():
    return envelope(
        "TuningSpec",
        id="thirteen-ed3-a1",
        reference_hz=55.0,
        reference_degree=0,
        period_ratio=3.0,
        degree_ratios=[3.0 ** (index / 13.0) for index in range(13)],
        keyboard=None,
    )


def _base_project(sample_rate_hz, bpm):
    from uptempo_harmony.multiband import SCULPT_PRESETS
    from uptempo_harmony.synth import PRESETS

    params = {
        **PRESETS["locked_bloom"].to_dict(),
        "sr": int(sample_rate_hz),
        "bpm": float(bpm),
        "beats": 1,
    }
    recipe = freeze_legacy(
        params,
        mode="synth",
        sculpt=SCULPT_PRESETS["gentle_separation"].to_dict(),
        master_gain_db=-6.0,
    )
    return Project(recipe).to_document()


def _runtime():
    return LayerRuntimeSpec(
        tuple(
            LayerGeneratorSpec(
                role,
                "sine",
                {"body": -31.0, "aux": -34.0, "sub": -27.0}[role],
                glide_samples=64,
                release_samples=512,
                initial_phase_cycles=0.125,
            )
            for role in ("body", "aux", "sub")
        )
    ).to_dict()


def _voicing():
    return VoicingConstraints(
        (
            VoiceSpec("sub", "sub", 20.0, 72.0, 36.0, max_leap_cents=1800.0),
            VoiceSpec("body", "body", 36.0, 132.0, 68.0, max_leap_cents=2200.0),
            VoiceSpec("aux", "aux", 70.0, 250.0, 118.0, max_leap_cents=2400.0),
            VoiceSpec("lead", "synthline", 95.0, 330.0, 180.0, max_leap_cents=2600.0),
        ),
        min_spacing_cents=0.0,
        movement_weight=1.0,
        register_weight=0.06,
        max_register_shifts=32,
        candidate_cap_per_voice=128,
        target_harmonics=12,
        target_max_hz=12000.0,
        target_max_teeth=128,
    ).to_dict()


def _harmony_template():
    return {
        "tones": [
            SonorityTone("root", degree_offset=0).to_dict(),
            SonorityTone("third", degree_offset=4).to_dict(),
            SonorityTone("fifth", degree_offset=7).to_dict(),
        ],
        "bass_tone_id": "root",
    }


def _event(
    event_id,
    beat,
    duration,
    degree,
    *,
    detune=0.0,
    gain=-24.0,
    roll=0,
    pitch_curve=(),
    gain_curve=(),
):
    return {
        "id": event_id,
        "beat": beat,
        "duration_beats": duration,
        "degree": degree,
        "detune_cents": float(detune),
        "gain_db": float(gain),
        "roll_density": int(roll),
        "pitch_curve_cents": [deepcopy(row) for row in pitch_curve],
        "gain_curve_db": [deepcopy(row) for row in gain_curve],
    }


def _motifs():
    return [
        {
            "id": "pulse-a",
            "name": "Pulse A",
            "length_beats": "4/1",
            "origin": {"kind": "authored", "source_id": "zg043-original-pulse-a"},
            "events": [
                _event("a0", "0/1", "1/2", 8, gain=-23.0),
                _event("a1", "1/1", "1/1", 12, gain=-24.0, roll=4),
                _event("a2", "2/1", "1/1", None, gain=-120.0),
                _event("a3", "3/1", "1/2", 10, gain=-25.0),
            ],
        },
        {
            "id": "answer-b",
            "name": "Answer B",
            "length_beats": "4/1",
            "origin": {"kind": "grammar", "source_id": "synthetic-step-return"},
            "events": [
                _event("b0", "0/1", "1/1", 7, gain=-25.0),
                _event("b1", "1/1", "1/1", 9, detune=7.0, gain=-25.0),
                _event("b2", "2/1", "1/1", 12, gain=-26.0),
                _event("b3", "3/1", "1/1", None, gain=-120.0),
            ],
        },
        {
            "id": "bend-c",
            "name": "Bend C",
            "length_beats": "4/1",
            "origin": {"kind": "authored", "source_id": "zg043-original-bend-c"},
            "events": [
                _event(
                    "c0",
                    "0/1",
                    "3/2",
                    9,
                    gain=-25.0,
                    pitch_curve=(
                        {"beat": "0/1", "value": 0.0},
                        {"beat": "3/4", "value": 37.0},
                        {"beat": "3/2", "value": -19.0},
                    ),
                ),
                _event("c1", "2/1", "1/2", None, gain=-120.0),
                _event(
                    "c2",
                    "3/1",
                    "1/1",
                    13,
                    gain=-26.0,
                    gain_curve=(
                        {"beat": "0/1", "value": -3.0},
                        {"beat": "1/2", "value": 2.0},
                        {"beat": "1/1", "value": -1.0},
                    ),
                ),
            ],
        },
        {
            "id": "return-d",
            "name": "Return D",
            "length_beats": "4/1",
            "origin": {"kind": "grammar", "source_id": "synthetic-step-return"},
            "events": [
                _event("d0", "0/1", "1/2", 12, gain=-25.0),
                _event("d1", "1/1", "1/2", 10, gain=-25.0),
                _event("d2", "2/1", "1/2", 8, gain=-25.0),
                _event("d3", "3/1", "1/1", 7, gain=-26.0),
            ],
        },
    ]


def _time_map(sample_rate_hz, tempo_segments, meter_segments):
    return envelope(
        "TimeMap",
        sample_rate_hz=sample_rate_hz,
        origin_sample=0,
        beat_unit="quarter_note",
        rounding="nearest_ties_even",
        tempo_segments=deepcopy(tempo_segments),
        meter_segments=deepcopy(meter_segments),
    )


def _pocket(sample_rate_hz, tempo_segments, meter_segments, end_beat):
    tm = _time_map(sample_rate_hz, tempo_segments, meter_segments)
    end = beat_to_sample(tm, end_beat)
    quarter = max(1, end // 4)
    return LayerPocketPlan(
        (60.0, min(500.0, sample_rate_hz * 0.12), min(1800.0, sample_rate_hz * 0.40)),
        static_pockets=(
            StaticPocketSpec(
                "body",
                "lowmid",
                (
                    PocketAutomationPoint(0, 0.0),
                    PocketAutomationPoint(quarter, 0.0),
                    PocketAutomationPoint(quarter + 1, 6.0),
                    PocketAutomationPoint(max(quarter + 2, end // 2), 6.0),
                    PocketAutomationPoint(max(quarter + 3, end - quarter), 0.0),
                    PocketAutomationPoint(end, 0.0),
                ),
            ),
        ),
    ).to_dict()


def _section(
    section_id,
    name,
    motif_id,
    *,
    repeats,
    tuning_id,
    bpm,
    roots=(0, 5),
    transpose=0,
    gain_db=0.0,
    automation=(),
    meter_segments=None,
    tempo_segments=None,
    pocket_plan=None,
    reset_roles=(),
    deferred_intent=(),
):
    end = 4 * repeats
    if tempo_segments is None:
        tempo_segments = [{"beat": "0/1", "bpm": f"{int(bpm)}/1"}]
    if meter_segments is None:
        meter_segments = [{"beat": "0/1", "numerator": 4, "denominator": 4}]
    half = end // 2
    harmony = [
        {"beat": "0/1", "duration_beats": f"{half}/1", "root_degree": int(roots[0])},
        {
            "beat": f"{half}/1",
            "duration_beats": f"{end - half}/1",
            "root_degree": int(roots[1]),
        },
    ]
    return {
        "id": section_id,
        "name": name,
        "motif_id": motif_id,
        "repeats": int(repeats),
        "tuning_id": tuning_id,
        "transpose_degrees": int(transpose),
        "gain_db": float(gain_db),
        "bass_role": "moving",
        "tempo_segments": deepcopy(tempo_segments),
        "meter_segments": deepcopy(meter_segments),
        "harmony_frames": harmony,
        "automation": [deepcopy(row) for row in automation],
        "pocket_plan": deepcopy(pocket_plan),
        "reset_roles": list(reset_roles),
        "deferred_intent": list(deferred_intent),
    }


def _curve(target, end_beat, mid_value_db, *, interpolation="linear"):
    end = int(end_beat)
    half = end // 2
    return {
        "target": target,
        "interpolation": interpolation,
        "points": [
            {"beat": "0/1", "value": 0.0},
            {"beat": f"{half}/1", "value": float(mid_value_db)},
            {"beat": f"{end}/1", "value": 0.0},
        ],
    }


def _document(name, sample_rate_hz, sections):
    grammar = starter_grammars()["step-return"].to_dict()
    return LongformDocument(
        {
            "format": "zaaggenz-longform-arrangement",
            "version": "1.0.0",
            "name": name,
            "base_project": _base_project(sample_rate_hz, 128.0),
            "tunings": [_twelve_edo(), _thirteen_ed3()],
            "grammar_sources": [grammar],
            "motifs": _motifs(),
            "sections": sections,
            "layer_runtime": _runtime(),
            "voicing": _voicing(),
            "harmony_template": _harmony_template(),
            "export_policy": {
                "simple_note_export": True,
                "include_source_bus": True,
                "include_pre_master": True,
            },
        }
    )


def structured_90s_example(sample_rate_hz=12000):
    tempos = [124, 128, 132, 126, 130, 128, 134, 126, 132, 128, 124, 130]
    motif_cycle = [
        "pulse-a",
        "answer-b",
        "pulse-a",
        "bend-c",
        "return-d",
        "answer-b",
        "pulse-a",
        "bend-c",
        "return-d",
        "pulse-a",
        "answer-b",
        "pulse-a",
    ]
    sections = []
    for index, (bpm, motif) in enumerate(zip(tempos, motif_cycle)):
        sid = f"s{index:02d}"
        end = 16
        tempo_segments = [{"beat": "0/1", "bpm": f"{bpm}/1"}]
        if index in (3, 8):
            tempo_segments = [
                {"beat": "0/1", "bpm": f"{bpm}/1"},
                {"beat": "8/1", "bpm": f"{bpm + 8}/1"},
            ]
        meter = [{"beat": "0/1", "numerator": 4, "denominator": 4}]
        if index == 6:
            meter = [
                {"beat": "0/1", "numerator": 4, "denominator": 4},
                {"beat": "8/1", "numerator": 7, "denominator": 8},
            ]
        automation = ()
        if index in (4, 9):
            automation = (
                _curve("source_bus", end, -1.5),
                _curve("body", end, -3.0),
            )
        pocket = None
        if index == 7:
            pocket = _pocket(sample_rate_hz, tempo_segments, meter, f"{end}/1")
        sections.append(
            _section(
                sid,
                f"Structured section {index + 1}",
                motif,
                repeats=4,
                tuning_id="twelve-edo-a1",
                bpm=bpm,
                roots=(0, 5 if index % 2 == 0 else 7),
                transpose=(index % 3) - 1,
                gain_db=-1.0 if index in (5, 10) else 0.0,
                automation=automation,
                meter_segments=meter,
                tempo_segments=tempo_segments,
                pocket_plan=pocket,
            )
        )
    return _document("ZG-043 structured ~90 second example", sample_rate_hz, sections)


def stress_64bar_example(sample_rate_hz=12000):
    motifs = ("pulse-a", "answer-b", "bend-c", "return-d")
    sections = []
    for index in range(16):
        bpm = 196 + (index % 4) * 4
        end = 16
        tempo_segments = [{"beat": "0/1", "bpm": f"{bpm}/1"}]
        if index % 5 == 2:
            tempo_segments = [
                {"beat": "0/1", "bpm": f"{bpm}/1"},
                {"beat": "8/1", "bpm": f"{bpm + 12}/1"},
            ]
        tuning_id = "thirteen-ed3-a1" if index in (5, 6, 7, 12, 13) else "twelve-edo-a1"
        deferred = ()
        if index == 6:
            deferred = ("continuous-spectral-retuning",)
        elif index == 12:
            deferred = ("adaptive-tuning", "timbral-gesture")
        automation = ()
        if index % 4 == 1:
            automation = (
                _curve("aux", end, -4.0),
                _curve("sub", end, 1.5),
            )
        meter = [{"beat": "0/1", "numerator": 4, "denominator": 4}]
        sections.append(
            _section(
                f"x{index:02d}",
                f"64-bar stress section {index + 1}",
                motifs[index % len(motifs)],
                repeats=4,
                tuning_id=tuning_id,
                bpm=bpm,
                roots=(index % 5, (index + 4) % 8),
                transpose=(index % 3) - 1,
                gain_db=0.0,
                automation=automation,
                meter_segments=meter,
                tempo_segments=tempo_segments,
                deferred_intent=deferred,
            )
        )
    return _document("ZG-043 64-bar stress construction", sample_rate_hz, sections)


def small_test_example(sample_rate_hz=8000):
    sections = [
        _section(
            "test-a",
            "Test A",
            "pulse-a",
            repeats=1,
            tuning_id="twelve-edo-a1",
            bpm=240,
            roots=(0, 5),
            automation=(_curve("body", 4, -2.0),),
        ),
        _section(
            "test-b",
            "Test B",
            "answer-b",
            repeats=1,
            tuning_id="thirteen-ed3-a1",
            bpm=220,
            roots=(0, 4),
            deferred_intent=("timbral-gesture",),
        ),
    ]
    return _document("ZG-043 small test", sample_rate_hz, sections)
