from __future__ import annotations
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app'))

from zaaggenz_contracts import Contract
from zaaggenz_contracts.legacy import envelope
from zaaggenz_contracts.model import fraction
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_meter import (MeterError, MeterPlan, nested_124_cross32, clock_relation,
                            generate_ticks, generate_all_ticks, control_schedule,
                            periodicity_overlay, feature_flux_samples, overlay_feature_flux)


def time_map(sr=44100, origin=17, tempos=None):
    tempos = [('0/1', '137/1')] if tempos is None else tempos
    return Contract(envelope('TimeMap', sample_rate_hz=sr, origin_sample=origin,
                             beat_unit='quarter_note', rounding='nearest_ties_even',
                             tempo_segments=[{'beat': beat, 'bpm': bpm} for beat, bpm in tempos],
                             meter_segments=[{'beat': '0/1', 'numerator': 4, 'denominator': 4}]))


def beats(rows):
    return [fraction(row['beat']) for row in rows]


def row(plan, clock_id):
    return next(clock for clock in plan.to_dict()['clocks'] if clock['id'] == clock_id)


class ValidationTests(unittest.TestCase):
    def setUp(self): self.plan = nested_124_cross32()

    def bad(self, edit, pattern=None):
        data = self.plan.to_dict(); edit(data)
        ctx = self.assertRaisesRegex(MeterError, pattern) if pattern else self.assertRaises(MeterError)
        with ctx: MeterPlan(data)

    def test_roundtrip_snapshot_and_hash(self):
        original = self.plan.sha256; data = self.plan.to_dict(); data['bindings'][0]['values'][0] = -20
        self.assertEqual(self.plan.sha256, original)
        reopened = MeterPlan.from_json(json.dumps(self.plan.to_dict()))
        self.assertEqual(reopened.sha256, original)

    def test_unknown_version_fields_nonfinite_and_bool_rejected(self):
        self.bad(lambda d: d.update(version='2.0.0'))
        self.bad(lambda d: d.update(extra=True))
        self.bad(lambda d: d['bindings'][0].update(values=[float('nan')]))
        self.bad(lambda d: d['clocks'][0]['relation'] if False else d['bindings'][0].update(values=[True]))

    def test_active_windows_phase_and_resets_are_bounded(self):
        self.bad(lambda d: d['clocks'][0]['active_windows'][1].update(start_beat='23/1'), 'non-overlapping')
        self.bad(lambda d: d['clocks'][0].update(phase_beats='1/4'), 'phase')
        self.bad(lambda d: d['clocks'][0].update(reset_beats=['48/1', '16/1']), 'strictly increasing')
        self.bad(lambda d: d['clocks'][0].update(reset_beats=['64/1']), 'outside')

    def test_nested_relation_period_window_reset_and_phase_contracts(self):
        self.bad(lambda d: d['clocks'][1]['relation'].update(period_denominator=2), 'integer period multiple')
        self.bad(lambda d: d['clocks'][1].update(period_beats='3/4'), 'disagrees')
        self.bad(lambda d: d['clocks'][1]['active_windows'][1].update(start_beat='33/1'), 'share active')
        self.bad(lambda d: d['clocks'][1].update(reset_beats=['16/1']), 'share active/re-entry/reset')
        self.bad(lambda d: d['clocks'][1].update(phase_beats='1/8'), 'phase is not aligned')

    def test_cross_clock_is_explicitly_nonbinary_and_reduced(self):
        self.bad(lambda d: (d['clocks'][3].update(period_beats='1/2'), d['clocks'][3]['relation'].update(pulses=2, reference_cycles=1)),
                 'power-of-two')
        self.bad(lambda d: d['clocks'][3]['relation'].update(pulses=6, reference_cycles=4), 'reduced')
        self.bad(lambda d: d['clocks'][3].update(period_beats='3/4'), 'disagrees')

    def test_relation_cycles_and_independent_cycle_policy_rejected(self):
        self.bad(lambda d: d['clocks'][0].update(relation={'reference_id':'bounce','period_numerator':1,'period_denominator':1}), 'cycle')
        self.bad(lambda d: d['clocks'][4].update(relation={'reference_id':'sway','pulses':5,'reference_cycles':4}), 'cycle clocks')

    def test_stable_anchor_binding_must_name_stable_clock(self):
        self.bad(lambda d: d['bindings'][0].update(clock_id='articulation'), 'stable_clock_id')
        self.bad(lambda d: d.update(stable_clock_id='missing'), 'does not name')
        self.bad(lambda d: [b.update(stability='variable') for b in d['bindings']], 'stable anchor')


