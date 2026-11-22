"""NYQ-004 source-authenticated upstream spectral-centroid clock control.

Experimental opt-in source-to-physical-time route. This is not a registered
Compose graph feature or permission to run a modified NYQ-002 SamplerPlan.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
import math

import numpy as np

from .nyquismic import (
    MAX_POINTS, ModulationRoute, Point, _Record, qtext, rational_value,
    record, require,
)
from .nyquismic_clock import ClockCancelled
from .nyquismic_input_envelope import (
    UpstreamGraphSnapshot, UpstreamRmsPolicy, compile_upstream_rms_route,
)

METHOD = 'nyq.source-bound-hann-centroid-steps.v1'
RATIONAL_DENOMINATOR = 1_000_000


@dataclass(frozen=True)
class UpstreamCentroidPolicy(_Record):
    """Full-window Hann magnitude centroid, AC-only, with explicit refusal.

    source authenticates the immutable source PCM, its physical origin and
    channel. A feature window [start, end) is visible at start, with the
    disclosed offline lookahead of one complete window.
    """
    version: str = 'nyq.upstream-centroid-policy.v1'
    source: UpstreamRmsPolicy = UpstreamRmsPolicy(window_frames=256)
    floor_hz: str = '0/1'
    ceiling_hz: str = '4000/1'
    minimum_ac_rms: str = '1/1000'
    low_confidence: str = 'reject'
    tail: str = 'zero_after_source'
    _children = {'source': UpstreamRmsPolicy}

    def __post_init__(self):
        require(self.version == 'nyq.upstream-centroid-policy.v1',
                'unsupported spectral centroid policy version')
        record(self.source, UpstreamRmsPolicy, 'centroid upstream PCM policy')
        width = self.source.window_frames
        require(32 <= width <= 8192 and width & (width - 1) == 0,
                'spectral centroid requires a 32..8192-frame power-of-two window')
        floor = rational_value(self.floor_hz, 'centroid floor Hz', 0,
                               Fraction(self.source.sample_rate_hz, 2))
        ceiling = rational_value(self.ceiling_hz, 'centroid ceiling Hz', 0,
                                 Fraction(self.source.sample_rate_hz, 2))
        require(floor < ceiling, 'centroid frequency range must be positive')
        minimum = rational_value(self.minimum_ac_rms, 'centroid minimum AC RMS',
                                 0, 1)
        require(self.low_confidence in ('reject', 'neutral_zero'),
                'centroid low-confidence policy must be explicit')
        require(self.tail in ('zero_after_source', 'hold_last'),
                'centroid tail policy must be explicit')
        object.__setattr__(self, 'floor_hz', qtext(floor))
        object.__setattr__(self, 'ceiling_hz', qtext(ceiling))
        object.__setattr__(self, 'minimum_ac_rms', qtext(minimum))


@dataclass(frozen=True)
class UpstreamCentroidResult:
    policy: UpstreamCentroidPolicy
    route: ModulationRoute
    diagnostics: dict


def compile_upstream_centroid_route(
    pcm, policy: UpstreamCentroidPolicy, *, consumer_id: str,
    upstream_ids: tuple[str, ...], route_id: str,
    mapping: str = 'add_hz', depth: float = 0.0, cancelled=None,
    graph_snapshot: UpstreamGraphSnapshot | None = None,
    expected_graph_sha256: str | None = None,
) -> UpstreamCentroidResult:
    """Turn *verified real PCM* spectral content into bounded event-time steps.

    Never use an unverified feature cache, inferred source identity or
    caller-only upstream list. The current graph owner must supply its exact
    DAG snapshot and expected revision hash. No partial route on refusal.
    """
    record(policy, UpstreamCentroidPolicy, 'spectral centroid source policy')
    record(graph_snapshot, UpstreamGraphSnapshot, 'required upstream DAG snapshot')
    require(expected_graph_sha256 is not None,
            'spectral centroid requires current graph SHA')
    require(cancelled is None or callable(cancelled),
            'spectral centroid cancellation hook must be callable')
    if cancelled is not None and cancelled():
        raise ClockCancelled('spectral centroid cancelled before source admission')
    source = policy.source
    width = source.window_frames
    require(source.frames > 0 and source.frames % width == 0,
            'spectral centroid requires nonempty complete source windows')
    count = source.frames // width
    origin = Fraction(source.origin_s)
    delayed = origin > 0
    tail_zero = policy.tail == 'zero_after_source'
    require(count - 1 + int(delayed) + int(tail_zero) <= MAX_POINTS,
            'spectral centroid route point budget exceeded')
    samples = np.asarray(pcm)
    require(samples.dtype == np.dtype('float32') and samples.ndim in (1, 2),
            'centroid source must be float32 mono/stereo PCM')
    # Freeze a private canonical copy *before* authenticating its hash.
    # Never re-read a mutable caller array after that identity check.
    frozen = np.array(samples, dtype='<f4', order='C', copy=True)
    authenticated = compile_upstream_rms_route(
        frozen, source, consumer_id=consumer_id, upstream_ids=upstream_ids,
        route_id=route_id, mapping='add_hz', depth=0.0, cancelled=cancelled,
        graph_snapshot=graph_snapshot,
        expected_graph_sha256=expected_graph_sha256,
    )
    selected = frozen if frozen.ndim == 1 else frozen[:, source.channel]
    taper = np.hanning(width).astype(np.float64)
    frequencies = np.fft.rfftfreq(width, d=1.0 / source.sample_rate_hz)
    reference = float(Fraction(source.reference_amplitude))
    minimum = float(Fraction(policy.minimum_ac_rms))
    floor = float(Fraction(policy.floor_hz))
    ceiling = float(Fraction(policy.ceiling_hz))
    levels: list[Fraction] = []
    centroids: list[str | None] = []
    confidences: list[str] = []
    unreliable: list[int] = []

    for i in range(count):
        if cancelled is not None and cancelled():
            raise ClockCancelled('spectral centroid cancelled during PCM analysis')
        window = np.asarray(selected[i * width:(i + 1) * width],
                            dtype=np.float64)
        # Disclose and remove DC before Hann analysis. Otherwise a constant
        # source acquires fictitious nonzero spectral centroid from leakage.
        ac = window - float(np.mean(window))
        ac_rms = float(np.sqrt(np.mean(ac * ac))) / reference
        require(math.isfinite(ac_rms), 'spectral centroid AC RMS must be finite')
        confidence = Fraction.from_float(ac_rms).limit_denominator(RATIONAL_DENOMINATOR)
        confidences.append(qtext(confidence))
        spectrum = np.abs(np.fft.rfft(ac * taper))
        spectrum[0] = 0.0
        weight = float(np.sum(spectrum, dtype=np.float64))
        if ac_rms <= minimum or not math.isfinite(weight) or weight <= 0.0:
            if policy.low_confidence == 'reject':
                require(False, 'spectral centroid missing or low-confidence AC feature')
            unreliable.append(i)
            levels.append(Fraction(0))
            centroids.append(None)
            continue
        centroid = float(np.dot(frequencies, spectrum) / weight)
        require(math.isfinite(centroid) and floor <= centroid <= ceiling,
                'spectral centroid outside declared Hz range; no hidden clipping')
        normalized = (centroid - floor) / (ceiling - floor)
        require(math.isfinite(normalized) and 0 <= normalized <= 1,
                'spectral centroid normalized value outside bounds')
        levels.append(Fraction.from_float(normalized).limit_denominator(RATIONAL_DENOMINATOR))
        centroids.append(str(centroid))

    points = []
    if delayed:
        points.append(Point(qtext(origin), qtext(levels[0])))
    for i in range(1, count):
        points.append(Point(qtext(origin + Fraction(i * width,
                                                   source.sample_rate_hz)),
                            qtext(levels[i])))
    if tail_zero:
        points.append(Point(qtext(origin + Fraction(source.frames,
                                                   source.sample_rate_hz)),
                            '0/1'))
    if cancelled is not None and cancelled():
        raise ClockCancelled('spectral centroid cancelled before route publication')
    route = ModulationRoute(
        id=route_id, mapping=mapping, depth=depth,
        initial='0/1' if delayed else qtext(levels[0]),
        points=tuple(points), interpolation='step',
    )
    digest = sha256()
    digest.update((METHOD + '\0' + policy.sha256 + '\0' +
                   authenticated.diagnostics['graph_snapshot_sha256'] +
                   '\0').encode('ascii'))
    for centroid, confidence, level in zip(centroids, confidences, levels):
        digest.update((str(centroid) + ':' + confidence + ':' +
                       qtext(level) + '\n').encode('ascii'))
    return UpstreamCentroidResult(
        policy=policy, route=route,
        diagnostics={
            'method': METHOD, 'policy_sha256': policy.sha256,
            'source_sha256': source.source_sha256,
            'source_policy_sha256': source.sha256,
            'feature_sha256': digest.hexdigest(),
            'route_sha256': route.sha256,
            'graph_snapshot_sha256': authenticated.diagnostics['graph_snapshot_sha256'],
            'graph_topology': 'snapshot-dag-verified',
            'windows': count, 'window_frames': width,
            'sample_rate_hz': source.sample_rate_hz,
            'channel': source.channel,
            'support': 'complete-half-open-window',
            'lookahead_s': qtext(Fraction(width, source.sample_rate_hz)),
            'window_hz': centroids, 'window_ac_rms_over_reference': confidences,
            'low_confidence_windows': unreliable,
            'low_confidence_policy': policy.low_confidence,
            'tail': policy.tail,
            'dc_policy': 'subtract-window-mean-before-Hann',
            'normalization': 'explicit-floor-ceiling-no-clamp',
            'control_denominator_bound': RATIONAL_DENOMINATOR,
            'source_revision_bound_to_live_compose': False,
            'product_graph_registered': False,
        },
    )
