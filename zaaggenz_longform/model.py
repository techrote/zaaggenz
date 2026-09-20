"""Versioned long-form arrangement state above frozen Project/RenderRecipe contracts."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import re
import tempfile

from zaaggenz_contracts import Contract, digest, validate
from zaaggenz_contracts.legacy import envelope
from zaaggenz_contracts.model import check_json, fraction, loads
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_grammar import GrammarSpec
from zaaggenz_harmony import SonorityTone, VoiceSpec, VoicingConstraints
from zaaggenz_layers import (
    LayerGeneratorSpec,
    LayerPocketPlan,
    LayerRuntimeSpec,
    LayerTransformTarget,
    PocketAutomationPoint,
    SidechainPocketSpec,
    StaticPocketSpec,
)
from zaaggenz_project import Project
from zaaggenz_tuning import tuning_from_spec

FORMAT = "zaaggenz-longform-arrangement"
VERSION = "1.0.0"
MAX_MOTIFS = 64
MAX_MOTIF_EVENTS = 256
MAX_SECTIONS = 128
MAX_SECTION_REPEATS = 64
MAX_TOTAL_EVENTS = 4096
MAX_TOTAL_FRAMES = 5_000_000
MAX_GRAMMAR_SOURCES = 32
MAX_TUNINGS = 32
MAX_AUTOMATION_POINTS = 128
MAX_HARMONY_FRAMES = 128
_AUTOMATION_TARGETS = ("source_bus", "body", "aux", "sub")
_DEFERRED_INTENT = (
    "continuous-spectral-retuning",
    "adaptive-tuning",
    "timbral-gesture",
)
_ID = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")


class LongformError(ValueError):
    pass


def _exact(value, keys, name):
    if type(value) is not dict or set(value) != set(keys):
        raise LongformError(f"{name}: missing or unknown fields")


def _id(value, name):
    if type(value) is not str or not _ID.fullmatch(value):
        raise LongformError(f"{name}: lowercase identifier required")
    return value


def _text(value, name, maximum=1024):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise LongformError(f"{name}: non-empty text up to {maximum} characters required")
    if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in value):
        raise LongformError(f"{name}: control characters are not allowed")
    return value


def _number(value, low, high, name):
    if (
        type(value) not in (int, float)
        or type(value) is bool
        or not math.isfinite(float(value))
        or not low <= float(value) <= high
    ):
        raise LongformError(f"{name}: finite value in {low}..{high} required")
    return float(value)


def _integer(value, low, high, name):
    if type(value) is not int or type(value) is bool or not low <= value <= high:
        raise LongformError(f"{name}: integer {low}..{high} required")
    return value


def _rat(value, name):
    try:
        result = fraction(value)
    except (TypeError, ValueError) as exc:
        raise LongformError(f"{name}: exact rational required") from exc
    return result


def _rat_text(value):
    return f"{value.numerator}/{value.denominator}"


def runtime_spec_from_dict(data):
    _exact(data, {"generators", "transform_claims", "transform_targets"}, "layer_runtime")
    generators = []
    for index, row in enumerate(data["generators"]):
        _exact(
            row,
            {
                "role",
                "waveform",
                "gain_db",
                "glide_samples",
                "release_samples",
                "initial_phase_cycles",
            },
            f"layer_runtime.generators[{index}]",
        )
        generators.append(LayerGeneratorSpec(**row))
    targets = []
    for index, row in enumerate(data["transform_targets"]):
        _exact(
            row,
            {"layer", "quantity", "owner", "voice_id", "value"},
            f"layer_runtime.transform_targets[{index}]",
        )
        targets.append(LayerTransformTarget(**row))
    if type(data["transform_claims"]) is not list:
        raise LongformError("layer_runtime.transform_claims must be a list")
    return LayerRuntimeSpec(
        tuple(generators),
        tuple(deepcopy(data["transform_claims"])),
        tuple(targets),
    )


def voicing_constraints_from_dict(data):
    expected = {
        "voices",
        "min_spacing_cents",
        "movement_weight",
        "register_weight",
        "max_register_shifts",
        "candidate_cap_per_voice",
        "target_harmonics",
        "target_max_hz",
        "target_max_teeth",
    }
    _exact(data, expected, "voicing")
    voices = []
    for index, row in enumerate(data["voices"]):
        _exact(
            row,
            {
                "id",
                "role",
                "min_hz",
                "max_hz",
                "preferred_hz",
                "max_leap_cents",
                "anchor_policy",
                "fixed_hz",
            },
            f"voicing.voices[{index}]",
        )
        voices.append(VoiceSpec(**row))
    return VoicingConstraints(
        tuple(voices),
        min_spacing_cents=data["min_spacing_cents"],
        movement_weight=data["movement_weight"],
        register_weight=data["register_weight"],
        max_register_shifts=data["max_register_shifts"],
        candidate_cap_per_voice=data["candidate_cap_per_voice"],
        target_harmonics=data["target_harmonics"],
        target_max_hz=data["target_max_hz"],
        target_max_teeth=data["target_max_teeth"],
    )


def harmony_tones_from_dict(data):
    if type(data) is not list or not 1 <= len(data) <= 12:
        raise LongformError("harmony_template.tones must contain 1..12 tones")
    tones = []
    for index, row in enumerate(data):
        _exact(
            row,
            {"id", "degree_offset", "ratio", "detune_cents", "required"},
            f"harmony_template.tones[{index}]",
        )
        tones.append(SonorityTone(**row))
    return tuple(tones)


def pocket_plan_from_dict(data):
    if data is None:
        return None
    _exact(data, {"kind", "version", "pocket_id", "crossovers_hz", "static_pockets", "sidechains"}, "pocket_plan")
    if data["kind"] != "LayerPocketPlan" or data["version"] != "1.0.0" or data["pocket_id"] != "zaaggenz.layer-pockets":
        raise LongformError("pocket_plan policy/version mismatch")
    static = []
    for index, row in enumerate(data["static_pockets"]):
        _exact(row, {"kind", "yielding_role", "band", "points"}, f"static_pockets[{index}]")
        if row["kind"] != "static":
            raise LongformError("static pocket kind mismatch")
        points = []
        for pi, point in enumerate(row["points"]):
            _exact(point, {"sample", "attenuation_db"}, f"static_pockets[{index}].points[{pi}]")
            points.append(PocketAutomationPoint(point["sample"], point["attenuation_db"]))
        static.append(StaticPocketSpec(row["yielding_role"], row["band"], tuple(points)))
    sidechains = []
    for index, row in enumerate(data["sidechains"]):
        _exact(
            row,
            {
                "kind",
                "yielding_role",
                "detector_role",
                "band",
                "threshold_dbfs",
                "attack_samples",
                "release_samples",
                "lookahead_samples",
                "max_attenuation_db",
            },
            f"sidechains[{index}]",
        )
        if row["kind"] != "sidechain":
            raise LongformError("sidechain pocket kind mismatch")
        payload = dict(row)
        payload.pop("kind")
        sidechains.append(SidechainPocketSpec(**payload))
    return LayerPocketPlan(
        tuple(data["crossovers_hz"]),
        static_pockets=tuple(static),
        sidechains=tuple(sidechains),
    )


def _validate_curve(points, duration, low, high, name):
    if type(points) is not list:
        raise LongformError(f"{name}: points must be a list")
    if not points:
        return
    if len(points) > MAX_AUTOMATION_POINTS:
        raise LongformError(f"{name}: too many points")
    parsed = []
    for index, point in enumerate(points):
        _exact(point, {"beat", "value"}, f"{name}[{index}]")
        beat = _rat(point["beat"], f"{name}[{index}].beat")
        value = _number(point["value"], low, high, f"{name}[{index}].value")
        parsed.append((beat, value))
    if parsed[0][0] != 0 or parsed[-1][0] != duration:
        raise LongformError(f"{name}: curve must span exactly 0..event duration")
    if any(a[0] >= b[0] for a, b in zip(parsed, parsed[1:])):
        raise LongformError(f"{name}: point beats must be strictly increasing")


def _validate_motif(motif, grammar_ids):
    _exact(motif, {"id", "name", "length_beats", "origin", "events"}, "motif")
    _id(motif["id"], "motif.id")
    _text(motif["name"], "motif.name", 120)
    length = _rat(motif["length_beats"], "motif.length_beats")
    if not 0 < length <= 64:
        raise LongformError("motif.length_beats must be in (0,64]")
    _exact(motif["origin"], {"kind", "source_id"}, "motif.origin")
    if motif["origin"]["kind"] not in ("authored", "grammar"):
        raise LongformError("motif.origin.kind must be authored or grammar")
    _text(motif["origin"]["source_id"], "motif.origin.source_id", 128)
    if motif["origin"]["kind"] == "grammar" and motif["origin"]["source_id"] not in grammar_ids:
        raise LongformError("motif grammar origin is not present in grammar_sources")
    events = motif["events"]
    if type(events) is not list or not 1 <= len(events) <= MAX_MOTIF_EVENTS:
        raise LongformError(f"motif.events must contain 1..{MAX_MOTIF_EVENTS} events")
    ids = set()
    for index, row in enumerate(events):
        _exact(
            row,
            {
                "id",
                "beat",
                "duration_beats",
                "degree",
                "detune_cents",
                "gain_db",
                "roll_density",
                "pitch_curve_cents",
                "gain_curve_db",
            },
            f"motif.events[{index}]",
        )
        _id(row["id"], "motif event id")
        if row["id"] in ids:
            raise LongformError("duplicate motif event id")
        ids.add(row["id"])
        beat = _rat(row["beat"], "motif event beat")
        duration = _rat(row["duration_beats"], "motif event duration")
        if beat < 0 or duration <= 0 or beat + duration > length:
            raise LongformError("motif event lies outside motif")
        if row["degree"] is not None:
            _integer(row["degree"], -4096, 4096, "motif event degree")
        _number(row["detune_cents"], -4800, 4800, "motif event detune_cents")
        _number(row["gain_db"], -120, 24, "motif event gain_db")
        _integer(row["roll_density"], 0, 16, "motif event roll_density")
        if row["degree"] is None and (
            row["roll_density"] or row["pitch_curve_cents"] or row["gain_curve_db"]
        ):
            raise LongformError("rest motif events cannot carry pitch/gain/roll gestures")
        _validate_curve(
            row["pitch_curve_cents"],
            duration,
            -1200,
            1200,
            "motif event pitch_curve_cents",
        )
        _validate_curve(
            row["gain_curve_db"],
            duration,
            -24,
            24,
            "motif event gain_curve_db",
        )
    return length


def _section_time_map(section, sample_rate_hz):
    tempo = []
    for row in section["tempo_segments"]:
        tempo.append({"beat": row["beat"], "bpm": row["bpm"]})
    meter = []
    for row in section["meter_segments"]:
        meter.append(
            {
                "beat": row["beat"],
                "numerator": row["numerator"],
                "denominator": row["denominator"],
            }
        )
    document = envelope(
        "TimeMap",
        sample_rate_hz=sample_rate_hz,
        origin_sample=0,
        beat_unit="quarter_note",
        rounding="nearest_ties_even",
        tempo_segments=tempo,
        meter_segments=meter,
    )
    try:
        validate(document, "TimeMap")
    except Exception as exc:
        raise LongformError("section TimeMap is invalid") from exc
    return document


def _validate_section(section, motif_lengths, tuning_ids, sample_rate_hz):
    _exact(
        section,
        {
            "id",
            "name",
            "motif_id",
            "repeats",
            "tuning_id",
            "transpose_degrees",
            "gain_db",
            "bass_role",
            "tempo_segments",
            "meter_segments",
            "harmony_frames",
            "automation",
            "pocket_plan",
            "reset_roles",
            "deferred_intent",
        },
        "section",
    )
    _id(section["id"], "section.id")
    _text(section["name"], "section.name", 120)
    if section["motif_id"] not in motif_lengths:
        raise LongformError("section references unknown motif")
    repeats = _integer(section["repeats"], 1, MAX_SECTION_REPEATS, "section.repeats")
    if section["tuning_id"] not in tuning_ids:
        raise LongformError("section references unknown tuning")
    _integer(section["transpose_degrees"], -4096, 4096, "section.transpose_degrees")
    _number(section["gain_db"], -120, 24, "section.gain_db")
    if section["bass_role"] not in ("none", "pedal", "moving"):
        raise LongformError("section.bass_role must be none, pedal or moving")

    end = motif_lengths[section["motif_id"]] * repeats
    if end > 512:
        raise LongformError("section exceeds 512 quarter-note beats")

    tempo = section["tempo_segments"]
    if type(tempo) is not list or not 1 <= len(tempo) <= 64:
        raise LongformError("section tempo_segments must contain 1..64 entries")
    parsed_tempo = []
    for index, row in enumerate(tempo):
        _exact(row, {"beat", "bpm"}, f"tempo_segments[{index}]")
        beat = _rat(row["beat"], "tempo segment beat")
        bpm = _rat(row["bpm"], "tempo segment bpm")
        if not 20 <= bpm <= 360:
            raise LongformError("tempo must be in 20..360 BPM")
        parsed_tempo.append(beat)
    if parsed_tempo[0] != 0 or any(
        a >= b for a, b in zip(parsed_tempo, parsed_tempo[1:])
    ) or parsed_tempo[-1] >= end:
        raise LongformError("tempo segments must start at 0 and be ordered inside section")

    meter = section["meter_segments"]
    if type(meter) is not list or not 1 <= len(meter) <= 64:
        raise LongformError("section meter_segments must contain 1..64 entries")
    parsed_meter = []
    for index, row in enumerate(meter):
        _exact(
            row,
            {"beat", "numerator", "denominator"},
            f"meter_segments[{index}]",
        )
        beat = _rat(row["beat"], "meter segment beat")
        _integer(row["numerator"], 1, 32, "meter numerator")
        if row["denominator"] not in (1, 2, 4, 8, 16, 32):
            raise LongformError("meter denominator must be 1,2,4,8,16,32")
        parsed_meter.append(beat)
    if parsed_meter[0] != 0 or any(
        a >= b for a, b in zip(parsed_meter, parsed_meter[1:])
    ) or parsed_meter[-1] >= end:
        raise LongformError("meter segments must start at 0 and be ordered inside section")

    time_map = _section_time_map(section, sample_rate_hz)
    frames = beat_to_sample(time_map, _rat_text(end)) - beat_to_sample(time_map, "0/1")
    if frames <= 0:
        raise LongformError("section rounds to zero samples")

    harmony = section["harmony_frames"]
    if type(harmony) is not list or not 1 <= len(harmony) <= MAX_HARMONY_FRAMES:
        raise LongformError("section harmony_frames must be bounded/non-empty")
    prior_end = Fraction(0)
    for index, row in enumerate(harmony):
        _exact(row, {"beat", "duration_beats", "root_degree"}, f"harmony_frames[{index}]")
        beat = _rat(row["beat"], "harmony beat")
        duration = _rat(row["duration_beats"], "harmony duration")
        _integer(row["root_degree"], -4096, 4096, "harmony root_degree")
        if beat < prior_end or duration <= 0 or beat + duration > end:
            raise LongformError("harmony frames must be ordered, non-overlapping and inside section")
        prior_end = beat + duration

    automation = section["automation"]
    if type(automation) is not list or len(automation) > len(_AUTOMATION_TARGETS):
        raise LongformError("section automation must contain at most one curve per accepted target")
    targets = set()
    for index, row in enumerate(automation):
        _exact(row, {"target", "interpolation", "points"}, f"automation[{index}]")
        if row["target"] not in _AUTOMATION_TARGETS or row["target"] in targets:
            raise LongformError("automation target must be unique source_bus/body/aux/sub")
        targets.add(row["target"])
        if row["interpolation"] not in ("linear", "step"):
            raise LongformError("automation interpolation must be linear or step")
        _validate_curve(
            row["points"],
            end,
            -120,
            24,
            f"automation[{index}].points",
        )
        if not row["points"]:
            raise LongformError("section automation curve cannot be empty")

    pocket = pocket_plan_from_dict(section["pocket_plan"])
    if pocket is not None:
        for spec in pocket.static_pockets:
            if spec.points and spec.points[-1].sample > frames:
                raise LongformError("static pocket sample lies beyond section extent")

    reset = section["reset_roles"]
    if type(reset) is not list or len(reset) != len(set(reset)) or not set(reset) <= {"body", "aux", "sub"}:
        raise LongformError("reset_roles must be unique BODY/AUX/SUB names")

    deferred = section["deferred_intent"]
    if (
        type(deferred) is not list
        or len(deferred) != len(set(deferred))
        or not set(deferred) <= set(_DEFERRED_INTENT)
    ):
        raise LongformError("deferred_intent contains unsupported or duplicate entries")

    return end, frames


@dataclass(frozen=True, init=False)
class LongformDocument:
    _json: str

    def __init__(self, document):
        try:
            check_json(document)
        except (TypeError, ValueError) as exc:
            raise LongformError("long-form document exceeds JSON bounds") from exc
        _exact(
            document,
            {
                "format",
                "version",
                "name",
                "base_project",
                "tunings",
                "grammar_sources",
                "motifs",
                "sections",
                "layer_runtime",
                "voicing",
                "harmony_template",
                "export_policy",
            },
            "longform",
        )
        if document["format"] != FORMAT or document["version"] != VERSION:
            raise LongformError("unsupported long-form format/version")
        _text(document["name"], "name", 160)

        try:
            project = Project.from_document(document["base_project"])
            base = project.head_recipe.to_dict()
            validate(base, "RenderRecipe")
        except Exception as exc:
            raise LongformError("base_project must be a valid current Project v1 document") from exc
        if (
            base["render_mode"] != "synth"
            or base["arrangement"] is not None
            or base["reversebass"] is not None
            or base["phrase"] is not None
            or base["channels"] != 1
        ):
            raise LongformError(
                "base_project head must be a phrase-free mono synth recipe; "
                "legacy arrangement/bass ownership is not silently rebound"
            )
        sample_rate = base["source"]["params"]["sr"]
        if type(sample_rate) is not int or not 8000 <= sample_rate <= 192000:
            raise LongformError("base project sample rate outside accepted range")

        tunings = document["tunings"]
        if type(tunings) is not list or not 1 <= len(tunings) <= MAX_TUNINGS:
            raise LongformError(f"tunings must contain 1..{MAX_TUNINGS} TuningSpec values")
        tuning_ids = set()
        for row in tunings:
            try:
                tuning = tuning_from_spec(row)
            except Exception as exc:
                raise LongformError("invalid TuningSpec in long-form document") from exc
            if tuning.id in tuning_ids:
                raise LongformError("duplicate long-form tuning id")
            tuning_ids.add(tuning.id)

        grammars = document["grammar_sources"]
        if type(grammars) is not list or len(grammars) > MAX_GRAMMAR_SOURCES:
            raise LongformError("too many grammar_sources")
        grammar_ids = set()
        for row in grammars:
            try:
                grammar = GrammarSpec(row)
            except Exception as exc:
                raise LongformError("invalid grammar source") from exc
            gid = grammar.to_dict()["id"]
            if gid in grammar_ids:
                raise LongformError("duplicate grammar source id")
            grammar_ids.add(gid)

        motifs = document["motifs"]
        if type(motifs) is not list or not 1 <= len(motifs) <= MAX_MOTIFS:
            raise LongformError(f"motifs must contain 1..{MAX_MOTIFS} entries")
        motif_lengths = {}
        for motif in motifs:
            if not isinstance(motif, dict) or "id" not in motif:
                raise LongformError("motif must contain an id and the exact long-form motif fields")
            motif_id = motif["id"]
            if motif_id in motif_lengths:
                raise LongformError("duplicate motif id")
            motif_lengths[motif_id] = _validate_motif(motif, grammar_ids)

        runtime_spec_from_dict(document["layer_runtime"])
        voicing_constraints_from_dict(document["voicing"])
        template = document["harmony_template"]
        _exact(template, {"tones", "bass_tone_id"}, "harmony_template")
        tones = harmony_tones_from_dict(template["tones"])
        if template["bass_tone_id"] is not None and template["bass_tone_id"] not in {tone.id for tone in tones}:
            raise LongformError("harmony_template bass_tone_id is not present in tones")

        sections = document["sections"]
        if type(sections) is not list or not 1 <= len(sections) <= MAX_SECTIONS:
            raise LongformError(f"sections must contain 1..{MAX_SECTIONS} entries")
        section_ids = set()
        total_events = 0
        total_frames = 0
        motif_by_id = {row["id"]: row for row in motifs}
        for section in sections:
            if section.get("id") in section_ids:
                raise LongformError("duplicate section id")
            section_ids.add(section["id"])
            _, frames = _validate_section(
                section, motif_lengths, tuning_ids, sample_rate
            )
            total_frames += frames
            total_events += len(motif_by_id[section["motif_id"]]["events"]) * section["repeats"]
        if total_events > MAX_TOTAL_EVENTS:
            raise LongformError(f"long-form expansion exceeds {MAX_TOTAL_EVENTS} events")
        if total_frames > MAX_TOTAL_FRAMES:
            raise LongformError(
                f"long-form arrangement exceeds {MAX_TOTAL_FRAMES} samples; "
                "split into explicit export parts rather than allocating unbounded stems"
            )

        policy = document["export_policy"]
        _exact(
            policy,
            {"simple_note_export", "include_source_bus", "include_pre_master"},
            "export_policy",
        )
        for key, value in policy.items():
            if type(value) is not bool:
                raise LongformError(f"export_policy.{key} must be boolean")

        object.__setattr__(
            self,
            "_json",
            json.dumps(
                document,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )

    def to_dict(self):
        return loads(self._json)

    @property
    def sha256(self):
        return digest(self.to_dict())

    @property
    def base_project(self):
        return Project.from_document(self.to_dict()["base_project"])

    @property
    def base_recipe(self):
        return self.base_project.head_recipe

    @property
    def sample_rate_hz(self):
        return self.base_recipe.to_dict()["source"]["params"]["sr"]

    @property
    def layer_runtime(self):
        return runtime_spec_from_dict(self.to_dict()["layer_runtime"])

    @property
    def voicing(self):
        return voicing_constraints_from_dict(self.to_dict()["voicing"])

    @property
    def harmony_tones(self):
        return harmony_tones_from_dict(self.to_dict()["harmony_template"]["tones"])

    @property
    def tuning_map(self):
        return {row["id"]: deepcopy(row) for row in self.to_dict()["tunings"]}

    @property
    def motif_map(self):
        return {row["id"]: deepcopy(row) for row in self.to_dict()["motifs"]}

    def section_time_map(self, section):
        row = section if isinstance(section, dict) else next(
            item for item in self.to_dict()["sections"] if item["id"] == section
        )
        return _section_time_map(row, self.sample_rate_hz)

    def section_end_beat(self, section):
        row = section if isinstance(section, dict) else next(
            item for item in self.to_dict()["sections"] if item["id"] == section
        )
        motif = self.motif_map[row["motif_id"]]
        return _rat(motif["length_beats"], "motif.length_beats") * row["repeats"]

    @classmethod
    def from_json(cls, text):
        return cls(loads(text))


def save_longform(document, path):
    if not isinstance(document, LongformDocument):
        raise LongformError("LongformDocument required")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(document._json + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_longform(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(2_000_001)
    if len(raw) > 2_000_000:
        raise LongformError("long-form document exceeds 2 MB")
    return LongformDocument.from_json(raw)
