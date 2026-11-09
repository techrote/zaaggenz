"""NYQ-003 compatibility entrypoint for the single physical-event convergence bridge.

The original same-model bridge and the newer executable sampler bridge used
different source identities, event-ledger encodings and admission budgets.
They must not independently certify the same request. This adapter retains
the old call surface, but delegates ALL physical-clock, PCM and numerical
qualification to evaluate_sampler_convergence.
"""
from __future__ import annotations

from zaaggenz_contracts.nyquismic import ResourceBudget, SonicSpec, record, require
from .nyquismic import FrozenInput
from .nyquismic_convergence import (
    FrozenConvergencePolicy, LocalConvergenceResult, evaluate_sampler_convergence,
)

METHOD = 'nyq.same-model-sampler-convergence-bridge.v1'


def evaluate_sampler_model_convergence(
    source: FrozenInput, sonic: SonicSpec, *,
    delivery_rate_hz: int = 48000,
    policy: FrozenConvergencePolicy = FrozenConvergencePolicy(),
    budget: ResourceBudget = ResourceBudget(),
    cancelled=None,
) -> LocalConvergenceResult:
    """Legacy call surface; executes the canonical physical-event comparator.

    The canonical physical-event bridge admits a separately declared delivery
    clock when all complete extents are integral and the explicitly bounded FIR
    ratio is supported. The virtual-event clock is never rederived from it.
    """
    record(source, FrozenInput, 'convergence immutable source')
    result = evaluate_sampler_convergence(
        source, sonic, delivery_rate_hz=delivery_rate_hz,
        policy=policy, budget=budget, cancelled=cancelled,
    )
    return LocalConvergenceResult(
        status=result.status, policy=result.policy,
        diagnostics={**result.diagnostics, 'compatibility_entrypoint': METHOD},
        selected_audio=result.selected_audio,
    )
