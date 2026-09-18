from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import math

import numpy as np

from zaaggenz_contracts import Contract, digest, ownership_manifest, validate
from zaaggenz_contracts.model import fraction
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_contracts.ownership import OwnershipConflict, validate_section_transition
from zaaggenz_dsp.graph import GraphError, apply_output_policy
from zaaggenz_harmony import ProgressionResult
from zaaggenz_melody import render_phrase
from zaaggenz_melody.render import _apply_preserved_topology

RUNTIME_ID = "zaaggenz.layer-runtime"
RUNTIME_VERSION = "1.0.0"
_PERSISTENT_ROLES = ("body", "aux", "sub")
_ALL_ROLES = ("synthline", "exciter", "body", "aux", "sub")


class LayerRuntimeError(ValueError):
    def __init__(self, diagnostic):
        self.diagnostic = deepcopy(diagnostic)
        super().__init__(self.diagnostic.get("message", "layer runtime error"))


def _fail(code, message, **details):
    raise LayerRuntimeError({
        "kind": "LayerRuntimeDiagnostic",
        "version": RUNTIME_VERSION,
        "runtime_id": RUNTIME_ID,
        "code": code,
        "message": message,
        **deepcopy(details),
    })


def _finite(value, name, lo=None, hi=None):
    if type(value) not in (int, float) or type(value) is bool or not math.isfinite(float(value)):
        _fail("invalid-runtime-value", f"{name} must be finite numeric", field=name)
    value = float(value)
    if lo is not None and value < lo:
        _fail("invalid-runtime-value", f"{name} is below its bound", field=name, value=value, minimum=lo)
    if hi is not None and value > hi:
        _fail("invalid-runtime-value", f"{name} is above its bound", field=name, value=value, maximum=hi)
    return value


@dataclass(frozen=True)
class LayerGeneratorSpec:
    role: str
    waveform: str
    gain_db: float
    glide_samples: int
    release_samples: int
    initial_phase_cycles: float = 0.0

    def __post_init__(self):
        if self.role not in _PERSISTENT_ROLES:
            _fail("invalid-generator-role", "persistent generator role must be body, aux or sub", role=self.role)
        if self.waveform != "sine":
            _fail("unsupported-generator", "v1 persistent runtime requires an explicitly selected sine generator", role=self.role, waveform=self.waveform)
        _finite(self.gain_db, "gain_db", -120.0, 24.0)
        if type(self.glide_samples) is not int or type(self.glide_samples) is bool or not 0 <= self.glide_samples <= 10_000_000:
            _fail("invalid-runtime-value", "glide_samples must be an integer in 0..10000000", field="glide_samples")
        if type(self.release_samples) is not int or type(self.release_samples) is bool or not 0 <= self.release_samples <= 10_000_000:
            _fail("invalid-runtime-value", "release_samples must be an integer in 0..10000000", field="release_samples")
        phase = _finite(self.initial_phase_cycles, "initial_phase_cycles", 0.0, 1.0)
        if phase == 1.0:
            object.__setattr__(self, "initial_phase_cycles", 0.0)

    def to_dict(self):
        return {
            "role": self.role,
            "waveform": self.waveform,
            "gain_db": float(self.gain_db),
            "glide_samples": self.glide_samples,
            "release_samples": self.release_samples,
            "initial_phase_cycles": float(self.initial_phase_cycles),
        }


@dataclass(frozen=True)
class LayerTransformTarget:
    layer: str
    quantity: str
    owner: str
    value: float
    voice_id: str = "*"

    def __post_init__(self):
        if self.layer not in _PERSISTENT_ROLES:
            _fail("invalid-transform-target", "runtime transforms may target persistent roles only", layer=self.layer)
        if self.quantity not in ("retune", "reweight"):
            _fail("invalid-transform-target", "runtime transform quantity must be retune or reweight", quantity=self.quantity)
        if not isinstance(self.owner, str) or not self.owner:
            _fail("invalid-transform-target", "runtime transform owner must be non-empty", owner=self.owner)
        if not isinstance(self.voice_id, str) or not self.voice_id:
            _fail("invalid-transform-target", "runtime transform voice_id must be non-empty", voice_id=self.voice_id)
        if self.quantity == "retune":
            _finite(self.value, "retune_cents", -4800.0, 4800.0)
        else:
            _finite(self.value, "reweight_db", -120.0, 24.0)

    def to_dict(self):
        return {"layer": self.layer, "quantity": self.quantity, "owner": self.owner,
                "voice_id": self.voice_id, "value": float(self.value)}


