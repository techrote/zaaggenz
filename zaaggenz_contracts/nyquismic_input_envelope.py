"""NYQ-004 opt-in upstream audio envelope -> frozen standard clock route.

Offline adapter only. This does not register a graph feature tap or weaken the
NYQ-002 routed-clock rejection. The caller must supply its actual graph's
verified upstream IDs; a claimed upstream list is not graph-cycle validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math

import numpy as np

from .nyquismic import (
    MAX_FRAMES, MAX_POINTS, MAX_TIME_S, ModulationRoute, Point, _Record,
    hash_value, identifier, integer, qtext, rational_value, record, require,
)
from .nyquismic_clock import ClockCancelled

METHOD = 'nyq.upstream-rms-envelope-v1'


@dataclass(frozen=True)
class UpstreamRmsPolicy(_Record):
    """Full-snapshot input identity and half-open, lookahead-based RMS policy.

    The raw source asset must already be an accepted immutable f32 PCM stream.
    Each control window [kW, (k+1)W) contributes an absolute-time step from
    its start; reading the full window means lookahead up to W/source_rate.
    Gain is explicitly chosen, not automatically peak/RMS normalized.
    """
    version: str = 'nyq.upstream-rms-policy.v1'
    source_id: str = 'upstream'
    source_sha256: str = '0' * 64
    sample_rate_hz: int = 48000
    frames: int = 0
    channel: int = 0
    window_frames: int = 480
    reference_amplitude: str = '1/1'
    origin_s: str = '0/1'

    def __post_init__(self):
        require(self.version == 'nyq.upstream-rms-policy.v1', 'upstream RMS version unsupported')
        identifier(self.source_id, 'upstream source ID')
        hash_value(self.source_sha256, 'upstream PCM hash')
        integer(self.sample_rate_hz, 'upstream sample rate', 8000, 192000)
        integer(self.frames, 'upstream frame count', 0, MAX_FRAMES)
        integer(self.channel, 'upstream selected channel', 0, 1)
        integer(self.window_frames, 'RMS control window frames', 1, 192000)
        reference = rational_value(self.reference_amplitude, 'RMS reference amplitude',
                                   Fraction(1, 1000000), 1024)
        origin = rational_value(self.origin_s, 'upstream origin', 0, MAX_TIME_S)
        require(origin + Fraction(self.frames, self.sample_rate_hz) <= MAX_TIME_S,
                'upstream PCM exceeds physical-time extent')
        object.__setattr__(self, 'reference_amplitude', qtext(reference))
        object.__setattr__(self, 'origin_s', qtext(origin))


@dataclass(frozen=True)
class UpstreamRmsResult:
    policy: UpstreamRmsPolicy
    route: ModulationRoute
    diagnostics: dict


def compile_upstream_rms_route(
    pcm, policy: UpstreamRmsPolicy, *, consumer_id: str,
    upstream_ids: tuple[str, ...], route_id: str,
    mapping: str = 'add_hz', depth: float = 0.0, cancelled=None,
) -> UpstreamRmsResult:
    """Bind immutable PCM to a bounded, saved, right-continuous step route.

    The graph owner must pass a verified upstream set (not a UI label or
    inferred processing order). No downstream/self/current-output taps.
    Window readings are full-context and independent of render block size.
    """
    record(policy, UpstreamRmsPolicy, 'upstream RMS policy')
    identifier(consumer_id, 'RMS consumer ID')
    require(type(upstream_ids) is tuple and len(upstream_ids) <= 128,
            'upstream source set must be bounded tuple')
    for node in upstream_ids:
        identifier(node, 'upstream ancestor ID')
    require(len(set(upstream_ids)) == len(upstream_ids),
            'upstream ancestor IDs must be unique')
    require(policy.source_id != consumer_id and consumer_id not in upstream_ids
            and policy.source_id in upstream_ids,
            'source is not a verified acyclic upstream input')
    require(cancelled is None or callable(cancelled), 'RMS cancellation hook must be callable')
    if cancelled is not None and cancelled():
        raise ClockCancelled('upstream RMS cancelled before source validation')
    # No implicit stereo mixing, integer PCM conversion or hidden source
    # resampling. The byte identity covers both channels of the actual asset.
    samples = np.asarray(pcm)
    require(samples.dtype == np.dtype('float32') and samples.ndim in (1, 2),
            'upstream input must be float32 mono/stereo PCM')
    channel_count = 1 if samples.ndim == 1 else samples.shape[1]
    require(channel_count in (1, 2) and policy.channel < channel_count,
            'upstream channel selection invalid')
    require(samples.shape[0] == policy.frames and samples.size <= MAX_FRAMES,
            'upstream PCM frame budget or snapshot mismatch')
    require(np.isfinite(samples).all(), 'upstream PCM must be finite')
    # Force a private canonical PCM snapshot *before* the hash. A caller
    # may hold a mutable contiguous NumPy buffer; reading it again after
    # validation would otherwise allow hash/level TOCTOU divergence.
    raw = np.array(samples, dtype='<f4', order='C', copy=True)
    require(hashlib.sha256(raw.tobytes()).hexdigest() == policy.source_sha256,
            'upstream source content hash mismatch')
    windows = (policy.frames + policy.window_frames - 1) // policy.window_frames
    # The accepted route has <=256 actual points. The initial window
    # supplies route.initial; windows after the first supply points.
    # A delayed source must first publish a neutral route, then a transition
    # at the true physical-time origin. This consumes an extra Point slot.
    origin = Fraction(policy.origin_s)
    delayed = bool(windows) and origin > 0
    require(windows + int(delayed) <= MAX_POINTS + 1,
            'upstream RMS control budget exceeded')
    source = raw if raw.ndim == 1 else raw[:, policy.channel]
    scale = float(Fraction(policy.reference_amplitude))
    levels = []
    for k in range(windows):
        if cancelled is not None and cancelled():
            raise ClockCancelled('upstream RMS cancelled; no partial route')
        block = np.asarray(source[k * policy.window_frames:
                                  (k + 1) * policy.window_frames], dtype=np.float64)
        # float32 PCM may contain finite numbers whose square overflows
        # float32; compute in float64 and reject nonfinite reductions.
        value = float(np.sqrt(np.mean(np.square(block)))) / scale
        require(math.isfinite(value) and value <= 1,
                'upstream RMS level exceeds explicit reference; no hidden clamping')
        # Denominator capped by existing bounded rational point contract.
        levels.append(Fraction.from_float(value).limit_denominator(1_000_000))
    points = tuple(
        Point(qtext(Fraction(policy.origin_s) +
                    Fraction(k * policy.window_frames, policy.sample_rate_hz)),
              qtext(levels[k]))
        for k in range(1, windows)
    )
    # ModulationRoute.initial applies from absolute time zero. Publishing the
    # first measured window there for a delayed source would leak future audio
    # into the clock before the source exists. Insert an explicit transition
    # at origin, and remain neutral before it; preserve zero-origin byte output.
    if delayed:
        points = (Point(qtext(origin), qtext(levels[0])),) + points
    route = ModulationRoute(id=route_id, mapping=mapping, depth=depth,
                            initial='0/1' if delayed or not levels else qtext(levels[0]),
                            points=points, interpolation='step')
    if cancelled is not None and cancelled():
        raise ClockCancelled('upstream RMS cancelled before route publication')
    return UpstreamRmsResult(
        policy=policy, route=route,
        diagnostics={'method': METHOD, 'source_id': policy.source_id,
                     'source_sha256': policy.source_sha256,
                     'policy_sha256': policy.sha256, 'route_sha256': route.sha256,
                     'windows': windows, 'source_frames': policy.frames,
                     'window_frames': policy.window_frames,
                     'lookahead_s': qtext(Fraction(policy.window_frames,
                                                  policy.sample_rate_hz)),
                     'selected_channel': policy.channel,
                     'interpolation': 'step',
                     'pre_origin_control': 'neutral_zero' if delayed else 'not_applicable',
                     'clipping': 'reject'},
    )
