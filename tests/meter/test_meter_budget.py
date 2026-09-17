from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app'))

from zaaggenz_meter import (
    CONTROLS,
    LAYERS,
    MAX_CONTROL_ROWS,
    MAX_TICKS_PER_CLOCK,
    MAX_TOTAL_TICKS,
    MeterError,
    MeterPlan,
    generate_ticks,
    work_estimate,
)


def window(start='0/1', stop='1/1', reset=True):
    return {'start_beat': start, 'end_beat': stop, 'reset_on_entry': reset}


def cycle_clock(clock_id='clock', *, period='1/4', phase='0/1', windows=None, resets=None):
    return {
        'id': clock_id,
        'kind': 'cycle',
        'period_beats': period,
        'phase_beats': phase,
        'relation': None,
        'active_windows': [window()] if windows is None else windows,
        'reset_beats': [] if resets is None else resets,
    }


def binding(index, clock_id='clock'):
    control = CONTROLS[index % len(CONTROLS)]
    return {
        'id': f'b{index}',
        'clock_id': clock_id,
        'layer': LAYERS[index % len(LAYERS)],
        'control': control,
        'values': [0.0],
        'stability': 'anchor',
    }


def plan(*, end='1/1', clocks=None, bindings=None, stable='clock'):
    return {
        'format': 'zaaggenz-meter-plan',
        'version': '1.0.0',
        'id': 'budget-fixture',
        'description': 'bounded-cardinality regression fixture',
        'end_beat': end,
        'stable_clock_id': stable,
        'clocks': [cycle_clock()] if clocks is None else clocks,
        'bindings': [] if bindings is None else bindings,
    }


