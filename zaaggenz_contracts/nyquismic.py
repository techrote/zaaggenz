"""NYQ-001 1.0.0 sonic, evaluation and adapter contracts (no audio executor).

This is an opt-in contract family built on the existing strict JSON/canonical
identity primitives. It deliberately does not modify Contract, RenderRecipe,
Project, MultibandRack or the executable DSP registry. See
``docs/dsp/NYQ001_FOUNDATION.md`` for units, timing and capability boundaries.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from fractions import Fraction
import json
import math
import re
from typing import ClassVar

from .model import Contract, ContractError, check_json, canonical_bytes, digest, loads, seed_value

VERSION = '1.0.0'
MIN_RATE_HZ = Fraction(1, 1000)
MAX_RATE_HZ = Fraction(1_536_000)
MIN_SPACING_S = 1 / MAX_RATE_HZ
MAX_TIME_S = 3600
MAX_READ_S = 86_400
MAX_LOOP_TRAVERSALS = 1_000_000
MAX_EVENTS = 1_000_000
MAX_NODES = 128
MAX_STAGES = 3
MAX_LANES = 16
MAX_POINTS = 256
MAX_RESETS = 256
MAX_LEVELS = 64
MAX_FILTER_TAPS = 4096
MAX_REFERENCE_PASSES = 4
MAX_EVALUATION_HZ = 3_072_000
MAX_FRAMES = 16_777_216
MAX_SPEC_BYTES = 65_536
MAX_DENOMINATOR = 1_000_000_000
MAX_NUMERATOR = 9_999_999_999_999


class UnsupportedNyquismic(ContractError):
    """Validly named intent for which no accepted execution capability exists."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError('Nyquismic: ' + message)


def number(value, name, low, high):
    require(type(value) in (int, float) and low <= value <= high and math.isfinite(value),
            f'{name} must be a finite number in [{low}, {high}], not bool')
    return value


def integer(value, name, low, high):
    require(type(value) is int and low <= value <= high, f'{name} must be integer {low}..{high}')
    return value


def choice(value, name, options):
    require(type(value) is str and value in options, f'unsupported {name}: {value!r}')


def identifier(value, name='id'):
    require(type(value) is str and re.fullmatch(r'[a-z][a-z0-9_.-]{0,63}', value),
            f'{name} must be a stable lower-case identifier (1..64 characters)')
    return value


def hash_value(value, name):
    require(type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value), f'{name} must be SHA-256')
    return value


def rational_value(value, name, low=None, high=None):
    """Bounded p/q spelling; reduce fractions only in this new opt-in family."""
    require(type(value) is str and re.fullmatch(r'-?(?:0|[1-9][0-9]{0,12})/[1-9][0-9]{0,9}', value),
            f'{name} must be a bounded rational p/q with nonzero positive denominator')
    q = Fraction(value)
    require(abs(q.numerator) <= MAX_NUMERATOR and q.denominator <= MAX_DENOMINATOR,
            f'{name} rational exceeds bounds')
    require((low is None or q >= low) and (high is None or q <= high), f'{name} outside supported range')
    return q


def qtext(q: Fraction) -> str:
    return f'{q.numerator}/{q.denominator}'


def normalized(obj, field, low=None, high=None):
    q = rational_value(getattr(obj, field), field, low, high)
    object.__setattr__(obj, field, qtext(q))
    return q


def record(value, cls, name):
    require(type(value) is cls, name + ' requires ' + cls.__name__)


def records(values, cls, name, maximum):
    require(type(values) is tuple and len(values) <= maximum, f'{name} must be tuple with at most {maximum} entries')
    for value in values:
        record(value, cls, name)


