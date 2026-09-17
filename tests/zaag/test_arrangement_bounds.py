from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from zaaggenz_zaag.arrange import (
    ArrangementManifest,
    BEATS_PER_BAR,
    GAIN_DB_MAX,
    GAIN_DB_MIN,
    MAX_ARRANGEMENT_EVENTS,
    MAX_ARRANGEMENT_VOICES,
    MAX_EVENT_POLYPHONY,
    MAX_EVENTS_PER_BAR,
    MAX_OUTPUT_SAMPLES,
    arrangement_work_estimate,
    example_manifests,
    render_arrangement,
)
from zaaggenz_zaag.model import ZaagFamilyError


def _event(beat=0.0,duration=0.25,family_id='zaag.vowel-sway',degrees=(0,),gain_db=-6.0):
    return {'beat':beat,'duration_beats':duration,'family_id':family_id,'degrees':list(degrees),'gain_db':gain_db}


def _manifest(events,*,bars=1,bpm=190.0,sr=12000):
    return ArrangementManifest('bounds-test',bars,bpm,sr,tuple(events),'ZG-022 boundary fixture')


class ArrangementAdmissionBoundsTests(unittest.TestCase):
    def test_existing_examples_keep_manifest_shape_and_render_deterministically(self):
        examples=example_manifests(12000)
        self.assertEqual([m.bars for m in examples],[1,4,16])
        self.assertEqual([len(m.events) for m in examples],[1,32,64])
        for manifest in examples:
            estimate=arrangement_work_estimate(manifest)
            self.assertEqual(estimate['event_count'],len(manifest.events))
            a=render_arrangement(manifest);b=render_arrangement(manifest)
            self.assertEqual(a.diagnostics,b.diagnostics)
            self.assertEqual(a.audio.tobytes(),b.audio.tobytes())

    def test_nonfinite_boolean_and_coerced_event_numbers_fail_at_construction(self):
        fields=('beat','duration_beats','gain_db')
        bad=(math.nan,math.inf,-math.inf,True,'0.25')
        for field in fields:
            for value in bad:
                row=_event();row[field]=value
                with self.subTest(field=field,value=value):
                    with self.assertRaises(ZaagFamilyError):_manifest((row,))

    def test_gain_has_finite_executable_bound(self):
        for gain in (GAIN_DB_MIN,GAIN_DB_MAX):_manifest((_event(gain_db=gain),))
        for gain in (math.nextafter(GAIN_DB_MIN,-math.inf),math.nextafter(GAIN_DB_MAX,math.inf)):
            with self.assertRaises(ZaagFamilyError):_manifest((_event(gain_db=gain),))

    def test_timeline_bounds_reject_huge_or_outside_starts_and_durations(self):
        _manifest((_event(beat=0.0,duration=4.0),))
        _manifest((_event(beat=3.75,duration=.25),))
        last=math.nextafter(4.0,0.0);_manifest((_event(beat=last,duration=4.0-last),))
        for row in (_event(beat=4.0),_event(beat=1e300),_event(beat=3.9,duration=.2),_event(duration=5.0)):
            with self.assertRaises(ZaagFamilyError):_manifest((row,))

    def test_exact_event_and_polyphony_limits_and_plus_one(self):
        events=[_event(beat=i/4.0,duration=.25) for i in range(MAX_EVENTS_PER_BAR)]
        manifest=_manifest(events)
        self.assertEqual(arrangement_work_estimate(manifest)['event_count'],MAX_EVENTS_PER_BAR)
        with self.assertRaises(ZaagFamilyError):_manifest(events+[_event()])
        _manifest((_event(degrees=(0,)*MAX_EVENT_POLYPHONY),))
        with self.assertRaises(ZaagFamilyError):_manifest((_event(degrees=(0,)*(MAX_EVENT_POLYPHONY+1)),))

    def test_family_degree_bounds_are_checked_before_exponentiation(self):
        # Vowel Sway's declared .5..2.0 range maps exactly to -12..+12 in 12-EDO.
        _manifest((_event(degrees=(-12,12)),))
        for degree in (-13,13,10**1000,-(10**1000)):
            with self.subTest(degree=str(degree)[:20]):
                with self.assertRaises(ZaagFamilyError):_manifest((_event(degrees=(degree,)),))

    def test_one_and_sixty_four_bar_resource_envelopes_are_model_owned(self):
        one=_manifest((_event(),),bars=1,bpm=60.0,sr=48000)
        self.assertLess(arrangement_work_estimate(one)['maximum_output_samples'],MAX_OUTPUT_SAMPLES)
        events=[]
        for i in range(MAX_ARRANGEMENT_EVENTS):
            beat=i/4.0
            events.append(_event(beat=beat,duration=.25,degrees=(0,)*MAX_EVENT_POLYPHONY))
        maximum=_manifest(events,bars=64,bpm=60.0,sr=48000)
        estimate=arrangement_work_estimate(maximum)
        self.assertEqual(estimate['event_count'],MAX_ARRANGEMENT_EVENTS)
        self.assertEqual(estimate['note_voices'],MAX_ARRANGEMENT_VOICES)
        self.assertEqual(estimate['maximum_output_samples'],MAX_OUTPUT_SAMPLES)

    def test_dense_in_bound_render_is_deterministic(self):
        events=[_event(beat=i/4.0,duration=.2,degrees=(0,)*MAX_EVENT_POLYPHONY,gain_db=-18.0) for i in range(MAX_EVENTS_PER_BAR)]
        manifest=_manifest(events)
        a=render_arrangement(manifest);b=render_arrangement(manifest)
        self.assertEqual(a.diagnostics['pcm_sha256'],b.diagnostics['pcm_sha256'])
        self.assertEqual(a.audio.tobytes(),b.audio.tobytes())

    def test_preserved_tail_can_only_extend_within_preflight_extent(self):
        manifest=_manifest((_event(beat=3.75,duration=.25),),bpm=60.0,sr=12000)
        estimate=arrangement_work_estimate(manifest);rendered=render_arrangement(manifest)
        self.assertGreater(len(rendered.audio),estimate['nominal_samples'])
        self.assertLessEqual(len(rendered.audio),estimate['maximum_output_samples'])

    def test_render_revalidates_before_source_work_or_allocation_growth(self):
        manifest=_manifest((_event(),))
        manifest.events[0]['beat']=1e300
        with patch('zaaggenz_zaag.arrange.render_family_source') as source:
            with self.assertRaises(ZaagFamilyError):render_arrangement(manifest)
            source.assert_not_called()

    def test_event_schema_and_top_level_numbers_do_not_coerce(self):
        row=_event();row['extra']='not part of v1 event schema'
        with self.assertRaises(ZaagFamilyError):_manifest((row,))
        for bpm in (True,'190'):
            with self.assertRaises(ZaagFamilyError):ArrangementManifest('x',1,bpm,12000,(_event(),),'x')
        for sr in (12000.0,True):
            with self.assertRaises(ZaagFamilyError):ArrangementManifest('x',1,190.0,sr,(_event(),),'x')


if __name__=='__main__':unittest.main()