@dataclass(frozen=True)
class LayerRuntimeSpec:
    generators: tuple[LayerGeneratorSpec, ...]
    transform_claims: tuple[dict, ...] = ()
    transform_targets: tuple[LayerTransformTarget, ...] = ()

    def __post_init__(self):
        generators = tuple(self.generators)
        if any(not isinstance(spec, LayerGeneratorSpec) for spec in generators):
            _fail("invalid-generator-spec", "generators must contain LayerGeneratorSpec values")
        if len({spec.role for spec in generators}) != len(generators):
            _fail("duplicate-generator-role", "one persistent generator spec is allowed per role")
        targets = tuple(self.transform_targets)
        if any(not isinstance(target, LayerTransformTarget) for target in targets):
            _fail("invalid-transform-target", "transform_targets must contain LayerTransformTarget values")
        target_keys = [(t.layer, t.quantity, t.owner, t.voice_id) for t in targets]
        if len(target_keys) != len(set(target_keys)):
            _fail("duplicate-transform-target", "runtime transform targets must be unique")
        object.__setattr__(self, "generators", generators)
        object.__setattr__(self, "transform_claims", tuple(deepcopy(list(self.transform_claims))))
        object.__setattr__(self, "transform_targets", targets)

    def to_dict(self):
        return {
            "generators": [spec.to_dict() for spec in self.generators],
            "transform_claims": [deepcopy(row) for row in self.transform_claims],
            "transform_targets": [target.to_dict() for target in self.transform_targets],
        }

    @property
    def sha256(self):
        return digest(self.to_dict())


@dataclass(frozen=True)
class LayerRuntimeState:
    sample_rate_hz: int
    voices: dict

    def __post_init__(self):
        if type(self.sample_rate_hz) is not int or type(self.sample_rate_hz) is bool or not 8000 <= self.sample_rate_hz <= 384000:
            _fail("invalid-runtime-state", "runtime state sample rate is out of range")
        if not isinstance(self.voices, dict):
            _fail("invalid-runtime-state", "runtime state voices must be an object")
        clean = {}
        for key, row in self.voices.items():
            if not isinstance(key, str) or ":" not in key or not isinstance(row, dict):
                _fail("invalid-runtime-state", "runtime state voice entry is malformed", voice_key=key)
            role, voice_id = key.split(":", 1)
            if role not in _PERSISTENT_ROLES or not voice_id:
                _fail("invalid-runtime-state", "runtime state voice identity is invalid", voice_key=key)
            phase = _finite(row.get("phase_cycles"), "phase_cycles", 0.0, 1.0)
            if phase == 1.0:
                phase = 0.0
            last = row.get("last_frequency_hz")
            if last is not None:
                last = _finite(last, "last_frequency_hz", 0.001, self.sample_rate_hz / 2.0)
            level = _finite(row.get("tail_level"), "tail_level", 0.0, 1.0)
            remaining = row.get("tail_samples_remaining")
            if type(remaining) is not int or type(remaining) is bool or remaining < 0 or remaining > 10_000_000:
                _fail("invalid-runtime-state", "tail_samples_remaining is invalid", voice_key=key)
            clean[key] = {
                "phase_cycles": phase,
                "last_frequency_hz": last,
                "tail_level": level,
                "tail_samples_remaining": remaining,
            }
        object.__setattr__(self, "voices", clean)

    def to_dict(self):
        payload = {
            "kind": "LayerRuntimeState",
            "version": RUNTIME_VERSION,
            "runtime_id": RUNTIME_ID,
            "sample_rate_hz": self.sample_rate_hz,
            "voices": deepcopy(self.voices),
        }
        payload["sha256"] = digest(payload)
        return payload

    @property
    def sha256(self):
        return self.to_dict()["sha256"]

    @classmethod
    def from_dict(cls, document):
        if not isinstance(document, dict) or document.get("kind") != "LayerRuntimeState":
            _fail("invalid-runtime-state", "expected LayerRuntimeState document")
        if document.get("version") != RUNTIME_VERSION or document.get("runtime_id") != RUNTIME_ID:
            _fail("invalid-runtime-state", "runtime state policy/version mismatch")
        supplied = document.get("sha256")
        payload = {k: deepcopy(v) for k, v in document.items() if k != "sha256"}
        if not isinstance(supplied, str) or supplied != digest(payload):
            _fail("invalid-runtime-state", "runtime state digest mismatch")
        return cls(document.get("sample_rate_hz"), deepcopy(document.get("voices")))


