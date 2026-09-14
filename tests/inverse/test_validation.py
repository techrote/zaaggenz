"""Adversarial engineering gates. No level-matching is applied to losses."""
import unittest
import numpy as np
from zaaggenz_inverse import AudioBuffer, Window, ObjectivePlan, FeatureStore, GatePolicy
from zaaggenz_inverse.contracts import Snapshot
from zaaggenz_inverse.render import Rendered, finish_render, execution_identity, DEFAULT_OUTPUT
from zaaggenz_inverse.objectives import compare_window, aggregate, measurement_values
from zaaggenz_inverse.validation import validate_window, screen_output


class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rate = 12000
        cls.t = np.arange(2048)/cls.rate
        cls.x = .18*np.sin(2*np.pi*187.5*cls.t)+.14*np.sin(2*np.pi*2250*cls.t)
        cls.plan = ObjectivePlan()
        cls.store = FeatureStore(execution_identity())
        cls.window = Window('test', 0, len(cls.x))

    def evaluate(self, target, candidate, *, rendered=None):
        target = AudioBuffer(target, self.rate, 'post_master')
        rendered = rendered or finish_render(candidate, self.rate, {'test': 'explicit-signal'})
        tf = self.store.measure(target, self.plan)
        cf = self.store.measure(rendered.output, self.plan)
        gate = validate_window(target, rendered, self.window, tf, cf, GatePolicy())
        objective = compare_window(target, rendered.output, tf, cf, self.plan)
        return gate, objective

    def test_identity_passes_without_hidden_gain(self):
        g, o = self.evaluate(self.x, self.x)
        self.assertTrue(g['valid'], g)
        self.assertEqual(o['losses']['waveform']['raw'], 0)
        self.assertTrue(g['gain_provenance']['policy_consistent'])

    def test_silence_never_wins_via_shape_or_descriptor_abstention(self):
        g, o = self.evaluate(self.x, np.zeros_like(self.x))
        self.assertIn('silence_collapse', g['codes'])
        self.assertIn('band_energy_collapse', g['codes'])
        self.assertAlmostEqual(o['losses']['waveform']['raw'], 1.)
        a = aggregate([{'objective': o}], self.plan)
        self.assertFalse(a['complete'])
        self.assertIsNone(a['search_score'])
        self.assertTrue(any(c['status'] == 'unavailable' for c in a['components'].values()))

    def test_quieter_copy_is_not_normalised_into_a_good_fit(self):
        g, o = self.evaluate(self.x, self.x*.1)
        self.assertIn('level_mismatch', g['codes'])
        self.assertIn('normalisation_exploit', g['codes'])
        self.assertAlmostEqual(o['losses']['waveform']['raw'], .9, places=6)
        self.assertAlmostEqual(g['level_delta_db'], -20, places=5)
        self.assertLess(g['gain_aligned_diagnostic_only']['gain_aligned_relative_rms'], 1e-6)

    def test_unintended_loudness_increase(self):
        g, _ = self.evaluate(self.x, self.x*4)
        self.assertIn('level_mismatch', g['codes'])
        self.assertIn('fullscale_excess', g['codes'])

    def test_hidden_normalisation_with_matching_output_is_detected(self):
        normal = finish_render(self.x, self.rate, {'test': 'lie-about-gain'})
        lie = Rendered(AudioBuffer(self.x*.1, self.rate, 'pre_master'), normal.output, normal.policy, normal.recipe)
        g, o = self.evaluate(self.x, self.x, rendered=lie)
        self.assertEqual(o['losses']['waveform']['raw'], 0.)
        self.assertIn('gain_provenance_mismatch', g['codes'])
        self.assertIn('normalisation_exploit', g['codes'])

    def test_explicit_gain_has_before_after_provenance(self):
        policy = {**DEFAULT_OUTPUT, 'master_gain_db': 6.}
        r = finish_render(self.x*.5, self.rate, {'test': 'declared'}, policy)
        g, _ = self.evaluate(r.output.audio, r.output.audio, rendered=r)
        self.assertTrue(g['valid'], g)
        p = g['gain_provenance']
        self.assertEqual(p['declared_master_gain_db'], 6.)
        self.assertGreater(p['actual_output_qc']['rms'], p['before_gain_qc']['rms'])

    def test_transient_loss_even_at_similar_whole_level(self):
        base = .025*np.sin(2*np.pi*187.5*self.t)
        target = base.copy(); target[720:760] += .7*np.hanning(80)[40:]
        # Match only energy for this adversary, not the omitted target attack.
        candidate = base*np.sqrt(np.mean(target**2)/np.mean(base**2))
        g, _ = self.evaluate(target, candidate)
        self.assertLess(abs(g['level_delta_db']), .01)
        self.assertGreater(len(g['transient']['target_onset_blocks']), 0)
        self.assertIn('transient_loss', g['codes'])

    def test_internal_clipping_below_full_scale_and_target_clipping_distinguished(self):
        clipped = np.clip(self.x, -.07, .07)
        clipped *= np.sqrt(np.mean(self.x**2)/np.mean(clipped**2))
        g, _ = self.evaluate(self.x, clipped)
        self.assertLess(np.max(np.abs(clipped)), 1.)
        self.assertIn('saturation_excess', g['codes'])
        own, _ = self.evaluate(clipped, clipped)
        self.assertTrue(own['valid'], own)

    def test_final_output_clipping_rejected_even_when_waveform_target_matches(self):
        r = finish_render(self.x*12, self.rate, {'test': 'clipped'}, {**DEFAULT_OUTPUT, 'clipping': 'clip_at_full_scale'})
        g, o = self.evaluate(r.output.audio, r.output.audio, rendered=r)
        self.assertEqual(o['losses']['waveform']['raw'], 0.)
        self.assertIn('destructive_output_clipping', g['codes'])
        self.assertGreater(g['gain_provenance']['output_clip_fraction'], 0.)

    def test_bandwidth_loss_cannot_hide_behind_level_match(self):
        low = np.sin(2*np.pi*187.5*self.t)
        candidate = low*np.sqrt(np.mean(self.x**2)/np.mean(low**2))
        g, _ = self.evaluate(self.x, candidate)
        self.assertLess(abs(g['level_delta_db']), .01)
        self.assertIn('band_energy_collapse', g['codes'])
        self.assertIn('bandwidth_collapse', g['codes'])

    def test_invalid_numeric_output_preflight(self):
        cases = [(np.array([]), 'invalid_shape'), (np.zeros((64,3)), 'invalid_shape'),
                 (np.ones(64,dtype=complex), 'invalid_numeric_type'), (np.array(['x']), 'invalid_numeric_type'),
                 (np.ones(64)*1e7, 'excessive_output')]
        for value, code in cases:
            self.assertEqual(screen_output(value)['code'], code)
        x = np.zeros(64); x[3] = np.nan; x[4] = np.inf
        d = screen_output(x)
        self.assertEqual(d['code'], 'nonfinite_output')
        self.assertEqual(d['finite_fraction'], 62/64)

    def test_stereo_antiphase_does_not_collapse_spectral_energy(self):
        stereo = np.column_stack((self.x, -self.x))
        b = AudioBuffer(stereo, self.rate)
        f = self.store.measure(b, self.plan).to_dict()
        mono = self.store.measure(AudioBuffer(self.x, self.rate), self.plan).to_dict()
        np.testing.assert_allclose(f['band_energy'], mono['band_energy'], rtol=1e-12)
        self.assertGreater(f['qc']['rms'], .1)


if __name__ == '__main__': unittest.main()
