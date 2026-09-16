"""Shared frozen-v1 tuning invariants used by schemas and executable consumers."""

FORMAL_PERIOD_MIN = -256
FORMAL_PERIOD_MAX = 256


def formal_period_degrees_schema():
    """Draft 2020-12 fragment for an executable v1 formal period."""
    return {
        'type': 'integer',
        'minimum': FORMAL_PERIOD_MIN,
        'maximum': FORMAL_PERIOD_MAX,
        'not': {'const': 0},
    }


def valid_formal_period_degrees(value):
    """True exactly for formal periods representable by frozen TuningSpec v1."""
    return (
        type(value) is int
        and FORMAL_PERIOD_MIN <= value <= FORMAL_PERIOD_MAX
        and value != 0
    )


def formal_period_degrees_description():
    return f'in [{FORMAL_PERIOD_MIN}, -1] or [1, {FORMAL_PERIOD_MAX}]'
