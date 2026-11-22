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
    MAX_FRAMES, MAX_NODES, MAX_POINTS, MAX_TIME_S, ModulationRoute, Point, _Record,
    hash_value, identifier, integer, qtext, rational_value, record, require,
)
from .nyquismic_clock import ClockCancelled

METHOD = 'nyq.upstream-rms-envelope-v1'


@dataclass(frozen=True)
class UpstreamGraphEdge(_Record):
    """An immutable audio dependency: upstream output -> downstream input."""
    source_id: str
    destination_id: str

    def __post_init__(self):
        identifier(self.source_id, 'graph edge source')
        identifier(self.destination_id, 'graph edge destination')
        require(self.source_id != self.destination_id, 'graph self-dependency forbidden')


@dataclass(frozen=True)
class UpstreamGraphSnapshot(_Record):
    """Bounded acyclic snapshot; product integration must bind its SHA to live graph."""
    version: str = 'nyq.upstream-graph-snapshot.v1'
    nodes: tuple[str, ...] = ()
    edges: tuple[UpstreamGraphEdge, ...] = ()
    _children = {'edges': (UpstreamGraphEdge,)}

    def __post_init__(self):
        require(self.version == 'nyq.upstream-graph-snapshot.v1',
                'unsupported upstream graph snapshot version')
        require(type(self.nodes) is tuple and 1 <= len(self.nodes) <= MAX_NODES,
                'graph nodes must be a bounded nonempty tuple')
        for node in self.nodes:
            identifier(node, 'graph node')
        require(tuple(sorted(set(self.nodes))) == self.nodes,
                'graph nodes must be unique and sorted by stable ID')
        require(type(self.edges) is tuple and len(self.edges) <= 1024,
                'graph dependency edge budget exceeded')
        for edge in self.edges:
            record(edge, UpstreamGraphEdge, 'graph dependency edge')
        require(tuple(sorted(self.edges, key=lambda e: (e.source_id, e.destination_id))) == self.edges
                and len({(e.source_id, e.destination_id) for e in self.edges}) == len(self.edges),
                'graph edges must be unique and sorted by stable IDs')
        nodes = set(self.nodes)
        require(all(e.source_id in nodes and e.destination_id in nodes
                    for e in self.edges), 'graph edge has missing/foreign endpoint')
        outgoing = {n: [] for n in self.nodes}
        indegree = {n: 0 for n in self.nodes}
        for edge in self.edges:
            outgoing[edge.source_id].append(edge.destination_id)
            indegree[edge.destination_id] += 1
        ready = [node for node in self.nodes if not indegree[node]]
        visited = 0
        for node in ready:
            visited += 1
            for child in outgoing[node]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        require(visited == len(self.nodes), 'upstream graph contains a feedback cycle')

    @classmethod
    def from_dict(cls, data):
        require(type(data) is dict and set(data) == {'version', 'nodes', 'edges'}
                and type(data['nodes']) is list and type(data['edges']) is list,
                'upstream graph snapshot requires complete version/nodes/edges arrays')
        return cls(version=data['version'], nodes=tuple(data['nodes']),
                   edges=tuple(UpstreamGraphEdge.from_dict(edge) for edge in data['edges']))

    def ancestors_of(self, consumer_id: str) -> tuple[str, ...]:
        identifier(consumer_id, 'graph consumer ID')
        require(consumer_id in self.nodes, 'consumer absent from graph snapshot')
        parents = {n: [] for n in self.nodes}
        for edge in self.edges:
            parents[edge.destination_id].append(edge.source_id)
        seen = set()
        pending = list(parents[consumer_id])
        while pending:
            node = pending.pop()
            if node not in seen:
                seen.add(node)
                pending.extend(parents[node])
        return tuple(sorted(seen))


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
    graph_snapshot: UpstreamGraphSnapshot | None = None,
    expected_graph_sha256: str | None = None,
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
            'source is not a declared upstream input')
    if graph_snapshot is None:
        require(expected_graph_sha256 is None,
                'expected graph identity supplied without a topology snapshot')
    else:
        record(graph_snapshot, UpstreamGraphSnapshot, 'upstream graph snapshot')
        hash_value(expected_graph_sha256, 'expected current upstream graph SHA-256')
        require(graph_snapshot.sha256 == expected_graph_sha256,
                'stale or foreign upstream graph snapshot')
        require(policy.source_id in graph_snapshot.nodes,
                'input source missing from upstream graph snapshot')
        require(set(upstream_ids) == set(graph_snapshot.ancestors_of(consumer_id)),
                'upstream declaration disagrees with complete acyclic graph ancestry')
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
                     'clipping': 'reject',
                     'graph_topology': ('snapshot-dag-verified' if graph_snapshot is not None
                                        else 'caller-declared-only'),
                     'graph_snapshot_sha256': (graph_snapshot.sha256
                                               if graph_snapshot is not None else None)},
    )