class _Record:
    """Strict full-snapshot JSON decoding; defaults apply only to constructors."""
    _children: ClassVar[dict] = {}

    def to_dict(self) -> dict:
        def convert(v):
            if isinstance(v, (_Record, Contract)):
                return v.to_dict()
            if type(v) is tuple:
                return [convert(x) for x in v]
            return v
        return {f.name: convert(getattr(self, f.name)) for f in fields(self)}

    def to_json(self) -> str:
        data = self.to_dict()
        check_json(data)
        return json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))

    @classmethod
    def from_dict(cls, data):
        check_json(data)
        require(type(data) is dict and set(data) == {f.name for f in fields(cls)},
                cls.__name__ + ': missing/unknown fields (explicit migration required)')
        values = dict(data)
        for key, kind in cls._children.items():
            value = values[key]
            if isinstance(kind, tuple):
                require(type(value) is list, key + ' must be an array')
                values[key] = tuple(kind[0].from_dict(v) for v in value)
            elif value is not None:
                values[key] = Contract(value) if kind is Contract else kind.from_dict(value)
        return cls(**values)

    @classmethod
    def from_json(cls, text):
        return cls.from_dict(loads(text))

    def canonical_bytes(self) -> bytes:
        """Existing tagged exact-number canonical serialization, not RFC 8785."""
        return canonical_bytes(self.to_dict())

    @property
    def sha256(self) -> str:
        return digest(self.to_dict())


@dataclass(frozen=True)
class RateReference(_Record):
    hz: str = '48000/1'
    kind: str = 'stored_hz'
    control_id: str | None = None
    control_sha256: str | None = None

    def __post_init__(self):
        normalized(self, 'hz', MIN_RATE_HZ, MAX_RATE_HZ)
        choice(self.kind, 'reference kind', ('stored_hz', 'resolved_control'))
        if self.kind == 'resolved_control':
            identifier(self.control_id, 'resolved control id')
            hash_value(self.control_sha256, 'resolved control content/method identity')
        else:
            require(self.control_id is None and self.control_sha256 is None, 'stored Hz reference has no implicit control')


@dataclass(frozen=True)
class VirtualRate(_Record):
    value: str = '11730/1'
    unit: str = 'Hz'
    reference: RateReference | None = None
    _children = {'reference': RateReference}

    def __post_init__(self):
        q = normalized(self, 'value')
        require(q > 0, 'virtual rate/ratio must be positive')
        choice(self.unit, 'virtual rate unit', ('Hz', 'ratio'))
        if self.unit == 'ratio':
            record(self.reference, RateReference, 'ratio reference')
        else:
            require(self.reference is None, 'absolute Hz does not have a ratio reference')
        require(MIN_RATE_HZ <= self.hz <= MAX_RATE_HZ, 'resolved virtual rate outside supported Hz range')

    @property
    def hz(self) -> Fraction:
        return Fraction(self.value) * (Fraction(self.reference.hz) if self.reference else 1)


@dataclass(frozen=True)
class Point(_Record):
    time_s: str
    value: str

    def __post_init__(self):
        normalized(self, 'time_s', 0, MAX_TIME_S)
        normalized(self, 'value')


def validate_points(points, name, initial, low, high, origin=Fraction(0)):
    records(points, Point, name, MAX_POINTS)
    times = [Fraction(p.time_s) for p in points]
    require(all(a < b for a, b in zip([origin, *times], times)),
            name + ' times must be strictly increasing and after origin; base value owns origin')
    values = [initial, *(Fraction(p.value) for p in points)]
    require(all(low <= v <= high for v in values), name + ' complete value range outside bounds')
    return min(values), max(values)


@dataclass(frozen=True)
class Reset(_Record):
    time_s: str
    phase_cycles: str = '0/1'

    def __post_init__(self):
        normalized(self, 'time_s', 0, MAX_TIME_S)
        p = normalized(self, 'phase_cycles', 0, 1)
        require(p < 1, 'reset phase must be in [0,1)')


