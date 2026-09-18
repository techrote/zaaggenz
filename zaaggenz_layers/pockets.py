from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import math

import numpy as np

from zaaggenz_contracts import digest
from zaaggenz_dsp.band_router import BAND_NAMES, filter_metadata, route_band_processors
from zaaggenz_dsp.multiband import BandError, split_bands, validate_crossovers

POCKET_ID = "zaaggenz.layer-pockets"
POCKET_VERSION = "1.0.0"
_YIELDING_ROLES = ("body", "aux", "sub")
_DETECTOR_ROLES = ("synthline", "exciter", "body", "aux", "sub")
_MAX_ATTENUATION_DB = 36.0
_MAX_TIME_SAMPLES = 10_000_000


class LayerPocketError(ValueError):
    def __init__(self, diagnostic):
        self.diagnostic = deepcopy(diagnostic)
        super().__init__(self.diagnostic.get("message", "layer pocket error"))


def _fail(code, message, **details):
    raise LayerPocketError({
        "kind": "LayerPocketDiagnostic",
        "version": POCKET_VERSION,
        "pocket_id": POCKET_ID,
        "code": code,
        "message": message,
        **deepcopy(details),
    })


def _finite(value, name, lo=None, hi=None):
    if type(value) not in (int, float) or type(value) is bool or not math.isfinite(float(value)):
        _fail("invalid-pocket-value", f"{name} must be finite numeric", field=name)
    value = float(value)
    if lo is not None and value < lo:
        _fail("invalid-pocket-value", f"{name} is below its bound", field=name, value=value, minimum=lo)
    if hi is not None and value > hi:
        _fail("invalid-pocket-value", f"{name} is above its bound", field=name, value=value, maximum=hi)
    return value


def _sample(value, name):
    if type(value) is not int or type(value) is bool or not 0 <= value <= _MAX_TIME_SAMPLES:
        _fail("invalid-pocket-value", f"{name} must be an integer in 0..{_MAX_TIME_SAMPLES}", field=name)
    return value


def _band(value):
    if value not in BAND_NAMES:
        _fail("invalid-pocket-band", "band must be one of the accepted ZG-016 bands", band=value, accepted=list(BAND_NAMES))
    return value


def _sha_audio(array):
    return hashlib.sha256(np.asarray(array, dtype="<f4").tobytes()).hexdigest()


def _rms(array):
    a = np.asarray(array, dtype=np.float64)
    return float(np.sqrt(np.mean(a * a))) if a.size else 0.0


@dataclass(frozen=True)
class PocketAutomationPoint:
    sample: int
    attenuation_db: float

    def __post_init__(self):
        _sample(self.sample, "sample")
        _finite(self.attenuation_db, "attenuation_db", 0.0, _MAX_ATTENUATION_DB)

    def to_dict(self):
        return {"sample": self.sample, "attenuation_db": float(self.attenuation_db)}


@dataclass(frozen=True)
class StaticPocketSpec:
    yielding_role: str
    band: str
    points: tuple[PocketAutomationPoint, ...]

    def __post_init__(self):
        if self.yielding_role not in _YIELDING_ROLES:
            _fail("invalid-yielding-role", "v1 pockets may yield BODY/AUX/SUB only; protected source roles remain untouched",
                  yielding_role=self.yielding_role)
        _band(self.band)
        points = tuple(self.points)
        if not points or any(not isinstance(point, PocketAutomationPoint) for point in points):
            _fail("invalid-pocket-automation", "static pocket requires PocketAutomationPoint values")
        samples = [point.sample for point in points]
        if samples != sorted(samples) or len(samples) != len(set(samples)):
            _fail("invalid-pocket-automation", "automation samples must be strictly increasing")
        object.__setattr__(self, "points", points)

    def to_dict(self):
        return {
            "kind": "static",
            "yielding_role": self.yielding_role,
            "band": self.band,
            "points": [point.to_dict() for point in self.points],
        }


