"""Raw/dry A/B must not adopt a detached project or publish stale PCM."""
import time
import unittest
import numpy as np
from zaaggenz_dsp.multiband import split_bands
from zaaggenz_timeline.model import compile_recipe

from zaaggenz_jobs import JobError
from zaaggenz_timeline.model import default_document
from zaaggenz_timeline.rack_edit import edit_rack, editor_state
from zaaggenz_timeline.service import TimelineService


class RawDryMonitorTests(unittest.TestCase):
    def setUp(self):
        self.service = TimelineService(debounce_seconds=0)
        self.original = default_document(12000)

    def tearDown(self):
        self.service.close()

    def prepared(self):
        current = edit_rack(self.original, {'kind': 'enable'})
        band = editor_state(current)['value']['bands'][1]['id']
        current = edit_rack(current, {'kind': 'add', 'band': band, 'type_id': 'zg.gain'})
        stage = editor_state(current)['value']['bands'][1]['inserts'][0]['id']
        return edit_rack(current, {
            'kind': 'set', 'scope': 'parameter', 'id': band + '/' + stage,
            'field': 'gain_db', 'value': 9.0,
        })

    def test_dry_comparison_is_detached_and_revoked_by_new_source(self):
        processed = self.prepared()
        self.service.validate(processed.to_dict())
        identity = self.service.session.current_identity()
        owned_document = self.service.session.snapshot()
        submitted = self.service.submit_dry_monitor(processed.to_dict())
        self.assertEqual(submitted['monitor_source_revision_id'], processed.revision_id)
        self.assertEqual(submitted['monitor_policy'], 'non-authoritative dry; no export slot')
        self.assertNotEqual(submitted['revision_id'], processed.revision_id)
        self.assertEqual(self.service.session.current_identity(), identity)
        self.assertEqual(self.service.session.snapshot(), owned_document)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = self.service.status(submitted['job_id'])
            if state['state'] in ('completed', 'failed', 'cancelled', 'stale'):
                break
            time.sleep(.025)
        self.assertEqual(state['state'], 'completed', state)
        wav, revision = self.service.wave(submitted['job_id'])
        self.assertEqual(revision, submitted['revision_id'])
        self.assertGreater(len(wav), 44)
        self.assertEqual(self.service.session.current_identity(), identity)
        self.service.validate(self.original.to_dict())
        self.assertEqual(self.service.status(submitted['job_id'])['state'], 'stale')
        with self.assertRaises(JobError):
            self.service.wave(submitted['job_id'])

    def _completed(self, job_id):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            state = self.service.status(job_id)
            if state['state'] in ('completed', 'failed', 'cancelled', 'stale'):
                break
            time.sleep(.025)
        self.assertEqual(state['state'], 'completed', state)
        return self.service.artifact(job_id)

    def test_post_master_band_solo_mute_detached_numerical_filter(self):
        # The default document is silent. Use actual source-derived note PCM
        # so a vacuous zero result cannot pass the independent band oracle.
        from zaaggenz_timeline.model import TimelineDocument
        data = self.original.to_dict()
        data['end_beat'] = '1/1'
        data['notes'] = [{'id':'n1', 'beat':'0/1', 'duration_beats':'1/1',
                          'degree':0, 'detune_cents':0., 'gain_db':0.,
                          'muted':False, 'roll_density':0}]
        data['next_id'] = 1
        self.original = TimelineDocument(data)
        document = self.prepared()
        self.service.validate(document.to_dict())
        identity = self.service.session.current_identity()
        session = self.service.session.snapshot()
        normal = self.service.submit(document.to_dict(), authoritative=False)
        reference = self._completed(normal['job_id'])
        original = np.frombuffer(reference.audio_bytes, dtype='<f4')
        crossovers = compile_recipe(document).to_dict()['rack']['crossovers']['frequencies_hz']
        isolated = split_bands(original, 12000, crossovers)[1]
        self.assertGreater(np.max(np.abs(original)), 0)
        for mode, expected in (('solo', isolated),
                               ('mute', original.astype(np.float64) - isolated)):
            submitted = self.service.submit_band_monitor(document.to_dict(), 'lowmid', mode)
            self.assertEqual(submitted['monitor_source_revision_id'], document.revision_id)
            self.assertEqual((submitted['monitor_band'], submitted['monitor_mode']), ('lowmid', mode))
            self.assertEqual(submitted['monitor_policy'],
                             'non-authoritative post-master band; no export slot')
            actual = self._completed(submitted['job_id'])
            self.assertEqual(actual.revision_id, reference.revision_id)
            self.assertNotEqual(actual.cache_key, reference.cache_key)
            np.testing.assert_array_equal(np.frombuffer(actual.audio_bytes, dtype='<f4'),
                                          np.asarray(expected, dtype='<f4'))
            self.assertEqual(actual.scopes['diagnostics']['monitor']['mode'], mode)
            self.assertNotIn('rack', actual.scopes['diagnostics'])
            self.assertEqual(self.service.session.current_identity(), identity)
            self.assertEqual(self.service.session.snapshot(), session)
        self.service.validate(self.original.to_dict())
        self.assertEqual(self.service.status(submitted['job_id'])['state'], 'stale')
        with self.assertRaises(JobError):
            self.service.wave(submitted['job_id'])

    def test_rejects_invalid_or_stale_band_monitor_requests(self):
        with self.assertRaisesRegex(JobError, 'installed rack'):
            self.service.submit_band_monitor(self.original.to_dict(), 'lowmid', 'solo')
        document = self.prepared()
        self.service.validate(document.to_dict())
        for band, mode in ((True, 'solo'), ('bass', 'solo'), ('lowmid', None),
                           ('lowmid', 'stereo'), ('lowmid', True)):
            with self.subTest(band=band, mode=mode), self.assertRaises(JobError):
                self.service.submit_band_monitor(document.to_dict(), band, mode)
        self.service.validate(self.original.to_dict())
        with self.assertRaisesRegex(JobError, 'current Compose'):
            self.service.submit_band_monitor(document.to_dict(), 'lowmid', 'mute')

    def test_rejects_dry_projects_and_stale_processed_revisions(self):
        with self.assertRaises(JobError):
            self.service.submit_dry_monitor(self.original.to_dict())
        processed = self.prepared()
        self.service.validate(processed.to_dict())
        with self.assertRaises(JobError):
            self.service.submit_dry_monitor(self.original.to_dict())
        self.service.validate(self.original.to_dict())
        with self.assertRaises(JobError):
            self.service.submit_dry_monitor(processed.to_dict())


if __name__ == '__main__':
    unittest.main()
