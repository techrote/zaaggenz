"""NYQ-003 opt-in same-model bridge from accepted NYQ-002 sampler to local convergence.

Local engineering evaluation, not graph/rack/export integration. Every rate
executes the same immutable PCM, sonic recipe and physical clock.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib

from zaaggenz_contracts import digest
from zaaggenz_contracts.nyquismic import (
    ResourceBudget, SonicSpec, record, require,
)
from zaaggenz_contracts.nyquismic_clock import ClockCancelled
from .nyquismic import FrozenInput, SamplerPlan, sampler_evaluation
from .nyquismic_convergence import (
    FrozenConvergencePolicy, LocalConvergenceResult, NumericalCandidate,
    evaluate_local_convergence,
)

METHOD = 'nyq.same-model-sampler-convergence-bridge.v1'


def evaluate_sampler_model_convergence(
    source: FrozenInput, sonic: SonicSpec, *,
    delivery_rate_hz: int = 48000,
    policy: FrozenConvergencePolicy = FrozenConvergencePolicy(),
    budget: ResourceBudget = ResourceBudget(),
    cancelled=None,
) -> LocalConvergenceResult:
    """Compare real sampler executions on exactly aligned physical-time grids.

    The complete physical event ledger is hashed and compared between passes.
    Numerical agreement cannot substitute for an independent analytic oracle
    or prove correctness of the eventual product export.
    """
    record(source, FrozenInput, 'convergence immutable source')
    record(sonic, SonicSpec, 'convergence sonic specification')
    record(policy, FrozenConvergencePolicy, 'convergence policy')
    record(budget, ResourceBudget, 'convergence resource budget')
    require(cancelled is None or callable(cancelled), 'convergence cancellation hook')
    require(sonic.mode == 'sampler', 'same-model comparison requires sampler mode')
    asset = source.asset.to_dict()
    require(asset['channels'] == sonic.channels, 'convergence source/channel mismatch')
    # Until NYQ-004 is integrated, do not advertise executed modulated clocks.
    require(not sonic.clock.routes and sonic.clock.jitter.model == 'none' and
            sonic.clock.quantizer.policy == 'none',
            'same-model bridge does not execute routed/jittered/quantized clocks')
    frame_counts = {}
    for rate in policy.rates_hz:
        count = Fraction(asset['frame_count'] * rate, source.sample_rate_hz)
        require(count.denominator == 1, 'evaluation grid must exactly cover source duration')
        require(count.numerator * sonic.channels <= budget.max_frames,
                'evaluation extent exceeds frame budget')
        frame_counts[rate] = count.numerator

    source_hash = asset['content_sha256']
    sonic_hash = sonic.sha256
    clock_hash = sonic.clock.sha256
    random_hash = digest({
        'domain': METHOD, 'random': 'none', 'clock_sha256': clock_hash,
    })
    event_sha = None
    event_count = None
    render_hashes = []

    def render(rate: int) -> NumericalCandidate:
        nonlocal event_sha, event_count
        if cancelled is not None and cancelled():
            raise ClockCancelled('same-model sampler cancelled before execution')
        plan = SamplerPlan.prepare(
            source, sonic, sampler_evaluation(rate, budget),
            frame_count=frame_counts[rate], cancelled=cancelled,
        )
        # Versioned exact event ledger: the rounded float display timestamp
        # cannot distinguish distinct Decimal80/exact-rational crossings.
        ledger = hashlib.sha256()
        ledger.update(b'nyq.exact-physical-event-ledger.v1\0')
        for i, event in enumerate(plan.events):
            if (i & 255) == 0 and cancelled is not None and cancelled():
                raise ClockCancelled('same-model sampler event ledger cancelled')
            coordinate = plan.clock.event_coordinate(i)
            if isinstance(coordinate, Fraction):
                timestamp = f'r:{coordinate.numerator}/{coordinate.denominator}'
            else:
                # ClockPlan's nonrational roots are Decimal80, never binary64.
                timestamp = 'd:' + str(coordinate)
            ledger.update(
                f'{event.index}:{event.epoch}:{event.crossing}:{timestamp}\n'.encode('ascii')
            )
        current = ledger.hexdigest()
        if event_sha is None:
            event_sha, event_count = current, len(plan.events)
        require(current == event_sha and len(plan.events) == event_count,
                'evaluation rate changed the physical event ledger')
        rendered = plan.render(cancelled=cancelled)
        render_hashes.append(rendered.render_sha256)
        return NumericalCandidate(
            rate, rendered.audio, source_hash, sonic_hash, clock_hash, random_hash,
        )

    result = evaluate_local_convergence(
        render, source_sha256=source_hash, sonic_sha256=sonic_hash,
        clock_sha256=clock_hash, random_control_sha256=random_hash,
        delivery_rate_hz=delivery_rate_hz, policy=policy,
        budget=budget, cancelled=cancelled,
    )
    return LocalConvergenceResult(
        status=result.status, policy=result.policy,
        diagnostics={
            **result.diagnostics, 'sampler_bridge_method': METHOD,
            'event_ledger_sha256': event_sha, 'event_count': event_count,
            'event_ledger_method': 'nyq.exact-physical-event-ledger.v1',
            'sampler_render_sha256_by_rate': dict(zip(policy.rates_hz, render_hashes)),
            'event_schedule_verified_across_rates': True,
            'same_model_execution': 'accepted-NYQ-002-SamplerPlan',
            'analytic_oracle_verified': False, 'product_export_verified': False,
        },
        selected_audio=result.selected_audio,
    )
