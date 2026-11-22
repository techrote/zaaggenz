"""NYQ-004 opt-in controlled-event PCM proof, outside registered rack/export.

Consumes the exact physical-clock crossings of nyquismic_controls rather than
substituting a rounded hold period. Reuses accepted NYQ-002 immutable capture
interpolation. Restricts output to the source's own sample grid: generalized
numerical-rate/convergence and persistent sampler checkpoints remain separate.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from math import ceil

import numpy as np

from zaaggenz_contracts.nyquismic import (
    ResourceBudget, SonicSpec, qtext, integer, record, require,
)
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from zaaggenz_contracts.nyquismic_controls import compile_step_clock_events
from .nyquismic import FrozenInput, _sample_at, _immutable

METHOD = 'nyq.controlled-native-grid-audio-proof.v1'
_BLOCK = 256


@dataclass(frozen=True)
class ControlledAudioProof:
    audio: np.ndarray
    diagnostics: dict


def render_controlled_audio_proof(
    source: FrozenInput, sonic: SonicSpec, *,
    start_frame: int = 0, stop_frame: int | None = None,
    budget: ResourceBudget = ResourceBudget(), cancelled=None,
) -> ControlledAudioProof:
    """Render a bounded source-native-grid hold/linear controlled-clock segment.

    Full-extent event admission precedes every region; no phase is reset at a
    region boundary. A crossing too near a frame/capture ambiguity to certify
    under its rational error interval is rejected, never silently rounded.
    No numerical delivery conversion or graph/rack execution is performed.
    """
    record(source, FrozenInput, 'controlled proof immutable input')
    record(sonic, SonicSpec, 'controlled proof sonic request')
    record(budget, ResourceBudget, 'controlled proof budget')
    require(cancelled is None or callable(cancelled), 'controlled proof cancellation')
    sonic = SonicSpec.from_json(sonic.to_json())
    require(sonic.mode == 'sampler' and sonic.clock is not None,
            'controlled proof requires sampler mode')
    require(sonic.clock.origin_s == '0/1',
            'controlled proof currently requires source-time origin zero')
    require(sonic.prefilter == 'off_v1' and
            sonic.reconstruction in ('hold_v1', 'linear_time_v1'),
            'controlled proof only admits unfiltered hold/time-linear reconstruction')
    asset = source.asset.to_dict()
    frames, channels, rate = asset['frame_count'], asset['channels'], source.sample_rate_hz
    require(channels == sonic.channels, 'controlled proof source/channel mismatch')
    require(frames * channels <= budget.max_frames, 'controlled proof frame budget')
    integer(start_frame, 'controlled proof start frame', 0, frames)
    stop = frames if stop_frame is None else stop_frame
    integer(stop, 'controlled proof stop frame', start_frame, frames)

    def check_cancel():
        if cancelled is not None and cancelled():
            raise ClockCancelled('controlled PCM cancelled; no partial publication')

    check_cancel()
    pcm = source.pcm.reshape(frames, channels)
    end = qtext(Fraction(frames, rate))
    events_by_channel = []
    first_by_channel = []
    captures_by_channel = []
    ledger = sha256()
    ledger.update(b'nyq.controlled-native-grid-ledger.v1\0')
    total_events = 0

    for channel in range(channels):
        check_cancel()
        events = compile_step_clock_events(
            sonic, end, channel=channel, budget=budget, cancelled=cancelled)
        total_events += len(events)
        require(total_events <= budget.max_events,
                'combined controlled channel event budget exceeded')
        first = []
        captures = []
        for i, event in enumerate(events):
            if (i & 255) == 0:
                check_cancel()
            stamp, error = event.coordinate_s, event.coordinate_error_bound_s
            require(stamp >= 0 and error >= 0, 'invalid controlled event coordinate')
            earliest = ceil((stamp - error) * rate)
            latest = ceil((stamp + error) * rate)
            require(earliest == latest and 0 <= earliest <= frames,
                    'controlled crossing too close to numerical grid to certify')
            if sonic.capture == 'nearest_left_tie_v1' and error:
                position = stamp * rate
                fraction = position - (position.numerator // position.denominator)
                require(abs(fraction - Fraction(1, 2)) > error * rate,
                        'controlled nearest capture tie cannot be certified')
            # A half-open event may occur after the final output frame but
            # before source end; first==frames is legitimate and affects
            # no published sample. It still belongs in the exact event ledger.
            first.append(earliest)
            captures.append(float(_sample_at(
                pcm, stamp * rate, sonic.capture, sonic.input_boundary)[channel]))
            ledger.update(
                f'{channel}:{event.index}:{event.epoch}:{event.crossing}:'
                f'{stamp.numerator}/{stamp.denominator}:'
                f'{error.numerator}/{error.denominator}\n'.encode('ascii'))
        require(all(a <= b for a, b in zip(first, first[1:])),
                'controlled grid event ownership must be monotone')
        events_by_channel.append(events)
        first_by_channel.append(np.asarray(first, dtype=np.int64))
        captures_by_channel.append(np.asarray(captures, dtype=np.float64))

    check_cancel()
    if sonic.is_boundary_identity:
        # Do not change f32 source representation, including signed zero.
        audio = _immutable(pcm[start_frame:stop].copy())
    else:
        out = np.zeros((stop - start_frame, channels), dtype=np.float64)
        for a in range(start_frame, stop, _BLOCK):
            check_cancel()
            b = min(stop, a + _BLOCK)
            frames_here = np.arange(a, b, dtype=np.int64)
            for channel in range(channels):
                events = events_by_channel[channel]
                first = first_by_channel[channel]
                captures = captures_by_channel[channel]
                owners = np.searchsorted(first, frames_here, side='right') - 1
                for owner in np.unique(owners):
                    if owner < 0:
                        continue
                    mask = owners == owner
                    if sonic.reconstruction == 'hold_v1' or owner + 1 == len(events):
                        out[a-start_frame:b-start_frame, channel][mask] = captures[owner]
                    else:
                        left, right = events[owner].coordinate_s, events[owner + 1].coordinate_s
                        require(right > left, 'controlled reconstruction event interval')
                        alpha = np.array([
                            float((Fraction(int(n), rate) - left) / (right - left))
                            for n in frames_here[mask]], dtype=np.float64)
                        out[a-start_frame:b-start_frame, channel][mask] = (
                            captures[owner] + alpha * (captures[owner + 1] - captures[owner]))
        if sonic.wet != 1.0:
            out = (1.0 - sonic.wet) * pcm[start_frame:stop].astype(np.float64) + sonic.wet * out
        require(np.isfinite(out).all(), 'controlled PCM proof produced nonfinite audio')
        audio = _immutable(out)
    check_cancel()
    if source._mono:
        audio = _immutable(audio[:, 0])
    diagnostics = {
        'method': METHOD,
        'native_evaluation_rate_hz': rate,
        'source_asset_sha256': source.asset.sha256,
        'sonic_sha256': sonic.sonic_sha256,
        'clock_sha256': sonic.clock.sha256,
        'event_count_by_channel': [len(events) for events in events_by_channel],
        'event_ledger_sha256': ledger.hexdigest(),
        'region_frames': [start_frame, stop],
        'full_output_frames': frames,
        'pcm_sha256': sha256(audio.tobytes()).hexdigest(),
        'product_rack_export_qualified': False,
        'reference_rate_convergence_qualified': False,
    }
    return ControlledAudioProof(audio, diagnostics)