@dataclass(frozen=True)
class CoordinatedRenderResult:
    mix: np.ndarray
    stems: dict
    state: LayerRuntimeState
    diagnostics: dict


def _recipe(recipe):
    try:
        contract = recipe if isinstance(recipe, Contract) else Contract(recipe)
        data = contract.to_dict()
        validate(data, "RenderRecipe")
    except Exception as exc:
        _fail("invalid-base-recipe", "valid RenderRecipe required", error=str(exc))
    if data["render_mode"] != "synth" or data["arrangement"] is not None or data["reversebass"] is not None:
        _fail("unsupported-base-recipe", "ZG-029 runtime currently requires an accepted synth-mode base recipe")
    if data["phrase"] is None:
        _fail("missing-source-phrase", "ZG-029 runtime requires the protected SYNTHLINE PhrasePlan")
    authored = sorted({event["layer_role"] for event in data["phrase"]["events"]})
    rejected = [role for role in authored if role != "synthline"]
    if rejected:
        _fail("ambiguous-authored-layer", "persistent/exciter authored PhrasePlan events require an explicit ZG-029 adapter; they are not silently consumed",
              rejected_roles=rejected)
    return contract, data


def _schedule(progression, frame_beats, duration_beats, phrase, time_map):
    if not isinstance(progression, ProgressionResult):
        _fail("invalid-progression", "ProgressionResult required")
    if progression.tuning_id != phrase["tuning_id"]:
        _fail("tuning-mismatch", "harmony progression and source phrase use different tuning ids",
              progression_tuning=progression.tuning_id, phrase_tuning=phrase["tuning_id"])
    try:
        starts = tuple(fraction(v) for v in frame_beats)
        if isinstance(duration_beats, str):
            durations = tuple(fraction(duration_beats) for _ in progression.frames)
        else:
            durations = tuple(fraction(v) for v in duration_beats)
    except Exception as exc:
        _fail("invalid-frame-schedule", "frame beats/durations must be exact rationals", error=str(exc))
    if len(starts) != len(progression.frames) or len(durations) != len(progression.frames):
        _fail("invalid-frame-schedule", "frame schedule counts must match harmony progression")
    p0, p1 = fraction(phrase["start_beat"]), fraction(phrase["end_beat"])
    previous_end = p0
    rows = []
    origin = beat_to_sample(time_map, phrase["start_beat"])
    for index, (frame, start, duration) in enumerate(zip(progression.frames, starts, durations)):
        if duration <= 0 or start < p0 or start + duration > p1:
            _fail("invalid-frame-schedule", "harmony frame lies outside the source phrase span", frame=index)
        if start < previous_end:
            _fail("overlapping-harmony-frames", "harmony frames may not overlap", frame=index)
        previous_end = start + duration
        start_sample = beat_to_sample(time_map, f"{start.numerator}/{start.denominator}") - origin
        end = start + duration
        end_sample = beat_to_sample(time_map, f"{end.numerator}/{end.denominator}") - origin
        if end_sample <= start_sample:
            _fail("invalid-frame-schedule", "harmony frame rounds to zero samples", frame=index)
        rows.append((start_sample, end_sample, frame))
    return rows


def _progression_roles(progression):
    roles = {}
    for frame in progression.frames:
        for voice in frame.voices:
            prior = roles.setdefault(voice.voice_id, voice.role)
            if prior != voice.role:
                _fail("voice-role-changed", "harmony voice changed persistent role across frames",
                      voice_id=voice.voice_id, before=prior, after=voice.role)
            if voice.role not in ("synthline", *_PERSISTENT_ROLES):
                _fail("unsupported-harmony-role", "harmony progression contains an unsupported role", role=voice.role)
    return roles


