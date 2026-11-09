"""NYQ-003 opt-in #267 controlled physical-event PCM consumer (component only).

The packet is *not* a live Compose graph attestation. Caller graph/source
revisions remain claims until Integration supplies an authenticated session.
Legacy ClockPlan, SamplerPlan PCM and SamplerCheckpoint remain unmodified.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from fractions import Fraction
import hashlib
import math

import numpy as np

from zaaggenz_contracts import digest
from zaaggenz_contracts.nyquismic import (
    MAX_EVENTS, MAX_FRAMES, MAX_TIME_S, SAMPLER_AUDIO_METHOD,
    SAMPLER_NUMERICAL_FILTER, EvaluationPolicy, RenderIdentity,
    SonicSpec, ResourceBudget, _Record, require, record, integer,
    hash_value, qtext, bind_render_identity, UnsupportedNyquismic,
)
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_dsp.nyquismic import (
    FrozenInput, SamplerResult, sampler_evaluation, _immutable, _sample_at,
    _check_hooks, _cancel, _notify, _NO_RACK,
)

METHOD = 'nyq.controlled-sampler-consumer.v1'
CHECKPOINT_VERSION = 'nyq.controlled-sampler-checkpoint.v1'
_BLOCK = 256


@dataclass(frozen=True)
class ControlledSamplerCheckpoint(_Record):
    """Packet-bound per-channel capture history, never a ClockCheckpoint."""
    render_sha256: str
    packet_sha256: str
    event_ledger_sha256: str
    next_frame: int
    events_before: tuple[int, ...]
    previous_event_index: tuple[int, ...]
    next_event_index: tuple[int, ...]
    previous_capture: tuple[tuple[float, ...], ...]
    next_capture: tuple[tuple[float, ...], ...]
    audio_active: bool
    version: str = CHECKPOINT_VERSION

    def __post_init__(self):
        require(self.version == CHECKPOINT_VERSION, 'controlled checkpoint version')
        for key in ('render_sha256', 'packet_sha256', 'event_ledger_sha256'):
            hash_value(getattr(self, key), 'controlled checkpoint ' + key)
        integer(self.next_frame, 'controlled next frame', 0, MAX_FRAMES)
        require(type(self.audio_active) is bool, 'controlled checkpoint active flag')
        count = len(self.events_before)
        require(count in (1, 2) and all(
            type(row) is tuple and len(row) == count for row in
            (self.previous_event_index, self.next_event_index,
             self.previous_capture, self.next_capture)),
            'controlled checkpoint channel shape')
        for before, prior, after, left, right in zip(
                self.events_before, self.previous_event_index,
                self.next_event_index, self.previous_capture, self.next_capture):
            integer(before, 'controlled events before', 0, MAX_EVENTS)
            integer(prior, 'controlled preceding event', -1, MAX_EVENTS - 1)
            integer(after, 'controlled following event', 0, MAX_EVENTS)
            require(before == after == prior + 1,
                    'controlled checkpoint event membership mismatch')
            for capture in (left, right):
                require(type(capture) is tuple and len(capture) in (0, 1) and
                        all(type(x) in (float, int) and math.isfinite(x) for x in capture),
                        'controlled checkpoint finite capture shape')

    @classmethod
    def from_dict(cls, data):
        require(type(data) is dict and set(data) == {f.name for f in fields(cls)},
                'controlled checkpoint missing/foreign fields')
        lists = ('events_before', 'previous_event_index', 'next_event_index',
                 'previous_capture', 'next_capture')
        require(all(type(data[k]) is list for k in lists),
                'controlled checkpoint arrays required')
        require(all(type(v) is list for k in ('previous_capture', 'next_capture')
                    for v in data[k]), 'controlled checkpoint nested arrays required')
        return cls(**{
            **data,
            **{k: tuple(data[k]) for k in lists[:3]},
            **{k: tuple(tuple(v) for v in data[k]) for k in lists[3:]},
        })


def _owned_grid_frame(t: Fraction, error: Fraction, origin: Fraction,
                      rate: int, count: int) -> int:
    """Conservative half-open first-frame ownership with certified enclosure."""
    require(t >= origin and error >= 0, 'controlled event outside clock origin')
    nominal = math.ceil((t - origin) * rate)
    require(0 <= nominal < count, 'controlled event not in output half-open grid')
    if error:
        low, high = (t - error - origin) * rate, (t + error - origin) * rate
        # A root on either side of an output-frame boundary has a different
        # owner. If a lower enclosure touches the previous boundary it is
        # ambiguous even when the ceil of the two endpoints happens to agree.
        require(math.ceil(low) == nominal == math.ceil(high) and
                low > nominal - 1,
                'controlled event output-grid membership uncertifiable')
    return nominal


def _nearest_source_index(t: Fraction) -> int:
    # Tie goes LEFT, exactly as nearest_left_tie_v1.
    return math.ceil(t - Fraction(1, 2))


@dataclass(frozen=True, init=False)
class ControlledSamplerPlan:
    """Prepared full-extent packet consumer, returned by SamplerPlan.prepare."""
    source: FrozenInput
    spec: SonicSpec
    evaluation: EvaluationPolicy
    identity: RenderIdentity
    packet: object
    frame_count: int
    events: tuple[tuple, ...]
    captures: tuple[np.ndarray, ...]
    _coordinates: tuple[tuple[Fraction, ...], ...]
    _first_frames: tuple[np.ndarray, ...]
    _origin: Fraction
    _active: bool

    def __init__(self, *args, **kwargs):
        # Dataclass freezing protects attributes only after construction.
        # Do not let dataclasses.replace or a public constructor install
        # captures that were never checked against the actual FrozenInput.
        require(False, 'ControlledSamplerPlan must be constructed by prepare; unadmitted/replaced capture histories are not executable')

    @classmethod
    def prepare(cls, source, spec, evaluation, *, frame_count, cancelled, progress,
                source_revision_sha256, context_sha256, delivery_rate_hz,
                controlled_clock, graph_revision_sha256, rack_revision_sha256):
        # Import only on the opt-in path. #267 producer is separately owned
        # and is not silently copied or cherry-picked into Draft #266.
        from zaaggenz_contracts.nyquismic_clock_packet import (
            ControlledSamplerClockV1, event_fraction,
        )

        _check_hooks(cancelled, progress)
        _cancel(cancelled)
        record(source, FrozenInput, 'controlled immutable source')
        record(spec, SonicSpec, 'controlled sonic')
        record(controlled_clock, ControlledSamplerClockV1, 'controlled clock packet')
        spec = SonicSpec.from_json(spec.to_json())
        packet = ControlledSamplerClockV1.from_json(controlled_clock.to_json())
        require(spec.mode == 'sampler', 'controlled sampling requires sampler mode')
        evaluation = sampler_evaluation(source.sample_rate_hz) if evaluation is None else evaluation
        record(evaluation, EvaluationPolicy, 'controlled evaluation')
        evaluation = EvaluationPolicy.from_json(evaluation.to_json())
        require(evaluation.audio_method == SAMPLER_AUDIO_METHOD and
                evaluation.numerical_filter == SAMPLER_NUMERICAL_FILTER and
                not evaluation.reference_rates_hz,
                'controlled sampling requires one explicit fractional-event numerical pass')
        require(spec.prefilter == 'off_v1',
                'controlled modulated clock cannot claim static anti-alias prefilter')
        require(spec.reconstruction in (
            'hold_v1', 'nearest_time_v1', 'linear_time_v1', 'cubic_time_v1'),
            'controlled clock reconstruction unsupported; choose time-aware policy')
        asset = source.asset.to_dict()
        require(asset['channels'] == spec.channels,
                'controlled source/channel mismatch')
        budget = evaluation.budget
        require(asset['frame_count'] * spec.channels <= budget.max_frames,
                'controlled source frame/channel budget exceeded')
        rate = evaluation.evaluation_rate_hz
        if delivery_rate_hz is None:
            delivery_rate_hz = source.sample_rate_hz
        integer(delivery_rate_hz, 'controlled delivery rate Hz', 8000, 192000)
        if frame_count is None:
            frame_count = math.ceil(Fraction(asset['frame_count'] * rate,
                                             source.sample_rate_hz))
        integer(frame_count, 'controlled output frames', 1,
                budget.max_frames // spec.channels)
        origin = Fraction(spec.clock.origin_s)
        end = origin + Fraction(frame_count, rate)
        require(end <= MAX_TIME_S and end <= budget.max_read_s,
                'controlled output exceeds bounded physical time/read extent')
        require(packet.full_end_s == qtext(end),
                'controlled packet full extent differs from numerical grid')
        # A source revision, claimed graph revision and rack revision must all
        # be explicit on this path; none establishes a live graph authority.
        for name, value in (('source revision', source_revision_sha256),
                            ('graph revision', graph_revision_sha256),
                            ('rack revision', rack_revision_sha256)):
            hash_value(value, 'controlled ' + name)
        packet.require_claims(
            spec, full_end_s=qtext(end),
            input_asset_sha256=source.asset.sha256,
            source_revision_sha256=source_revision_sha256,
            graph_revision_sha256=graph_revision_sha256,
        )
        require(not (packet.live_graph_authorized or packet.upstream_pcm_authorized or
                     packet.sampler_checkpoint_qualified),
                'packet cannot self-authorize graph, PCM or checkpoint')
        total = sum(len(channel.events) for channel in packet.channels)
        require(total <= budget.max_events and
                packet.channels_count == spec.channels,
                'controlled combined channel event budget exceeded')
        active = not spec.is_boundary_identity
        require(active or rate == source.sample_rate_hz,
                'controlled exact bypass requires matching numerical/source grids')
        if context_sha256 is None:
            context_sha256 = digest({
                'domain': METHOD, 'packet': packet.sha256, 'extent': qtext(end),
                'origin': qtext(origin),
            })
        identity = bind_render_identity(
            spec, evaluation, input_asset=source.asset,
            source_revision_sha256=source_revision_sha256,
            graph_revision_sha256=graph_revision_sha256,
            rack_revision_sha256=rack_revision_sha256,
            context_sha256=context_sha256, delivery_rate_hz=delivery_rate_hz,
            start_s=qtext(origin), end_s=qtext(end),
        )
        _notify(progress, 0, cancelled)
        pcm = source.pcm.reshape(asset['frame_count'], spec.channels)
        events, times, first, captured = [], [], [], []
        done = 0
        for channel_index, channel in enumerate(packet.channels):
            ts, frames, values = [], [], []
            previous = None
            for event in channel.events:
                if done % _BLOCK == 0:
                    _notify(progress, done / max(total, 1), cancelled)
                t = event_fraction(event.coordinate_s)
                err = event_fraction(event.coordinate_error_bound_s)
                require(t >= origin and t + err < end and t - err >= origin,
                        'controlled event enclosure escapes physical capture extent')
                if previous is not None:
                    require(t - err > previous,
                            'controlled event interval not strictly monotone')
                previous = t + err
                frames.append(_owned_grid_frame(t, err, origin, rate, frame_count))
                relative = t - origin
                if spec.capture == 'nearest_left_tie_v1' and err:
                    lo = _nearest_source_index((relative - err) * source.sample_rate_hz)
                    hi = _nearest_source_index((relative + err) * source.sample_rate_hz)
                    require(lo == hi,
                            'controlled capture nearest-source tie uncertifiable')
                # The selected canonical bounded rational coordinate is the
                # deterministic capture representative of its certified range.
                values.append(float(_sample_at(
                    pcm, relative * source.sample_rate_hz,
                    spec.capture, spec.input_boundary,
                )[channel_index]))
                ts.append(relative)
                done += 1
            events.append(channel.events)
            times.append(tuple(ts))
            first.append(_immutable(np.asarray(frames, dtype=np.int64)))
            captured.append(_immutable(np.asarray(values, dtype=np.float64)))
        _notify(progress, 1, cancelled)
        # Prepare is the sole normal admission path. Every executable field
        # comes from the verified packet, actual source and bounded capture
        # loop above; never accept caller-supplied capture arrays here.
        values = dict(
            source=source, spec=spec, evaluation=evaluation, identity=identity,
            packet=packet, frame_count=frame_count, events=tuple(events),
            captures=tuple(captured), _coordinates=tuple(times),
            _first_frames=tuple(first), _origin=origin, _active=active,
        )
        require(set(values) == {field.name for field in fields(cls)},
                'incomplete controlled sampler preparation')
        result = object.__new__(cls)
        for name, value in values.items():
            object.__setattr__(result, name, value)
        _cancel(cancelled)
        return result

    @property
    def sample_rate_hz(self):
        return self.evaluation.evaluation_rate_hz

    @property
    def render_sha256(self):
        return digest({
            'domain': METHOD, 'request': self.identity.to_dict(),
            'packet': self.packet.sha256,
            'event_ledger': self.packet.event_ledger_sha256,
            'frames': self.frame_count, 'source_shape_mono': self.source._mono,
        })

    def checkpoint(self, frame: int) -> ControlledSamplerCheckpoint:
        integer(frame, 'controlled checkpoint frame', 0, self.frame_count)
        counts, prev, next_, left, right = [], [], [], [], []
        for channel, (frames, captures) in enumerate(
                zip(self._first_frames, self.captures)):
            before = int(np.searchsorted(frames, frame, side='right'))
            counts.append(before)
            prev.append(before - 1)
            next_.append(before)
            left.append((float(captures[before - 1]),) if before else ())
            right.append((float(captures[before]),) if before < len(captures) else ())
        return ControlledSamplerCheckpoint(
            self.render_sha256, self.packet.sha256,
            self.packet.event_ledger_sha256, frame,
            tuple(counts), tuple(prev), tuple(next_), tuple(left), tuple(right),
            self._active,
        )

    def _dry(self, start, stop):
        pcm = self.source.pcm.reshape(-1, self.spec.channels)
        indices = np.arange(start, stop, dtype=np.int64)
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

    def render(self, start_frame=None, stop_frame=None, *,
               checkpoint=None, cancelled=None, progress=None) -> SamplerResult:
        _check_hooks(cancelled, progress)
        _cancel(cancelled)
        if checkpoint is not None:
            record(checkpoint, ControlledSamplerCheckpoint, 'controlled sampler checkpoint')
            require(checkpoint == self.checkpoint(checkpoint.next_frame),
                    'foreign/stale/tampered controlled sampler checkpoint')
        start = (checkpoint.next_frame if checkpoint is not None else 0) if start_frame is None else start_frame
        stop = self.frame_count if stop_frame is None else stop_frame
        integer(start, 'controlled region start', 0, self.frame_count)
        integer(stop, 'controlled region stop', start, self.frame_count)
        require(checkpoint is None or start == checkpoint.next_frame,
                'controlled checkpoint/region start mismatch')
        _notify(progress, 0, cancelled)
        if not self._active:
            original = self.source.pcm.reshape(-1, self.spec.channels)
            out = np.zeros((stop - start, self.spec.channels), dtype=np.float32)
            for a in range(start, stop, _BLOCK):
                b = min(stop, a + _BLOCK)
                overlap = min(b, len(original))
                if a < overlap:
                    out[a-start:overlap-start] = original[a:overlap]
                if overlap < b and len(original) and self.spec.input_boundary == 'edge_hold':
                    out[max(a, overlap)-start:b-start] = original[-1]
                _notify(progress, (b-start) / max(stop-start, 1), cancelled)
        else:
            out = np.zeros((stop-start, self.spec.channels), dtype=np.float64)
            for a in range(start, stop, _BLOCK):
                _cancel(cancelled)
                b = min(stop, a+_BLOCK)
                frames = np.arange(a, b, dtype=np.int64)
                block = np.zeros((b-a, self.spec.channels), dtype=np.float64)
                for ch in range(self.spec.channels):
                    first = self._first_frames[ch]
                    times = self._coordinates[ch]
                    samples = self.captures[ch]
                    owners = np.searchsorted(first, frames, side='right') - 1
                    for owner in np.unique(owners):
                        if owner < 0:
                            continue
                        mask = owners == owner
                        left = samples[owner]
                        if self.spec.reconstruction == 'hold_v1' or owner+1 == len(times):
                            block[mask, ch] = left
                            continue
                        right = samples[owner+1]
                        duration = times[owner+1] - times[owner]
                        require(duration > 0, 'controlled reconstruction interval must be positive')
                        if self.spec.reconstruction == 'nearest_time_v1':
                            block[mask, ch] = np.fromiter((
                                left if 2*(Fraction(int(frame), self.sample_rate_hz) - times[owner])
                                    <= duration else right for frame in frames[mask]),
                                dtype=np.float64, count=int(np.count_nonzero(mask)))
                        else:
                            # Stable anchor in absolute full-frame coordinates,
                            # identical for full, chunk and restored checkpoint.
                            anchor = int(first[owner])
                            alpha0 = float((Fraction(anchor, self.sample_rate_hz) - times[owner]) / duration)
                            step = float(Fraction(1, self.sample_rate_hz) / duration)
                            alpha = alpha0 + (frames[mask] - anchor)*step
                            if self.spec.reconstruction == 'cubic_time_v1':
                                span = float(duration)
                                if owner > 0:
                                    slope_left = (right-samples[owner-1]) / float(
                                        times[owner+1]-times[owner-1])
                                else:
                                    slope_left = (right-left)/span
                                if owner+2 < len(times):
                                    slope_right = (samples[owner+2]-left) / float(
                                        times[owner+2]-times[owner])
                                else:
                                    slope_right = (right-left)/span
                                u2, u3 = alpha*alpha, alpha*alpha*alpha
                                block[mask, ch] = (
                                    (2*u3-3*u2+1)*left + (u3-2*u2+alpha)*span*slope_left
                                    + (-2*u3+3*u2)*right + (u3-u2)*span*slope_right)
                            else:
                                block[mask, ch] = left + alpha*(right-left)
                if self.spec.wet != 1:
                    block = (1-self.spec.wet)*self._dry(a,b) + self.spec.wet*block
                require(np.isfinite(block).all(), 'controlled reconstruction nonfinite')
                out[a-start:b-start] = block
                _notify(progress, (b-start)/max(stop-start,1), cancelled)
        _notify(progress, 1, cancelled)
        state = self.checkpoint(stop)
        audio = _immutable(out[:, 0] if self.source._mono else out)
        diagnostics = {
            'method': METHOD,
            'source_asset_sha256': self.source.asset.sha256,
            'sonic_sha256': self.spec.sonic_sha256,
            'render_sha256': self.render_sha256,
            'packet_sha256': self.packet.sha256,
            'event_ledger_sha256': self.packet.event_ledger_sha256,
            'channel_seed_sha256': [c.seed_identity_sha256 for c in self.packet.channels],
            'event_count_by_channel': [len(v) for v in self.events],
            'numerical_rate_hz': self.sample_rate_hz,
            'region_frames': [start, stop],
            'pcm_sha256': hashlib.sha256(np.asarray(audio, dtype='<f8').tobytes()).hexdigest(),
            'pcm_identity_domain': 'unclamped-f64le-interleaved-numerical-v1',
            'live_graph_authenticated': False,
            'upstream_pcm_authenticated': False,
            'compose_bound': False,
            'delivery_conversion_performed': False,
            'finite': bool(np.isfinite(audio).all()),
        }
        _cancel(cancelled)
        return SamplerResult(audio, state, diagnostics, self.render_sha256)