@dataclass(frozen=True)
class SidechainPocketSpec:
    yielding_role: str
    detector_role: str
    band: str
    threshold_dbfs: float
    attack_samples: int
    release_samples: int
    lookahead_samples: int
    max_attenuation_db: float

    def __post_init__(self):
        if self.yielding_role not in _YIELDING_ROLES:
            _fail("invalid-yielding-role", "v1 sidechain pockets may yield BODY/AUX/SUB only",
                  yielding_role=self.yielding_role)
        if self.detector_role not in _DETECTOR_ROLES:
            _fail("invalid-detector-role", "detector_role is not an executable layer role", detector_role=self.detector_role)
        if self.detector_role == self.yielding_role:
            _fail("self-sidechain", "sidechain detector must be a distinct layer; use static automation for self attenuation",
                  role=self.yielding_role)
        _band(self.band)
        _finite(self.threshold_dbfs, "threshold_dbfs", -120.0, 0.0)
        _sample(self.attack_samples, "attack_samples")
        _sample(self.release_samples, "release_samples")
        _sample(self.lookahead_samples, "lookahead_samples")
        _finite(self.max_attenuation_db, "max_attenuation_db", 0.0, _MAX_ATTENUATION_DB)

    def to_dict(self):
        return {
            "kind": "sidechain",
            "yielding_role": self.yielding_role,
            "detector_role": self.detector_role,
            "band": self.band,
            "threshold_dbfs": float(self.threshold_dbfs),
            "attack_samples": self.attack_samples,
            "release_samples": self.release_samples,
            "lookahead_samples": self.lookahead_samples,
            "max_attenuation_db": float(self.max_attenuation_db),
        }


@dataclass(frozen=True)
class LayerPocketPlan:
    crossovers_hz: tuple[float, float, float]
    static_pockets: tuple[StaticPocketSpec, ...] = ()
    sidechains: tuple[SidechainPocketSpec, ...] = ()

    def __post_init__(self):
        try:
            if len(self.crossovers_hz) != 3:
                raise ValueError
            crossovers = tuple(float(value) for value in self.crossovers_hz)
        except (TypeError, ValueError, OverflowError):
            _fail("invalid-crossovers", "crossovers_hz must contain exactly three finite values")
        if not all(math.isfinite(value) for value in crossovers):
            _fail("invalid-crossovers", "crossovers_hz must contain exactly three finite values")
        static = tuple(self.static_pockets)
        sidechains = tuple(self.sidechains)
        if any(not isinstance(item, StaticPocketSpec) for item in static):
            _fail("invalid-pocket-plan", "static_pockets must contain StaticPocketSpec values")
        if any(not isinstance(item, SidechainPocketSpec) for item in sidechains):
            _fail("invalid-pocket-plan", "sidechains must contain SidechainPocketSpec values")
        targets = [(item.yielding_role, item.band) for item in (*static, *sidechains)]
        if len(targets) != len(set(targets)):
            _fail("ambiguous-pocket-order", "v1 permits only one pocket owner per yielding role/band; chain order must not be implicit",
                  duplicate_targets=sorted({target for target in targets if targets.count(target) > 1}))
        object.__setattr__(self, "crossovers_hz", crossovers)
        object.__setattr__(self, "static_pockets", static)
        object.__setattr__(self, "sidechains", sidechains)

    def to_dict(self):
        return {
            "kind": "LayerPocketPlan",
            "version": POCKET_VERSION,
            "pocket_id": POCKET_ID,
            "crossovers_hz": list(self.crossovers_hz),
            "static_pockets": [item.to_dict() for item in self.static_pockets],
            "sidechains": [item.to_dict() for item in self.sidechains],
        }

    @property
    def sha256(self):
        return digest(self.to_dict())


def _automation_gain(points, n_samples):
    if n_samples == 0:
        return np.zeros(0, dtype=np.float64)
    xp = np.asarray([point.sample for point in points], dtype=np.float64)
    attenuation = np.asarray([point.attenuation_db for point in points], dtype=np.float64)
    positions = np.arange(n_samples, dtype=np.float64)
    attenuation = np.interp(positions, xp, attenuation, left=attenuation[0], right=attenuation[-1])
    return np.power(10.0, -attenuation / 20.0)


