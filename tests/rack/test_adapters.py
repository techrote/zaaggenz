"""Actual legacy DSP parity and strict, non-lossy compatibility boundaries."""
from copy import deepcopy
from itertools import permutations
import unittest
from unittest.mock import patch
import numpy as np

from zaaggenz_contracts import ContractError
from zaaggenz_contracts.rack import RackRecipe, RackCompatibilityError, empty_rack, STAGES
from zaaggenz_spectral.band_selective import BandSelectiveRequest, BandSlotSpec, process_band_selective
from zaaggenz_spectral.rack_adapter import (request_to_rack, rack_to_request, execution_request,
                                           slot_to_band, band_to_slot, insert_spec)
from helpers import source, slot, rack, retune, chordness, insert, external


def signal(stereo=False):
    t = np.arange(2400) / 12000
    x = (.3 * np.sin(2 * np.pi * 247 * t) + .2 * np.sin(2 * np.pi * 820 * t))
    return np.column_stack((x, -.7*x)).astype('float32') if stereo else x.astype('float32')


class RackAdapterTests(unittest.TestCase):
    def test_all_24_orders_and_every_parameter_round_trip(self):
        base = source()
        for spectral in (None, retune(base), chordness()):
            for order in permutations(STAGES):
                with self.subTest(spectral=type(spectral).__name__, order=order):
                    original = BandSelectiveRequest((100., 500., 3500.),
                        (None, slot(spectral, order), BandSlotSpec(), None), (False, True, False, True))
                    saved = request_to_rack(original, base)
                    actual = rack_to_request(RackRecipe.from_json(saved.to_json()))
                    self.assertEqual(actual.to_dict(12000), original.to_dict(12000))
                    self.assertIsNone(actual.slots[0])
                    self.assertIsNotNone(actual.slots[2])  # absent vs present identity retained
                    self.assertEqual(band_to_slot(slot_to_band(original.slots[1], band='lowmid'), base),
                                     original.slots[1])

    def test_numerical_parity_all_orders_and_both_channel_layouts(self):
        base = source()
        for order in permutations(STAGES):
            for stereo in (False, True):
                with self.subTest(order=order, stereo=stereo):
                    original = BandSelectiveRequest(slots=(None, slot(order=order), None, None),
                                                    confine_delta=(True, False, True, True))
                    converted = rack_to_request(request_to_rack(original, base))
                    audio = signal(stereo)
                    expected = process_band_selective(audio, 12000, original)
                    actual = process_band_selective(audio, 12000, converted)
                    np.testing.assert_array_equal(actual.audio, expected.audio)
                    self.assertEqual(actual.diagnostics, expected.diagnostics)
                    self.assertFalse(np.array_equal(actual.audio, audio))  # not only identity tested

    def test_actual_retune_and_chordness_numerical_parity(self):
        for spectral in (retune(), chordness()):
            for order in (STAGES, tuple(reversed(STAGES))):
                for stereo in (False, True):
                    with self.subTest(spectral=type(spectral).__name__, order=order, stereo=stereo):
                        original = BandSelectiveRequest(slots=(None, slot(spectral, order), None, None))
                        expected = process_band_selective(signal(stereo), 12000, original)
                        actual = process_band_selective(signal(stereo), 12000,
                                                       rack_to_request(request_to_rack(original, source())))
                        np.testing.assert_array_equal(actual.audio, expected.audio)
                        self.assertEqual(actual.request.to_dict(), original.to_dict())

    def test_bypass_projection_is_exact_identity_and_does_not_erase_saved_settings(self):
        mutations = [lambda d: d.update(bypass=True), lambda d: d.update(wet=0),
            lambda d: d['bands'][1].update(bypass=True), lambda d: d['bands'][1].update(wet=0),
            lambda d: [i.update(bypass=True) for i in d['bands'][1]['inserts']],
            lambda d: [i.update(wet=0) for i in d['bands'][1]['inserts']]]
        variants = [empty_rack(source())]
        for mutate in mutations:
            data = rack(spectral=retune()).to_dict(); mutate(data); variants.append(RackRecipe(data))
        for saved in variants:
            before = saved.to_json()
            for stereo in (False, True):
                audio = signal(stereo)
                actual = process_band_selective(audio, 12000, execution_request(saved)).audio
                self.assertEqual(actual.dtype, audio.dtype)
                self.assertEqual(actual.shape, audio.shape)
                self.assertEqual(actual.tobytes(), audio.tobytes())
            self.assertEqual(saved.to_json(), before)
        for stage in STAGES:
            data = rack(spectral=retune()).to_dict(); insert(data, stage)['bypass'] = True
            saved = RackRecipe(data)
            projected = execution_request(saved).slots[1]
            self.assertEqual(getattr(projected, 'gain_db' if stage == 'gain' else stage),
                             0. if stage == 'gain' else None)
            self.assertEqual(saved.to_dict()['bands'][1]['inserts'], data['bands'][1]['inserts'])

    def test_old_contract_is_not_redefined_to_an_arbitrary_chain(self):
        for mutate in [lambda d: d.update(bypass=True), lambda d: d.update(wet=.5),
                       lambda d: d['bands'][1].update(bypass=True),
                       lambda d: d['bands'][1].update(wet=.5),
                       lambda d: insert(d).update(bypass=True), lambda d: insert(d).update(wet=.5),
                       lambda d: d['bands'][1]['inserts'].pop()]:
            data = rack().to_dict(); mutate(data)
            with self.assertRaises(RackCompatibilityError): rack_to_request(RackRecipe(data))
        for mutate in [lambda d: d.update(wet=.5), lambda d: d['bands'][1].update(wet=.5),
                       lambda d: insert(d).update(wet=.5), lambda d: d['bands'][1]['inserts'].pop()]:
            data = rack().to_dict(); mutate(data)
            with self.assertRaises(RackCompatibilityError): execution_request(RackRecipe(data))
        data = rack().to_dict(); data['bands'][1]['inserts'].pop(); data['bypass'] = True
        self.assertTrue(all(s is None for s in execution_request(data).slots))

    def test_external_descriptors_never_execute_or_become_silent_identity(self):
        data = rack().to_dict(); ext = external(); data['bands'][1]['inserts'].append(ext)
        for bypass in (False, True):
            data['bypass'] = bypass; saved = RackRecipe(data)
            for convert in (rack_to_request, execution_request):
                with self.assertRaisesRegex(RackCompatibilityError, 'VST3'): convert(saved)
        with self.assertRaisesRegex(RackCompatibilityError, 'not an executable host'):
            insert_spec(ext, 12000)

    def test_invalid_bypassed_parameters_fail_before_any_dsp_allocation(self):
        data = rack().to_dict(); data['bypass'] = True
        insert(data)['params']['ratio'] = float('nan')
        with patch('zaaggenz_dsp.band_router.route_band_processors') as route:
            with self.assertRaises(ContractError): execution_request(data)
            route.assert_not_called()
        with self.assertRaises(ContractError): rack_to_request(rack(), execution=1)
        for invalid in (None, [], 'band'):
            with self.assertRaises(ContractError): band_to_slot(invalid, source())


if __name__ == '__main__': unittest.main()
