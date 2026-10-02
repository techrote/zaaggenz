"""Direct numerical oracles for saved-rack execution, not metadata-only smoke tests."""
from copy import deepcopy
from dataclasses import replace
from itertools import permutations
import unittest
from unittest.mock import patch
import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.rack import RackRecipe, RackCompatibilityError, empty_rack, STAGES
from zaaggenz_dsp import CompressionSpec, BitcrushSpec, compress, bitcrush, split_bands
from zaaggenz_dsp.band_router import route_band_processors
from zaaggenz_jobs import JobCancelled
from zaaggenz_spectral import (SpectralRetuneRequest, LatticeVoice, ChordnessRequest, CombTemplate)
from zaaggenz_spectral.band_selective import BandSelectiveRequest, BandSlotSpec, process_band_selective
from zaaggenz_spectral.rack_adapter import request_to_rack, execution_request
from zaaggenz_spectral.rack_executor import (compile_rack, execute_rack, estimate_rack_resources,
                                            MAX_WORKING_BYTES)
from zaaggenz_tuning import fixture_pack, tuning_to_spec
from helpers import source, slot, rack, insert, external


def pcm(sr=12000, channels=1, seconds=.16):
    t = np.arange(round(sr * seconds)) / sr
    x = (.32*np.sin(2*np.pi*247*t) + .18*np.sin(2*np.pi*890*t)
         + .08*np.cos(2*np.pi*50*t)) * (.3 + .7*np.sin(np.pi*t/seconds)**2)
    if channels == 2:
        x = np.column_stack((x, -.7*x + .03*np.sin(2*np.pi*1120*t)))
    return x.astype(np.float32)


def saved_pcm(request, sr=12000, channels=1):
    # The standalone rack PCM contract supports stereo. The accepted legacy
    # Compose source remains mono; no fake stereo RenderRecipe is introduced.
    data = request_to_rack(request, source(sr)).to_dict()
    data['channels'] = channels
    return RackRecipe(data)


def retune880():
    return SpectralRetuneRequest(tuning_to_spec(fixture_pack()['12tet-a440']),
        (LatticeVoice(12, (1.,), '880'),), min_confidence=.35, min_hz=600., max_hz=1600.,
        max_displacement_cents=120., max_correction_slew_cents_per_second=3000.)


def reweight1000():
    return ChordnessRequest((CombTemplate('target', (1000.,)),), mode='reweight',
        selected_template_ids=('target',), max_selected_templates=1, min_confidence=.35,
        max_gain_db=4., max_gain_slew_db_per_second=80.)


