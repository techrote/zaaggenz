from __future__ import annotations
import hashlib
import tempfile
import unittest
import wave
from dataclasses import replace
from pathlib import Path
import numpy as np
from zaaggenz_zaag import krach_retry_v3 as v3
from zaaggenz_zaag.registry import PRODUCTION_PRESET_IDS, family, product_preset_catalogue

class KrachV3Tests(unittest.TestCase):
    def test_four_new_unapproved_identities(self):
        self.assertEqual(len(v3.RECIPES), 4)
        self.assertEqual(len({r.id for r in v3.RECIPES}), 4)
        self.assertTrue(set(r.id for r in v3.RECIPES).isdisjoint(PRODUCTION_PRESET_IDS))
        self.assertTrue(all(r.payload()['classification'] == 'krach-candidate' for r in v3.RECIPES))

    def test_deterministic_finite_sources_at_both_rates(self):
        for sr in (12000, 48000):
            digests = []
            for r in v3.RECIPES:
                a, info = v3.render_source(r, sr)
                b, again = v3.render_source(r, sr)
                np.testing.assert_array_equal(a, b)
                self.assertEqual(info, again)
                self.assertTrue(np.isfinite(a).all())
                self.assertGreater(float(np.sqrt(np.mean(a*a))), .01)
                self.assertEqual(len(a), round(sr*60/190*.97))
                self.assertEqual(a[0], 0.); self.assertEqual(a[-1], 0.)
                self.assertFalse(info['formant_resonators'])
                self.assertFalse(info['whole_mix_grit'])
                digests.append(info['source_pcm_sha256'])
            self.assertEqual(len(set(digests)), 4)

    def test_parameter_bounds_before_rendering(self):
        r = v3.RECIPES[0]
        for sr in (True, 0, 8000, 44100, 48000.):
            with self.assertRaises(ValueError): v3.render_source(r, sr)
        for bpm in (True, 59., 261., float('nan'), float('inf')):
            with self.assertRaises(ValueError): v3.render_source(r, bpm=bpm)
        for sr in (12000, 48000):
            for bpm in (60., 260.):
                a, _ = v3.render_source(r, sr, bpm=bpm)
                self.assertEqual(len(a), round(sr*60/bpm*.97))
        for kwargs in ({'style': True}, {'style': 4}, {'body': float('nan')}, {'upper': -1.}, {'id':'zaag.upper-chop'}):
            with self.assertRaises(ValueError): replace(r, **kwargs)

    def test_riff_is_shared_sparse_and_bounded(self):
        self.assertEqual(set(n[2] for n in v3.RIFF), {0, -1, -5})
        self.assertGreater(sum(n[2] == 0 for n in v3.RIFF), len(v3.RIFF)//2)
        self.assertLess(len(v3.RIFF), 32)
        self.assertTrue(any(n[0] % 1 for n in v3.RIFF))
        for i, (at, duration, degree, gain) in enumerate(v3.RIFF):
            self.assertGreater(duration, 0.)
            self.assertLessEqual(at+duration, v3.RIFF[i+1][0] if i+1 < len(v3.RIFF) else 16.)

    def test_sampler_replay_extent_and_silent_gaps(self):
        source, _ = v3.render_source(v3.RECIPES[1], 12000)
        a, info = v3.render_phrase(source, 12000, riff=True)
        b, _ = v3.render_phrase(source, 12000, riff=True)
        np.testing.assert_array_equal(a, b)
        self.assertEqual(len(a), round(32*12000*60/190))
        self.assertFalse(info['tail_overlap'])
        self.assertTrue(np.all(a[round(14.61*12000*60/190):round(15.49*12000*60/190)] == 0.))
        for degree, (up, down) in info['sampler_length_ratios'].items():
            error = abs(1200*np.log2(down/up)-100*degree)
            self.assertLess(error, .01)
        for bad in (np.zeros(10), np.array([np.nan]*100), np.zeros((100, 2))):
            with self.assertRaises(ValueError): v3.render_phrase(bad, 12000)

    def test_matching_is_a_single_scalar_and_bounds_are_enforced(self):
        source, _ = v3.render_source(v3.RECIPES[0], 12000)
        matched, info = v3.match(source)
        np.testing.assert_allclose(matched, source*info['gain'], atol=1e-7)
        self.assertLessEqual(float(np.max(np.abs(matched))), .900001)
        for source in (np.zeros(100), np.array([np.inf]), np.zeros((100,2))):
            with self.assertRaises(ValueError): v3.match(source)
        with self.assertRaises(ValueError): v3.match(np.ones(100), target=float('nan'))

    def test_approved_presets_are_not_mutated(self):
        before = {k: family(k).to_dict() for k in PRODUCTION_PRESET_IDS}
        catalogue = product_preset_catalogue()
        for r in v3.RECIPES: v3.render_source(r, 12000)
        self.assertEqual(before, {k: family(k).to_dict() for k in PRODUCTION_PRESET_IDS})
        self.assertEqual(catalogue, product_preset_catalogue())
        self.assertEqual(catalogue['default'], 'locked_bloom')

    def test_pack_files_pcm24_hashes_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'pack'
            report = v3.build_pack(path, 12000)
            self.assertEqual(len(report['files']), 14)
            self.assertEqual(report['owner_status'], 'pending-owner')
            self.assertFalse(report['production_promoted'])
            for row in report['files']:
                file = path/row['path']
                self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(), row['sha256'])
                with wave.open(str(file)) as wav:
                    self.assertEqual((wav.getframerate(), wav.getsampwidth(), wav.getnchannels()), (12000,3,1))
                    self.assertEqual(wav.getnframes(), row['frames'])
            self.assertTrue((path/'listen.html').is_file())
            with self.assertRaises(ValueError): v3.build_pack(path, 12000)

if __name__ == '__main__': unittest.main(verbosity=2)
