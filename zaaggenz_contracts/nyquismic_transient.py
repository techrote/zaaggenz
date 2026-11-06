"""NYQ-004 frozen upstream transient-onset to ordinary rate-control route.

A bounded positive window-to-window RMS rise detector, not a realtime onset
classifier, spectral feature or graph node. Reuses the fully checked immutable
input / graph-owner ancestry gate of the upstream RMS adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .nyquismic import (
    ModulationRoute, Point, _Record, normalized, qtext, record, require,
)
from .nyquismic_clock import ClockCancelled
from .nyquismic_input_envelope import (
    UpstreamRmsPolicy, compile_upstream_rms_route,
)

METHOD = 'nyq.upstream-rms-rise-transient-v1'


@dataclass(frozen=True)
class UpstreamTransientPolicy(_Record):
    """Saved source identity/support and exact dimensionless onset threshold.

    A value at window k equals max(0, RMS[k]-RMS[k-1]-threshold). The first
    window compares to silence. RMS values are the already normalized bounded
    rationals of the source's explicit full-scale reference amplitude.
    """
    version: str = 'nyq.upstream-transient-policy.v1'
    source: UpstreamRmsPolicy = UpstreamRmsPolicy()
    minimum_rise: str = '0/1'
    _children = {'source': UpstreamRmsPolicy}

    def __post_init__(self):
        require(self.version == 'nyq.upstream-transient-policy.v1',
                'unsupported upstream transient method version')
        record(self.source, UpstreamRmsPolicy, 'transient source policy')
        normalized(self, 'minimum_rise', 0, 1)
        # The upstream RMS route carries a neutral pre-origin value and an
        # explicit first-window point at a delayed source origin. The onset
        # compiler retains that support rather than leaking it at time zero.


@dataclass(frozen=True)
class UpstreamTransientResult:
    policy: UpstreamTransientPolicy
    route: ModulationRoute
    diagnostics: dict


def compile_upstream_transient_route(
    pcm, policy: UpstreamTransientPolicy, *, consumer_id: str,
    upstream_ids: tuple[str, ...], route_id: str,
    mapping: str = 'add_hz', depth: float = 0.0, cancelled=None,
) -> UpstreamTransientResult:
    """Compile one source-verified positive RMS-rise onset lane.

    Reuse upstream full-snapshot hash, float32 PCM, exact window times,
    denominator and ancestry validation. This adapter does not validate a
    graph itself: upstream_ids MUST come from its verified DAG authority.
    No partial route is returned on cancellation or invalid source.
    """
    record(policy, UpstreamTransientPolicy, 'transient detector policy')
    base = compile_upstream_rms_route(
        pcm, policy.source, consumer_id=consumer_id,
        upstream_ids=upstream_ids, route_id=route_id,
        mapping='add_hz', depth=0.0, cancelled=cancelled,
    )
    levels = (Fraction(base.route.initial),
              *(Fraction(point.value) for point in base.route.points))
    threshold = Fraction(policy.minimum_rise)
    previous = Fraction(0)
    rises = []
    for i, level in enumerate(levels):
        if cancelled is not None and cancelled():
            raise ClockCancelled('upstream transient cancelled; no partial route')
        rises.append(max(Fraction(0), level - previous - threshold))
        previous = level
    # Each RMS level is deliberately quantized to <=1e6 denominator. Exact
    # subtraction of two such fractions may have a denominator near 1e12,
    # which the frozen Point contract (<=1e9) cannot serialize. Quantize the
    # derived rise *after* exact subtraction back to the input RMS resolution;
    # do not widen the public rational contract or silently clip the clock.
    points = tuple(
        Point(p.time_s, qtext(rises[i + 1].limit_denominator(1_000_000)))
        for i, p in enumerate(base.route.points)
    )
    route = ModulationRoute(
        id=route_id, mapping=mapping, depth=depth,
        initial=qtext(rises[0].limit_denominator(1_000_000)) if rises else '0/1',
        points=points, interpolation='step',
    )
    if cancelled is not None and cancelled():
        raise ClockCancelled('upstream transient cancelled before route publication')
    return UpstreamTransientResult(
        policy=policy, route=route,
        diagnostics={
            'method': METHOD, 'policy_sha256': policy.sha256,
            'source_id': policy.source.source_id,
            'source_sha256': policy.source.source_sha256,
            'source_policy_sha256': policy.source.sha256,
            'upstream_rms_route_sha256': base.route.sha256,
            'route_sha256': route.sha256, 'windows': base.diagnostics['windows'],
            'window_frames': policy.source.window_frames,
            'selected_channel': policy.source.channel,
            'lookahead_s': base.diagnostics['lookahead_s'],
            'minimum_rise': policy.minimum_rise,
            'detector': 'positive-RMS-rise/previous-window-v1',
            'rms_quantization_denominator': 1000000,
            'rise_quantization_denominator': 1000000,
            'clipping': 'reject-upstream-rms-and-no-transient-clipping',
            'graph_topology': 'caller-verified-only',
        },
    )
