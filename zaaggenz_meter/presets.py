"""Original synthetic clock fixtures; not genre or listener-preference claims."""
from __future__ import annotations
from .model import MeterPlan, VERSION


def nested_124_cross32(*, end_beat='64/1'):
    windows = [
        {'start_beat': '0/1', 'end_beat': '24/1', 'reset_on_entry': True},
        {'start_beat': '32/1', 'end_beat': end_beat, 'reset_on_entry': True},
    ]
    def nested(identifier, period, relation):
        return {'id': identifier, 'kind': 'nested', 'period_beats': period, 'phase_beats': '0/1',
                'relation': relation, 'active_windows': windows, 'reset_beats': ['16/1', '48/1']}
    clocks = [
        nested('articulation', '1/4', None),
        nested('bounce', '1/2', {'reference_id': 'articulation', 'period_numerator': 2, 'period_denominator': 1}),
        nested('sway', '1/1', {'reference_id': 'bounce', 'period_numerator': 2, 'period_denominator': 1}),
        {'id': 'cross-3-2', 'kind': 'cross', 'period_beats': '2/3', 'phase_beats': '0/1',
         'relation': {'reference_id': 'sway', 'pulses': 3, 'reference_cycles': 2},
         'active_windows': [{'start_beat': '0/1', 'end_beat': end_beat, 'reset_on_entry': True}], 'reset_beats': []},
        {'id': 'long-cycle', 'kind': 'cycle', 'period_beats': '5/4', 'phase_beats': '1/8', 'relation': None,
         'active_windows': [{'start_beat': '0/1', 'end_beat': end_beat, 'reset_on_entry': True}], 'reset_beats': ['40/1']},
    ]
    return MeterPlan({'format': 'zaaggenz-meter-plan', 'version': VERSION, 'id': 'synthetic-124-cross32',
                      'description': 'Exact 1:2:4 nested articulation/bounce/sway clocks plus independent 3:2 and longer-cycle controls, with a deliberate 8-beat nested re-entry gap.',
                      'end_beat': end_beat, 'stable_clock_id': 'sway', 'clocks': clocks,
                      'bindings': [
                          {'id': 'sway-anchor', 'clock_id': 'sway', 'layer': 'body', 'control': 'accent_db', 'values': [-3.0], 'stability': 'anchor'},
                          {'id': 'articulation-density', 'clock_id': 'articulation', 'layer': 'synthline', 'control': 'density_per_beat', 'values': [4.0, 8.0, 4.0, 12.0], 'stability': 'variable'},
                          {'id': 'cross-brightness', 'clock_id': 'cross-3-2', 'layer': 'aux', 'control': 'brightness_hz', 'values': [1800.0, 3200.0, 5200.0], 'stability': 'variable'},
                          {'id': 'cycle-roughness', 'clock_id': 'long-cycle', 'layer': 'exciter', 'control': 'roughness_fraction', 'values': [0.2, 0.5, 0.35], 'stability': 'variable'},
                      ]})
