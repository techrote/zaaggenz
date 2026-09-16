"""Shared semantic rules for executable multiband crossover configurations."""
from __future__ import annotations

import math

from .model import ContractError

MULTIBAND_TYPE_ID = 'core.multiband_gain.v1'
MULTIBAND_MIN_CROSSOVER_HZ = 20.0
MULTIBAND_NYQUIST_FRACTION = 0.49


def validate_multiband_crossovers(crossovers, sample_rate_hz=None):
    """Return validated crossover values, optionally bound to an actual sample rate.

    DSPNodeSpec validation can enforce the cross-parameter ordering without a sample
    rate. RenderRecipe and executable DSP consumers must supply the actual rate so
    the complete v1 feasibility invariant is checked before any filtering occurs.
    """
    try:
        if len(crossovers) != 3:
            raise ContractError('multiband crossovers require low_xover_hz, mid_xover_hz and high_xover_hz')
        low, mid, high = (float(v) for v in crossovers)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContractError('multiband crossovers must be finite numeric Hz values') from exc

    if not all(math.isfinite(v) for v in (low, mid, high)):
        raise ContractError('multiband crossovers must be finite numeric Hz values')
    if low < MULTIBAND_MIN_CROSSOVER_HZ:
        raise ContractError('low_xover_hz must be >= 20 Hz')
    if not low < mid:
        raise ContractError('mid_xover_hz must be greater than low_xover_hz')
    if not mid < high:
        raise ContractError('high_xover_hz must be greater than mid_xover_hz')

    if sample_rate_hz is not None:
        try:
            sample_rate = float(sample_rate_hz)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ContractError('sample_rate_hz must be a finite positive value') from exc
        if not math.isfinite(sample_rate) or sample_rate <= 0:
            raise ContractError('sample_rate_hz must be a finite positive value')
        limit = MULTIBAND_NYQUIST_FRACTION * sample_rate
        if not high < limit:
            raise ContractError(
                f'high_xover_hz must be < 0.49 * sample_rate_hz ({limit:g} Hz at {sample_rate:g} Hz)'
            )

    return low, mid, high
