"""NYQ-004 v1 immutable controlled-clock packet (producer ONLY).

This module does not make a caller-supplied graph digest authoritative: the
Compose/session integration owner must independently bind the live revision.
No SamplerPlan, registry, render, or persisted audio checkpoint is installed.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import re

from .model import digest
from .nyquismic import (
    MAX_EVENTS, MAX_RESETS, MAX_TIME_S, MAX_RATE_HZ, MIN_SPACING_S,
    ModulationRoute, ResourceBudget, SonicSpec, UnsupportedNyquismic,
    _Record, hash_value, identifier, integer, normalized, qtext,
    rational_value, record, records, require,
)
from .nyquismic_clock import ClockCancelled
from .nyquismic_controls import compile_step_clock_events
from .nyquismic_input_envelope import UpstreamGraphSnapshot

METHOD = 'nyq.controlled-sampler-clock-packet.v1'
RECEIPT_VERSION = 'nyq.control-route-receipt.v1'
EVENT_VERSION = 'nyq.controlled-event.v1'
CHANNEL_VERSION = 'nyq.controlled-channel.v1'
LEDGER_METHOD = 'nyq.controlled-physical-event-ledger.v1'
MAX_EVENT_BITS = 32768


def event_fraction(value: str) -> Fraction:
    """Strict decoder for bounded physical-event fractions including big roots.

    Saved controls use intentionally small decimal p/q caps. Exact rational
    jitter crossings can exceed those caps. The h:NUM/DEN hex encoding stays
    canonical and bit-bounded, never a binary64 approximation.
    """
    require(type(value) is str, 'controlled event fraction must be text')
    if value.startswith('h:'):
        match = re.fullmatch(r'h:(0|[1-9a-f][0-9a-f]*)/([1-9a-f][0-9a-f]*)', value)
        require(match is not None and len(match.group(1)) <= MAX_EVENT_BITS // 4
                and len(match.group(2)) <= MAX_EVENT_BITS // 4,
                'controlled event hex fraction encoding/budget')
        n, d = int(match.group(1), 16), int(match.group(2), 16)
        require(n.bit_length() <= MAX_EVENT_BITS and d.bit_length() <= MAX_EVENT_BITS,
                'controlled event hex fraction bit budget')
        fraction = Fraction(n, d)
        require(fraction.numerator == n and fraction.denominator == d,
                'controlled event hex fraction must be reduced')
        return fraction
    return rational_value(value, 'controlled event decimal fraction', 0, MAX_TIME_S)


def event_text(value: Fraction) -> str:
    require(type(value) is Fraction and 0 <= value <= MAX_TIME_S,
            'controlled event fraction range')
    if (value.numerator <= 9_999_999_999_999 and
            value.denominator <= 999_999_999):
        return qtext(value)
    require(value.numerator.bit_length() <= MAX_EVENT_BITS and
            value.denominator.bit_length() <= MAX_EVENT_BITS,
            'controlled event fraction bit budget')
    return f'h:{value.numerator:x}/{value.denominator:x}'



@dataclass(frozen=True)
class AuthenticatedRouteReceiptV1(_Record):
    """Saved route/source receipt; not an independent live-source attestation.

    The exact compiled route hash is checked. For an upstream feature, the
    immutable claimed graph snapshot is checked for acyclic ancestry, but
    immutable PCM bytes and the live graph must STILL be authenticated by
    their owning integration lane. A claimed SHA alone cannot prove either.
    """
    route_id: str
    route_sha256: str
    source_sha256: str
    source_method: str
    source_kind: str = 'authored'
    feature_sha256: str | None = None
    feature_method_sha256: str | None = None
    input_pcm_sha256: str | None = None
    upstream_source_id: str | None = None
    graph_snapshot: UpstreamGraphSnapshot | None = None
    support_start_s: str | None = None
    support_end_s: str | None = None
    lookahead_s: str | None = None
    version: str = RECEIPT_VERSION
    _children = {'graph_snapshot': UpstreamGraphSnapshot}

    def __post_init__(self):
        require(self.version == RECEIPT_VERSION, 'controlled route receipt version')
        identifier(self.route_id, 'controlled route ID')
        hash_value(self.route_sha256, 'compiled control route SHA')
        hash_value(self.source_sha256, 'immutable control source SHA')
        identifier(self.source_method, 'control source method')
        require(self.source_kind in ('authored', 'upstream_feature'),
                'unsupported controlled route source kind')
        optional = (self.feature_sha256, self.feature_method_sha256,
                    self.input_pcm_sha256, self.upstream_source_id,
                    self.graph_snapshot, self.support_start_s,
                    self.support_end_s, self.lookahead_s)
        if self.source_kind == 'authored':
            require(all(x is None for x in optional),
                    'authored route must not masquerade as an upstream feature')
        else:
            hash_value(self.feature_sha256, 'upstream feature content hash')
            hash_value(self.feature_method_sha256, 'upstream feature method hash')
            hash_value(self.input_pcm_sha256, 'upstream immutable PCM hash')
            identifier(self.upstream_source_id, 'upstream graph node')
            record(self.graph_snapshot, UpstreamGraphSnapshot, 'feature graph snapshot')
            start = normalized(self, 'support_start_s', 0, MAX_TIME_S)
            end = normalized(self, 'support_end_s', start, MAX_TIME_S)
            normalized(self, 'lookahead_s', 0, MAX_TIME_S)


@dataclass(frozen=True)
class ControlledClockEventV1(_Record):
    index: int
    epoch: int
    crossing: int
    coordinate_s: str
    coordinate_error_bound_s: str
    version: str = EVENT_VERSION

    def __post_init__(self):
        require(self.version == EVENT_VERSION, 'controlled event version')
        integer(self.index, 'controlled event index', 0, MAX_EVENTS)
        integer(self.epoch, 'controlled event epoch', 0, MAX_RESETS)
        integer(self.crossing, 'controlled event crossing', 0,
                int(MAX_RATE_HZ) * MAX_TIME_S + 1)
        stamp = event_fraction(self.coordinate_s)
        error = event_fraction(self.coordinate_error_bound_s)
        require(stamp <= MAX_TIME_S and error <= Fraction(1, 10**18),
                'controlled event timestamp/uncertainty bounds')
        require(event_text(stamp) == self.coordinate_s and
                event_text(error) == self.coordinate_error_bound_s,
                'controlled event fraction must be canonical')


@dataclass(frozen=True)
class ControlledChannelClockV1(_Record):
    channel: int
    seed_identity_sha256: str
    events: tuple[ControlledClockEventV1, ...]
    version: str = CHANNEL_VERSION
    _children = {'events': (ControlledClockEventV1,)}

    def __post_init__(self):
        require(self.version == CHANNEL_VERSION, 'controlled channel version')
        integer(self.channel, 'controlled channel index', 0, 1)
        hash_value(self.seed_identity_sha256, 'controlled channel seed identity')
        records(self.events, ControlledClockEventV1, 'controlled channel events', MAX_EVENTS)


def _ledger_sha256(channels: tuple[ControlledChannelClockV1, ...]) -> str:
    """Physical events only: never include numerical evaluation-frame count."""
    return digest({
        'domain': LEDGER_METHOD,
        'channels': [{
            'channel': c.channel,
            'events': [e.to_dict() for e in c.events],
        } for c in channels],
    })

def _seed_receipt_sha256(sonic: SonicSpec, channel: int) -> str:
    """Re-derive a packet *context* receipt, not a per-cell jitter draw seed.

    This identity intentionally includes the complete clock SHA and an
    ungrouped band. The accepted clock_cell_value counter namespace instead
    uses root/stream/instance-or-group/cell/channel; it is not changed here.
    """
    record(sonic, SonicSpec, 'controlled seed receipt sonic')
    require(sonic.clock is not None, 'controlled seed receipt requires clock')
    integer(channel, 'controlled seed receipt channel', 0, sonic.channels - 1)
    clock = sonic.clock
    seed_channel = channel if sonic.stereo_link == 'independent' else 0
    return digest({
        'domain': 'nyq.controlled-clock-seed-namespace.v1',
        'root': clock.jitter.seed, 'stream': clock.jitter.stream,
        'clock': clock.sha256,
        'scope': sonic.clock_group or sonic.instance_id,
        'band': None if sonic.clock_group is not None else sonic.band,
        'channel': seed_channel,
    })


@dataclass(frozen=True)
class ControlledSamplerClockV1(_Record):
    method: str
    full_end_s: str
    sonic_sha256: str
    clock_sha256: str
    input_asset_sha256: str
    source_revision_sha256: str
    graph_revision_sha256: str
    claimed_live_graph_sha256: str
    instance_id: str
    band: str | None
    clock_group: str | None
    stereo_link: str
    channels_count: int
    jitter_sha256: str
    route_receipts: tuple[AuthenticatedRouteReceiptV1, ...]
    channels: tuple[ControlledChannelClockV1, ...]
    event_ledger_sha256: str
    budget_max_events: int
    # These deliberately cannot be set to True by this component producer.
    live_graph_authorized: bool = False
    upstream_pcm_authorized: bool = False
    sampler_checkpoint_qualified: bool = False
    version: str = METHOD
    _children = {
        'route_receipts': (AuthenticatedRouteReceiptV1,),
        'channels': (ControlledChannelClockV1,),
    }

    def __post_init__(self):
        require(self.method == METHOD and self.version == METHOD,
                'unsupported controlled sampler packet method/version')
        end = normalized(self, 'full_end_s', 0, MAX_TIME_S)
        for name in ('sonic_sha256', 'clock_sha256', 'input_asset_sha256',
                     'source_revision_sha256', 'graph_revision_sha256',
                     'claimed_live_graph_sha256', 'jitter_sha256',
                     'event_ledger_sha256'):
            hash_value(getattr(self, name), name)
        identifier(self.instance_id, 'controlled packet instance')
        if self.band is not None:
            require(self.band in ('sub', 'lowmid', 'highmid', 'air'),
                    'controlled packet band')
        if self.clock_group is not None:
            identifier(self.clock_group, 'controlled packet clock group')
        require(self.stereo_link in ('linked', 'independent'),
                'controlled packet stereo link')
        integer(self.channels_count, 'controlled channel count', 1, 2)
        integer(self.budget_max_events, 'packet admitted event budget', 1, MAX_EVENTS)
        require(type(self.live_graph_authorized) is bool and
                type(self.upstream_pcm_authorized) is bool and
                type(self.sampler_checkpoint_qualified) is bool and
                not (self.live_graph_authorized or self.upstream_pcm_authorized or
                     self.sampler_checkpoint_qualified),
                'packet producer cannot certify live graph, upstream PCM or audio checkpoint')
        records(self.route_receipts, AuthenticatedRouteReceiptV1,
                'packet route receipts', 16)
        records(self.channels, ControlledChannelClockV1,
                'packet channel ledgers', 2)
        require(tuple(c.channel for c in self.channels) ==
                tuple(range(self.channels_count)),
                'packet channels missing/duplicate/out of order')
        require(self.graph_revision_sha256 == self.claimed_live_graph_sha256,
                'caller graph revision claims disagree')
        require(_ledger_sha256(self.channels) == self.event_ledger_sha256,
                'controlled packet event ledger digest mismatch')
        total = 0
        for channel in self.channels:
            previous = None
            previous_epoch = 0
            previous_crossing = -1
            for i, event in enumerate(channel.events):
                require(event.index == i, 'controlled event index gap/reordering')
                t = event_fraction(event.coordinate_s)
                error = event_fraction(event.coordinate_error_bound_s)
                require(t >= error and t + error < end,
                        'controlled event uncertainty escapes half-open extent')
                if previous is not None:
                    require(t - error - previous[1] - previous[2] >= MIN_SPACING_S,
                            'controlled event order/spacing uncertifiable')
                    require(event.epoch >= previous_epoch and
                            (event.epoch != previous_epoch or
                             event.crossing > previous_crossing),
                            'controlled event epoch/crossing not ordered')
                previous = (t, t, error)
                previous_epoch, previous_crossing = event.epoch, event.crossing
            total += len(channel.events)
            require(total <= self.budget_max_events,
                    'packet exceeds combined-channel event admission budget')
        if self.stereo_link == 'linked' and self.channels_count == 2:
            require(self.channels[0].seed_identity_sha256 ==
                    self.channels[1].seed_identity_sha256 and
                    self.channels[0].events == self.channels[1].events,
                    'linked channels must share one clock and seed identity')
        if self.stereo_link == 'independent' and self.channels_count == 2:
            require(self.channels[0].seed_identity_sha256 !=
                    self.channels[1].seed_identity_sha256,
                    'independent channels require distinct seed namespaces')

    def require_claims(self, sonic: SonicSpec, *, full_end_s: str,
                       input_asset_sha256: str, source_revision_sha256: str,
                       graph_revision_sha256: str) -> None:
        """Consumer preflight of claims, NOT authentication of live revisions."""
        record(sonic, SonicSpec, 'controlled consumer sonic')
        require(self.sonic_sha256 == sonic.sonic_sha256 and
                self.clock_sha256 == sonic.clock.sha256 and
                self.instance_id == sonic.instance_id and
                self.band == sonic.band and self.clock_group == sonic.clock_group and
                self.stereo_link == sonic.stereo_link and
                self.channels_count == sonic.channels and
                self.jitter_sha256 == sonic.clock.jitter.sha256,
                'controlled packet foreign/stale sonic or clock')
        require(self.full_end_s == qtext(rational_value(
                full_end_s, 'consumer full extent', 0, MAX_TIME_S)),
                'controlled packet different physical extent')
        require(self.input_asset_sha256 == input_asset_sha256 and
                self.source_revision_sha256 == source_revision_sha256 and
                self.graph_revision_sha256 == graph_revision_sha256,
                'controlled packet stale source/graph revision')
        require(tuple((r.route_id, r.route_sha256) for r in self.route_receipts) ==
                tuple((r.id, r.sha256) for r in sonic.clock.routes),
                'controlled packet route mismatch')
        # A self-consistent rehashed packet can still forge a seed receipt
        # even when its physical events are correct. Re-derive each context
        # identity from the separately frozen SonicSpec before accepting it.
        # This is not authentication of actual live PCM or graph state.
        for channel in self.channels:
            require(channel.seed_identity_sha256 ==
                    _seed_receipt_sha256(sonic, channel.channel),
                    'controlled packet seed receipt differs from source clock')
            expected = compile_step_clock_events(
                sonic, self.full_end_s, channel=channel.channel,
                budget=ResourceBudget(max_events=self.budget_max_events))
            require(tuple((
                e.index, e.epoch, e.crossing, event_text(e.coordinate_s),
                event_text(e.coordinate_error_bound_s),
            ) for e in expected) == tuple((
                e.index, e.epoch, e.crossing, e.coordinate_s,
                e.coordinate_error_bound_s,
            ) for e in channel.events),
                'controlled packet event membership/uncertainty differs from source clock')


def compile_controlled_sampler_clock_v1(
    sonic: SonicSpec, *, full_end_s: str,
    input_asset_sha256: str, source_revision_sha256: str,
    graph_revision_sha256: str, expected_live_graph_sha256: str,
    upstream_route_receipts: tuple[AuthenticatedRouteReceiptV1, ...],
    budget: ResourceBudget, cancelled=None,
) -> ControlledSamplerClockV1:
    """Compile the frozen physical event packet without numerical-grid sampling.

    The expected-live-graph argument is a caller claim until Integration checks
    it against a real immutable project/session revision. The input SHA is
    likewise a caller receipt; #266 must compare it to the actual FrozenInput.
    """
    record(sonic, SonicSpec, 'controlled packet sonic')
    record(budget, ResourceBudget, 'controlled packet resource budget')
    require(cancelled is None or callable(cancelled),
            'controlled packet cancellation must be callable')
    if cancelled is not None and cancelled():
        raise ClockCancelled('controlled packet cancelled before admission')
    require(sonic.mode == 'sampler' and sonic.clock is not None,
            'controlled packet requires sampler clock')
    clock = sonic.clock
    origin = Fraction(clock.origin_s)
    end = rational_value(full_end_s, 'controlled packet full physical end',
                         origin, min(MAX_TIME_S, budget.max_read_s))
    require(end > origin, 'controlled packet requires nonzero physical extent')
    for name, value in (
        ('input asset', input_asset_sha256),
        ('source revision', source_revision_sha256),
        ('graph revision', graph_revision_sha256),
        ('claimed live graph revision', expected_live_graph_sha256),
    ):
        hash_value(value, name)
    require(graph_revision_sha256 == expected_live_graph_sha256,
            'claimed graph revision mismatch; live authorization not established')
    require(type(upstream_route_receipts) is tuple and
            len(upstream_route_receipts) == len(clock.routes),
            'every controlled route needs one versioned source receipt')
    for route, receipt in zip(clock.routes, upstream_route_receipts):
        record(receipt, AuthenticatedRouteReceiptV1, 'controlled route receipt')
        require(receipt.route_id == route.id and
                receipt.route_sha256 == route.sha256,
                'missing/foreign/stale compiled route receipt')
        if receipt.source_kind == 'upstream_feature':
            snapshot = receipt.graph_snapshot
            require(snapshot.sha256 == graph_revision_sha256,
                    'upstream feature graph snapshot/revision mismatch')
            require(sonic.instance_id in snapshot.nodes and
                    receipt.upstream_source_id in snapshot.ancestors_of(sonic.instance_id),
                    'upstream feature lacks verified acyclic ancestor')
            require(Fraction(receipt.support_start_s) <= origin and
                    Fraction(receipt.support_end_s) >= end,
                    'upstream feature lacks full physical support/lookahead')
            # Input PCM, feature method and measured content must be resolved
            # by Integration, not invented from this digest-only receipt.
    frozen = SonicSpec.from_json(sonic.to_json())
    channels = []
    total = 0
    for channel in range(frozen.channels):
        if cancelled is not None and cancelled():
            raise ClockCancelled('controlled packet cancelled before channel compilation')
        events = compile_step_clock_events(
            frozen, qtext(end), channel=channel,
            budget=budget, cancelled=cancelled)
        total += len(events)
        require(total <= budget.max_events,
                'controlled packet combined stereo event budget exceeded')
        channels.append(ControlledChannelClockV1(
            channel=channel,
            seed_identity_sha256=_seed_receipt_sha256(frozen, channel),
            events=tuple(ControlledClockEventV1(
                index=e.index, epoch=e.epoch, crossing=e.crossing,
                coordinate_s=event_text(e.coordinate_s),
                coordinate_error_bound_s=event_text(e.coordinate_error_bound_s),
            ) for e in events),
        ))
    if cancelled is not None and cancelled():
        raise ClockCancelled('controlled packet cancelled before immutable publication')
    channel_tuple = tuple(channels)
    packet = ControlledSamplerClockV1(
        method=METHOD, full_end_s=qtext(end),
        sonic_sha256=frozen.sonic_sha256, clock_sha256=frozen.clock.sha256,
        input_asset_sha256=input_asset_sha256,
        source_revision_sha256=source_revision_sha256,
        graph_revision_sha256=graph_revision_sha256,
        claimed_live_graph_sha256=expected_live_graph_sha256,
        instance_id=frozen.instance_id, band=frozen.band,
        clock_group=frozen.clock_group, stereo_link=frozen.stereo_link,
        channels_count=frozen.channels,
        jitter_sha256=frozen.clock.jitter.sha256,
        route_receipts=upstream_route_receipts,
        channels=channel_tuple,
        event_ledger_sha256=_ledger_sha256(channel_tuple),
        budget_max_events=budget.max_events,
    )
    packet.require_claims(
        frozen, full_end_s=qtext(end),
        input_asset_sha256=input_asset_sha256,
        source_revision_sha256=source_revision_sha256,
        graph_revision_sha256=graph_revision_sha256,
    )
    return packet
