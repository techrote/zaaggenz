"""NYQ-002 immutable-source, fractional-event sampler.

This is an opt-in numerical-domain kernel, not a registered rack/graph node or
delivery converter. The source is explicitly canonical float32 PCM; capture and
reconstruction use float64 and the accepted exact rational/Decimal80 clock.
No amplitude quantization, normalization, master or implicit antialias filter
is applied. See docs/dsp/NYQ002_SAMPLER.md for the source/edge/state contract.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Context, Decimal, localcontext
from fractions import Fraction
import hashlib
import math
from typing import Callable

import numpy as np

from zaaggenz_contracts import Contract, digest
from zaaggenz_contracts.nyquismic import (
    MAX_DENOMINATOR, MAX_FRAMES, MAX_TIME_S, MAX_EVENTS, VERSION,
    SAMPLER_AUDIO_METHOD, SAMPLER_NUMERICAL_FILTER,
    STATIC_FIR_PREFILTER_POLICIES, GUARDED_CLEAN_PREFILTER,
    SonicSpec, EvaluationPolicy, ResourceBudget, RenderIdentity,
    UnsupportedNyquismic, _Record, require, record, integer, hash_value,
    qtext, bind_render_identity,
)
from zaaggenz_contracts.nyquismic_clock import (
    ClockPlan, ClockEvent, ClockCheckpoint, ClockCancelled, admit_foundation,
)

CHECKPOINT_VERSION = 'nyq.sampler-checkpoint.v1'
EXECUTION_DOMAIN = 'zaaggenz.nyquismic.sampler-execution.v1'
_BLOCK = 256
_SOURCE_FIR_BLOCK = 8192  # pre-capture FIR: cancellation between bounded source windows
_NO_RACK = digest({'domain': EXECUTION_DOMAIN, 'rack': None})
_NO_GRAPH = digest({'domain': EXECUTION_DOMAIN, 'graph': None})


def _decimal(value: Fraction | Decimal) -> Decimal:
    if type(value) is Decimal:
        return value
    return Decimal(value.numerator) / Decimal(value.denominator)


def _relative(value: Fraction | Decimal, origin: Fraction) -> Fraction | Decimal:
    if type(value) is Fraction:
        return value - origin
    with localcontext(Context(prec=80)):
        return +(_decimal(value) - _decimal(origin))


def _ratio(a: Fraction | Decimal, b: Fraction | Decimal) -> float:
    if type(a) is Fraction and type(b) is Fraction:
        return float(a / b)
    with localcontext(Context(prec=80)):
        return float(_decimal(a) / _decimal(b))


def _difference(a: Fraction | Decimal, b: Fraction | Decimal) -> Fraction | Decimal:
    if type(a) is Fraction and type(b) is Fraction:
        return a - b
    with localcontext(Context(prec=80)):
        return +(_decimal(a) - _decimal(b))


def _immutable(array: np.ndarray) -> np.ndarray:
    """A bytes-backed array cannot be made writable by its caller."""
    return np.frombuffer(array.tobytes(order='C'), dtype=array.dtype).reshape(array.shape)


def _check_hooks(cancelled, progress):
    require(cancelled is None or callable(cancelled), 'cancellation callback must be callable')
    require(progress is None or callable(progress), 'progress callback must be callable')


def _cancel(cancelled):
    if cancelled is not None and cancelled():
        raise ClockCancelled('Nyquismic sampler cancelled; no partial audio or checkpoint publication')


def _notify(progress, value, cancelled):
    _cancel(cancelled)
    if progress is not None:
        progress(float(value))
    # A callback may cancel the request, including its final flush/publication.
    _cancel(cancelled)


@dataclass(frozen=True)
class FrozenInput:
    """Explicit immutable pcm-f32le-interleaved-v1 snapshot.

    from_pcm performs one declared float32 representation conversion. It never
    rescales, clips or accepts nonfinite/unrepresentable values. All subsequent
    evaluation rates sample these identical bytes, not regenerated source PCM.
    """
    _payload: bytes
    asset: Contract
    _mono: bool

    def __post_init__(self):
        record(self.asset, Contract, 'source asset')
        row = self.asset.to_dict()
        require(row['kind'] == 'AudioAssetRef' and row['identity_domain'] == 'pcm-f32le-interleaved-v1',
                'sampler source requires a canonical PCM AudioAssetRef')
        require(type(self._payload) is bytes and type(self._mono) is bool, 'immutable PCM snapshot required')
        require(row['frame_count'] * row['channels'] <= MAX_FRAMES, 'source frame/channel hard budget exceeded')
        require(len(self._payload) == row['frame_count'] * row['channels'] * 4, 'source PCM length mismatch')
        require(hashlib.sha256(self._payload).hexdigest() == row['content_sha256'], 'source PCM identity mismatch')
        require(np.isfinite(np.frombuffer(self._payload, dtype='<f4')).all(), 'source PCM must be finite')
        require(not self._mono or row['channels'] == 1, 'mono source shape mismatch')

    @classmethod
    def from_pcm(cls, value, sample_rate_hz: int, asset: Contract | None = None):
        integer(sample_rate_hz, 'immutable source rate Hz', 8000, 192000)
        raw = np.asarray(value)
        require(raw.ndim in (1, 2) and (raw.ndim == 1 or raw.shape[1] in (1, 2)), 'source must be mono/stereo PCM')
        require(raw.dtype.kind in 'iuf' and raw.size <= MAX_FRAMES, 'bounded real numeric source PCM required')
        require(np.isfinite(raw).all(), 'source PCM must be finite')
        with np.errstate(over='ignore', invalid='ignore'):
            pcm = np.asarray(raw, dtype='<f4', order='C')
        require(np.isfinite(pcm).all(), 'source is not representable as finite float32 PCM')
        channels = 1 if raw.ndim == 1 else raw.shape[1]
        payload = pcm.tobytes(order='C')
        data = dict(kind='AudioAssetRef', version='1.0.0',
                    content_sha256=hashlib.sha256(payload).hexdigest(),
                    identity_domain='pcm-f32le-interleaved-v1',
                    sample_rate_hz=sample_rate_hz, channels=channels,
                    channel_layout='mono' if channels == 1 else 'stereo-lr',
                    frame_count=len(raw), level_domain='source', sample_policy='unclamped_float')
        if asset is not None:
            record(asset, Contract, 'supplied source asset')
            supplied = asset.to_dict()
            require(supplied['kind'] == 'AudioAssetRef', 'source must be AudioAssetRef')
            for key in data:
                if key != 'level_domain':
                    require(supplied[key] == data[key], 'source asset ' + key + ' mismatch')
            data['level_domain'] = supplied['level_domain']
        return cls(payload, Contract(data), raw.ndim == 1)

    @property
    def pcm(self) -> np.ndarray:
        row = self.asset.to_dict()
        a = np.frombuffer(self._payload, dtype='<f4')
        return a if self._mono else a.reshape(row['frame_count'], row['channels'])

    @property
    def sample_rate_hz(self):
        return self.asset.to_dict()['sample_rate_hz']


def sampler_evaluation(rate: int, budget: ResourceBudget = ResourceBudget()) -> EvaluationPolicy:
    """A fixed numerical grid; deliberately no final antialias conversion."""
    return EvaluationPolicy(evaluation_rate_hz=rate, audio_method=SAMPLER_AUDIO_METHOD,
                            numerical_filter=SAMPLER_NUMERICAL_FILTER, budget=budget)



def _fir33_kernel(source_rate_hz: int, virtual_hz: Fraction, policy: str = 'fir33_hann_static_0p45_v1') -> tuple[np.ndarray, Fraction]:
    """A versioned symmetric 33-tap FIR with an explicit cutoff and dry mix.

    A mix of one preserves the accepted 0p45 policy bit for bit.  A partial
    mix is implemented in the kernel itself (delta at the middle tap), which
    keeps unity DC, zero phase and one coefficient/identity authority.
    """
    require(policy != GUARDED_CLEAN_PREFILTER, 'guarded comparator requires a Kaiser kernel')
    cutoff_ratio, strength = STATIC_FIR_PREFILTER_POLICIES[policy]
    cutoff_hz = cutoff_ratio * virtual_hz
    require(Fraction(0) < cutoff_hz < Fraction(source_rate_hz, 2),
            'static Nyquismic FIR cutoff must lie below source Nyquist')
    fraction = float(cutoff_hz / source_rate_hz)
    indices = np.arange(33, dtype=np.float64) - 16
    kernel = (2 * fraction) * np.sinc(2 * fraction * indices) * np.hanning(33)
    norm = float(np.sum(kernel))
    require(np.isfinite(norm) and norm > 0, 'static Nyquismic FIR normalization invalid')
    kernel /= norm
    if strength != 1:
        kernel *= float(strength)
        kernel[16] += float(1 - strength)
    return kernel, cutoff_hz


def _fir_guarded_comparison(source_rate_hz: int, virtual_hz: Fraction) -> tuple[np.ndarray, Fraction]:
    """Finite 129-tap Kaiser low-pass for a narrowly admitted static comparison.

    This is an opt-in source prefilter, not a universal alias-free theorem.
    Restrict the clock so that a real stopband can be measured before capture.
    """
    require(Fraction(source_rate_hz, 8) <= virtual_hz <= Fraction(source_rate_hz, 2),
            'guarded FIR requires virtual rate between 1/8 and 1/2 source Hz')
    cutoff_hz = Fraction(2, 5) * virtual_hz
    x = np.arange(129, dtype=np.float64) - 64
    fraction = float(cutoff_hz / source_rate_hz)
    kernel = (2 * fraction) * np.sinc(2 * fraction * x) * np.kaiser(129, 10.0)
    dc = float(np.sum(kernel))
    require(np.isfinite(dc) and dc > 0, 'guarded Kaiser normalization invalid')
    kernel /= dc
    return kernel, cutoff_hz


def _static_fir_kernel(source_rate_hz: int, virtual_hz: Fraction,
                       policy: str) -> tuple[np.ndarray, Fraction]:
    if policy == GUARDED_CLEAN_PREFILTER:
        return _fir_guarded_comparison(source_rate_hz, virtual_hz)
    return _fir33_kernel(source_rate_hz, virtual_hz, policy)


def _prefilter_static_source(pcm: np.ndarray, kernel: np.ndarray, boundary: str,
                             cancelled=None) -> np.ndarray:
    """Offline zero-phase symmetric FIR, with bounded exact source context."""
    _cancel(cancelled)
    require(type(kernel) is np.ndarray and kernel.ndim == 1 and len(kernel) in (33, 129)
            and np.isfinite(kernel).all(), 'unsupported/nonfinite static FIR coefficient array')
    half = (len(kernel) - 1) // 2
    if not len(pcm):
        return np.zeros(pcm.shape, dtype=np.float64)
    padding = ((half, half), (0, 0))
    padded = np.pad(np.asarray(pcm, dtype=np.float64), padding,
                    mode='edge' if boundary == 'edge_hold' else 'constant')
    result = np.empty(pcm.shape, dtype=np.float64)
    for channel in range(pcm.shape[1]):
        for start in range(0, len(pcm), _SOURCE_FIR_BLOCK):
            _cancel(cancelled)
            stop = min(start + _SOURCE_FIR_BLOCK, len(pcm))
            # Full source-context convolution; 33-tap output is unchanged.
            window = padded[start:stop + 2 * half, channel]
            result[start:stop, channel] = np.convolve(window, kernel, mode='valid')
    require(np.isfinite(result).all(), 'static Nyquismic FIR produced nonfinite samples')
    _cancel(cancelled)
    return result


def _sample_at(pcm: np.ndarray, position: Fraction | Decimal, capture: str, boundary: str) -> np.ndarray:
    """Evaluate canonical PCM at an exact/Decimal80 fractional sample index."""
    left = math.floor(position)
    fraction = position - left
    if capture == 'nearest_left_tie_v1':
        index = left + int(fraction > Fraction(1, 2) if type(fraction) is Fraction else fraction > Decimal('0.5'))
        if not len(pcm):
            return np.zeros(pcm.shape[1], dtype=np.float64)
        if boundary == 'edge_hold':
            return pcm[min(max(index, 0), len(pcm) - 1)].astype(np.float64)
        return pcm[index].astype(np.float64) if 0 <= index < len(pcm) else np.zeros(pcm.shape[1], dtype=np.float64)
    # Virtual sample values outside the source extent are zero or the edge.
    # Linear zero_pad therefore ramps from the last sample to the zero sample
    # at the excluded source endpoint; no last-interval clamp is hidden.
    def value(index):
        if not len(pcm):
            return np.zeros(pcm.shape[1], dtype=np.float64)
        if boundary == 'edge_hold':
            return pcm[min(max(index, 0), len(pcm) - 1)].astype(np.float64)
        return pcm[index].astype(np.float64) if 0 <= index < len(pcm) else np.zeros(pcm.shape[1], dtype=np.float64)
    a, b = value(left), value(left + 1)
    if capture == 'cubic_catmull_rom_v1':
        # Four *source*-frame Catmull-Rom samples, not the separate
        # virtual-event reconstruction cubic. Uniform source-frame spacing
        # makes the central secants (b - p)/2 and (q - a)/2 physical-time
        # slopes after the common source-period factor cancels.
        # Evaluate an exact integer source position without a needless
        # polynomial combination, retaining its float32 -> float64 value.
        if fraction == 0:
            return a
        p, q = value(left - 1), value(left + 2)
        u = float(fraction)
        u2, u3 = u * u, u * u * u
        return ((2*u3 - 3*u2 + 1)*a + (u3 - 2*u2 + u)*(b - p)/2
                + (-2*u3 + 3*u2)*b + (u3 - u2)*(q - a)/2)
    return a + float(fraction) * (b - a)


def _first_frame(plan: ClockPlan, index: int, coordinate, origin, rate, count):
    """Locate a root on a numerical grid with exact membership correction."""
    with localcontext(Context(prec=80)):
        estimate = math.ceil((_decimal(coordinate) - _decimal(origin)) * rate)
    estimate = min(max(estimate, 0), count)
    def captured(frame):
        return plan.capture_count_at(origin + Fraction(frame, rate), inclusive=True) > index
    if ((estimate == count or captured(estimate)) and
            (estimate == 0 or not captured(estimate - 1))):
        return estimate
    # Decimal coordinates are not membership authority. A bounded exact binary
    # search also handles a root arbitrarily close to a representable boundary.
    low, high = 0, count
    while low < high:
        middle = (low + high) // 2
        if captured(middle):
            high = middle
        else:
            low = middle + 1
    return low


@dataclass(frozen=True)
class SamplerCheckpoint(_Record):
    render_sha256: str
    next_frame: int
    clock: ClockCheckpoint
    previous_event_index: int
    previous_capture: tuple[float, ...]
    next_event_index: int
    next_capture: tuple[float, ...]
    audio_active: bool
    version: str = CHECKPOINT_VERSION
    _children = {'clock': ClockCheckpoint}

    def __post_init__(self):
        require(self.version == CHECKPOINT_VERSION, 'unsupported sampler checkpoint version')
        hash_value(self.render_sha256, 'sampler checkpoint render')
        integer(self.next_frame, 'checkpoint frame', 0, MAX_FRAMES)
        record(self.clock, ClockCheckpoint, 'checkpoint clock history')
        integer(self.previous_event_index, 'previous capture index', -1, MAX_EVENTS - 1)
        integer(self.next_event_index, 'next capture index', 0, MAX_EVENTS)
        require(type(self.audio_active) is bool, 'checkpoint active flag must be bool')
        for values in (self.previous_capture, self.next_capture):
            require(type(values) is tuple and len(values) <= 2, 'checkpoint capture history must be bounded tuple')
            require(all(type(v) in (float, int) and math.isfinite(v) for v in values), 'checkpoint history must be finite')

    @classmethod
    def from_dict(cls, data):
        require(type(data) is dict and set(data) == {f.name for f in fields(cls)}, 'sampler checkpoint fields')
        for field in ('previous_capture', 'next_capture'):
            require(type(data[field]) is list, 'sampler checkpoint capture history must be an array')
        return cls(**{**data, 'clock': ClockCheckpoint.from_dict(data['clock']),
                      'previous_capture': tuple(data['previous_capture']), 'next_capture': tuple(data['next_capture'])})


@dataclass(frozen=True)
class SamplerResult:
    audio: np.ndarray
    checkpoint: SamplerCheckpoint
    diagnostics: dict
    render_sha256: str


@dataclass(frozen=True, init=False)
class SamplerPlan:
    """An admitted immutable full-context render, reusable across region jobs.

    Preparing captures is atomic. Rendering/restore has no global PRNG, mutable
    cursor or shared channel history. A cancelled region cannot contaminate the
    next request. Restoring verifies every history field against the original
    source and complete future extent before using it.
    """
    source: FrozenInput
    spec: SonicSpec
    evaluation: EvaluationPolicy
    identity: RenderIdentity
    clock: ClockPlan
    frame_count: int
    events: tuple[ClockEvent, ...]
    captures: np.ndarray
    _coordinates: tuple
    _first_frames: np.ndarray
    _origin: Fraction
    _active: bool
    _interval_rate_range: tuple[float, float] | None
    _timestamp_rounding_s: float

    def __init__(self, *args, **kwargs):
        require(False, 'SamplerPlan must be constructed by prepare; unadmitted/replaced capture histories are not executable')

    @property
    def sample_rate_hz(self):
        return self.evaluation.evaluation_rate_hz

    @property
    def render_sha256(self):
        return digest({'domain': EXECUTION_DOMAIN, 'request': self.identity.to_dict(),
                       'numerical_output_frames': self.frame_count,
                       'representation': 'unclamped-f64-point-grid', 'source_shape_mono': self.source._mono})

    @classmethod
    def prepare(cls, source: FrozenInput, spec: SonicSpec, evaluation: EvaluationPolicy | None = None,
                *, frame_count: int | None = None, cancelled=None, progress=None,
                source_revision_sha256: str | None = None, context_sha256: str | None = None):
        _check_hooks(cancelled, progress)
        _cancel(cancelled)
        require(cls is SamplerPlan, 'sampler plan subclasses are not an execution capability')
        record(source, FrozenInput, 'immutable PCM input')
        record(spec, SonicSpec, 'sonic spec')
        # Revalidate snapshots, including latent bypassed settings. Defaults on
        # the foundation remain explicitly non-executable until selected here.
        spec = SonicSpec.from_json(spec.to_json())
        if spec.mode != 'sampler':
            raise UnsupportedNyquismic('NYQ-002 executes sampler only; playback warp and cascades need their kernel child')
        evaluation = sampler_evaluation(source.sample_rate_hz) if evaluation is None else evaluation
        record(evaluation, EvaluationPolicy, 'numerical policy')
        evaluation = EvaluationPolicy.from_json(evaluation.to_json())
        require(evaluation.audio_method == SAMPLER_AUDIO_METHOD and evaluation.numerical_filter == SAMPLER_NUMERICAL_FILTER,
                'select the explicit fractional-event sampler numerical policy')
        require(not evaluation.reference_rates_hz, 'NYQ-002 is one fixed-rate pass; convergence belongs to NYQ-003')
        asset = source.asset.to_dict()
        require(asset['channels'] == spec.channels, 'source/sampler channel mismatch')
        require(asset['frame_count'] * spec.channels <= evaluation.budget.max_frames, 'source frame/channel admission budget exceeded')
        rate = evaluation.evaluation_rate_hz
        if frame_count is None:
            frame_count = math.ceil(Fraction(asset['frame_count'] * rate, asset['sample_rate_hz']))
        integer(frame_count, 'output frame count', 0, evaluation.budget.max_frames // spec.channels)
        origin = Fraction(spec.clock.origin_s)
        require(math.lcm(origin.denominator, rate) <= MAX_DENOMINATOR, 'output grid cannot be serialized within rational checkpoint bounds')
        end = origin + Fraction(frame_count, rate)
        require(end <= MAX_TIME_S, 'output extent exceeds physical-time bound')
        # This admits the FULL render, even when the caller will later ask for a
        # small region, and validates unsupported clocks and latent bypasses.
        clock = admit_foundation(spec, qtext(end), evaluation.budget)[0]
        if spec.reconstruction in ('sinc4_hann_uniform_v1', 'sinc8_hann_uniform_v1'):
            require(not spec.clock.points_hz and not spec.clock.resets and
                    not spec.clock.routes and spec.clock.quantizer.policy == 'none' and
                    spec.clock.jitter.model == 'none',
                    'sinc8 Hann reconstruction requires a static uniform event lattice')
            radius = 4 if spec.reconstruction == 'sinc4_hann_uniform_v1' else 8
            require(evaluation.budget.max_filter_taps >= 2 * radius + 1,
                    f'sinc{radius} Hann reconstruction exceeds admitted kernel support')
        if spec.reconstruction in ('shepard8_hann_local_time_v1',
                                   'sinc8_hann_local_time_v1'):
            # Both bounded irregular-event modes use at most 17 captures.
            # The windowed-sinc mode is density-weighted in physical seconds,
            # not a uniform-grid sinc silently applied to a changing clock.
            require(evaluation.budget.max_filter_taps >= 17,
                    'local-time reconstruction exceeds admitted kernel support')
        if spec.prefilter in STATIC_FIR_PREFILTER_POLICIES:
            require(not spec.clock.points_hz, 'static FIR prefilter rejects modulated virtual rate')
            if spec.prefilter == GUARDED_CLEAN_PREFILTER:
                # A phase reset breaks the uniform capture lattice even if the
                # configured Hz is constant. Keep the clean *comparison* strict;
                # dirty capture and static-cutoff artistic FIRs may deliberately
                # operate across a discontinuous clock.
                require(not spec.clock.resets,
                        'guarded clean FIR requires an uninterrupted uniform virtual clock')
            require(spec.clock.rate.hz < source.sample_rate_hz,
                    'static FIR prefilter requires virtual rate below source rate')
            taps = 129 if spec.prefilter == GUARDED_CLEAN_PREFILTER else 33
            require(evaluation.budget.max_filter_taps >= taps,
                    'static FIR exceeds admitted tap budget')
            _static_fir_kernel(source.sample_rate_hz, spec.clock.rate.hz, spec.prefilter)
        active = not spec.is_boundary_identity
        require(active or rate == source.sample_rate_hz, 'exact bypass requires matched source/numerical grids; no hidden resampling')
        if context_sha256 is None:
            context_sha256 = digest({'domain': EXECUTION_DOMAIN, 'extent': qtext(end), 'origin': qtext(origin)})
        if source_revision_sha256 is None:
            source_revision_sha256 = source.asset.sha256
        identity = bind_render_identity(spec, evaluation, input_asset=source.asset,
                    source_revision_sha256=source_revision_sha256,
                    rack_revision_sha256=_NO_RACK, graph_revision_sha256=_NO_GRAPH,
                    context_sha256=context_sha256, delivery_rate_hz=source.sample_rate_hz,
                    start_s=qtext(origin), end_s=qtext(end))
        _notify(progress, 0.0, cancelled)
        events = clock.events(cancelled=cancelled) if active else ()
        coordinates, first_frames = [], []
        minimum_interval_rate = math.inf
        maximum_interval_rate = 0.0
        timestamp_rounding = 0.0
        captured = np.empty((len(events), spec.channels), dtype=np.float64)
        pcm = source.pcm.reshape(asset['frame_count'], spec.channels)
        capture_pcm = pcm
        if active and spec.prefilter in STATIC_FIR_PREFILTER_POLICIES:
            kernel, _ = _static_fir_kernel(source.sample_rate_hz, spec.clock.rate.hz, spec.prefilter)
            capture_pcm = _prefilter_static_source(pcm, kernel, spec.input_boundary, cancelled)
        for i in range(len(events)):
            if i % _BLOCK == 0:
                _notify(progress, i / max(len(events), 1), cancelled)
            coordinate = clock.event_coordinate(i)
            relative = _relative(coordinate, origin)
            if coordinates:
                interval_rate = 1.0 / float(_difference(relative, coordinates[-1]))
                minimum_interval_rate = min(minimum_interval_rate, interval_rate)
                maximum_interval_rate = max(maximum_interval_rate, interval_rate)
            with localcontext(Context(prec=80)):
                timestamp_rounding = max(timestamp_rounding,
                    float(abs(Decimal.from_float(events[i].time_s) - _decimal(coordinate))))
            coordinates.append(relative)
            first_frames.append(_first_frame(clock, i, coordinate, origin, rate, frame_count))
            with localcontext(Context(prec=80)):
                captured[i] = _sample_at(capture_pcm, relative * source.sample_rate_hz, spec.capture, spec.input_boundary)
        require(np.isfinite(captured).all(), 'capture produced nonfinite audio')
        _notify(progress, 1.0, cancelled)
        values = dict(source=source, spec=spec, evaluation=evaluation, identity=identity,
                      clock=clock, frame_count=frame_count, events=events,
                      captures=_immutable(captured), _coordinates=tuple(coordinates),
                      _first_frames=_immutable(np.asarray(first_frames, dtype=np.int64)),
                      _origin=origin, _active=active,
                      _interval_rate_range=(minimum_interval_rate, maximum_interval_rate) if len(events) > 1 else None,
                      _timestamp_rounding_s=timestamp_rounding)
        require(set(values) == {f.name for f in fields(cls)}, 'incomplete sampler preparation')
        result = object.__new__(cls)
        for name, value in values.items():
            object.__setattr__(result, name, value)
        _cancel(cancelled)
        return result

    def checkpoint(self, frame: int) -> SamplerCheckpoint:
        integer(frame, 'checkpoint frame', 0, self.frame_count)
        at = self._origin + Fraction(frame, self.sample_rate_hz)
        clock_state = self.clock.checkpoint(qtext(at))
        next_index = clock_state.events_before if self._active else 0
        previous = next_index - 1
        before = tuple(float(x) for x in self.captures[previous]) if self._active and previous >= 0 else ()
        after = tuple(float(x) for x in self.captures[next_index]) if self._active and next_index < len(self.events) else ()
        return SamplerCheckpoint(self.render_sha256, frame, clock_state, previous, before,
                                 next_index, after, self._active)

    def _dry(self, start, stop):
        row = self.source.asset.to_dict()
        pcm = self.source.pcm.reshape(row['frame_count'], self.spec.channels)
        indices = np.arange(start, stop, dtype=np.int64)
        # Integer quotient/remainder avoid phase drift and chunk-dependent
        # floating operations when evaluating the same source on another grid.
        positions = indices * self.source.sample_rate_hz
        left, remainder = positions // self.sample_rate_hz, positions % self.sample_rate_hz
        def values(at):
            if not len(pcm):
                return np.zeros((len(at), self.spec.channels), dtype=np.float64)
            selected = pcm[np.clip(at, 0, len(pcm) - 1)].astype(np.float64)
            if self.spec.input_boundary == 'zero_pad':
                selected[(at < 0) | (at >= len(pcm))] = 0
            return selected
        a, b = values(left), values(left + 1)
        return a + (remainder / self.sample_rate_hz)[:, None] * (b - a)

    def render(self, start_frame: int | None = None, stop_frame: int | None = None,
               *, checkpoint: SamplerCheckpoint | None = None, cancelled=None, progress=None) -> SamplerResult:
        _check_hooks(cancelled, progress)
        _cancel(cancelled)
        if checkpoint is not None:
            record(checkpoint, SamplerCheckpoint, 'sampler checkpoint')
            require(checkpoint == self.checkpoint(checkpoint.next_frame), 'foreign/stale/tampered sampler checkpoint')
        start = (checkpoint.next_frame if checkpoint is not None else 0) if start_frame is None else start_frame
        stop = self.frame_count if stop_frame is None else stop_frame
        integer(start, 'region start frame', 0, self.frame_count)
        integer(stop, 'region stop frame', start, self.frame_count)
        require(checkpoint is None or checkpoint.next_frame == start, 'checkpoint/region start mismatch')
        _notify(progress, 0.0, cancelled)
        out = np.zeros((stop - start, self.spec.channels), dtype=np.float64 if self._active else np.float32)
        if not self._active:
            # Matching grids were admitted before any audio work. Copy original
            # bytes, including signed zero; crop/pad only under the saved bound.
            source = self.source.pcm.reshape(-1, self.spec.channels)
            for a in range(start, stop, _BLOCK):
                b = min(a + _BLOCK, stop)
                overlap = max(a, min(b, len(source)))
                if a < overlap:
                    out[a - start:overlap - start] = source[a:overlap]
                if overlap < b and len(source) and self.spec.input_boundary == 'edge_hold':
                    out[overlap - start:b - start] = source[-1]
                _notify(progress, (b - start) / max(stop - start, 1), cancelled)
        else:
            # Process numerical blocks; each sample uses a fixed event-relative
            # arithmetic anchor, independent of the requested chunk boundaries.
            for a in range(start, stop, _BLOCK):
                b = min(a + _BLOCK, stop)
                _cancel(cancelled)
                frames = np.arange(a, b, dtype=np.int64)
                owners = np.searchsorted(self._first_frames, frames, side='right') - 1
                block = np.zeros((b - a, self.spec.channels), dtype=np.float64)
                for owner in np.unique(owners):
                    if owner < 0:
                        continue
                    mask = owners == owner
                    left = self.captures[owner]
                    if self.spec.reconstruction == 'hold_v1' or owner + 1 == len(self.events):
                        block[mask] = left
                    else:
                        duration = _difference(self._coordinates[owner + 1], self._coordinates[owner])
                        anchor = int(self._first_frames[owner])
                        alpha0 = _ratio(_difference(Fraction(anchor, self.sample_rate_hz), self._coordinates[owner]), duration)
                        step = _ratio(Fraction(1, self.sample_rate_hz), duration)
                        alpha = alpha0 + (frames[mask] - anchor) * step
                        right = self.captures[owner + 1]
                        if self.spec.reconstruction in ('sinc4_hann_uniform_v1', 'sinc8_hann_uniform_v1'):
                            # Static uniform grid only (admitted at prepare).
                            # Evaluate physical-time cardinal-sinc with an
                            # explicit radius-4 or radius-8 symmetric Hann window.
                            # Renormalize the truncated edge kernel for
                            # declared constant-signal DC response; this
                            # does not perform global peak normalization.
                            radius = 4 if self.spec.reconstruction == 'sinc4_hann_uniform_v1' else 8
                            positions = np.flatnonzero(mask)
                            for j, relative in zip(positions, alpha):
                                if relative == 0:
                                    block[j] = left  # exact event capture
                                    continue
                                lo = max(0, owner - (radius - 1))
                                hi = min(len(self.events), owner + radius + 1)
                                offsets = np.arange(lo, hi, dtype=np.float64) - owner
                                x = relative - offsets
                                support = np.abs(x) < radius
                                weights = np.zeros(len(offsets), dtype=np.float64)
                                weights[support] = (np.sinc(x[support]) *
                                    (0.5 + 0.5 * np.cos(np.pi * x[support] / radius)))
                                dc = float(np.sum(weights))
                                require(math.isfinite(dc) and abs(dc) > 1e-12,
                                        'uniform Hann sinc local DC normalization invalid')
                                block[j] = np.sum(self.captures[lo:hi] *
                                                  weights[:, None], axis=0) / dc
                        elif self.spec.reconstruction == 'sinc8_hann_local_time_v1':
                            # Experimental, time-aware *nonuniform* windowed
                            # sinc quadrature. h[k] is the physical Voronoi
                            # cell width (half adjacent span at interiors,
                            # immediate interval at endpoints). Weighting by
                            # h[k] prevents a locally dense event cluster
                            # from receiving disproportionate mass. This
                            # is not ideal nonuniform-sampling inversion:
                            # ringing and aliases already captured survive.
                            positions = np.flatnonzero(mask)
                            for j, frame in zip(positions, frames[mask]):
                                t = Fraction(int(frame), self.sample_rate_hz)
                                lo = max(0, owner - 8)
                                hi = min(len(self.events), owner + 9)
                                weights = np.zeros(hi - lo, dtype=np.float64)
                                for k in range(lo, hi):
                                    delta = _difference(t, self._coordinates[k])
                                    if delta == 0:
                                        # Preserve an exact event's captured
                                        # amplitude, even on a nonuniform grid.
                                        weights.fill(0)
                                        weights[k - lo] = 1
                                        break
                                    if k == 0:
                                        h = _difference(self._coordinates[1],
                                                        self._coordinates[0])
                                    elif k == len(self.events) - 1:
                                        h = _difference(self._coordinates[-1],
                                                        self._coordinates[-2])
                                    else:
                                        h = _difference(self._coordinates[k + 1],
                                                        self._coordinates[k - 1]) / 2
                                    x = _ratio(delta, h)
                                    if abs(x) < 8:
                                        weights[k - lo] = (float(h) * float(np.sinc(x))
                                            * (0.5 + 0.5 * math.cos(math.pi * x / 8)))
                                dc = float(np.sum(weights))
                                mass = float(np.sum(np.abs(weights)))
                                # Negative sinc lobes can cancel. Refuse a
                                # numerically ill-conditioned DC normalizer
                                # rather than amplify an unbounded result.
                                require(math.isfinite(dc) and math.isfinite(mass)
                                        and mass > 0 and abs(dc) > 1e-8 * mass,
                                        'local-time windowed-sinc has ill-conditioned DC mass')
                                block[j] = np.sum(self.captures[lo:hi] *
                                                  weights[:, None], axis=0) / dc
                        elif self.spec.reconstruction == 'shepard8_hann_local_time_v1':
                            # Bounded, explicitly non-bandlimited irregular-event
                            # Shepard reconstruction: each kernel's scale is
                            # the mean of its adjacent physical event intervals.
                            # Positive inverse-square weights, tapered smoothly
                            # to zero at +/-8 local spacings, preserve DC and
                            # approach exact captures continuously. The event
                            # index window also prevents unbounded work when
                            # a local interval becomes unusually wide.
                            positions = np.flatnonzero(mask)
                            for j, frame in zip(positions, frames[mask]):
                                t = Fraction(int(frame), self.sample_rate_hz)
                                if _difference(t, self._coordinates[owner]) == 0:
                                    block[j] = left
                                    continue
                                lo = max(0, owner - 8)
                                hi = min(len(self.events), owner + 9)
                                weights = np.zeros(hi - lo, dtype=np.float64)
                                for k in range(lo, hi):
                                    if k == 0:
                                        scale = _difference(self._coordinates[1], self._coordinates[0])
                                    elif k == len(self.events) - 1:
                                        scale = _difference(self._coordinates[-1], self._coordinates[-2])
                                    else:
                                        scale = _difference(self._coordinates[k + 1], self._coordinates[k - 1]) / 2
                                    x = _ratio(_difference(t, self._coordinates[k]), scale)
                                    if x == 0:
                                        # Exact source/event capture, no interpolation
                                        # or binary64 distance-singularity substitution.
                                        weights.fill(0)
                                        weights[k - lo] = 1
                                        break
                                    if abs(x) < 8:
                                        weights[k - lo] = (0.5 + 0.5 * math.cos(math.pi * x / 8)) / (x * x)
                                dc = float(np.sum(weights))
                                require(math.isfinite(dc) and dc > 0,
                                        'local-time Shepard reconstruction has no positive finite kernel mass')
                                block[j] = np.sum(self.captures[lo:hi] * weights[:, None], axis=0) / dc
                        elif self.spec.reconstruction == 'nearest_time_v1':
                            # Decide ties using exact/Decimal80 event coordinates;
                            # a binary64 midpoint comparison can choose the
                            # wrong event near a sub-sample rational boundary.
                            before_midpoint = np.fromiter(
                                (2 * _difference(Fraction(int(frame), self.sample_rate_hz),
                                                 self._coordinates[owner]) <= duration
                                 for frame in frames[mask]),
                                dtype=bool, count=int(np.count_nonzero(mask)))
                            block[mask] = np.where(before_midpoint[:, None], left, right)
                        elif self.spec.reconstruction == 'cubic_time_v1':
                            # Nonuniform cubic Hermite: slopes use physical event
                            # spacing, not source/evaluation sample indices.
                            span = float(duration)
                            if owner > 0:
                                previous_span = float(_difference(self._coordinates[owner + 1],
                                                                 self._coordinates[owner - 1]))
                                slope_left = (right - self.captures[owner - 1]) / previous_span
                            else:
                                slope_left = (right - left) / span
                            if owner + 2 < len(self.events):
                                next_span = float(_difference(self._coordinates[owner + 2],
                                                             self._coordinates[owner]))
                                slope_right = (self.captures[owner + 2] - left) / next_span
                            else:
                                slope_right = (right - left) / span
                            u = alpha[:, None]
                            u2, u3 = u * u, u * u * u
                            block[mask] = ((2*u3 - 3*u2 + 1)*left
                                           + (u3 - 2*u2 + u)*span*slope_left
                                           + (-2*u3 + 3*u2)*right
                                           + (u3 - u2)*span*slope_right)
                        else:
                            block[mask] = left + alpha[:, None] * (right - left)
                if self.spec.wet != 1:
                    dry = self._dry(a, b)
                    block = (1.0 - self.spec.wet) * dry + self.spec.wet * block
                require(np.isfinite(block).all(), 'reconstruction produced nonfinite audio')
                out[a - start:b - start] = block
                _notify(progress, (b - start) / max(stop - start, 1), cancelled)
        _notify(progress, 1.0, cancelled)
        state = self.checkpoint(stop)
        if self.source._mono:
            out = out[:, 0]
        audio = _immutable(out)
        diagnostics = self._diagnostics(start, stop, audio)
        _cancel(cancelled)
        return SamplerResult(audio, state, diagnostics, self.render_sha256)

    def _diagnostics(self, start, stop, audio):
        lo, hi = self.spec.clock.rate_bounds()
        return {
            'method': SAMPLER_AUDIO_METHOD, 'numerical_filter': SAMPLER_NUMERICAL_FILTER,
            'quality': 'fixed-grid point evaluation; no final antialias conversion or convergence claim',
            'source_asset_sha256': self.source.asset.sha256, 'sonic_sha256': self.spec.sonic_sha256,
            'render_sha256': self.render_sha256, 'source_rate_hz': self.source.sample_rate_hz,
            'numerical_rate_hz': self.sample_rate_hz, 'delivery_conversion_performed': False,
            'requested_rate_range_hz': [float(lo), float(hi)],
            'realized_interval_rate_range_hz': list(self._interval_rate_range) if self._interval_rate_range else None,
            'admitted_event_count': self.clock.event_count, 'captured_event_count': len(self.events),
            'clock_method': self.evaluation.clock_method, 'max_timestamp_display_rounding_s': self._timestamp_rounding_s,
            'clock_oracle_tolerance': '2e-12 seconds + 8 ulps; counts and membership exact',
            'origin_s': self.spec.clock.origin_s, 'initial_phase_cycles': self.spec.clock.phase_cycles,
            'resets': [r.to_dict() for r in self.spec.clock.resets],
            'capture': self.spec.capture,
            'capture_support_source_frames': ([-1, 0, 1, 2] if self.spec.capture == 'cubic_catmull_rom_v1'
                                              else [0, 1] if self.spec.capture == 'linear_v1' else [0]),
            'reconstruction': self.spec.reconstruction,
            'reconstruction_support_events': (4 if self.spec.reconstruction == 'sinc4_hann_uniform_v1'
                                              else 8 if self.spec.reconstruction in
                                              ('sinc8_hann_uniform_v1', 'shepard8_hann_local_time_v1',
                                               'sinc8_hann_local_time_v1')
                                              else 2 if self.spec.reconstruction == 'cubic_time_v1'
                                              else 1 if self.spec.reconstruction != 'hold_v1' else 0),
            'reconstruction_window': ('hann_symmetric_radius_4_v1'
                                      if self.spec.reconstruction == 'sinc4_hann_uniform_v1'
                                      else 'hann_symmetric_radius_8_v1'
                                      if self.spec.reconstruction == 'sinc8_hann_uniform_v1'
                                      else 'hann_radius_8_local_time_density_weighted_sinc_v1'
                                      if self.spec.reconstruction == 'sinc8_hann_local_time_v1'
                                      else 'hann_symmetric_radius_8_local_shepard_inverse_square_v1'
                                      if self.spec.reconstruction == 'shepard8_hann_local_time_v1' else None),
            'prefilter': self.spec.prefilter,
            'prefilter_support_source_frames': (64 if self.spec.prefilter == GUARDED_CLEAN_PREFILTER
                                                 else 16 if self.spec.prefilter != 'off_v1' else 0),
            'prefilter_window': ('kaiser_beta10_129_v1' if self.spec.prefilter == GUARDED_CLEAN_PREFILTER
                                 else 'hann_33_v1' if self.spec.prefilter != 'off_v1' else None),
            'prefilter_cutoff_hz': (float(STATIC_FIR_PREFILTER_POLICIES[self.spec.prefilter][0] *
                                          self.spec.clock.rate.hz)
                                    if self.spec.prefilter != 'off_v1' else None),
            'prefilter_strength': (float(STATIC_FIR_PREFILTER_POLICIES[self.spec.prefilter][1])
                                   if self.spec.prefilter != 'off_v1' else None),
            'prefilter_coefficients_sha256': (
                hashlib.sha256(_static_fir_kernel(self.source.sample_rate_hz,
                                            self.spec.clock.rate.hz, self.spec.prefilter)[0].astype('<f8').tobytes()).hexdigest()
                if self.spec.prefilter != 'off_v1' else None),
            'input_boundary': self.spec.input_boundary, 'stereo_link': self.spec.stereo_link,
            'channel_identities': ['mono'] if self.spec.channels == 1 else ['left', 'right'],
            'context': 'complete admitted render including next-capture lookahead; no region budget discount',
            'full_output_frames': self.frame_count, 'region_frames': [start, stop],
            'output_extent_s': qtext(Fraction(stop - start, self.sample_rate_hz)),
            'finite': bool(np.isfinite(audio).all()),
            'peak': float(np.max(np.abs(audio))) if audio.size else 0.0,
            'pcm_sha256': hashlib.sha256(np.asarray(audio, dtype='<f8').tobytes()).hexdigest(),
            'pcm_identity_domain': 'unclamped-f64le-interleaved-numerical-v1',
        }


def render_sampler(source: FrozenInput, spec: SonicSpec, evaluation: EvaluationPolicy | None = None,
                   *, frame_count=None, cancelled=None, progress=None) -> SamplerResult:
    """Single atomic pass with monotone hooks suitable for JobContext adapters.

    For the existing scheduler pass ``cancelled=lambda: (ctx.check_cancelled()
    or False)`` and ``progress=ctx.progress``. The scheduler then retains its own
    JobCancelled type and sole publication/cache authority. No pool is created.
    """
    _check_hooks(cancelled, progress)
    plan = SamplerPlan.prepare(source, spec, evaluation, frame_count=frame_count,
                               cancelled=cancelled, progress=(lambda p: progress(p * .5)) if progress else None)
    return plan.render(cancelled=cancelled, progress=(lambda p: progress(.5 + p * .5)) if progress else None)
