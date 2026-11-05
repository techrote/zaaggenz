"""NYQ-003 opt-in frozen-rate numerical convergence, NOT a master/export gate.

Every candidate must be evaluated from the same declared immutable sonic,
source, clock, and random-control identities. Delivery conversion is performed
only AFTER the supplied candidate has completed its artistic DSP processing.
This comparison alone is not an analytic oracle or proof of correctness.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from fractions import Fraction

import numpy as np

from zaaggenz_contracts.nyquismic import (
    MAX_EVALUATION_HZ, MAX_REFERENCE_PASSES, ResourceBudget, _Record,
    hash_value, integer, record, require,
)
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from .nyquismic_delivery import DeliveryConversionPolicy, convert_numerical_to_delivery

METHOD = 'nyq.local-frozen-rate-convergence.v1'


@dataclass(frozen=True)
class FrozenConvergencePolicy(_Record):
    """Explicit local rate sequence and *numerical*, not aesthetic tolerances."""
    version: str = METHOD
    rates_hz: tuple[int, ...] = (192000, 384000, 768000)
    relative_rms_limit: float = 0.02
    relative_spectrum_limit: float = 0.02
    relative_transient_limit: float = 0.10

    def __post_init__(self):
        require(self.version == METHOD, 'unsupported local convergence method')
        require(type(self.rates_hz) is tuple and
                3 <= len(self.rates_hz) <= MAX_REFERENCE_PASSES,
                'convergence requires 3..4 exact frozen rates')
        for rate in self.rates_hz:
            integer(rate, 'convergence numerical Hz', 8000, MAX_EVALUATION_HZ)
        require(all(a < b for a, b in zip(self.rates_hz, self.rates_hz[1:])),
                'convergence rates must be strictly increasing')
        for field in ('relative_rms_limit', 'relative_spectrum_limit',
                      'relative_transient_limit'):
            value = getattr(self, field)
            require(type(value) is float and math.isfinite(value) and 0 < value <= 1,
                    'convergence tolerance must be finite float in (0,1]')

    @classmethod
    def from_dict(cls, data):
        from zaaggenz_contracts.nyquismic import require
        require(type(data) is dict and set(data) ==
                {'version', 'rates_hz', 'relative_rms_limit',
                 'relative_spectrum_limit', 'relative_transient_limit'},
                'convergence snapshot requires exact fields')
        require(type(data['rates_hz']) is list, 'convergence rate list must be JSON array')
        return cls(**{**data, 'rates_hz': tuple(data['rates_hz'])})


@dataclass(frozen=True)
class NumericalCandidate:
    """Actual numerical PCM plus the caller's immutable execution identities."""
    numerical_rate_hz: int
    audio: np.ndarray
    source_sha256: str
    sonic_sha256: str
    clock_sha256: str
    random_control_sha256: str


@dataclass(frozen=True)
class LocalConvergenceResult:
    status: str
    policy: FrozenConvergencePolicy
    diagnostics: dict
    # None until all required comparator tests pass. No accidental promotion
    # of an unconverged final candidate as 'production-quality' output.
    selected_audio: np.ndarray | None


