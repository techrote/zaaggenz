"""NYQ-003 opt-in frozen-rate numerical convergence, NOT a master/export gate.

Every candidate must be evaluated from the same declared immutable sonic,
source, clock, and random-control identities. Delivery conversion is performed
only AFTER the supplied candidate has completed its artistic DSP processing.
This comparison alone is not an analytic oracle or proof of correctness.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from fractions import Fraction

import numpy as np

from zaaggenz_contracts import digest
from zaaggenz_contracts.nyquismic import (
    MAX_EVALUATION_HZ, MAX_REFERENCE_PASSES, ResourceBudget, _Record,
    hash_value, integer, record, require,
)
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from .nyquismic_delivery import (
    METHOD as DIRECT_DELIVERY_METHOD, DeliveryConversionPolicy,
    admit_delivery_stages, convert_numerical_to_delivery,
)

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
    # A single delivery-frame comparison has no temporal derivative, so its
    # "transient" metric would merely repeat RMS and its one-bin FFT cannot
    # discriminate folded frequencies. Retain diagnostics, not qualification.
    insufficient_extent = a.shape[0] < 2
    # Perfect silence trivially agrees at every numerical rate, even when
    # no actual clock/reconstruction behavior has been exercised. Preserve
    # that equality as a measured null result, not a convergence certificate.
    # Exact silence is used rather than a hidden amplitude threshold.
    null_signal = not np.any(a) and not np.any(b)
    # A stereo comparison needs an independent amplitude reference for EACH
    # channel. A global scale and pooled RMS/spectrum can conceal a complete
    # loss or phase error in a quiet channel beside a loud one. In particular,
    # squaring a 1e-250 quiet channel after dividing only by the loud channel
    # can underflow its evidence to zero. Normalize channels independently and
    # publish the WORST relative channel metric, never a volume-weighted mean.
    source_a = np.asarray(a, dtype=np.float64)
    source_b = np.asarray(b, dtype=np.float64)
    if source_a.ndim == 1:
        source_a, source_b = source_a[:, None], source_b[:, None]
    scales = np.maximum(np.max(np.abs(source_a), axis=0),
                        np.max(np.abs(source_b), axis=0))
    scales[scales == 0] = 1.0  # Both signals truly silent in this channel.
    aa, bb = source_a / scales, source_b / scales
    diff = aa - bb
    undefined = []
    def relative(numerators, denominators, name):
        ratios = []
        for channel, (num, den) in enumerate(zip(numerators, denominators)):
            if den == 0:
                if num != 0:
                    undefined.append(name if len(denominators) == 1
                                     else f'{name}_ch{channel}')
                    ratios.append(1.0)  # Diagnostic, NEVER an admission.
                else:
                    ratios.append(0.0)
            else:
                ratios.append(float(num / den))
        return max(ratios)
    rms = lambda x: np.sqrt(np.mean(x * x, axis=0))
    relative_rms = relative(rms(diff), rms(bb), 'rms')
    # Axis zero is physical time; keep each channel's spectrum independent.
    spectrum_a = np.abs(np.fft.rfft(aa, axis=0))
    spectrum_b = np.abs(np.fft.rfft(bb, axis=0))
    relative_spectrum = relative(
        np.linalg.norm(spectrum_a - spectrum_b, axis=0),
        np.linalg.norm(spectrum_b, axis=0), 'spectrum')
    if len(a) > 1:
        transient_a = np.diff(aa, axis=0)
        transient_b = np.diff(bb, axis=0)
        # Constant channels carry no derivative information at either rate.
        # Their zero transient residual is NOT independent validation of
        # numerical agreement: RMS and a DC-only FFT are the same scalar
        # assertion in different representations. Never certify such a
        # channel on three nominal metrics when only one is informative.
        no_transient_evidence = tuple(
            channel for channel in range(aa.shape[1])
            if not np.any(transient_a[:, channel]) and
               not np.any(transient_b[:, channel])
        )
        relative_transient = relative(
            np.linalg.norm(transient_a - transient_b, axis=0),
            np.linalg.norm(transient_b, axis=0), 'transient')
    else:
        no_transient_evidence = tuple(range(aa.shape[1]))
        relative_transient = relative_rms
    require(all(math.isfinite(x) for x in
                (relative_rms, relative_spectrum, relative_transient)),
            'convergence produced nonfinite metrics')
    return {'relative_rms': relative_rms,
            'relative_spectrum': relative_spectrum,
            'relative_transient': relative_transient,
            'zero_reference_metrics': tuple(undefined),
            'null_signal': bool(null_signal),
            'insufficient_extent': bool(insufficient_extent),
            'no_transient_evidence_channels': no_transient_evidence}


def evaluate_local_convergence(
    render_candidate, *, source_sha256: str, sonic_sha256: str,
    clock_sha256: str, random_control_sha256: str,
    delivery_rate_hz: int = 48000,
    delivery_policy: DeliveryConversionPolicy = DeliveryConversionPolicy(),
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
    record(delivery_policy, DeliveryConversionPolicy, 'frozen delivery conversion policy')
    record(budget, ResourceBudget, 'convergence resource budget')
    require(callable(render_candidate), 'convergence requires callable renderer')
    require(cancelled is None or callable(cancelled), 'convergence cancellation hook')
    # This bound controls actual comparison executions, not merely the
    # contract's maximum policy length. Reject before calling a renderer.
    require(len(policy.rates_hz) <= budget.max_reference_passes,
            'convergence reference-pass budget exceeded')
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
        if delivery_policy.method == DIRECT_DELIVERY_METHOD:
            # Preserve the existing direct-policy refusal and default behavior.
            common = gcd(rate, delivery_rate_hz)
            up, down = delivery_rate_hz // common, rate // common
            if up != down:
                require(24 * max(up, down) + 1 <= budget.max_filter_taps,
                        'frozen convergence rate requires unsupported delivery FIR taps')
        else:
            # Qualify every stage BEFORE the expensive numerical renderer.
            admit_delivery_stages(rate, delivery_rate_hz,
                                  policy=delivery_policy, budget=budget)

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
            policy=delivery_policy, budget=budget, cancelled=cancelled)
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
                not metrics.get('insufficient_extent', False) and
                not metrics.get('null_signal', False) and
                not metrics.get('no_transient_evidence_channels') and
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
            'delivery_method': delivery_policy.method,
            'delivery_policy_sha256': delivery_policy.sha256,
            'rates_hz': list(policy.rates_hz),
            'passes': len(converted),
            'candidate_conversion': candidate_diagnostics,
            'successive_metrics': comparisons,
            'status': status,
            'analytic_oracle_verified': False,
            'product_export_verified': False,
        },
    )


def evaluate_sampler_convergence(
    source, sonic, *, delivery_rate_hz: int | None = None,
    delivery_policy: DeliveryConversionPolicy = DeliveryConversionPolicy(),
    policy: FrozenConvergencePolicy = FrozenConvergencePolicy(),
    budget: ResourceBudget = ResourceBudget(), cancelled=None,
) -> LocalConvergenceResult:
    """Execute the real physical-event sampler for every local comparator.

    No external NYQ-004 clock modulation or product graph/export integration.
    Freeze the original PCM and verify *actual* exact event roots, including
    reset epoch and crossing, rather than trusting a callback's declared hash.
    """
    from zaaggenz_contracts.nyquismic import SonicSpec
    from .nyquismic import FrozenInput, SamplerPlan, sampler_evaluation

    require(type(source) is FrozenInput, 'convergence requires immutable source PCM')
    record(sonic, SonicSpec, 'convergence sonic spec')
    record(policy, FrozenConvergencePolicy, 'convergence policy')
    record(delivery_policy, DeliveryConversionPolicy, 'convergence delivery policy')
    record(budget, ResourceBudget, 'convergence budget')
    require(cancelled is None or callable(cancelled),
            'convergence cancellation hook must be callable')
    require(sonic.mode == 'sampler', 'local convergence cannot execute warp/cascade')
    require(not sonic.clock.routes and sonic.clock.quantizer.policy == 'none'
            and sonic.clock.jitter.model == 'none',
            'unadapted NYQ-004 virtual-clock controls are not executable')
    asset = source.asset.to_dict()
    require(asset['channels'] == sonic.channels, 'source/channel mismatch')
    if delivery_rate_hz is None:
        delivery_rate_hz = source.sample_rate_hz
    integer(delivery_rate_hz, 'sampler convergence delivery rate Hz', 8000, 192000)
    delivered_frames = Fraction(asset['frame_count'] * delivery_rate_hz,
                                source.sample_rate_hz)
    require(delivered_frames.denominator == 1,
            'sampler convergence requires integral delivery extent')
    require(delivered_frames.numerator * sonic.channels <= budget.max_frames,
            'sampler convergence delivery frame budget exceeded')
    require(len(policy.rates_hz) <= budget.max_reference_passes,
            'convergence pass budget exceeded')
    # Align complete physical extent at every declared numerical rate.
    # No silent frame rounding and no discounted region/frame admission.
    frames_by_rate = {}
    for rate in policy.rates_hz:
        frames = Fraction(asset['frame_count'] * rate, source.sample_rate_hz)
        require(frames.denominator == 1,
                'sampler convergence requires integral numerical extents')
        require(frames.numerator * sonic.channels <= budget.max_frames,
                'sampler convergence numerical frame budget exceeded')
        frames_by_rate[rate] = frames.numerator
        if delivery_policy.method != DIRECT_DELIVERY_METHOD:
            # Validate exact intermediate and final extents before capture.
            admit_delivery_stages(rate, delivery_rate_hz, policy=delivery_policy,
                                  budget=budget, frames=frames.numerator)

    hashes = (source.asset.sha256, sonic.sonic_sha256, sonic.clock.sha256)
    random_hash = digest({'domain': 'nyq003.no-external-control-v1',
                          'clock_sha256': hashes[2]})
    ledgers, counts, pcm_hashes = [], [], []

    def actual_candidate(rate):
        if cancelled is not None and cancelled():
            raise ClockCancelled('sampler convergence cancelled before pass')
        plan = SamplerPlan.prepare(
            source, sonic, sampler_evaluation(rate, budget),
            frame_count=frames_by_rate[rate], cancelled=cancelled,
            delivery_rate_hz=delivery_rate_hz)
        # Event float timestamps are diagnostic only. Use the unrounded
        # Fraction/Decimal80 coordinate as the custody identity.
        ledger = hashlib.sha256(b'nyq003.physical-events.v1\n')
        for i, event in enumerate(plan.events):
            if i % 256 == 0 and cancelled is not None and cancelled():
                raise ClockCancelled('sampler convergence cancelled in event ledger')
            root = plan.clock.event_coordinate(i)
            ledger.update(f'{event.index}|{event.epoch}|{event.crossing}|{root}\n'.encode('ascii'))
        event_hash = ledger.hexdigest()
        require(not ledgers or event_hash == ledgers[0],
                'physical event ledger changed with numerical evaluation rate')
        ledgers.append(event_hash)
        counts.append(len(plan.events))
        numeric = plan.render(cancelled=cancelled)
        pcm_hashes.append(numeric.diagnostics['pcm_sha256'])
        return NumericalCandidate(rate, numeric.audio, *hashes, random_hash)

    result = evaluate_local_convergence(
        actual_candidate, source_sha256=hashes[0], sonic_sha256=hashes[1],
        clock_sha256=hashes[2], random_control_sha256=random_hash,
        delivery_rate_hz=delivery_rate_hz, delivery_policy=delivery_policy,
        policy=policy, budget=budget, cancelled=cancelled)
    diagnostics = {
        **result.diagnostics,
        'sampler_bridge': 'nyq003.physical-event-frozen-convergence.v1',
        'exact_event_ledger_sha256': ledgers[0],
        'event_ledger_sha256_by_rate': ledgers,
        'event_counts_by_rate': counts,
        'numerical_pcm_sha256_by_rate': pcm_hashes,
        'frozen_source_pcm_sha256': asset['content_sha256'],
        'physical_event_geometry_equal': True,
        'nyq004_adapter_qualified': False,
    }
    return LocalConvergenceResult(result.status, result.policy,
                                  diagnostics, result.selected_audio)