def _validate_bass_mode(progression, phrase):
    bass_role = phrase["bass_role"]
    sub = {}
    for frame in progression.frames:
        for voice in frame.voices:
            if voice.role == "sub":
                sub.setdefault(voice.voice_id, []).append(float(voice.frequency_hz))
    if bass_role == "none" and sub:
        _fail("undeclared-sub", "SUB voices require PhrasePlan bass_role pedal or moving")
    if bass_role == "pedal":
        for voice_id, values in sub.items():
            if values and max(values) - min(values) > max(1e-9, abs(values[0]) * 1e-12):
                _fail("pedal-sub-moved", "fixed-pedal SUB changed frequency across harmony frames",
                      voice_id=voice_id, frequencies_hz=values)
    return bass_role, sub


def _transform_index(manifest, spec):
    plan = manifest["transform_plan"]
    claims = {(row["layer"], row["quantity"], row["owner"]) for row in plan}
    index = {}
    for target in spec.transform_targets:
        key = (target.layer, target.quantity, target.owner)
        if key not in claims:
            _fail("unowned-transform-target", "runtime transform target has no matching ownership claim",
                  layer=target.layer, quantity=target.quantity, owner=target.owner)
        index[(target.layer, target.quantity, target.owner, target.voice_id)] = float(target.value)
    return plan, index


def _transform_value(plan, index, role, voice_id, quantity):
    total = 0.0
    trace = []
    for row in plan:
        if row["layer"] != role or row["quantity"] != quantity:
            continue
        exact = (role, quantity, row["owner"], voice_id)
        wildcard = (role, quantity, row["owner"], "*")
        value = index.get(exact, index.get(wildcard))
        if value is None:
            trace.append({"owner": row["owner"], "order": row["order"], "state": "bypass", "value": 0.0})
            continue
        total += value
        trace.append({"owner": row["owner"], "order": row["order"], "state": "applied", "value": value})
    return total, trace


def _phase_block(phase, frequencies, sample_rate_hz):
    frequencies = np.asarray(frequencies, dtype=np.float64)
    if not len(frequencies):
        return np.zeros(0, dtype=np.float64), float(phase)
    increments = frequencies / float(sample_rate_hz)
    phases = float(phase) + np.concatenate(([0.0], np.cumsum(increments[:-1], dtype=np.float64)))
    wave = np.sin(2.0 * np.pi * phases)
    final = float((float(phase) + float(np.sum(increments, dtype=np.float64))) % 1.0)
    return wave, final


def _advance_gap(out, start, end, state, generator, sample_rate_hz):
    n = end - start
    if n <= 0:
        return state
    phase = state["phase_cycles"]
    frequency = state["last_frequency_hz"]
    level = state["tail_level"]
    remaining = state["tail_samples_remaining"]
    if frequency is None:
        return state
    frequencies = np.full(n, frequency, dtype=np.float64)
    wave, phase = _phase_block(phase, frequencies, sample_rate_hz)
    if remaining > 0 and level > 0:
        active = min(n, remaining)
        levels = np.zeros(n, dtype=np.float64)
        levels[:active] = level * (1.0 - np.arange(active, dtype=np.float64) / max(1, remaining))
        out[start:end] += wave * levels * (10.0 ** (generator.gain_db / 20.0))
        level = float(level * max(0.0, 1.0 - active / max(1, remaining)))
        remaining -= active
        if remaining == 0:
            level = 0.0
    return {"phase_cycles": phase, "last_frequency_hz": frequency,
            "tail_level": level, "tail_samples_remaining": remaining}


