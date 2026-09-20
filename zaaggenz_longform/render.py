"""Long-form section compilation and aligned stem rendering for ZG-043."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math

import numpy as np

from zaaggenz_contracts import Contract
from zaaggenz_contracts.legacy import envelope
from zaaggenz_contracts.model import fraction
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_dsp.graph import GraphError, apply_output_policy
from zaaggenz_harmony import SonoritySpec, solve_progression
from zaaggenz_layers import apply_layer_pockets
from zaaggenz_melody import (
    make_phrase_plan,
    note_event,
    render_phrase,
    rest_event,
    transform_melodic_recipe,
)
from zaaggenz_performance import (
    LayerSection,
    estimate_persistent_sequence,
    render_persistent_sections,
)
from zaaggenz_tuning import tuning_from_spec

from .model import LongformDocument, LongformError, pocket_plan_from_dict

STEM_NAMES = (
    "synthline",
    "exciter",
    "source_bus",
    "body",
    "aux",
    "sub",
    "pre_master",
)


@dataclass(frozen=True)
class LongformRenderResult:
    mix: np.ndarray
    stems: dict
    sample_rate_hz: int
    section_ranges: tuple
    note_events: tuple
    final_runtime_state: dict
    diagnostics: dict

    def __post_init__(self):
        mix = np.asarray(self.mix, dtype=np.float32)
        mix.setflags(write=False)
        object.__setattr__(self, "mix", mix)
        frozen = {}
        for name, value in self.stems.items():
            audio = np.asarray(value, dtype=np.float32)
            audio.setflags(write=False)
            frozen[name] = audio
        object.__setattr__(self, "stems", frozen)
        object.__setattr__(self, "section_ranges", tuple(deepcopy(self.section_ranges)))
        object.__setattr__(self, "note_events", tuple(deepcopy(self.note_events)))
        object.__setattr__(self, "final_runtime_state", deepcopy(self.final_runtime_state))
        object.__setattr__(self, "diagnostics", deepcopy(self.diagnostics))


@dataclass(frozen=True)
class _CompiledSection:
    section: dict
    time_map: dict
    tuning: dict
    recipe: Contract
    progression: object
    frame_beats: tuple
    frame_durations: tuple
    layer_section: LayerSection
    note_rows: tuple
    nominal_samples: int


def _rat(value):
    value = fraction(value)
    return f"{value.numerator}/{value.denominator}"


def _gesture_curve(axis, unit, interpolation, points):
    return {
        "axis": axis,
        "unit": unit,
        "interpolation": interpolation,
        "points": [deepcopy(point) for point in points],
    }


def _compile_phrase(document, section, motif, tuning):
    motif_length = fraction(motif["length_beats"])
    events = []
    gestures = []
    rows = []
    transpose = section["transpose_degrees"]
    section_gain = float(section["gain_db"])

    for repeat in range(section["repeats"]):
        offset = repeat * motif_length
        for source in motif["events"]:
            beat = offset + fraction(source["beat"])
            event_id = f"{section['id']}-{repeat:02d}-{source['id']}"
            duration = source["duration_beats"]
            if source["degree"] is None:
                events.append(rest_event(event_id, _rat(beat), duration))
                rows.append(
                    {
                        "event_id": event_id,
                        "section_id": section["id"],
                        "motif_id": motif["id"],
                        "repeat": repeat,
                        "beat": _rat(beat),
                        "duration_beats": duration,
                        "rest": True,
                        "degree": None,
                        "detune_cents": 0.0,
                        "gain_db": float(source["gain_db"]) + section_gain,
                        "pitch_curve_cents": [],
                    }
                )
                continue

            gain = float(source["gain_db"]) + section_gain
            if not -120.0 <= gain <= 24.0:
                raise LongformError(
                    f"section {section['id']} event {source['id']} effective gain "
                    "lies outside frozen PhrasePlan -120..24 dB"
                )
            degree = int(source["degree"]) + int(transpose)
            curves = []
            if source["pitch_curve_cents"]:
                curves.append(
                    _gesture_curve(
                        "pitch_cents",
                        "cents",
                        "linear",
                        source["pitch_curve_cents"],
                    )
                )
            if source["gain_curve_db"]:
                curves.append(
                    _gesture_curve(
                        "gain_db",
                        "dB",
                        "linear",
                        source["gain_curve_db"],
                    )
                )
            if source["roll_density"] > 1:
                curves.append(
                    _gesture_curve(
                        "density_per_beat",
                        "events/beat",
                        "step",
                        [{"beat": "0/1", "value": float(source["roll_density"])}],
                    )
                )
            gesture_id = None
            if curves:
                gesture_id = f"g-{event_id}"
                gestures.append(
                    envelope(
                        "GestureSpec",
                        id=gesture_id,
                        duration_beats=duration,
                        curves=curves,
                    )
                )
            events.append(
                note_event(
                    event_id,
                    _rat(beat),
                    duration,
                    tuning["id"],
                    degree,
                    detune_cents=source["detune_cents"],
                    gain_db=gain,
                    gesture_id=gesture_id,
                )
            )
            rows.append(
                {
                    "event_id": event_id,
                    "section_id": section["id"],
                    "motif_id": motif["id"],
                    "repeat": repeat,
                    "beat": _rat(beat),
                    "duration_beats": duration,
                    "rest": False,
                    "degree": degree,
                    "detune_cents": float(source["detune_cents"]),
                    "gain_db": gain,
                    "pitch_curve_cents": deepcopy(source["pitch_curve_cents"]),
                }
            )

    end = motif_length * section["repeats"]
    phrase = make_phrase_plan(
        tuning["id"],
        events,
        start_beat="0/1",
        end_beat=_rat(end),
        gestures=gestures,
        bass_role=section["bass_role"],
        seed=section["id"],
    )
    return phrase, tuple(rows)


def _section_recipe(document, section, motif, tuning):
    phrase, rows = _compile_phrase(document, section, motif, tuning)
    base = document.base_recipe.to_dict()
    time_map = document.section_time_map(section)
    base["time_map"] = deepcopy(time_map)
    base["tuning"] = deepcopy(tuning)
    # The one-shot source is tempo-aware in the recovered renderer; make the
    # authored section's entry tempo explicit without changing any other source
    # parameter or protected topology.
    base["source"]["params"]["bpm"] = float(fraction(section["tempo_segments"][0]["bpm"]))
    base["source"]["params"]["sr"] = document.sample_rate_hz
    try:
        base_contract = Contract(base)
        recipe = transform_melodic_recipe(
            base_contract,
            phrase,
            quality=None,
            tail_mode="truncate",
            master_gain_db=base["output"]["master_gain_db"],
        )
    except Exception as exc:
        raise LongformError(
            f"section {section['id']} could not preserve the base source/topology contract"
        ) from exc
    return recipe, time_map, rows


def _section_progression(document, section, tuning):
    tones = document.harmony_tones
    template = document.to_dict()["harmony_template"]
    sonorities = []
    frame_beats = []
    durations = []
    transpose = int(section["transpose_degrees"])
    for index, row in enumerate(section["harmony_frames"]):
        sonorities.append(
            SonoritySpec(
                f"{section['id']}-h{index:03d}",
                int(row["root_degree"]) + transpose,
                tones,
                bass_tone_id=template["bass_tone_id"],
                context_id=section["id"],
            )
        )
        frame_beats.append(row["beat"])
        durations.append(row["duration_beats"])
    try:
        progression = solve_progression(
            tuning,
            sonorities,
            document.voicing,
        )
    except Exception as exc:
        raise LongformError(
            f"section {section['id']} harmony intent is not executable under its tuning"
        ) from exc
    return progression, tuple(frame_beats), tuple(durations)


def compile_sections(document):
    if not isinstance(document, LongformDocument):
        raise LongformError("LongformDocument required")
    data = document.to_dict()
    motifs = document.motif_map
    tunings = document.tuning_map
    compiled = []
    for section in data["sections"]:
        motif = motifs[section["motif_id"]]
        tuning_spec = tunings[section["tuning_id"]]
        tuning = tuning_from_spec(tuning_spec)
        recipe, time_map, note_rows = _section_recipe(
            document, section, motif, tuning_spec
        )
        progression, frame_beats, frame_durations = _section_progression(
            document, section, tuning
        )
        end_beat = document.section_end_beat(section)
        nominal = beat_to_sample(time_map, _rat(end_beat)) - beat_to_sample(
            time_map, "0/1"
        )
        layer_section = LayerSection(
            recipe,
            progression,
            frame_beats,
            frame_durations,
            section["id"],
            tuple(section["reset_roles"]),
        )
        compiled.append(
            _CompiledSection(
                deepcopy(section),
                deepcopy(time_map),
                deepcopy(tuning_spec),
                recipe,
                progression,
                frame_beats,
                frame_durations,
                layer_section,
                note_rows,
                nominal,
            )
        )
    # Reuse the accepted ZG-042 sequence-memory authority here. The subsequent
    # render_persistent_sections() call independently performs its stricter
    # continuation/unfinished-glide preflight before retained PCM allocation.
    estimate_persistent_sequence(tuple(row.layer_section for row in compiled))
    return tuple(compiled)


def _gain_envelope(curve, time_map, end_beat, n_samples):
    if curve is None:
        return np.ones(n_samples, dtype=np.float64)
    positions = []
    values = []
    origin = beat_to_sample(time_map, "0/1")
    for point in curve["points"]:
        positions.append(beat_to_sample(time_map, point["beat"]) - origin)
        values.append(float(point["value"]))
    positions = np.asarray(positions, dtype=np.int64)
    values = np.asarray(values, dtype=np.float64)
    if positions[0] != 0 or positions[-1] != n_samples:
        # The document validator requires exact 0..section-end beat coverage.
        # Rounding is checked again here because tempo changes can make adjacent
        # rational beats share a sample under pathological maps.
        expected = beat_to_sample(time_map, _rat(end_beat)) - origin
        if positions[0] != 0 or positions[-1] != expected:
            raise LongformError("automation sample extent disagrees with section")
    x = np.arange(n_samples, dtype=np.float64)
    if curve["interpolation"] == "linear":
        db = np.interp(x, positions.astype(np.float64), values)
    else:
        db = np.empty(n_samples, dtype=np.float64)
        cursor = 0
        current = values[0]
        for pos, value in zip(positions, values):
            pos = min(n_samples, int(pos))
            db[cursor:pos] = current
            current = value
            cursor = pos
        db[cursor:] = current
    return np.power(10.0, db / 20.0)


def _automation_map(section):
    return {row["target"]: row for row in section["automation"]}


def _sha_audio(audio):
    return hashlib.sha256(np.asarray(audio, dtype="<f4").tobytes()).hexdigest()


def _is_12edo(tuning):
    ratios = tuning["degree_ratios"]
    if len(ratios) != 12 or not math.isclose(float(tuning["period_ratio"]), 2.0, rel_tol=0, abs_tol=1e-12):
        return False
    return all(
        math.isclose(float(value), 2.0 ** (index / 12.0), rel_tol=1e-10, abs_tol=1e-12)
        for index, value in enumerate(ratios)
    )


def _midi_note_if_exact(hz):
    if hz <= 0:
        return None
    value = 69.0 + 12.0 * math.log2(float(hz) / 440.0)
    nearest = round(value)
    if 0 <= nearest <= 127 and abs(value - nearest) <= 1e-7:
        return int(nearest)
    return None


def _absolute_note_rows(compiled, section_start, tuning):
    t = tuning_from_spec(tuning)
    origin = beat_to_sample(compiled.time_map, "0/1")
    rows = []
    for source in compiled.note_rows:
        start = beat_to_sample(compiled.time_map, source["beat"]) - origin
        end = beat_to_sample(
            compiled.time_map,
            _rat(fraction(source["beat"]) + fraction(source["duration_beats"])),
        ) - origin
        row = deepcopy(source)
        row["tuning_id"] = tuning["id"]
        row["start_sample"] = section_start + start
        row["duration_samples"] = end - start
        row["start_seconds"] = (section_start + start) / compiled.recipe.to_dict()["time_map"]["sample_rate_hz"]
        row["duration_seconds"] = (end - start) / compiled.recipe.to_dict()["time_map"]["sample_rate_hz"]
        if source["rest"]:
            row["frequency_hz"] = None
            row["midi_note_12tet"] = None
        else:
            hz = t.frequency(source["degree"], source["detune_cents"])
            row["frequency_hz"] = float(hz)
            row["midi_note_12tet"] = (
                _midi_note_if_exact(hz)
                if _is_12edo(tuning)
                and not source["pitch_curve_cents"]
                and abs(source["detune_cents"]) <= 1e-12
                else None
            )
        rows.append(row)
    return rows


def render_longform(document):
    if not isinstance(document, LongformDocument):
        raise LongformError("LongformDocument required")
    compiled = compile_sections(document)
    layer_sections = tuple(row.layer_section for row in compiled)

    # ZG-042 owns persistent state continuity and representability. SYNTHLINE and
    # exciter are explicitly muted inside this path; only BODY/AUX/SUB retained
    # products and state are consumed below.
    try:
        persistent = render_persistent_sections(
            layer_sections,
            document.layer_runtime,
            muted_roles=("synthline", "exciter"),
        )
    except Exception as exc:
        raise LongformError("persistent long-form section rendering failed") from exc

    total = sum(row.nominal_samples for row in compiled)
    if len(persistent.mix) != total:
        raise LongformError("persistent render extent disagrees with long-form preflight")
    buffers = {
        name: np.zeros(total, dtype=np.float64)
        for name in ("synthline", "exciter", "source_bus", "body", "aux", "sub")
    }
    persistent_stems = {
        role: np.asarray(persistent.stems[role], dtype=np.float64)
        for role in ("body", "aux", "sub")
    }

    note_rows = []
    section_ranges = []
    section_diagnostics = []
    first_motif_section = {}
    cursor = 0

    for compiled_section in compiled:
        section = compiled_section.section
        n = compiled_section.nominal_samples
        end = cursor + n
        try:
            source = render_phrase(compiled_section.recipe)
        except Exception as exc:
            raise LongformError(
                f"section {section['id']} source render failed"
            ) from exc
        for role in ("synthline", "exciter", "pre_master"):
            if len(source.stems[role]) != n:
                raise LongformError(
                    f"section {section['id']} source/roll tail crosses the explicit "
                    "section boundary; add a rest or shorten the source gesture"
                )

        raw_synthline = np.asarray(source.stems["synthline"], dtype=np.float64)
        raw_exciter = np.asarray(source.stems["exciter"], dtype=np.float64)
        source_bus = np.asarray(source.stems["pre_master"], dtype=np.float64)
        pocket_input = {
            "synthline": raw_synthline,
            "exciter": raw_exciter,
            "body": persistent_stems["body"][cursor:end].copy(),
            "aux": persistent_stems["aux"][cursor:end].copy(),
            "sub": persistent_stems["sub"][cursor:end].copy(),
        }
        pocket_plan = pocket_plan_from_dict(section["pocket_plan"])
        pocket_diag = None
        if pocket_plan is not None:
            try:
                pocket_output, pocket_diag = apply_layer_pockets(
                    pocket_input,
                    document.sample_rate_hz,
                    pocket_plan,
                )
            except Exception as exc:
                raise LongformError(
                    f"section {section['id']} pocket plan failed"
                ) from exc
        else:
            pocket_output = pocket_input

        automation = _automation_map(section)
        end_beat = document.section_end_beat(section)
        source_bus *= _gain_envelope(
            automation.get("source_bus"),
            compiled_section.time_map,
            end_beat,
            n,
        )
        for role in ("body", "aux", "sub"):
            pocket_output[role] = np.asarray(pocket_output[role], dtype=np.float64)
            pocket_output[role] *= _gain_envelope(
                automation.get(role),
                compiled_section.time_map,
                end_beat,
                n,
            )

        buffers["synthline"][cursor:end] = raw_synthline
        buffers["exciter"][cursor:end] = raw_exciter
        buffers["source_bus"][cursor:end] = source_bus
        for role in ("body", "aux", "sub"):
            buffers[role][cursor:end] = pocket_output[role]

        tuning = compiled_section.tuning
        note_rows.extend(
            _absolute_note_rows(compiled_section, cursor, tuning)
        )
        return_of = first_motif_section.get(section["motif_id"])
        if return_of is None:
            first_motif_section[section["motif_id"]] = section["id"]
        section_ranges.append(
            {
                "id": section["id"],
                "name": section["name"],
                "motif_id": section["motif_id"],
                "return_of_section_id": return_of,
                "start_sample": cursor,
                "end_sample": end,
                "frame_count": n,
                "start_seconds": cursor / document.sample_rate_hz,
                "end_seconds": end / document.sample_rate_hz,
                "tuning_id": section["tuning_id"],
                "tempo_segments": deepcopy(section["tempo_segments"]),
                "meter_segments": deepcopy(section["meter_segments"]),
                "automation": deepcopy(section["automation"]),
                "deferred_intent": list(section["deferred_intent"]),
                "pocket_plan_sha256": None if pocket_plan is None else pocket_plan.sha256,
            }
        )
        section_diagnostics.append(
            {
                "section_id": section["id"],
                "recipe_sha256": compiled_section.recipe.sha256,
                "progression_sha256": compiled_section.progression.sha256,
                "source_diagnostics": deepcopy(source.diagnostics),
                "pockets": deepcopy(pocket_diag),
            }
        )
        cursor = end

    pre_master = (
        buffers["source_bus"]
        + buffers["body"]
        + buffers["aux"]
        + buffers["sub"]
    )
    base = document.base_recipe.to_dict()
    try:
        mix, master_diag = apply_output_policy(pre_master, base["output"])
    except GraphError as exc:
        raise LongformError("long-form final master failed") from exc

    buffers["pre_master"] = pre_master
    stems = {
        name: np.asarray(buffers[name], dtype=np.float32)
        for name in STEM_NAMES
    }
    mix = np.asarray(mix, dtype=np.float32)
    if any(len(audio) != len(mix) for audio in stems.values()):
        raise AssertionError("long-form stem alignment bug")

    diagnostics = {
        "kind": "ZG043LongformRender",
        "version": "1.0.0",
        "document_sha256": document.sha256,
        "sample_rate_hz": document.sample_rate_hz,
        "frame_count": len(mix),
        "duration_seconds": len(mix) / document.sample_rate_hz,
        "section_count": len(compiled),
        "tail_latency_policy": {
            "source_phrase_tail": "truncate-at-explicit-section-boundary; crossing source/roll tails fail closed",
            "persistent_layer_tail": "ZG-042 LayerRuntimeState continues across representable section boundaries",
            "pocket_latency": "ZG-030 offline zero-phase effect-delta; no shifted dry path",
            "final_master": "one RenderRecipe.output stage after all source/persistent/pocket/automation assembly",
        },
        "automation_stage": "post-source-topology/post-ZG030-pocket, pre-final-master contribution gain",
        "raw_source_stems": "synthline/exciter remain unautomated audition/provenance stems",
        "final_master_owner": "render-recipe.output",
        "normalization": base["output"]["normalisation"],
        "master": deepcopy(master_diag),
        "stem_sha256": {name: _sha_audio(audio) for name, audio in stems.items()},
        "mix_sha256": _sha_audio(mix),
        "sections": section_diagnostics,
    }
    return LongformRenderResult(
        mix,
        stems,
        document.sample_rate_hz,
        tuple(section_ranges),
        tuple(note_rows),
        persistent.state.to_dict(),
        diagnostics,
    )
