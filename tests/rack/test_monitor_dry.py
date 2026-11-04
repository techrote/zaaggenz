"""Raw/dry A/B must not adopt a detached project or publish stale PCM."""
import time
import unittest

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
