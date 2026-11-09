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
        require(self.method == METHOD,
                'unsupported Nyquismic numerical conversion method')
        require(self.boundary == 'constant_zero',
                'unsupported delivery conversion edge policy')
        require(self.clipping == 'none',
                'Nyquismic conversion must not clip or normalize samples')


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
    common = gcd(numerical_rate_hz, delivery_rate_hz)
    up, down = delivery_rate_hz // common, numerical_rate_hz // common
    output_frames = (frames * up + down - 1) // down
    require(output_frames * channels <= budget.max_frames,
            'delivery output frames exceed admitted budget')
    # The identity path must not introduce ringing, conversion, or padding.
    if up == down:
        kernel = np.array([1.], dtype='<f8')
        result = samples
    else:
        taps = 24 * max(up, down) + 1
        require(taps <= budget.max_filter_taps,
                'delivery FIR ratio exceeds admitted kernel tap budget')
        from scipy.signal import firwin, resample_poly
        kernel = firwin(taps, 1. / max(up, down),
                        window=('kaiser', 10.), pass_zero='lowpass')
        require(len(kernel) == taps and np.isfinite(kernel).all(),
                'delivery FIR kernel is not finite')
        # SciPy's resample_poly rejects an empty input. An admitted empty
        # physical extent instead maps to an empty, correctly shaped extent.
        result = (
            np.empty((0,) if samples.ndim == 1 else (0, channels), dtype=np.float64)
            if frames == 0 else
            resample_poly(
                samples, up, down,
                axis=0, window=kernel, padtype='constant',
            )
        )
    require(result.shape == (output_frames,) if samples.ndim == 1
            else result.shape == (output_frames, channels),
            'delivery converter returned unexpected frame/channel extent')
    require(np.isfinite(result).all(),
            'delivery conversion would publish nonfinite PCM')
    if cancelled is not None and cancelled():
        raise ClockCancelled('delivery conversion cancelled before publication')
    return DeliveryConversionResult(
        audio=_immutable(result),
        diagnostics={
            'method': METHOD,
            'policy_sha256': policy.sha256,
            'numerical_rate_hz': numerical_rate_hz,
            'delivery_rate_hz': delivery_rate_hz,
            'ratio_up': up, 'ratio_down': down,
            'kernel_taps': len(kernel),
            'kernel_sha256': hashlib.sha256(
                np.asarray(kernel, dtype='<f8').tobytes()).hexdigest(),
            'window': 'kaiser_beta10',
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
