"""Original phrase-role fixtures; numbers are phrase labels, not metre numerators."""
from __future__ import annotations
from .model import PhraseRolePlan, VERSION


def _event(offset, degree, *, duration='1/2', gain=-18., roll=0):
    return {'offset': offset, 'duration_beats': duration, 'degree': degree,
            'detune_cents': 0., 'gain_db': float(gain), 'roll_density': int(roll)}


def template_1234_5555(*, placement_seed='0', content_seed='0'):
    stable = [_event('0/1', 0, duration='1/1'), _event('1/1', 2, duration='1/1'),
              _event('2/1', 4, duration='1/1'), _event('3/1', 7, duration='1/1')]
    def stable_window(identifier, role, start):
        return {'id': identifier, 'role': role, 'start_beat': f'{start}/1', 'end_beat': f'{start+4}/1',
                'placements': [{'offset': '0/1', 'weight': 1}],
                'variants': [{'id': 'stable-1234', 'weight': 1, 'source_family': 'locked-bloom', 'events': stable}],
                'destination': None}
    variation = {
        'id': 'bar4-permission-window', 'role': 'vary', 'start_beat': '12/1', 'end_beat': '16/1',
        'placements': [{'offset': '0/1', 'weight': 3}, {'offset': '1/4', 'weight': 2}, {'offset': '1/2', 'weight': 1}],
        'variants': [
            {'id': 'fill-rise', 'weight': 3, 'source_family': 'locked-bloom-rise',
             'events': [_event('0/1', 4, roll=4), _event('1/1', 7, roll=4), _event('2/1', 9, roll=8)]},
            {'id': 'fill-fall', 'weight': 3, 'source_family': 'locked-bloom-fall',
             'events': [_event('0/1', 9, roll=4), _event('1/1', 7, roll=4), _event('2/1', 4, roll=8)]},
            {'id': 'fill-neighbour', 'weight': 2, 'source_family': 'locked-bloom-neighbour',
             'events': [_event('0/1', 7, roll=4), _event('1/1', 9, roll=4), _event('2/1', 7, roll=8)]},
            {'id': 'no-fill', 'weight': 1, 'source_family': 'silence', 'events': []}
        ],
        'destination': {'beat': '15/1', 'duration_beats': '1/1', 'degree': 0, 'detune_cents': 0.,
                        'gain_db': -18., 'source_family': 'locked-bloom'}
    }
    return PhraseRolePlan({
        'format': 'zaaggenz-phrase-role-plan', 'version': VERSION, 'id': 'template-1234-1234-1234-5555',
        'description': 'Four-bar role template: three stable 1234 bars then one predictable variation/return permission window; 5555 is a phrase-function label, not quintuple metre.',
        'end_beat': '16/1', 'placement_seed': str(placement_seed), 'content_seed': str(content_seed),
        'windows': [stable_window('bar1-establish', 'establish', 0), stable_window('bar2-repeat', 'repeat', 4),
                    stable_window('bar3-reinforce', 'reinforce', 8), variation]
    })
