from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'app'))

from zaaggenz_melody import MelodyError,MelodicRenderSpec,render_phrase
from zaaggenz_timeline.model import TimelineDocument,compile_recipe,default_document


def timeline_with_roll(duration,density=16):
    data=default_document(12000).to_dict()
    data.update(end_beat=duration,next_id=1,clips=[],notes=[{
        'id':'roll','beat':'0/1','duration_beats':duration,'degree':0,'detune_cents':0.,
        'gain_db':-18.,'muted':False,'roll_density':density,
    }])
    return data


class TimelineRollRetriggerCapTests(unittest.TestCase):
    def test_timeline_and_renderer_share_strict_interior_grid_boundary(self):
        exact=TimelineDocument(timeline_with_roll('65/16'))
        recipe=compile_recipe(exact)
        with patch('uptempo_harmony.synth.synthesize_one',side_effect=AssertionError('source render must not start')) as synth:
            with self.assertRaisesRegex(MelodyError,r'requested 64 retriggers exceeds max_roll_retriggers=63'):
                render_phrase(recipe,MelodicRenderSpec(max_roll_retriggers=63))
        synth.assert_not_called()

        with self.assertRaisesRegex(ValueError,r'64 retriggers'):
            TimelineDocument(timeline_with_roll('33/8'))


if __name__=='__main__':unittest.main(verbosity=2)