def _mono_detector_magnitude(detector_band):
    a = np.asarray(detector_band, dtype=np.float64)
    if a.ndim == 1:
        return np.abs(a)
    if a.ndim == 2 and a.shape[1] in (1, 2):
        return np.sqrt(np.mean(a * a, axis=1))
    _fail("invalid-detector-audio", "detector audio must be finite mono/stereo")


def _sidechain_gain(detector_band, spec):
    magnitude = _mono_detector_magnitude(detector_band)
    n = len(magnitude)
    if spec.lookahead_samples:
        look = min(n, spec.lookahead_samples)
        future = np.zeros(n, dtype=np.float64)
        if look < n:
            future[:n - look] = magnitude[look:]
        magnitude = future
    env = np.zeros(n, dtype=np.float64)
    attack_coeff = 0.0 if spec.attack_samples == 0 else math.exp(-1.0 / float(spec.attack_samples))
    release_coeff = 0.0 if spec.release_samples == 0 else math.exp(-1.0 / float(spec.release_samples))
    previous = 0.0
    for index, value in enumerate(magnitude):
        coeff = attack_coeff if value > previous else release_coeff
        previous = coeff * previous + (1.0 - coeff) * float(value)
        env[index] = previous
    threshold = 10.0 ** (float(spec.threshold_dbfs) / 20.0)
    ratio = np.maximum(env / max(threshold, np.finfo(np.float64).tiny), 1.0)
    requested = np.minimum(20.0 * np.log10(ratio), float(spec.max_attenuation_db))
    return np.power(10.0, -requested / 20.0), requested


def _route_gain(source, sample_rate_hz, crossovers, band, gain):
    gain = np.asarray(gain, dtype=np.float64)
    source = np.asarray(source, dtype=np.float64)
    if len(gain) != len(source):
        _fail("gain-length-mismatch", "pocket gain envelope does not match yielding stem length")
    if not np.isfinite(gain).all() or np.any(gain <= 0.0) or np.any(gain > 1.0):
        _fail("invalid-gain-envelope", "pocket gain must remain strictly positive and never exceed unity")
    if np.array_equal(gain, np.ones(len(gain), dtype=np.float64)):
        return source.copy(), None
    band_index = BAND_NAMES.index(band)
    processors = [None, None, None, None]
    processors[band_index] = lambda selected: np.asarray(selected, dtype=np.float64) * (gain if selected.ndim == 1 else gain[:, None])
    try:
        processed, reports = route_band_processors(source, sample_rate_hz, crossovers, processors)
    except BandError as exc:
        _fail("band-routing-failed", "ZG-016 effect-delta pocket routing failed", error=str(exc), band=band)
    return processed, reports[band_index].to_dict()