class ClockTests(unittest.TestCase):
    def setUp(self): self.plan = nested_124_cross32()

    def test_124_nested_ticks_are_phase_consistent_and_reentry_is_exact(self):
        all_ticks = generate_all_ticks(self.plan)
        articulation, bounce, sway = map(lambda name: set(beats(all_ticks[name])), ('articulation','bounce','sway'))
        self.assertTrue(sway <= bounce <= articulation)
        self.assertTrue(all(Fraction(24) > beat or beat >= 32 for beat in articulation))
        for name in ('articulation','bounce','sway'):
            rows = generate_ticks(self.plan, name)
            self.assertIn(Fraction(32), beats(rows))
            first_after = next(r for r in rows if fraction(r['beat']) >= 32)
            self.assertEqual(first_after['beat'], '32/1')
            self.assertEqual(first_after['phase_origin_beat'], '32/1')
        self.assertEqual(len(articulation), len(bounce) * 2)
        self.assertEqual(len(bounce), len(sway) * 2)

    def test_shared_nested_beats_map_to_identical_samples_at_20_and_360_bpm(self):
        for bpm in ('20/1','360/1'):
            with self.subTest(bpm=bpm):
                tm = time_map(sr=48000, origin=23, tempos=[('0/1', bpm)])
                mapped = {name:{fraction(r['beat']):r['sample'] for r in generate_ticks(self.plan,name,tm)}
                          for name in ('articulation','bounce','sway')}
                for beat, sample in mapped['sway'].items():
                    self.assertEqual(sample, mapped['bounce'][beat]); self.assertEqual(sample, mapped['articulation'][beat])
                self.assertEqual(list(mapped['articulation'].values()), sorted(mapped['articulation'].values()))

    def test_tempo_changes_do_not_change_beat_phase_hierarchy(self):
        tm = time_map(sr=44100, origin=11, tempos=[('0/1','137/1'),('8/1','173/1'),('40/1','83/1'),('56/1','251/1')])
        beat_sets = {name:set(beats(generate_ticks(self.plan,name,tm))) for name in ('articulation','bounce','sway')}
        self.assertTrue(beat_sets['sway'] <= beat_sets['bounce'] <= beat_sets['articulation'])
        rows = generate_ticks(self.plan,'sway',tm)
        intervals = [(fraction(a['beat']), b['sample']-a['sample']) for a,b in zip(rows,rows[1:])
                     if a['phase_segment_index']==b['phase_segment_index']]
        before = {delta for beat,delta in intervals if beat < 8}; after = {delta for beat,delta in intervals if Fraction(8)<=beat<Fraction(16)}
        self.assertNotEqual(before, after)

    def test_noninteger_sample_boundaries_use_frozen_round_once_policy(self):
        tm = time_map(sr=44100, origin=0, tempos=[('0/1','137/1')])
        rows = generate_ticks(self.plan,'articulation',tm)
        fractional = [r for r in rows if fraction(r['exact_sample']).denominator != 1]
        self.assertGreater(len(fractional), 10)
        for r in rows:
            self.assertEqual(r['sample'], beat_to_sample(tm.to_dict(), r['beat']))
            self.assertLessEqual(abs(fraction(r['rounding_error_samples'])), Fraction(1,2))

    def test_cross_3_2_is_not_half_or_double_time(self):
        relation = clock_relation(self.plan,'cross-3-2')
        self.assertEqual(relation['cross_label'],'3:2'); self.assertFalse(relation['binary_nested'])
        self.assertEqual(relation['period_ratio'],'2/3')
        cross = beats(generate_ticks(self.plan,'cross-3-2'))
        sway = set(beats(generate_ticks(self.plan,'sway')))
        self.assertTrue(any(beat.denominator == 3 for beat in cross))
        self.assertTrue(any(beat not in sway for beat in cross))
        self.assertIn(Fraction(2), set(cross) & sway)

    def test_long_cycle_phase_reset_restarts_from_declared_phase(self):
        rows = generate_ticks(self.plan,'long-cycle')
        before = [fraction(r['beat']) for r in rows if fraction(r['beat']) < 40]
        after = [fraction(r['beat']) for r in rows if fraction(r['beat']) >= 40]
        self.assertTrue(before and after)
        self.assertEqual(after[0], Fraction(321,8))  # 40 + 1/8 phase
        first = next(r for r in rows if fraction(r['beat']) >= 40)
        self.assertEqual(first['phase_origin_beat'],'40/1')

    def test_control_schedule_keeps_anchor_and_variable_lanes_separate(self):
        rows = control_schedule(self.plan)
        anchor = [r for r in rows if r['stability']=='anchor']; variable = [r for r in rows if r['stability']=='variable']
        self.assertTrue(anchor and variable)
        self.assertTrue(all(r['clock_id']=='sway' and r['stable_clock'] for r in anchor))
        self.assertTrue(any(r['control']=='density_per_beat' and r['clock_id']=='articulation' for r in variable))
        self.assertTrue(any(r['control']=='brightness_hz' and r['clock_id']=='cross-3-2' for r in variable))