@dataclass(frozen=True)
class ModulationRoute(_Record):
    """Ordered normalized control: add Hz or multiply by 2**(depth*control).

    Control is a saved absolute-time curve, not a runtime feature lookup.
    Upstream/audio-derived controls require a later explicit version, not an
    unbound feature name. Evaluation is deliberately unavailable before #253.
    """
    id: str = 'route'
    mapping: str = 'add_hz'
    depth: float = 0.0
    initial: str = '0/1'
    points: tuple[Point, ...] = ()
    interpolation: str = 'step'
    _children = {'points': (Point,)}

    def __post_init__(self):
        identifier(self.id)
        choice(self.mapping, 'modulation mapping', ('add_hz', 'log2_ratio'))
        number(self.depth, 'modulation depth', -float(MAX_RATE_HZ) if self.mapping == 'add_hz' else -16,
               float(MAX_RATE_HZ) if self.mapping == 'add_hz' else 16)
        normalized(self, 'initial', -1, 1)
        choice(self.interpolation, 'control interpolation', ('step', 'linear'))
        validate_points(self.points, 'route points', Fraction(self.initial), -1, 1)


@dataclass(frozen=True)
class RateQuantizer(_Record):
    policy: str = 'none'
    levels_hz: tuple[str, ...] = ()
    tie: str = 'lower'
    switching: str = 'step'

    def __post_init__(self):
        choice(self.policy, 'rate quantizer', ('none', 'nearest_hz'))
        choice(self.tie, 'rate quantizer tie', ('lower',))
        choice(self.switching, 'rate quantizer switching', ('step',))
        require(type(self.levels_hz) is tuple and len(self.levels_hz) <= MAX_LEVELS, 'rate ladder bound')
        qs = [rational_value(q, 'ladder Hz', MIN_RATE_HZ, MAX_RATE_HZ) for q in self.levels_hz]
        require(all(a < b for a, b in zip(qs, qs[1:])), 'rate ladder must be strictly increasing')
        require(bool(qs) == (self.policy == 'nearest_hz'), 'rate ladder presence disagrees with policy')
        object.__setattr__(self, 'levels_hz', tuple(map(qtext, qs)))

    @classmethod
    def from_dict(cls, data):
        check_json(data)
        require(type(data) is dict and set(data) == {'policy', 'levels_hz', 'tie', 'switching'}, 'quantizer fields')
        require(type(data['levels_hz']) is list, 'levels_hz must be an array')
        return cls(**{**data, 'levels_hz': tuple(data['levels_hz'])})


@dataclass(frozen=True)
class JitterSpec(_Record):
    model: str = 'none'
    amount: float = 0.0
    cell_s: str = '1/1000'
    seed: str = '0'
    stream: str = 'clock'

    def __post_init__(self):
        choice(self.model, 'jitter model', ('none', 'uniform_frequency_cells_v1'))
        number(self.amount, 'fractional-frequency jitter amount', 0, 0.25)
        normalized(self, 'cell_s', MIN_SPACING_S, MAX_TIME_S)
        seed_value(self.seed)
        identifier(self.stream, 'jitter stream')
        require(self.model != 'none' or self.amount == 0, 'none jitter requires zero amount')