def apply_layer_pockets(stems, sample_rate_hz, plan, *, muted_roles=()):
    """Apply explicitly authored subtractive pockets to persistent layer stems.

    V1 intentionally leaves protected SYNTHLINE/exciter bytes untouched. Detector inputs are
    snapshotted before pocketing, so sidechain behavior is independent of operation ordering.
    Every audible edit is dry + a ZG-016 confined effect delta; no normalization or makeup gain
    is performed here.
    """
    if not isinstance(plan, LayerPocketPlan):
        _fail("invalid-pocket-plan", "LayerPocketPlan required")
    if type(sample_rate_hz) is not int or type(sample_rate_hz) is bool or not 8000 <= sample_rate_hz <= 384000:
        _fail("invalid-sample-rate", "sample_rate_hz must be an integer in 8000..384000")
    try:
        crossovers = validate_crossovers(plan.crossovers_hz, sample_rate_hz)
    except BandError as exc:
        _fail("invalid-crossovers", "pocket crossovers are not executable at this sample rate", error=str(exc))
    if not isinstance(stems, dict):
        _fail("invalid-stems", "layer pocket input must be a stem mapping")
    missing = [role for role in _DETECTOR_ROLES if role not in stems]
    if missing:
        _fail("missing-stems", "layer pocket execution requires all role stems", missing_roles=missing)
    original = {}
    shape = None
    for role in _DETECTOR_ROLES:
        audio = np.asarray(stems[role], dtype=np.float64)
        if audio.ndim not in (1, 2) or (audio.ndim == 2 and audio.shape[1] not in (1, 2)) or not np.isfinite(audio).all():
            _fail("invalid-stems", "layer stems must be finite mono/stereo", role=role)
        if shape is None:
            shape = audio.shape
        if audio.shape != shape:
            _fail("stem-shape-mismatch", "all pocket role stems must share one shape", role=role, shape=list(audio.shape), expected=list(shape))
        original[role] = audio.copy()
    muted = frozenset(muted_roles)
    if not muted <= frozenset(_DETECTOR_ROLES):
        _fail("invalid-muted-role", "muted_roles contains an unknown pocket role", muted_roles=sorted(muted))
    output = {role: audio.copy() for role, audio in original.items()}
    operations = []

    for spec in plan.static_pockets:
        before = output[spec.yielding_role]
        gain = _automation_gain(spec.points, len(before))
        after, band_report = _route_gain(before, sample_rate_hz, crossovers, spec.band, gain)
        output[spec.yielding_role] = after
        attenuation = -20.0 * np.log10(np.maximum(gain, np.finfo(np.float64).tiny))
        operations.append({
            **spec.to_dict(),
            "before_sha256": _sha_audio(before),
            "after_sha256": _sha_audio(after),
            "before_rms": _rms(before),
            "after_rms": _rms(after),
            "observed_max_attenuation_db": float(np.max(attenuation, initial=0.0)),
            "active_samples": int(np.count_nonzero(attenuation > 1e-12)),
            "band_delta": deepcopy(band_report),
            "makeup_gain_db": 0.0,
        })

    for spec in plan.sidechains:
        before = output[spec.yielding_role]
        detector = np.zeros_like(original[spec.detector_role]) if spec.detector_role in muted else original[spec.detector_role]
        try:
            detector_band = split_bands(detector, sample_rate_hz, crossovers)[BAND_NAMES.index(spec.band)]
        except BandError as exc:
            _fail("detector-routing-failed", "sidechain detector band could not be evaluated", error=str(exc), band=spec.band)
        gain, attenuation = _sidechain_gain(detector_band, spec)
        after, band_report = _route_gain(before, sample_rate_hz, crossovers, spec.band, gain)
        output[spec.yielding_role] = after
        active = np.flatnonzero(attenuation > 1e-12)
        operations.append({
            **spec.to_dict(),
            "detector_muted": spec.detector_role in muted,
            "detector_sha256": _sha_audio(detector),
            "before_sha256": _sha_audio(before),
            "after_sha256": _sha_audio(after),
            "before_rms": _rms(before),
            "after_rms": _rms(after),
            "observed_max_attenuation_db": float(np.max(attenuation, initial=0.0)),
            "active_samples": int(len(active)),
            "first_active_sample": None if not len(active) else int(active[0]),
            "last_active_sample": None if not len(active) else int(active[-1]),
            "band_delta": deepcopy(band_report),
            "makeup_gain_db": 0.0,
        })

    diagnostics = {
        "pocket_id": POCKET_ID,
        "version": POCKET_VERSION,
        "plan_sha256": plan.sha256,
        "crossovers_hz": list(crossovers),
        "filter": filter_metadata(crossovers, sample_rate_hz),
        "detector_domain": "pre-pocket role stems; muted detectors are explicit zero",
        "reconstruction": "dry + confined effect delta",
        "normalization": "none",
        "makeup_gain_db": 0.0,
        "operations": operations,
    }
    return output, diagnostics