class OverlayTests(unittest.TestCase):
    def setUp(self): self.plan = nested_124_cross32()

    def candidate(self, report, clock_id):
        return next(row for row in report['candidates'] if row['clock_id']==clock_id)

    def test_fast_measurements_can_support_slower_nested_levels_simultaneously(self):
        measured = [r['beat'] for r in generate_ticks(self.plan,'articulation')]
        report = periodicity_overlay(self.plan, measured_beats=measured, tolerance_fraction='1/16', support_threshold=.95)
        for clock in ('articulation','bounce','sway'):
            self.assertEqual(self.candidate(report,clock)['tick_coverage'],1.0)
            self.assertIn(clock, report['ambiguity_clock_ids'])
        self.assertLess(self.candidate(report,'sway')['measurement_alignment'], self.candidate(report,'articulation')['measurement_alignment'])
        self.assertNotIn('cross-3-2', report['ambiguity_clock_ids'])
        self.assertEqual(report['winner_policy'],'none; multiple metrical levels may be simultaneously supported')
        self.assertTrue(report['extra_events_do_not_penalize_tick_coverage'])

    def test_cross_measurements_identify_cross_clock_without_calling_it_binary(self):
        measured = [r['beat'] for r in generate_ticks(self.plan,'cross-3-2')]
        report = periodicity_overlay(self.plan, measured_beats=measured, tolerance_fraction='1/32', support_threshold=.95)
        self.assertEqual(self.candidate(report,'cross-3-2')['tick_coverage'],1.0)
        self.assertIn('cross-3-2', report['ambiguity_clock_ids'])
        self.assertEqual(clock_relation(self.plan,'cross-3-2')['kind'],'cross')

    def test_sample_overlay_uses_time_map_and_reports_rounding_range(self):
        tm = time_map(sr=44100, origin=29, tempos=[('0/1','137/1'),('16/1','181/1')])
        measured = [r['sample'] for r in generate_ticks(self.plan,'sway',tm)]
        report = periodicity_overlay(self.plan,time_map=tm,measured_samples=measured,tolerance_fraction='1/32',support_threshold=.95)
        sway = self.candidate(report,'sway')
        self.assertEqual(sway['tick_coverage'],1.0)
        self.assertIsNotNone(sway['sample_interval_min']); self.assertIsNotNone(sway['sample_interval_max'])
        self.assertLess(sway['sample_interval_min'], sway['sample_interval_max'])

    def test_zg012_feature_timeline_adapter_preserves_multiple_hypotheses(self):
        tm = time_map(sr=48000, origin=0, tempos=[('0/1','200/1')])
        samples = [r['sample'] for r in generate_ticks(self.plan,'sway',tm)]
        frames = [SimpleNamespace(anchor_sample=s, valid=True, spectral_flux=1.0) for s in samples]
        feature = SimpleNamespace(sample_rate_hz=48000, frames=frames)
        self.assertEqual(feature_flux_samples(feature,.5), samples)
        report = overlay_feature_flux(self.plan,tm,feature,.5,tolerance_fraction='1/32',support_threshold=.95)
        self.assertEqual(self.candidate(report,'sway')['tick_coverage'],1.0)
        with self.assertRaisesRegex(MeterError,'sample rates differ'):
            overlay_feature_flux(self.plan,tm,SimpleNamespace(sample_rate_hz=44100,frames=frames),.5)

    def test_measurement_input_errors_are_explicit(self):
        with self.assertRaisesRegex(MeterError,'exactly one'):
            periodicity_overlay(self.plan, measured_beats=[], measured_samples=[])
        with self.assertRaisesRegex(MeterError,'strictly increasing'):
            periodicity_overlay(self.plan, measured_beats=['1/1','1/1'])
        with self.assertRaisesRegex(MeterError,'tolerance'):
            periodicity_overlay(self.plan, measured_beats=[], tolerance_fraction='3/4')


if __name__ == '__main__': unittest.main(verbosity=2)