def _metrics(a: np.ndarray, b: np.ndarray) -> dict:
    """Compare same-extent delivery-band PCM with three independent measures."""
    # An empty timeline provides no spectral/temporal convergence evidence.
    # Still return finite metrics for an explicit inconclusive outcome rather
    # than allowing NumPy's zero-length FFT to throw an unclassified error.
    if a.shape[0] == 0:
        return {'relative_rms': 0.0, 'relative_spectrum': 0.0,
                'relative_transient': 0.0, 'empty_extent': True}
    # Perfect silence trivially agrees at every numerical rate, even when
    # no actual clock/reconstruction behavior has been exercised. Preserve
    # that equality as a measured null result, not a convergence certificate.
    # Exact silence is used rather than a hidden amplitude threshold.
    null_signal = not np.any(a) and not np.any(b)
    # Compare on a common amplitude scale. An absolute denominator floor
    # (formerly 1e-12) falsely certified 100% errors on quiet but nonzero
    # audio, and squaring the original PCM can underflow for tiny signals.
    # Scaling both operands is dimensionless; it changes no sonic samples.
    scale = max(float(np.max(np.abs(a))), float(np.max(np.abs(b))))
    aa = np.asarray(a, dtype=np.float64) / scale if scale else np.asarray(a, dtype=np.float64)
    bb = np.asarray(b, dtype=np.float64) / scale if scale else np.asarray(b, dtype=np.float64)
    diff = aa - bb
    undefined = []
    def relative(numerator, denominator, name):
        if denominator == 0:
            if numerator != 0:
                undefined.append(name)
                # A finite diagnostic, not a zero-reference convergence pass.
                return 1.0
            return 0.0
        return numerator / denominator
    rms = lambda x: float(np.sqrt(np.mean(x * x))) if x.size else 0.0
    relative_rms = relative(rms(diff), rms(bb), 'rms')
    # Axis zero is physical time; preserve independent channel spectra.
    spectrum_a = np.abs(np.fft.rfft(aa, axis=0))
    spectrum_b = np.abs(np.fft.rfft(bb, axis=0))
    relative_spectrum = relative(
        float(np.linalg.norm(spectrum_a - spectrum_b)),
        float(np.linalg.norm(spectrum_b)), 'spectrum')
    if len(a) > 1:
        transient_a = np.diff(aa, axis=0)
        transient_b = np.diff(bb, axis=0)
        relative_transient = relative(
            float(np.linalg.norm(transient_a - transient_b)),
            float(np.linalg.norm(transient_b)), 'transient')
    else:
        relative_transient = relative_rms
    require(all(math.isfinite(x) for x in
                (relative_rms, relative_spectrum, relative_transient)),
            'convergence produced nonfinite metrics')
    return {'relative_rms': relative_rms,
            'relative_spectrum': relative_spectrum,
            'relative_transient': relative_transient,
            'zero_reference_metrics': tuple(undefined),
            'null_signal': bool(null_signal)}