@dataclass(frozen=True)
class ClockSpec(_Record):
    rate: VirtualRate = VirtualRate()
    origin_s: str = '0/1'
    phase_cycles: str = '0/1'
    points_hz: tuple[Point, ...] = ()
    interpolation: str = 'step'
    resets: tuple[Reset, ...] = ()
    routes: tuple[ModulationRoute, ...] = ()
    quantizer: RateQuantizer = RateQuantizer()
    jitter: JitterSpec = JitterSpec()
    invalid_policy: str = 'reject'
    order: str = 'base-automation-routes-quantizer-jitter'
    _children = {'rate': VirtualRate, 'points_hz': (Point,), 'resets': (Reset,),
                 'routes': (ModulationRoute,), 'quantizer': RateQuantizer, 'jitter': JitterSpec}

    def __post_init__(self):
        record(self.rate, VirtualRate, 'rate')
        origin = normalized(self, 'origin_s', 0, MAX_TIME_S)
        phase = normalized(self, 'phase_cycles', 0, 1)
        require(phase < 1, 'initial phase must be in [0,1)')
        choice(self.interpolation, 'Hz automation interpolation', ('step', 'linear'))
        validate_points(self.points_hz, 'Hz automation', self.rate.hz, MIN_RATE_HZ, MAX_RATE_HZ, origin)
        records(self.resets, Reset, 'resets', MAX_RESETS)
        reset_times = [Fraction(r.time_s) for r in self.resets]
        require(all(a < b for a, b in zip([origin, *reset_times], reset_times)), 'resets must be strictly ordered after origin')
        records(self.routes, ModulationRoute, 'routes', MAX_LANES)
        require(len({r.id for r in self.routes}) == len(self.routes), 'duplicate modulation route id')
        for r in self.routes:
            require(all(Fraction(p.time_s) > origin for p in r.points), 'route points before clock origin')
        record(self.quantizer, RateQuantizer, 'quantizer')
        record(self.jitter, JitterSpec, 'jitter')
        choice(self.invalid_policy, 'invalid-value policy', ('reject',))
        choice(self.order, 'clock operation order', ('base-automation-routes-quantizer-jitter',))
        self.rate_bounds()

    def rate_bounds(self) -> tuple[Fraction, Fraction]:
        """Conservative complete-range admission, including every ordered route.

        Control correlations are not used to excuse out-of-range intermediate
        values. Log2 depth uses the conservative integer-octave envelope to
        avoid optimistic platform-dependent exp2 rounding near hard bounds.
        """
        lo, hi = validate_points(self.points_hz, 'Hz automation', self.rate.hz,
                                 MIN_RATE_HZ, MAX_RATE_HZ, Fraction(self.origin_s))
        for route in self.routes:
            rlo, rhi = validate_points(route.points, 'route', Fraction(route.initial), -1, 1,
                                      Fraction(self.origin_s))
            a, b = sorted((Fraction(route.depth) * rlo, Fraction(route.depth) * rhi))
            if route.mapping == 'add_hz':
                lo, hi = lo + a, hi + b
            else:
                lo *= Fraction(2) ** math.floor(a)
                hi *= Fraction(2) ** math.ceil(b)
            require(MIN_RATE_HZ <= lo <= hi <= MAX_RATE_HZ, 'complete modulated rate range is invalid')
        if self.quantizer.policy != 'none':
            lo, hi = Fraction(self.quantizer.levels_hz[0]), Fraction(self.quantizer.levels_hz[-1])
        lo *= 1 - Fraction(self.jitter.amount)
        hi *= 1 + Fraction(self.jitter.amount)
        require(MIN_RATE_HZ <= lo <= hi <= MAX_RATE_HZ, 'jitter violates full rate/minimum-spacing bounds')
        return lo, hi

    def require_geometry(self) -> None:
        if self.routes or self.quantizer.policy != 'none' or self.jitter.model != 'none':
            raise UnsupportedNyquismic('Nyquismic routed/quantized/jitter clock geometry requires NYQ-004/#253; no approximation/fallback')


@dataclass(frozen=True)
class PlaybackMap(_Record):
    source_origin_s: str = '0/1'
    speed: str = '1/1'
    speed_points: tuple[Point, ...] = ()
    interpolation: str = 'step'
    source_extent_s: str = '1/1'
    boundary: str = 'zero_pad'
    loop_start_s: str = '0/1'
    loop_end_s: str = '1/1'
    loop_crossfade_s: str = '0/1'
    _children = {'speed_points': (Point,)}

    def __post_init__(self):
        normalized(self, 'source_origin_s', 0, MAX_READ_S)
        speed = normalized(self, 'speed', Fraction(1, 64), 64)
        choice(self.interpolation, 'speed interpolation', ('step', 'linear'))
        validate_points(self.speed_points, 'speed points', speed, Fraction(1, 64), 64)
        extent = normalized(self, 'source_extent_s', 0, MAX_READ_S)
        require(extent > 0, 'playback source extent must be positive')
        choice(self.boundary, 'source boundary', ('zero_pad', 'edge_hold', 'loop'))
        start = normalized(self, 'loop_start_s', 0, MAX_READ_S)
        end = normalized(self, 'loop_end_s', 0, MAX_READ_S)
        crossfade = normalized(self, 'loop_crossfade_s', 0, 0)
        require(crossfade == 0, 'loop crossfade requires a future tested contract')
        if self.boundary == 'loop':
            require(0 <= start < end <= extent, 'invalid loop extent')
            require(end - start >= MIN_SPACING_S, 'loop extent below minimum spacing')
            require(start <= Fraction(self.source_origin_s) < end, 'loop source origin must be inside its half-open loop; no implicit intro')
        else:
            require(start == 0 and end == 1, 'inactive loop fields must retain canonical defaults')