class MeterBudgetTests(unittest.TestCase):
    def test_smallest_legal_period_is_rejected_before_expansion(self):
        data = plan(clocks=[cycle_clock(period='1/9999999999999')])
        with self.assertRaisesRegex(MeterError, r'implied tick count 9999999999999 exceeds'):
            MeterPlan(data)

    def test_contract_maximum_extent_is_rejected_by_exact_arithmetic(self):
        data = plan(end='4096/1', clocks=[cycle_clock(
            period='1/9999999999999',
            windows=[window('0/1', '4096/1')],
        )])
        with self.assertRaisesRegex(MeterError, r'clock clock: implied tick count .* exceeds'):
            MeterPlan(data)

    def test_per_clock_exact_limit_and_limit_plus_one(self):
        accepted = MeterPlan(plan(clocks=[cycle_clock(period=f'1/{MAX_TICKS_PER_CLOCK}')]))
        estimate = work_estimate(accepted)
        self.assertEqual(estimate['clock_tick_counts']['clock'], MAX_TICKS_PER_CLOCK)
        self.assertEqual(estimate['total_ticks'], MAX_TICKS_PER_CLOCK)

        data = plan(clocks=[cycle_clock(period=f'1/{MAX_TICKS_PER_CLOCK + 1}')])
        with self.assertRaisesRegex(MeterError, rf'implied tick count {MAX_TICKS_PER_CLOCK + 1} exceeds'):
            MeterPlan(data)

    def test_sixty_fourth_notes_remain_valid_over_maximum_plan_extent(self):
        # One tick every 1/16 quarter-note beat is a 64th-note clock.
        accepted = MeterPlan(plan(
            end='4096/1',
            clocks=[cycle_clock(period='1/16', windows=[window('0/1', '4096/1')])],
        ))
        self.assertEqual(work_estimate(accepted)['total_ticks'], MAX_TICKS_PER_CLOCK)

    def test_zero_and_one_tick_boundaries(self):
        zero = MeterPlan(plan(clocks=[cycle_clock(
            period='1/1', phase='1/2', windows=[window('0/1', '1/4')]
        )]))
        self.assertEqual(work_estimate(zero)['total_ticks'], 0)
        self.assertEqual(generate_ticks(zero, 'clock'), [])

        one = MeterPlan(plan(clocks=[cycle_clock(
            period='1/1', phase='0/1', windows=[window('0/1', '1/2')]
        )]))
        self.assertEqual(work_estimate(one)['total_ticks'], 1)
        self.assertEqual(len(generate_ticks(one, 'clock')), 1)

    def test_plan_total_exact_limit_and_aggregate_limit(self):
        clocks = [
            cycle_clock('a', period=f'1/{MAX_TICKS_PER_CLOCK}'),
            cycle_clock('b', period=f'1/{MAX_TICKS_PER_CLOCK}'),
        ]
        accepted = MeterPlan(plan(clocks=clocks, stable='a'))
        self.assertEqual(work_estimate(accepted)['total_ticks'], MAX_TOTAL_TICKS)

        too_many = deepcopy(clocks)
        too_many.append(cycle_clock('c', period=f'1/{MAX_TICKS_PER_CLOCK}'))
        with self.assertRaisesRegex(MeterError, rf'plan implied tick count .* exceeds executable limit {MAX_TOTAL_TICKS}'):
            MeterPlan(plan(clocks=too_many, stable='a'))

    def test_control_schedule_exact_limit_and_one_row_over(self):
        exact = MeterPlan(plan(
            clocks=[cycle_clock(period=f'1/{MAX_TICKS_PER_CLOCK}')],
            bindings=[binding(i) for i in range(4)],
        ))
        self.assertEqual(work_estimate(exact)['control_schedule_rows'], MAX_CONTROL_ROWS)

        # 52,429 ticks * 5 bindings = 262,145, exactly one above the budget.
        one_over_ticks = MAX_CONTROL_ROWS // 5 + 1
        self.assertEqual(one_over_ticks * 5, MAX_CONTROL_ROWS + 1)
        data = plan(
            clocks=[cycle_clock(period=f'1/{one_over_ticks}')],
            bindings=[binding(i) for i in range(5)],
        )
        with self.assertRaisesRegex(MeterError, rf'control schedule row count {MAX_CONTROL_ROWS + 1} exceeds'):
            MeterPlan(data)

    def test_reset_and_reentry_segmentation_is_counted_exactly(self):
        data = plan(
            end='5/1',
            clocks=[cycle_clock(
                period='1/3',
                phase='1/6',
                windows=[window('0/1', '2/1', False), window('3/1', '5/1', True)],
                resets=['1/1', '4/1'],
            )],
        )
        accepted = MeterPlan(data)
        estimate = work_estimate(accepted)
        rows = generate_ticks(accepted, 'clock')
        self.assertEqual(estimate['clock_tick_counts']['clock'], len(rows))
        self.assertEqual(estimate['total_ticks'], len(rows))
        self.assertEqual(len({row['phase_segment_index'] for row in rows}), 4)

    def test_64_clock_64_window_128_binding_adversary_fails_preflight(self):
        windows = [window(f'{i}/1', f'{i + 1}/1', True) for i in range(64)]
        clocks = [cycle_clock(f'c{i}', period='1/1024', windows=deepcopy(windows)) for i in range(64)]
        bindings = []
        for i in range(128):
            item = binding(i, 'c0')
            bindings.append(item)
        data = plan(end='64/1', clocks=clocks, bindings=bindings, stable='c0')
        with self.assertRaisesRegex(MeterError, r'plan implied tick count .* exceeds executable limit'):
            MeterPlan(data)

    def test_work_estimate_is_exact_integer_and_reports_limits(self):
        accepted = MeterPlan(plan(
            end='3/1',
            clocks=[cycle_clock(period='2/3', windows=[window('0/1', '3/1')])],
            bindings=[binding(0)],
        ))
        estimate = work_estimate(accepted)
        self.assertEqual(estimate['clock_tick_counts'], {'clock': 5})
        self.assertEqual(estimate['total_ticks'], 5)
        self.assertEqual(estimate['control_schedule_rows'], 5)
        self.assertEqual(estimate['limits'], {
            'ticks_per_clock': MAX_TICKS_PER_CLOCK,
            'total_ticks': MAX_TOTAL_TICKS,
            'control_schedule_rows': MAX_CONTROL_ROWS,
        })
        self.assertTrue(all(type(value) is int for value in (
            estimate['total_ticks'], estimate['control_schedule_rows'],
            *estimate['clock_tick_counts'].values(),
        )))


if __name__ == '__main__':
    unittest.main(verbosity=2)