def evaluate_local_convergence(
    render_candidate, *, source_sha256: str, sonic_sha256: str,
    clock_sha256: str, random_control_sha256: str,
    delivery_rate_hz: int = 48000,
    policy: FrozenConvergencePolicy = FrozenConvergencePolicy(),
    budget: ResourceBudget = ResourceBudget(), cancelled=None,
) -> LocalConvergenceResult:
    """Render and convert 3..4 full-context candidates at frozen rates.

    The callback returns a NumericalCandidate at each requested rate; it must
    actually render that numerical rate from the same physical-time source,
    event/control realization and sonic recipe. Identity validation detects
    declared changes but cannot independently prove that callback's model.
    """
    record(policy, FrozenConvergencePolicy, 'frozen convergence policy')
    record(budget, ResourceBudget, 'convergence resource budget')
    require(callable(render_candidate), 'convergence requires callable renderer')
    require(cancelled is None or callable(cancelled), 'convergence cancellation hook')
    for name, value in (
        ('source', source_sha256), ('sonic', sonic_sha256),
        ('clock', clock_sha256), ('random control', random_control_sha256),
    ):
        hash_value(value, name + ' SHA256')
    integer(delivery_rate_hz, 'delivery rate Hz', 8000, 192000)
    require(policy.rates_hz[0] >= delivery_rate_hz,
            'all evaluation rates must be at least delivery rate')
    # Qualify EVERY frozen conversion ratio before invoking an expensive
    # renderer. Co-prime 192000 -> 44100 requires 15,361 Kaiser taps, far
    # above the default 4,096-tap budget; never render then silently fail.
    from math import gcd
    for rate in policy.rates_hz:
        common = gcd(rate, delivery_rate_hz)
        up, down = delivery_rate_hz // common, rate // common
        if up != down:
            require(24 * max(up, down) + 1 <= budget.max_filter_taps,
                    'frozen convergence rate requires unsupported delivery FIR taps')

    candidate_diagnostics = []
    converted = []
    common_extent = None
    shape = None
    for rate in policy.rates_hz:
        if cancelled is not None and cancelled():
            raise ClockCancelled('convergence cancelled before candidate publication')
        candidate = render_candidate(rate)
        record(candidate, NumericalCandidate, 'numerical candidate')
        require(candidate.numerical_rate_hz == rate,
                'renderer silently changed frozen numerical evaluation rate')
        require((candidate.source_sha256, candidate.sonic_sha256,
                 candidate.clock_sha256, candidate.random_control_sha256) ==
                (source_sha256, sonic_sha256, clock_sha256, random_control_sha256),
                'numerical candidate changed source/sonic/clock/random realization')
        # The renderer can return a caller-owned mutable NumPy buffer.
        # Freeze exactly one private PCM snapshot before validating finiteness
        # or invoking the converter (which runs an external cancel callback).
        # Otherwise a callback can replace the checked samples with different
        # finite PCM while preserving the declared source/sonic identities.
        view = np.asarray(candidate.audio)
        require(view.ndim in (1, 2) and
                (view.ndim == 1 or view.shape[1] in (1, 2)) and
                view.dtype.kind == 'f' and view.size <= budget.max_frames,
                'invalid/oversized numerical candidate PCM')
        audio = np.array(view, copy=True, order='C')
        require(np.isfinite(audio).all(),
                'invalid/oversized numerical candidate PCM')
        extent = Fraction(audio.shape[0], rate)
        if common_extent is None:
            common_extent = extent
        require(extent == common_extent,
                'numerical candidates must cover identical physical-time extent')
        result = convert_numerical_to_delivery(
            audio, rate, delivery_rate_hz,
            policy=DeliveryConversionPolicy(), budget=budget, cancelled=cancelled)
        if shape is None:
            shape = result.audio.shape
        require(result.audio.shape == shape,
                'converted candidates differ in delivery extent or channel shape')
        candidate_diagnostics.append(result.diagnostics)
        converted.append(result.audio)
    comparisons = []
    passed = True
    for a, b in zip(converted, converted[1:]):
        if cancelled is not None and cancelled():
            raise ClockCancelled('convergence cancelled before comparison')
        metrics = _metrics(a, b)
        good = (not metrics.get('empty_extent', False) and
                not metrics.get('null_signal', False) and
                not metrics.get('zero_reference_metrics') and
                metrics['relative_rms'] <= policy.relative_rms_limit and
                metrics['relative_spectrum'] <= policy.relative_spectrum_limit and
                metrics['relative_transient'] <= policy.relative_transient_limit)
        comparisons.append({**metrics, 'within_limits': good})
        passed = passed and good
    # This is agreement of at least three same-model calculations, NOT proof
    # of musical/artistic fidelity, independent analytic truth, or output
    # fitness of the real export path.
    status = 'converged' if passed else 'inconclusive'
    result_audio = converted[-1] if passed else None
    if cancelled is not None and cancelled():
        raise ClockCancelled('convergence cancelled before atomic publication')
    return LocalConvergenceResult(
        status=status, policy=policy, selected_audio=result_audio,
        diagnostics={
            'method': METHOD, 'policy_sha256': policy.sha256,
            'source_sha256': source_sha256, 'sonic_sha256': sonic_sha256,
            'clock_sha256': clock_sha256,
            'random_control_sha256': random_control_sha256,
            'delivery_rate_hz': delivery_rate_hz,
            'rates_hz': list(policy.rates_hz),
            'passes': len(converted),
            'candidate_conversion': candidate_diagnostics,
            'successive_metrics': comparisons,
            'status': status,
            'analytic_oracle_verified': False,
            'product_export_verified': False,
        },
    )