@dataclass(frozen=True)
class SonicSpec(_Record):
    version: str = VERSION
    instance_id: str = 'nyquismic'
    label: str = ''
    mode: str = 'sampler'
    clock: ClockSpec | None = ClockSpec()
    playback: PlaybackMap | None = None
    stages: tuple[SonicSpec, ...] = ()
    capture: str = 'linear_v1'
    prefilter: str = 'off_v1'
    reconstruction: str = 'hold_v1'
    channels: int = 1
    stereo_link: str = 'linked'
    clock_group: str | None = None
    wet: float = 1.0
    bypass: bool = False
    bus: str = 'SYNTHLINE'
    band: str | None = None
    placement: str = 'post_source_pre_master'
    confine_delta: bool = True
    input_boundary: str = 'zero_pad'
    initial_capture: str = 'crossing_only_zero_until_first'
    tail: str = 'crop_to_output_extent'
    reset_history: str = 'retain_capture'

    def __post_init__(self):
        choice(self.version, 'sonic version', (VERSION,))
        identifier(self.instance_id, 'instance id')
        require(type(self.label) is str and len(self.label) <= 256, 'display label bound')
        choice(self.mode, 'mode', ('sampler', 'playback_warp', 'cascade'))
        records(self.stages, SonicSpec, 'cascade stages', MAX_STAGES)
        if self.mode == 'cascade':
            require(self.clock is None and self.playback is None, 'cascade owns child clocks, not an implicit global clock')
            require(self.capture == 'linear_v1' and self.prefilter == 'off_v1' and self.reconstruction == 'hold_v1'
                    and self.stereo_link == 'linked' and self.clock_group is None and self.input_boundary == 'zero_pad',
                    'inactive cascade clock/kernel fields must retain canonical defaults')
            require(all(s.mode != 'cascade' for s in self.stages), 'nested cascade unsupported')
            require(len({self.instance_id, *(s.instance_id for s in self.stages)}) == len(self.stages) + 1,
                    'cascade instance IDs must be unique and stable')
            require(all(s.channels == self.channels for s in self.stages), 'cascade channel mismatch')
            require(all(s.bus == self.bus and s.band == self.band and s.placement == self.placement and
                        s.confine_delta == self.confine_delta for s in self.stages), 'cascade children cannot secretly reroute audio')
            groups = {}
            for stage in self.stages:
                if stage.clock_group is not None:
                    settings = (stage.clock.sha256, stage.stereo_link, stage.channels)
                    previous = groups.setdefault(stage.clock_group, settings)
                    require(previous == settings, 'linked clock group has inconsistent clock/channel settings')
        else:
            record(self.clock, ClockSpec, 'clock')
            require(not self.stages, 'non-cascade cannot contain stages')
            if self.mode == 'playback_warp':
                record(self.playback, PlaybackMap, 'playback map')
                require(all(Fraction(p.time_s) > Fraction(self.clock.origin_s) for p in self.playback.speed_points),
                        'speed points must follow clock origin')
            else:
                require(self.playback is None, 'sampler does not contain an implicit playback warp')
        choice(self.capture, 'capture interpolation', ('linear_v1', 'nearest_left_tie_v1'))
        choice(self.prefilter, 'prefilter', ('off_v1',))
        choice(self.reconstruction, 'reconstruction', ('hold_v1', 'linear_time_v1'))
        integer(self.channels, 'channels', 1, 2)
        choice(self.stereo_link, 'stereo clock linking', ('linked', 'independent'))
        if self.clock_group is not None:
            identifier(self.clock_group, 'clock link group')
        number(self.wet, 'wet ratio', 0, 1)
        require(type(self.bypass) is bool and type(self.confine_delta) is bool, 'bypass/confinement must be bool')
        choice(self.bus, 'bus', ('SYNTHLINE',))
        if self.band is not None:
            choice(self.band, 'spectral band (not stem)', ('sub', 'lowmid', 'highmid', 'air'))
        choice(self.placement, 'placement', ('post_source_pre_master',))
        choice(self.input_boundary, 'sampler input boundary', ('zero_pad', 'edge_hold'))
        choice(self.initial_capture, 'initial capture', ('crossing_only_zero_until_first',))
        choice(self.tail, 'tail policy', ('crop_to_output_extent',))
        choice(self.reset_history, 'reset history', ('retain_capture',))
        require(len(self.to_json().encode('utf-8')) <= MAX_SPEC_BYTES, 'sonic snapshot byte budget exceeded')

    @property
    def sonic_sha256(self) -> str:
        def without_labels(d):
            return {k: ([without_labels(x) for x in v] if k == 'stages' else v)
                    for k, v in d.items() if k != 'label'}
        return digest({'domain': 'zaaggenz.nyquismic.sonic.v1', 'spec': without_labels(self.to_dict())})

    @property
    def is_boundary_identity(self) -> bool:
        # A declaration, not permission to invoke an unsupported audio executor.
        return self.bypass or self.wet == 0 or (self.mode == 'cascade' and
               all(s.is_boundary_identity for s in self.stages))

    def require_audio_execution(self) -> None:
        raise UnsupportedNyquismic(f'Nyquismic {self.mode} audio kernel is unavailable in NYQ-001; '
                                   'requires accepted NYQ-002..006. No placeholder renderer.')


