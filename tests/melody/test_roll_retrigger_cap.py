from __future__ import annotations

from copy import deepcopy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'app'))

from zaaggenz_contracts.legacy import adapt_parameters,freeze_legacy,envelope
from zaaggenz_melody import MelodyError,MelodicRenderSpec,make_melodic_recipe,make_phrase_plan,note_event,render_phrase


def roll_recipe(duration,density,*,bpm=200.,sr=12000):
    params=adapt_parameters('synth',{'sr':sr,'bpm':float(bpm),'beats':1,'f0_hz':48.})
    frozen=freeze_legacy(params).to_dict();tm=deepcopy(frozen['time_map']);tu=deepcopy(frozen['tuning'])
    gesture=envelope('GestureSpec',id='roll',duration_beats=duration,curves=[{
        'axis':'density_per_beat','unit':'events/beat','interpolation':'step',
        'points':[{'beat':'0/1','value':float(density)}],
    }])
    event=note_event('n','0/1',duration,tu['id'],0,gesture_id='roll')
    phrase=make_phrase_plan(tu['id'],[event],start_beat='0/1',end_beat=duration,gestures=[gesture])
    return make_melodic_recipe(params,tm,tu,phrase,tail_mode='truncate')


class RollRetriggerCapTests(unittest.TestCase):
    def test_custom_cap_below_exact_and_one_over_are_not_truncated(self):
        spec=MelodicRenderSpec(max_roll_retriggers=2)
        below=render_phrase(roll_recipe('1/2',4),spec)
        exact=render_phrase(roll_recipe('3/4',4),spec)
        self.assertEqual(below.events[0]['roll_retriggers'],1)
        self.assertEqual(exact.events[0]['roll_retriggers'],2)
        with patch('uptempo_harmony.synth.synthesize_one',side_effect=AssertionError('source render must not start')) as synth:
            with self.assertRaisesRegex(MelodyError,r'requested 3 retriggers exceeds max_roll_retriggers=2'):
                render_phrase(roll_recipe('1/1',4),spec)
        synth.assert_not_called()

    def test_default_cap_accepts_64_and_rejects_65_before_source_render(self):
        from uptempo_harmony.synth import synthesize_one
        with patch('uptempo_harmony.synth.synthesize_one',wraps=synthesize_one) as synth:
            result=render_phrase(roll_recipe('65/16',16))
        self.assertEqual(result.events[0]['roll_retriggers'],64)
        self.assertEqual(result.diagnostics['roll_retriggers'],64)
        self.assertEqual(synth.call_count,1)
        with patch('uptempo_harmony.synth.synthesize_one',side_effect=AssertionError('source render must not start')) as synth:
            with self.assertRaisesRegex(MelodyError,r'requested 65 retriggers exceeds max_roll_retriggers=64'):
                render_phrase(roll_recipe('33/8',16))
        synth.assert_not_called()

    def test_zero_cap_has_explicit_no_retrigger_semantics(self):
        spec=MelodicRenderSpec(max_roll_retriggers=0)
        no_roll=render_phrase(roll_recipe('2/1',1),spec)
        boundary=render_phrase(roll_recipe('1/2',2),spec)
        self.assertEqual(no_roll.events[0]['roll_retriggers'],0)
        self.assertEqual(boundary.events[0]['roll_retriggers'],0)
        with patch('uptempo_harmony.synth.synthesize_one',side_effect=AssertionError('source render must not start')) as synth:
            with self.assertRaisesRegex(MelodyError,r'requested 1 retriggers exceeds max_roll_retriggers=0'):
                render_phrase(roll_recipe('1/1',2),spec)
        synth.assert_not_called()

    def test_over_cap_count_is_exact_and_tempo_independent(self):
        for bpm in (20.,360.):
            with self.subTest(bpm=bpm):
                with patch('uptempo_harmony.synth.synthesize_one',side_effect=AssertionError('source render must not start')) as synth:
                    with self.assertRaisesRegex(MelodyError,r'requested 79 retriggers exceeds max_roll_retriggers=64'):
                        render_phrase(roll_recipe('5/1',16,bpm=bpm))
                synth.assert_not_called()


if __name__=='__main__':unittest.main(verbosity=2)