def _render_voice(n_samples, segments, state, generator, sample_rate_hz, retune_cents, reweight_db):
    out = np.zeros(n_samples, dtype=np.float64)
    current = deepcopy(state)
    cursor = 0
    for start, end, target_hz in segments:
        if start < cursor:
            _fail("overlapping-voice-frames", "one persistent harmony voice has overlapping frames")
        current = _advance_gap(out, cursor, start, current, generator, sample_rate_hz)
        target = float(target_hz) * (2.0 ** (float(retune_cents) / 1200.0))
        if not 0.001 <= target < sample_rate_hz / 2.0:
            _fail("persistent-target-out-of-band", "persistent layer target is outside the renderable band", target_hz=target)
        n = end - start
        if current["last_frequency_hz"] is not None and generator.glide_samples > 0:
            glide = min(n, generator.glide_samples)
            if glide:
                a = math.log(current["last_frequency_hz"])
                b = math.log(target)
                frequencies = np.full(n, target, dtype=np.float64)
                frequencies[:glide] = np.exp(np.linspace(a, b, glide, endpoint=False, dtype=np.float64))
            else:
                frequencies = np.full(n, target, dtype=np.float64)
        else:
            frequencies = np.full(n, target, dtype=np.float64)
        wave, phase = _phase_block(current["phase_cycles"], frequencies, sample_rate_hz)
        gain = 10.0 ** ((generator.gain_db + reweight_db) / 20.0)
        out[start:end] += wave * gain
        current = {"phase_cycles": phase, "last_frequency_hz": target,
                   "tail_level": 1.0, "tail_samples_remaining": generator.release_samples}
        cursor = end
    current = _advance_gap(out, cursor, n_samples, current, generator, sample_rate_hz)
    return out, current


def _sha_audio(array):
    return hashlib.sha256(np.asarray(array, dtype="<f4").tobytes()).hexdigest()