SonicSpec._children = {'clock': ClockSpec, 'playback': PlaybackMap, 'stages': (SonicSpec,)}


@dataclass(frozen=True)
class ResourceBudget(_Record):
    max_events: int = MAX_EVENTS
    max_frames: int = MAX_FRAMES
    max_nodes: int = MAX_NODES
    max_read_s: int = MAX_READ_S
    max_filter_taps: int = MAX_FILTER_TAPS
    max_reference_passes: int = MAX_REFERENCE_PASSES

    def __post_init__(self):
        for name, maximum in (('max_events', MAX_EVENTS), ('max_frames', MAX_FRAMES),
                              ('max_nodes', MAX_NODES), ('max_read_s', MAX_READ_S),
                              ('max_filter_taps', MAX_FILTER_TAPS), ('max_reference_passes', MAX_REFERENCE_PASSES)):
            integer(getattr(self, name), name, 1, maximum)


@dataclass(frozen=True)
class EvaluationPolicy(_Record):
    """Numerical identity/admission only; not a claim that an audio method ran."""
    version: str = VERSION
    evaluation_rate_hz: int = 192000
    clock_method: str = 'exact_rational_piecewise_affine_decimal80_v1'
    audio_method: str = 'unavailable_nyq001'
    numerical_filter: str = 'unavailable_nyq001'
    reference_rates_hz: tuple[int, ...] = ()
    budget: ResourceBudget = ResourceBudget()
    _children = {'budget': ResourceBudget}

    def __post_init__(self):
        choice(self.version, 'evaluation version', (VERSION,))
        integer(self.evaluation_rate_hz, 'evaluation rate Hz', 8000, MAX_EVALUATION_HZ)
        choice(self.clock_method, 'clock method', ('exact_rational_piecewise_affine_decimal80_v1',))
        choice(self.audio_method, 'audio method', ('unavailable_nyq001',))
        choice(self.numerical_filter, 'numerical filter', ('unavailable_nyq001',))
        record(self.budget, ResourceBudget, 'resource budget')
        require(type(self.reference_rates_hz) is tuple and len(self.reference_rates_hz) <= self.budget.max_reference_passes,
                'reference-pass budget exceeded')
        for rate in self.reference_rates_hz:
            integer(rate, 'reference rate Hz', 8000, MAX_EVALUATION_HZ)
        require(all(a < b for a, b in zip((self.evaluation_rate_hz, *self.reference_rates_hz), self.reference_rates_hz)),
                'reference rates must strictly increase after the evaluation rate')

    @classmethod
    def from_dict(cls, data):
        check_json(data)
        require(type(data) is dict and set(data) == {f.name for f in fields(cls)}, 'evaluation fields')
        require(type(data['reference_rates_hz']) is list, 'reference rates must be an array')
        return cls(**{**data, 'reference_rates_hz': tuple(data['reference_rates_hz']),
                      'budget': ResourceBudget.from_dict(data['budget'])})


