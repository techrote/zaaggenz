"""NYQ-003 optional *local* numerical-to-delivery conversion, not export wiring.

This deliberately follows (rather than precedes) any sonic nonlinear stages.
It cannot undo virtual-clock capture aliases and makes no musical-quality claim.
No existing SamplerPlan or graph/rack/output owner calls this module yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
from math import gcd

import numpy as np

from zaaggenz_contracts.nyquismic import (
    MAX_EVALUATION_HZ, ResourceBudget, _Record, integer, record, require,
)
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from .nyquismic import _immutable

METHOD = 'nyq.polyphase-delivery-kaiser10-24lobes.v1'
STAGED_44100_METHOD = 'nyq.polyphase-delivery-44100-via-48000.v1'


@dataclass(frozen=True)
class DeliveryConversionPolicy(_Record):
    """Full-snapshot identity for one bounded, non-normalizing FIR converter."""
    version: str = 'nyq.delivery-conversion.v1'
    method: str = METHOD
    boundary: str = 'constant_zero'
    clipping: str = 'none'

    def __post_init__(self):
        require(self.version == 'nyq.delivery-conversion.v1',
                'unsupported Nyquismic delivery conversion version')
        require(self.method in (METHOD, STAGED_44100_METHOD),
                'unsupported Nyquismic numerical conversion method')
        require(self.boundary == 'constant_zero',
                'unsupported delivery conversion edge policy')
        require(self.clipping == 'none',
                'Nyquismic conversion must not clip or normalize samples')



def admit_delivery_stages(numerical_rate_hz: int, delivery_rate_hz: int, *,
                          policy: DeliveryConversionPolicy = DeliveryConversionPolicy(),
                          budget: ResourceBudget = ResourceBudget(),
                          frames: int | None = None):
    """Return exact (input Hz, output Hz, up, down, taps) FIR stage plan.

    The explicitly selected 44.1 kHz mode routes AFTER all sonic DSP via an
    integral 48 kHz intermediate. Direct/default conversion is unchanged.
    """
    record(policy, DeliveryConversionPolicy, 'delivery policy')
    record(budget, ResourceBudget, 'delivery budget')
    integer(numerical_rate_hz, 'numerical rate Hz', 8000, MAX_EVALUATION_HZ)
    integer(delivery_rate_hz, 'delivery rate Hz', 8000, 192000)
    require(numerical_rate_hz >= delivery_rate_hz,
            'delivery converter only admits downconversion or identical rates')
    if policy.method == STAGED_44100_METHOD:
        require(delivery_rate_hz == 44100 and numerical_rate_hz >= 48000 and
                numerical_rate_hz % 48000 == 0,
                'staged 44.1 kHz delivery requires an integral 48 kHz intermediate')
        if frames is not None:
            require(frames * 48000 % numerical_rate_hz == 0 and
                    frames * delivery_rate_hz % numerical_rate_hz == 0,
                    'staged delivery requires integral intermediate/final physical extent')
        clocks = ((numerical_rate_hz, 48000), (48000, 44100)) if numerical_rate_hz > 48000 else ((48000, 44100),)
    else:
        clocks = ((numerical_rate_hz, delivery_rate_hz),)
    stages = []
    for incoming, outgoing in clocks:
        common = gcd(incoming, outgoing)
        up, down = outgoing // common, incoming // common
        taps = 1 if up == down else 24 * max(up, down) + 1
        require(taps <= budget.max_filter_taps,
                'delivery FIR ratio exceeds admitted kernel tap budget')
        stages.append((incoming, outgoing, up, down, taps))
    return tuple(stages)


@dataclass(frozen=True)
class DeliveryConversionResult:
    audio: np.ndarray
    diagnostics: dict
    policy: DeliveryConversionPolicy


def convert_numerical_to_delivery(
    audio, numerical_rate_hz: int, delivery_rate_hz: int, *,
    policy: DeliveryConversionPolicy = DeliveryConversionPolicy(),
    budget: ResourceBudget = ResourceBudget(), cancelled=None,
) -> DeliveryConversionResult:
    """FIR conversion at fixed physical time origin, after artistic DSP.

    The 24*max(up,down)+1 tap beta-10 Kaiser FIR is explicit. Unsupported
    co-prime ratios/tap counts are rejected, not approximated. The first output
    sample corresponds to the first input sample. The tail is cropped to
    ceil(N*delivery/evaluation); finite zero padding is deliberate. Supports
    empty, mono and stereo float PCM; no implicit clipping/peak normalization.
    This bounded one-shot helper has before/after cancellation only.
    """
    record(policy, DeliveryConversionPolicy, 'delivery policy')
    record(budget, ResourceBudget, 'delivery conversion budget')
    require(cancelled is None or callable(cancelled),
            'delivery cancellation hook must be callable')
    if cancelled is not None and cancelled():
        raise ClockCancelled('delivery conversion cancelled before publication')
    integer(numerical_rate_hz, 'numerical evaluation rate Hz',
            8000, MAX_EVALUATION_HZ)
    integer(delivery_rate_hz, 'delivery output rate Hz', 8000, 192000)
    require(numerical_rate_hz >= delivery_rate_hz,
            'delivery converter only admits downconversion or identical rates')

    view = np.asarray(audio)
    require(view.ndim in (1, 2) and (view.ndim == 1 or view.shape[1] in (1, 2)),
            'delivery PCM must be mono or stereo')
    require(view.dtype.kind == 'f' and view.size <= budget.max_frames,
            'delivery PCM must be bounded floating-point source')
    # Own the admitted PCM before testing finiteness or calling external
    # SciPy code. A caller may retain a writable view and alter it while the
    # conversion is in flight; validation must describe the bytes processed.
    # The full source and converted output are independently budgeted.
    samples = np.array(view, dtype=np.float64, copy=True, order='C')
    require(np.isfinite(samples).all(), 'delivery PCM must be finite')
    frames = samples.shape[0]
    channels = 1 if samples.ndim == 1 else samples.shape[1]
    stages = admit_delivery_stages(
        numerical_rate_hz, delivery_rate_hz, policy=policy, budget=budget, frames=frames)
    common = gcd(numerical_rate_hz, delivery_rate_hz)
    up, down = delivery_rate_hz // common, numerical_rate_hz // common
    output_frames = (frames * up + down - 1) // down
    require(output_frames * channels <= budget.max_frames,
            'delivery output frames exceed admitted budget')
    result = samples
    stage_details = []
    for incoming, outgoing, stage_up, stage_down, taps in stages:
        if stage_up == stage_down:
            kernel = np.array([1.], dtype='<f8')
        else:
            from scipy.signal import firwin, resample_poly
            kernel = firwin(taps, 1. / max(stage_up, stage_down),
                            window=('kaiser', 10.), pass_zero='lowpass')
        require(len(kernel) == taps and np.isfinite(kernel).all(),
                'delivery FIR kernel is not finite')
        expected = (result.shape[0] * stage_up + stage_down - 1) // stage_down
        if stage_up != stage_down:
            result = (np.empty((0,) if samples.ndim == 1 else (0, channels),
                               dtype=np.float64) if result.shape[0] == 0 else
                      resample_poly(result, stage_up, stage_down, axis=0,
                                    window=kernel, padtype='constant'))
        require(result.shape[0] == expected,
                'delivery FIR stage changed declared physical extent')
        stage_details.append({
            'input_rate_hz': incoming, 'output_rate_hz': outgoing,
            'ratio_up': stage_up, 'ratio_down': stage_down,
            'kernel_taps': taps,
            'kernel_sha256': hashlib.sha256(
                np.asarray(kernel, dtype='<f8').tobytes()).hexdigest(),
        })
        if cancelled is not None and cancelled():
            raise ClockCancelled('delivery conversion cancelled between FIR stages')
    require(result.shape == (output_frames,) if samples.ndim == 1
            else result.shape == (output_frames, channels),
            'delivery converter returned unexpected frame/channel extent')
    if policy.method == STAGED_44100_METHOD:
        aggregate = hashlib.sha256(b'nyq.delivery-ordered-fir-stages.v1\\n')
        for row in stage_details:
            aggregate.update(f"{row['input_rate_hz']}|{row['output_rate_hz']}|{row['kernel_sha256']}\\n".encode('ascii'))
        kernel_hash = aggregate.hexdigest()
    else:
        kernel_hash = stage_details[0]['kernel_sha256']
    require(np.isfinite(result).all(),
            'delivery conversion would publish nonfinite PCM')
    if cancelled is not None and cancelled():
        raise ClockCancelled('delivery conversion cancelled before publication')
    return DeliveryConversionResult(
        audio=_immutable(result),
        diagnostics={
            'method': policy.method,
            'policy_sha256': policy.sha256,
            'numerical_rate_hz': numerical_rate_hz,
            'delivery_rate_hz': delivery_rate_hz,
            'ratio_up': up, 'ratio_down': down,
            'kernel_taps': sum(row['kernel_taps'] for row in stage_details),
            'kernel_sha256': kernel_hash,
            'window': ('staged_kaiser_beta10_v1'
                       if policy.method == STAGED_44100_METHOD else 'kaiser_beta10'),
            **({'stages': stage_details} if policy.method == STAGED_44100_METHOD else {}),
            'boundary': policy.boundary,
            'clipping': policy.clipping,
            'source_frames': frames,
            'output_frames': output_frames,
            # Hash the PRIVATE admitted numerical PCM and the actual delivered
            # PCM in a canonical f64le interleaved domain. Kernel identity alone
            # cannot establish which audible bytes a candidate processed.
            'pcm_identity_domain': 'unclamped-f64le-interleaved-v1',
            'source_pcm_sha256': hashlib.sha256(
                np.asarray(samples, dtype='<f8').tobytes(order='C')).hexdigest(),
            'output_pcm_sha256': hashlib.sha256(
                np.asarray(result, dtype='<f8').tobytes(order='C')).hexdigest(),
            'time_origin_s': '0/1',
            'output_extent_s': f'{Fraction(output_frames, delivery_rate_hz).numerator}/{Fraction(output_frames, delivery_rate_hz).denominator}',
        },
        policy=policy,
    )


@dataclass(frozen=True)
class SamplerDeliveryResult:
    """Actual opt-in local PCM, not product export or quality certification."""
    audio: np.ndarray
    diagnostics: dict
    policy: DeliveryConversionPolicy


def render_sampler_to_delivery(source, sonic, *, numerical_rate_hz: int,
                               delivery_rate_hz: int | None = None,
                               policy: DeliveryConversionPolicy = DeliveryConversionPolicy(),
                               budget: ResourceBudget = ResourceBudget(),
                               cancelled=None) -> SamplerDeliveryResult:
    """Atomically compose physical-time capture/reconstruction and final FIR.

    Independently declare immutable source and final delivery clocks.
    Whole physical extents must fit both numerical and delivery grids exactly;
    unsupported FIR ratios fail before expensive event capture.
    """
    from zaaggenz_contracts.nyquismic import SonicSpec
    from .nyquismic import FrozenInput, SamplerPlan, sampler_evaluation

    require(type(source) is FrozenInput, 'expected immutable sampler source')
    record(sonic, SonicSpec, 'sampler delivery sonic spec')
    record(policy, DeliveryConversionPolicy, 'sampler delivery conversion policy')
    record(budget, ResourceBudget, 'sampler delivery budget')
    require(cancelled is None or callable(cancelled), 'invalid cancellation hook')
    if cancelled is not None and cancelled():
        raise ClockCancelled('sampler delivery cancelled before preparation')
    if delivery_rate_hz is None:
        delivery_rate_hz = source.sample_rate_hz
    integer(delivery_rate_hz, 'delivery rate Hz', 8000, 192000)
    integer(numerical_rate_hz, 'numerical evaluation rate Hz', 8000, MAX_EVALUATION_HZ)
    require(numerical_rate_hz >= delivery_rate_hz,
            'sampler delivery requires numerical rate >= delivery rate')
    asset = source.asset.to_dict()
    source_extent = Fraction(asset['frame_count'], source.sample_rate_hz)
    expected_delivery_frames = source_extent * delivery_rate_hz
    require(expected_delivery_frames.denominator == 1,
            'sampler delivery requires integral final physical extent')
    require(expected_delivery_frames.numerator * asset['channels'] <= budget.max_frames,
            'sampler final extent over admitted frame budget')
    # Qualify every exact FIR stage and intermediate extent before capture.
    extent = source_extent * numerical_rate_hz
    require(extent.denominator == 1, 'sampler delivery requires aligned physical extent')
    require(extent.numerator * asset['channels'] <= budget.max_frames,
            'sampler numerical extent over admitted frame budget')
    admit_delivery_stages(numerical_rate_hz, delivery_rate_hz,
                          policy=policy, budget=budget, frames=extent.numerator)

    plan = SamplerPlan.prepare(source, sonic, sampler_evaluation(numerical_rate_hz, budget),
                               frame_count=extent.numerator, cancelled=cancelled,
                               delivery_rate_hz=delivery_rate_hz)
    numeric = plan.render(cancelled=cancelled)
    final = convert_numerical_to_delivery(numeric.audio, numerical_rate_hz,
                                         delivery_rate_hz, policy=policy,
                                         budget=budget, cancelled=cancelled)
    require(final.audio.shape[0] == expected_delivery_frames.numerator,
            'sampler delivery physical extent changed during conversion')
    require(final.diagnostics['source_pcm_sha256'] == numeric.diagnostics['pcm_sha256'],
            'sampler-to-delivery numerical PCM provenance mismatch')
    if cancelled is not None and cancelled():
        raise ClockCancelled('sampler delivery cancelled before publication')
    return SamplerDeliveryResult(
        audio=final.audio, policy=final.policy,
        diagnostics={
            'method': ('nyq.local-physical-sampler-to-delivery.v1'
                       if delivery_rate_hz == source.sample_rate_hz
                       else 'nyq.local-physical-sampler-to-crossrate-delivery.v1'),
            'source_asset_sha256': source.asset.sha256,
            'source_rate_hz': source.sample_rate_hz,
            'source_extent_s': str(source_extent),
            'expected_delivery_frames': expected_delivery_frames.numerator,
            'sonic_sha256': sonic.sonic_sha256,
            'clock_sha256': sonic.clock.sha256,
            'sampler_render_sha256': numeric.render_sha256,
            'event_count': len(plan.events),
            'numerical_rate_hz': numerical_rate_hz,
            'delivery_rate_hz': delivery_rate_hz,
            'sampler': numeric.diagnostics,
            'delivery': final.diagnostics,
            'output_pcm_sha256': final.diagnostics['output_pcm_sha256'],
            'analytic_oracle_verified': False,
            'convergence_qualified': False,
            'product_export_verified': False,
        })
