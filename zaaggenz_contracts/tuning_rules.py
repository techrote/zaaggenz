"""Shared frozen-v1 tuning invariants used by schemas and executable consumers."""
import math

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
    """Match Draft 2020-12 integer-number semantics for the frozen v1 domain."""
    if type(value) is int:
        integer = value
    elif type(value) is float and math.isfinite(value) and value.is_integer():
        integer = int(value)
    else:
        return False
    return FORMAL_PERIOD_MIN <= integer <= FORMAL_PERIOD_MAX and integer != 0


def formal_period_degrees_value(value):
    """Return the exact integer value after shared validation, without mutating input."""
    if not valid_formal_period_degrees(value):
        raise ValueError('invalid formal period degrees')
    return int(value)


def formal_period_degrees_description():
    return f'in [{FORMAL_PERIOD_MIN}, -1] or [1, {FORMAL_PERIOD_MAX}]'