class SavedRackExecutorTests(unittest.TestCase):
    def test_all_24_orders_direct_legacy_parity_12_48_mono_stereo(self):
        for sr in (12000, 48000):
            for channels in (1, 2):
                x = pcm(sr, channels)
                for order in permutations(STAGES):
                    with self.subTest(sr=sr, channels=channels, order=order):
                        request = BandSelectiveRequest(slots=(None, slot(order=order), BandSlotSpec(), None),
                                                       confine_delta=(True, False, True, False))
                        saved = saved_pcm(request, sr, channels)
                        before = saved.to_json(); original = x.tobytes()
                        expected = process_band_selective(x, sr, request).audio
                        actual, diagnostics = execute_rack(x, sr, saved)
                        np.testing.assert_array_equal(actual, expected)
                        self.assertFalse(np.array_equal(actual, x))
                        self.assertEqual(saved.to_json(), before)
                        self.assertEqual(x.tobytes(), original)
                        self.assertEqual(diagnostics['normalization'], 'none')
                        self.assertEqual(diagnostics['master_gain_db'], 0)

    def test_spectral_orders_direct_parity_across_both_rates_and_channels(self):
        # All 24 orders exercise real spectral calls, alternating the two
        # accepted spectral modes and distributing the rate/layout cross product.
        orders = list(permutations(STAGES))
        for i, order in enumerate(orders):
            sr = (12000, 48000)[i % 2]; channels = 1 + (i // 2) % 2
            spectral = retune880() if (i // 4) % 2 == 0 else reweight1000()
            with self.subTest(sr=sr, channels=channels, order=order, mode=type(spectral).__name__):
                x = pcm(sr, channels, .24)
                request = BandSelectiveRequest(slots=(None, None, slot(spectral, order), None))
                expected = process_band_selective(x, sr, request).audio
                actual, _ = execute_rack(x, sr, saved_pcm(request, sr, channels))
                np.testing.assert_array_equal(actual, expected)

    def test_spectral_transforms_really_change_frames_and_preserve_dry_pocket(self):
        for sr in (12000, 48000):
            for channels in (1, 2):
                for spectral, frequency in ((retune880(), 890.), (reweight1000(), 1000.)):
                    with self.subTest(sr=sr, channels=channels, mode=type(spectral).__name__):
                        t = np.arange(round(sr*.8)) / sr
                        x = (.45*np.cos(2*np.pi*60*t+.13) + .28*np.cos(2*np.pi*frequency*t+.13)).astype(np.float32)
                        if channels == 2:x = np.column_stack((x, -.7*x))
                        request = BandSelectiveRequest(slots=(None, None, BandSlotSpec(spectral=spectral), None))
                        expected = process_band_selective(x, sr, request).audio
                        actual, diagnostics = execute_rack(x, sr, saved_pcm(request, sr, channels))
                        np.testing.assert_array_equal(actual, expected)
                        row = diagnostics['bands'][2]['stages'][0]['processor']
                        self.assertGreater(row['diagnostics']['changed_frames'], 0)
                        self.assertTrue(row['analysis']['transient_detector'])
                        self.assertIsNotNone(row['pitch_observations']['estimated_hz_range'])
                        self.assertLessEqual(len(row['pitch_observations']['sample']), 16)
                        self.assertEqual(sum(row['decision_counts_by_reason'].values()), row['diagnostics']['frames'])
                        delta_bands = split_bands(actual-x, sr, (105., 520., 3600.))
                        rms = lambda a: float(np.sqrt(np.mean(a*a)))
                        self.assertGreater(rms(delta_bands[2]), rms(delta_bands[0])*5.)
                        self.assertEqual(len(diagnostics['bands'][2]['input']['channel_peak']), channels)

    def test_fractional_insert_band_and_rack_wet_match_independent_composition(self):
        sr = 12000; x = pcm(sr).astype(np.float64)
        request = BandSelectiveRequest(slots=(None, slot(order=('bitcrush','gain','compression','spectral')), None, None),
                                       confine_delta=(True, False, True, True))
        data = saved_pcm(request).to_dict(); data['wet'] = .63; data['bands'][1]['wet'] = .47
        for value, wet in zip(data['bands'][1]['inserts'], (.29, .71, .53, 1.)):
            value['wet'] = wet
        spec = request.slots[1]
        def direct(band):
            current = np.asarray(band, dtype=np.float64)
            crushed = bitcrush(current, spec.bitcrush).audio
            current = current + .29*(crushed-current)
            gained = current * 10.**(spec.gain_db/20.)
            current = current + .71*(gained-current)
            compressed = compress(current, sr, spec.compression).audio
            current = current + .53*(compressed-current)
            return band + .47*(current-band)
        routed, _ = route_band_processors(x, sr, request.crossovers_hz, (None, direct, None, None), request.confine_delta)
        expected = x + .63*(routed-x)
        actual, diagnostics = execute_rack(x, sr, data)
        np.testing.assert_array_equal(actual, expected)
        self.assertEqual(diagnostics['delta_report_domain'], 'after-band-wet-before-global-wet')
        # Restoring full wet returns the exact original legacy operation order.
        data['wet'] = data['bands'][1]['wet'] = 1.
        for value in data['bands'][1]['inserts']:value['wet'] = 1.
        np.testing.assert_array_equal(execute_rack(x, sr, data)[0], process_band_selective(x, sr, request).audio)

    def test_partial_chain_and_reorder_preserve_instances_and_change_audio(self):
        data = rack().to_dict()
        data['bands'][1]['inserts'] = [insert(data, 'compression'), insert(data, 'gain')]
        saved = RackRecipe(data); moved = saved.move_insert('band.lowmid', 'band.lowmid.gain', 0)
        self.assertEqual({i['id']:i for i in saved.to_dict()['bands'][1]['inserts']},
                         {i['id']:i for i in moved.to_dict()['bands'][1]['inserts']})
        self.assertNotEqual(saved.sonic_sha256, moved.sonic_sha256)
        x = pcm(); self.assertFalse(np.array_equal(execute_rack(x, 12000, saved)[0], execute_rack(x, 12000, moved)[0]))

    def test_every_bypass_scope_is_byte_exact_even_empty_and_short(self):
        mutations = [lambda d:d.update(bypass=True), lambda d:d.update(wet=0.),
            lambda d:d['bands'][1].update(bypass=True), lambda d:d['bands'][1].update(wet=0.),
            lambda d:[i.update(bypass=True) for i in d['bands'][1]['inserts']],
            lambda d:[i.update(wet=0.) for i in d['bands'][1]['inserts']]]
        variants = [empty_rack(source()).to_dict()]
        for mutate in mutations:
            data = rack().to_dict(); mutate(data); variants.append(data)
        unity = BandSlotSpec(compression=CompressionSpec(ratio=1., makeup_db=0.),
                             bitcrush=BitcrushSpec(wet=0.), spectral=replace(retune880(), amount=0.))
        variants.append(saved_pcm(BandSelectiveRequest(slots=(None, unity, None, None))).to_dict())
        for original in variants:
            for channels in (1, 2):
                data = deepcopy(original); data['channels'] = channels
                for dtype in (np.float32, np.float64):
                    for frames in (0, 1, 7, 8, 64):
                        x = np.zeros((frames, channels), dtype=dtype)
                        if frames:x[0] = -0.
                        if channels == 1:x = x[:, 0]
                        actual, diagnostics = execute_rack(x, 12000, data)
                        self.assertEqual((actual.shape,actual.dtype,actual.tobytes()), (x.shape,x.dtype,x.tobytes()))
                        self.assertTrue(diagnostics['identity_path'])
                        if frames < 8:self.assertIsNone(diagnostics['bands'][0]['input'])

    def test_single_insert_bypass_matches_the_lossless_execution_projection(self):
        x = pcm()
        for stage in STAGES:
            for field, value in (('bypass', True), ('wet', 0.)):
                data = rack(spectral=retune880()).to_dict(); insert(data, stage)[field] = value
                expected = process_band_selective(x, 12000, execution_request(data)).audio
                np.testing.assert_array_equal(execute_rack(x, 12000, data)[0], expected)

    def test_natural_spectral_identity_in_active_chain_keeps_legacy_float32_boundary(self):
        # Do not replace this with independent primitive identity shortcuts.
        request = BandSelectiveRequest(slots=(None, slot(replace(retune880(), amount=0.)), None, None))
        x = pcm().astype(np.float64) + 1e-12
        np.testing.assert_array_equal(execute_rack(x, 12000, saved_pcm(request))[0],
                                      process_band_selective(x, 12000, request).audio)

    def test_meter_values_and_compressor_gain_reduction_come_from_audio(self):
        x = pcm(); saved = rack(); actual, diagnostics = execute_rack(x, 12000, saved)
        band = split_bands(x, 12000, (105.,520.,3600.))[1]
        self.assertAlmostEqual(diagnostics['bands'][1]['input']['rms'], float(np.sqrt(np.mean(band*band))), 14)
        row = next(row for row in diagnostics['bands'][1]['stages'] if row['type_id'] == 'zg.compression')
        self.assertGreater(row['processor']['diagnostics']['max_gain_reduction_db'], 0)
        self.assertAlmostEqual(diagnostics['output']['peak'], float(np.max(np.abs(actual))))
        silence, quiet = execute_rack(np.zeros_like(x), 12000, saved)
        # Preserve the accepted quantizer's midpoint/DC behavior, not an
        # invented silence shortcut. Input meters and compressor GR stay zero.
        expected_silence = process_band_selective(np.zeros_like(x),12000,execution_request(saved)).audio
        np.testing.assert_array_equal(silence, expected_silence)
        self.assertGreater(np.max(np.abs(silence)), 0)
        for row, band in zip(quiet['bands'], split_bands(silence,12000,(105.,520.,3600.))):
            self.assertEqual(row['input']['rms'], 0)
            self.assertAlmostEqual(row['routed_output']['peak'], float(np.max(np.abs(band))))
        comp = next(row for row in quiet['bands'][1]['stages'] if row['type_id'] == 'zg.compression')
        self.assertEqual(comp['processor']['diagnostics']['max_gain_reduction_db'], 0)

    def test_invalid_hidden_state_and_unavailable_types_fail_before_dsp(self):
        mutations = [lambda d:insert(d)['params'].update(ratio=float('nan')),
                     lambda d:d['bands'][1]['inserts'].append(external()),
                     lambda d:insert(d).update(version='99.0.0'),
                     lambda d:d['crossovers'].update(frequencies_hz=[500.,100.,3500.])]
        for mutate in mutations:
            data = rack().to_dict(); data['bypass'] = True; mutate(data)
            with patch('zaaggenz_spectral.rack_executor.split_bands') as split, \
                 patch('zaaggenz_spectral.rack_executor.route_band_processors') as route:
                with self.assertRaises((ContractError, RackCompatibilityError)):execute_rack(pcm(),12000,data)
                split.assert_not_called(); route.assert_not_called()

    def test_source_rate_and_channel_bindings_fail_without_implicit_conversion(self):
        saved = rack()
        with self.assertRaisesRegex(ValueError, 'sample-rate'):execute_rack(pcm(),48000,saved)
        with self.assertRaisesRegex(ValueError, 'channel-count'):execute_rack(pcm(channels=2),12000,saved)
        with self.assertRaisesRegex(ValueError, 'binding'):compile_rack(saved, source(48000))
        data = saved.to_dict(); data['channels'] = 2
        with self.assertRaisesRegex(ValueError, 'channel-count'):compile_rack(data, source())
        for x in (np.zeros((16,3)), np.zeros((1,2,3)), np.array([np.nan]), np.array([np.inf]), np.array([1j])):
            with self.assertRaises(ValueError):execute_rack(x,12000,saved)

    def test_short_active_and_extreme_unrepresentable_inputs_fail_explicitly(self):
        for frames in (0,1,7):
            with self.assertRaisesRegex(ValueError, 'at least 8'):execute_rack(np.zeros(frames),12000,rack())
        for sign in (-1,1):
            with self.assertRaisesRegex(ValueError, 'finite float32'):
                execute_rack(np.full(16, sign*1e100),12000,empty_rack(source()))
        x = pcm().astype(np.float64) * 1e20
        self.assertTrue(np.isfinite(execute_rack(x,12000,rack())[0]).all())

    def test_memory_and_work_admission_precede_large_dsp_allocations(self):
        saved = rack(spectral=retune880()); estimate = estimate_rack_resources(saved, 12000)
        self.assertEqual(estimate['spectral_analyses'], 1)
        self.assertGreater(estimate['estimated_live_bytes'], estimate_rack_resources(rack(),12000)['estimated_live_bytes'])
        with patch('zaaggenz_spectral.rack_executor.route_band_processors') as route:
            with self.assertRaisesRegex(ValueError, 'memory'):
                execute_rack(pcm(),12000,saved,max_working_bytes=1)
            route.assert_not_called()
        request = BandSelectiveRequest(slots=(BandSlotSpec(spectral=retune880()),)*4)
        with self.assertRaisesRegex(ValueError, 'work budget'):
            estimate_rack_resources(saved_pcm(request),12000*60)
        for frames in (-1,True,12000*60+1):
            with self.assertRaises(ValueError):estimate_rack_resources(saved,frames)

    def test_cancellation_is_observed_inside_real_compression_and_component_analysis(self):
        for saved in (rack(), rack(spectral=retune880())):
            calls = 0
            def checkpoint():
                nonlocal calls
                calls += 1
                if calls >= 10:raise JobCancelled('test cancellation')
            with self.assertRaisesRegex(JobCancelled, 'test cancellation'):
                execute_rack(pcm(seconds=.8),12000,saved,checkpoint=checkpoint)
            self.assertEqual(calls,10)


if __name__ == '__main__':unittest.main(verbosity=2)