@dataclass(frozen=True)
class RenderIdentity(_Record):
    """Context-bound planned render/cache key, NOT a completed artifact record."""
    sonic_sha256: str
    input_asset: Contract
    source_revision_sha256: str
    rack_revision_sha256: str
    graph_revision_sha256: str
    context_sha256: str
    evaluation: EvaluationPolicy = EvaluationPolicy()
    delivery_rate_hz: int = 48000
    channels: int = 1
    start_s: str = '0/1'
    end_s: str = '1/1'
    version: str = VERSION
    _children = {'evaluation': EvaluationPolicy, 'input_asset': Contract}

    def __post_init__(self):
        choice(self.version, 'render identity version', (VERSION,))
        for name in ('sonic_sha256', 'source_revision_sha256',
                     'rack_revision_sha256', 'graph_revision_sha256', 'context_sha256'):
            hash_value(getattr(self, name), name)
        record(self.input_asset, Contract, 'immutable input asset')
        asset = self.input_asset.to_dict()
        require(asset['kind'] == 'AudioAssetRef', 'input must be an existing AudioAssetRef contract')
        # Canonical key order for our own defensive snapshot only. The original
        # immutable Contract and its historical canonical identity are unchanged.
        object.__setattr__(self, 'input_asset', Contract.from_json(json.dumps(asset, sort_keys=True, separators=(',', ':'))))
        require(asset['channels'] == self.channels, 'input/render channel shape mismatch')
        require(Fraction(asset['frame_count'], asset['sample_rate_hz']) <= MAX_READ_S, 'input source extent exceeds hard read bound')
        record(self.evaluation, EvaluationPolicy, 'evaluation')
        integer(self.delivery_rate_hz, 'delivery rate Hz (identity domain, not export availability)', 8000, 192000)
        integer(self.channels, 'render channels', 1, 2)
        start = normalized(self, 'start_s', 0, MAX_TIME_S)
        end = normalized(self, 'end_s', 0, MAX_TIME_S)
        require(start <= end, 'reversed render interval')
        require(math.ceil((end - start) * max((self.evaluation.evaluation_rate_hz,
                *self.evaluation.reference_rates_hz, self.delivery_rate_hz))) * self.channels <= self.evaluation.budget.max_frames,
                'evaluation frame/channel admission budget exceeded')

    @property
    def render_sha256(self) -> str:
        return digest({'domain': 'zaaggenz.nyquismic.render.v1', 'request': self.to_dict()})


@dataclass(frozen=True)
class RackBoundary(_Record):
    """Typed handoff for #256, never a MultibandRack 1.0 insert or migration."""
    spec: SonicSpec
    source_revision_sha256: str
    rack_sonic_sha256: str
    anchor_instance_id: str
    side: str = 'after'
    _children = {'spec': SonicSpec}

    def __post_init__(self):
        record(self.spec, SonicSpec, 'spec')
        hash_value(self.source_revision_sha256, 'source revision')
        hash_value(self.rack_sonic_sha256, 'accepted rack sonic identity')
        identifier(self.anchor_instance_id, 'accepted anchor instance')
        choice(self.side, 'anchor side', ('before', 'after'))

    def require_execution(self) -> None:
        raise UnsupportedNyquismic('Nyquismic rack adaptation requires NYQ-007/#256 and an explicitly accepted rack version')