def render_coordinated_layers(base_recipe, progression, frame_beats, duration_beats, spec,
                              *, state=None, section_transition=None, muted_roles=()):
    """Render protected SYNTHLINE/exciter plus explicit persistent harmony roles.

    This is a ZG-029 adapter around the frozen RenderRecipe/PhrasePlan contracts. It does not
    synthesize a replacement SYNTHLINE, does not alter source identity and applies the base
    recipe output policy exactly once after role assembly.
    """
    if not isinstance(spec, LayerRuntimeSpec):
        _fail("invalid-runtime-spec", "LayerRuntimeSpec required")
    contract, data = _recipe(base_recipe)
    phrase = data["phrase"]
    roles = _progression_roles(progression)
    schedule = _schedule(progression, frame_beats, duration_beats, phrase, data["time_map"])
    bass_role, _ = _validate_bass_mode(progression, phrase)
    try:
        ownership = ownership_manifest(phrase, phase_policy=data["phase_policy"], transform_claims=spec.transform_claims)
    except OwnershipConflict as exc:
        raise LayerRuntimeError(exc.diagnostic) from exc
    transform_plan, transform_index = _transform_index(ownership, spec)

    muted = frozenset(muted_roles)
    if not muted <= frozenset(_ALL_ROLES):
        _fail("invalid-mute-role", "muted_roles contains an unknown layer", muted_roles=sorted(muted))

    generator_by_role = {row.role: row for row in spec.generators}
    needed = sorted({role for role in roles.values() if role in _PERSISTENT_ROLES})
    missing = [role for role in needed if role not in generator_by_role]
    if missing:
        _fail("missing-persistent-generator", "persistent harmony roles require explicit generator specs", missing_roles=missing)

    sample_rate = data["time_map"]["sample_rate_hz"]
    if state is None:
        runtime_state = LayerRuntimeState(sample_rate, {})
    elif isinstance(state, LayerRuntimeState):
        runtime_state = state
    else:
        runtime_state = LayerRuntimeState.from_dict(state)
    if runtime_state.sample_rate_hz != sample_rate:
        _fail("state-sample-rate-mismatch", "runtime state and recipe sample rates differ")
    if runtime_state.voices and section_transition is None:
        _fail("missing-section-transition", "continuing persistent layer state requires an explicit section transition")

    voices_state = deepcopy(runtime_state.voices)
    if section_transition is not None:
        try:
            transition = validate_section_transition(section_transition, ownership=ownership)
        except OwnershipConflict as exc:
            raise LayerRuntimeError(exc.diagnostic) from exc
        for role in transition["reset_roles"]:
            for key in list(voices_state):
                if key.startswith(role + ":"):
                    del voices_state[key]

    source = render_phrase(contract)
    raw_synthline = np.asarray(source.stems["synthline"], dtype=np.float64)
    raw_exciter = np.asarray(source.stems["exciter"], dtype=np.float64)
    phrase_start = beat_to_sample(data["time_map"], phrase["start_beat"])
    phrase_end = beat_to_sample(data["time_map"], phrase["end_beat"])
    section_samples = max(0, phrase_end - phrase_start)
    n = max(section_samples, len(raw_synthline), len(raw_exciter))

    def pad(array):
        array = np.asarray(array, dtype=np.float64)
        return np.pad(array, (0, max(0, n - len(array))))

    raw_synthline, raw_exciter = pad(raw_synthline), pad(raw_exciter)
    source_sum = np.zeros(n, dtype=np.float64) if "synthline" in muted else raw_synthline.copy()
    if "exciter" not in muted:
        source_sum += raw_exciter
    source_pre = pad(_apply_preserved_topology(source_sum, data))

    role_stems = {role: np.zeros(n, dtype=np.float64) for role in _PERSISTENT_ROLES}
    traces = []
    for voice_id, role in sorted(roles.items()):
        if role == "synthline":
            traces.append({"voice_id": voice_id, "role": role, "action": "source-owned-not-resynthesized"})
            continue
        generator = generator_by_role[role]
        segments = []
        for start, end, frame in schedule:
            voice = next((v for v in frame.voices if v.voice_id == voice_id), None)
            if voice is not None:
                segments.append((start, end, float(voice.frequency_hz)))
        key = f"{role}:{voice_id}"
        current = voices_state.get(key, {
            "phase_cycles": generator.initial_phase_cycles,
            "last_frequency_hz": None,
            "tail_level": 0.0,
            "tail_samples_remaining": 0,
        })
        retune, retune_trace = _transform_value(transform_plan, transform_index, role, voice_id, "retune")
        reweight, reweight_trace = _transform_value(transform_plan, transform_index, role, voice_id, "reweight")
        rendered, new_state = _render_voice(section_samples, segments, current, generator, sample_rate, retune, reweight)
        role_stems[role][:section_samples] += rendered
        voices_state[key] = new_state
        traces.append({"voice_id": voice_id, "role": role, "action": "persistent-render",
                       "retune_cents": retune, "reweight_db": reweight,
                       "retune_trace": retune_trace, "reweight_trace": reweight_trace})

    pre_master = source_pre.copy()
    for role in _PERSISTENT_ROLES:
        if role not in muted:
            pre_master += role_stems[role]
    try:
        mix, master_diag = apply_output_policy(pre_master, data["output"])
    except GraphError as exc:
        _fail("final-master-failed", "declared final output policy could not execute", error=str(exc))

    next_state = LayerRuntimeState(sample_rate, voices_state)
    stems = {
        "synthline": np.asarray(raw_synthline, dtype=np.float32),
        "exciter": np.asarray(raw_exciter, dtype=np.float32),
        "body": np.asarray(role_stems["body"], dtype=np.float32),
        "aux": np.asarray(role_stems["aux"], dtype=np.float32),
        "sub": np.asarray(role_stems["sub"], dtype=np.float32),
        "pre_master": np.asarray(pre_master, dtype=np.float32),
    }
    diagnostics = {
        "runtime_id": RUNTIME_ID,
        "version": RUNTIME_VERSION,
        "recipe_sha256": contract.sha256,
        "progression_sha256": progression.sha256,
        "runtime_spec_sha256": spec.sha256,
        "ownership_sha256": ownership["sha256"],
        "input_state_sha256": runtime_state.sha256,
        "output_state_sha256": next_state.sha256,
        "bass_role": bass_role,
        "muted_roles": sorted(muted),
        "transform_plan": deepcopy(transform_plan),
        "voice_trace": traces,
        "master": deepcopy(master_diag),
        "stem_sha256": {name: _sha_audio(audio) for name, audio in stems.items()},
        "mix_sha256": _sha_audio(mix),
        "final_master_owner": ownership["master"]["owner"],
        "normalization": ownership["master"]["normalization"],
    }
    return CoordinatedRenderResult(np.asarray(mix, dtype=np.float32), stems, next_state, diagnostics)