@dataclass(frozen=True)
class UpstreamSignedSamplePolicy(_Record):
    """Source-bound, one-sample-per-control-step bipolar audio-rate source.

    This narrow adapter shares the immutable upstream PCM/DAG admission of
    UpstreamRmsPolicy but preserves sample *sign*, unlike RMS envelope control.
    The 256-point ModulationRoute limit bounds one admission to a short source
    excerpt; longer audio-rate streams are not silently decimated.
    """
    version: str = 'nyq.upstream-signed-sample-policy.v1'
    source: UpstreamRmsPolicy = UpstreamRmsPolicy(window_frames=1)
    tail: str = 'zero_after_source'
    _children = {'source': UpstreamRmsPolicy}

    def __post_init__(self):
        require(self.version == 'nyq.upstream-signed-sample-policy.v1',
                'unsupported signed sample control policy version')
        record(self.source, UpstreamRmsPolicy, 'signed sample source policy')
        require(self.source.window_frames == 1,
                'signed sample control requires one source frame per control step')
        require(self.tail in ('zero_after_source', 'hold_last'),
                'unsupported signed sample control tail policy')


@dataclass(frozen=True)
class UpstreamSignedSampleResult:
    policy: UpstreamSignedSamplePolicy
    route: ModulationRoute
    diagnostics: dict


def compile_upstream_signed_sample_route(
    pcm, policy: UpstreamSignedSamplePolicy, *, consumer_id: str,
    upstream_ids: tuple[str, ...], route_id: str,
    mapping: str = 'add_hz', depth: float = 0.0, cancelled=None,
    graph_snapshot: UpstreamGraphSnapshot | None = None,
    expected_graph_sha256: str | None = None,
) -> UpstreamSignedSampleResult:
    """Compile bounded signed f32 samples into exact-time clock rate steps.

    Reuse the fully checked RMS adapter only for source, bound and DAG
    authentication; *do not* use its sign-destroying RMS magnitudes as control.
    A private PCM snapshot is made before authentication and is the only
    array used thereafter (including against mutable caller-owned buffers).
    """
    record(policy, UpstreamSignedSamplePolicy, 'signed audio-rate policy')
    source = policy.source
    origin = Fraction(source.origin_s)
    delayed = origin > 0 and source.frames > 0
    tail_zero = policy.tail == 'zero_after_source' and source.frames > 0
    needed = max(0, source.frames - 1) + int(delayed) + int(tail_zero)
    require(needed <= MAX_POINTS,
            'signed sample route exceeds 256 exact-time points; no hidden decimation')
    # Preserve the accepted f32-only input rule. Converting an arbitrary input
    # dtype before authentication would silently change the user's source.
    samples = np.asarray(pcm)
    require(samples.dtype == np.dtype('float32') and samples.ndim in (1, 2),
            'signed sample source must be float32 mono/stereo PCM')
    frozen = np.array(samples, dtype='<f4', order='C', copy=True)
    checked = compile_upstream_rms_route(
        frozen, source, consumer_id=consumer_id, upstream_ids=upstream_ids,
        route_id=route_id, mapping='add_hz', depth=0.0, cancelled=cancelled,
        graph_snapshot=graph_snapshot,
        expected_graph_sha256=expected_graph_sha256,
    )
    chosen = frozen if frozen.ndim == 1 else frozen[:, source.channel]
    reference = Fraction(source.reference_amplitude)
    levels = []
    for i, sample in enumerate(chosen):
        if (i & 31) == 0 and cancelled is not None and cancelled():
            raise ClockCancelled('signed sample control cancelled before route publication')
        # Float32-to-float64 conversion is exact; division by the saved
        # rational reference and signed bounds are checked before the one
        # declared <=1e6 denominator control quantization.
        value = Fraction.from_float(float(sample)) / reference
        require(-1 <= value <= 1,
                'signed sample exceeds explicit reference amplitude')
        levels.append(value.limit_denominator(1_000_000))
    points = []
    if delayed:
        points.append(Point(qtext(origin), qtext(levels[0])))
    for i in range(1, len(levels)):
        points.append(Point(
            qtext(origin + Fraction(i, source.sample_rate_hz)),
            qtext(levels[i]),
        ))
    if tail_zero:
        points.append(Point(
            qtext(origin + Fraction(source.frames, source.sample_rate_hz)),
            '0/1',
        ))
    if cancelled is not None and cancelled():
        raise ClockCancelled('signed sample control cancelled before route publication')
    route = ModulationRoute(
        id=route_id, mapping=mapping, depth=depth,
        initial='0/1' if delayed or not levels else qtext(levels[0]),
        points=tuple(points), interpolation='step',
    )
    diagnostics = {
        'method': 'nyq.upstream-signed-sample-steps.v1',
        'policy_sha256': policy.sha256,
        'source_policy_sha256': source.sha256,
        'source_id': source.source_id,
        'source_sha256': source.source_sha256,
        'route_sha256': route.sha256,
        'source_frames': source.frames,
        'sample_rate_hz': source.sample_rate_hz,
        'channel': source.channel,
        'origin_s': source.origin_s,
        'tail': policy.tail,
        'route_points': len(points),
        'sample_quantization_denominator': 1_000_000,
        'lookahead_s': qtext(Fraction(1, source.sample_rate_hz)),
        'pre_origin_control': 'neutral_zero' if delayed else 'not_applicable',
        'graph_topology': checked.diagnostics['graph_topology'],
        'graph_snapshot_sha256': checked.diagnostics['graph_snapshot_sha256'],
        'product_graph_registered': False,
    }
    return UpstreamSignedSampleResult(policy, route, diagnostics)