def event_seed(spec: SonicSpec, *, epoch: int, crossing: int, channel: int = 0) -> str:
    """SHA-256 first 64 bits BE, absolute event identity; no mutable PRNG cursor.

    Linked clocks use the group identity instead of instance ID. Independent
    stereo uses a channel coordinate; linked stereo always uses zero. A duplicate
    must receive a fresh instance ID unless explicitly sharing a clock group.
    """
    record(spec, SonicSpec, 'spec')
    require(spec.clock is not None, 'cascade seed belongs to a child stage')
    integer(epoch, 'epoch', 0, MAX_RESETS)
    integer(crossing, 'crossing', 0, int(MAX_RATE_HZ) * MAX_TIME_S + 1)
    integer(channel, 'channel', 0, spec.channels - 1)
    material = {'domain': 'zaaggenz.nyquismic.event-seed.v1', 'root': spec.clock.jitter.seed,
                'stream': spec.clock.jitter.stream, 'instance': spec.clock_group or spec.instance_id,
                'epoch': epoch, 'crossing': crossing,
                'channel': channel if spec.stereo_link == 'independent' else 0}
    return str(int.from_bytes(bytes.fromhex(digest(material))[:8], 'big'))


def clock_cell_value(spec: SonicSpec, *, cell_index: int, channel: int = 0) -> Fraction:
    """Exact counter-addressed cell value in (-1,1); this is not jitter DSP.

    Uniform cell centres: (2*word + 1 - 2**64)/2**64, SHA256 first u64 BE.
    Physical cell index is floor((t-origin)/cell_s); phase resets do not rewind it.
    """
    record(spec, SonicSpec, 'spec')
    require(spec.clock is not None, 'cascade cell identity belongs to a child')
    integer(cell_index, 'physical cell index', 0, int(MAX_RATE_HZ) * MAX_TIME_S)
    integer(channel, 'channel', 0, spec.channels - 1)
    material = {'domain': 'zaaggenz.nyquismic.clock-cell.v1', 'root': spec.clock.jitter.seed,
                'stream': spec.clock.jitter.stream, 'instance': spec.clock_group or spec.instance_id,
                'cell': cell_index, 'channel': channel if spec.stereo_link == 'independent' else 0}
    word = int.from_bytes(bytes.fromhex(digest(material))[:8], 'big')
    return Fraction(2 * word + 1 - 2**64, 2**64)


def bind_render_identity(spec: SonicSpec, evaluation: EvaluationPolicy, *, input_asset: Contract,
                         source_revision_sha256: str, rack_revision_sha256: str,
                         graph_revision_sha256: str, context_sha256: str,
                         delivery_rate_hz: int, start_s: str, end_s: str) -> RenderIdentity:
    """Bind validated sonic intent to a planned numerical/context identity."""
    record(spec, SonicSpec, 'sonic spec')
    record(evaluation, EvaluationPolicy, 'evaluation policy')
    record(input_asset, Contract, 'immutable input asset')
    asset = input_asset.to_dict()
    require(asset['kind'] == 'AudioAssetRef', 'input must be an existing AudioAssetRef contract')
    extent = Fraction(asset['frame_count'], asset['sample_rate_hz'])
    stages = spec.stages[:1] if spec.mode == 'cascade' else (spec,)
    for stage in stages:
        if stage.playback is not None:
            require(Fraction(stage.playback.source_extent_s) == extent, 'first playback extent must match bound immutable input asset')
    return RenderIdentity(spec.sonic_sha256, input_asset, source_revision_sha256,
                          rack_revision_sha256, graph_revision_sha256, context_sha256,
                          evaluation, delivery_rate_hz, spec.channels, start_s, end_s)
