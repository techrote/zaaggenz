"""Exact step-tempo time map. No renderer rounding policy is silently replaced."""
from fractions import Fraction
from .model import ContractError, fraction


def _checked(time_map):
    from .validation import validate
    validate(time_map, 'TimeMap')
    return [(fraction(v['beat']), fraction(v['bpm'])) for v in time_map['tempo_segments']]


def beat_to_seconds(time_map, beat):
    segments = _checked(time_map)
    b = fraction(beat)
    if b < 0:
        return b * 60 / segments[0][1]
    total = Fraction(0)
    for i, (start, bpm) in enumerate(segments):
        end = segments[i + 1][0] if i + 1 < len(segments) else b
        if b <= start:
            break
        total += (min(b, end) - start) * 60 / bpm
    return total


def beat_to_sample(time_map, beat):
    # Round once, using ties-to-even for positive AND negative values.
    return int(time_map['origin_sample']) + round(beat_to_seconds(time_map, beat) * int(time_map['sample_rate_hz']))


def sample_to_beat(time_map, sample):
    segments = _checked(time_map)
    if type(sample) is not int or abs(sample) > 2**53 - 1:
        raise ContractError('sample must be a safe integer')
    seconds = Fraction(sample - int(time_map['origin_sample']), int(time_map['sample_rate_hz']))
    if seconds < 0:
        return seconds * segments[0][1] / 60
    for i, (start, bpm) in enumerate(segments):
        if i + 1 == len(segments):
            return start + seconds * bpm / 60
        span = (segments[i + 1][0] - start) * 60 / bpm
        if seconds <= span:
            return start + seconds * bpm / 60
        seconds -= span
    raise AssertionError('validated map has no segment')
