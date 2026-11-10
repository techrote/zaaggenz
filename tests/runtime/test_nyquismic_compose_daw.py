"""One-command saved Compose -> source-verified 48-kHz WAVs and fail-closed publication."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from zaaggenz_runtime import nyquismic_compose_daw as direct


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class IsolatedDirectDaw(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.project = self.root / 'song.zgtimeline.json'
        self.project.write_bytes(b'{"a":1}')
        self.output = self.root / 'daw.zip'
        self.events = []
        self.sweep_raw = b'synthetic-authenticated-sweep'
        self.stems_raw = b'synthetic-original-and-nyquismic-wav-archive'
        self.sweep_patcher = mock.patch.object(direct.sweep, 'export_saved_compose_rate_sweep', self.sweep)
        self.stems_patcher = mock.patch.object(direct.stems, 'export_daw_stems', self.stems)
        self.sweep_patcher.start()
        self.stems_patcher.start()
        self.addCleanup(self.sweep_patcher.stop)
        self.addCleanup(self.stems_patcher.stop)

    def sweep(self, project, output, *, virtual_rates_hz, evaluation_rate_hz, wait_seconds, cancelled):
        self.events.append(('sweep', list(virtual_rates_hz)))
        Path(output).write_bytes(self.sweep_raw)
        return {'project_file_sha256': sha(Path(project).read_bytes()),
                'source_asset_sha256': '1'*64, 'dry_pcm_f32le_sha256': '2'*64,
                'archive_sha256': sha(self.sweep_raw), 'rates_hz': list(virtual_rates_hz)}

    def stems(self, sweep, output, *, cancelled):
        self.events.append(('stems', sha(Path(sweep).read_bytes())))
        Path(output).write_bytes(self.stems_raw)
        return {'source_sweep_sha256': sha(self.sweep_raw), 'zip_sha256': sha(self.stems_raw),
                'delivery_hz': 48000, 'stems': [{}, {}, {}]}

    def execute(self, **kwargs):
        return direct.export_saved_compose_daw(self.project, self.output,
                                               virtual_rates_hz=['4', '5/1'], **kwargs)

    def assert_stage_clean(self):
        self.assertFalse(any(p.name.startswith('.nyq-direct-daw-') for p in self.root.iterdir()))

    def test_exact_composition_receipts_and_cold_reopen(self):
        result = self.execute()
        self.assertEqual(result['delivery_hz'], 48000)
        self.assertEqual(result['virtual_rates_hz'], ['4/1', '5/1'])
        self.assertEqual(result['project_file_sha256'], sha(self.project.read_bytes()))
        self.assertEqual(result['zip_sha256'], sha(self.output.read_bytes()))
        self.assertEqual(self.output.read_bytes(), self.stems_raw)
        self.assertEqual([e[0] for e in self.events], ['sweep', 'stems'])
        self.assert_stage_clean()
        self.output.rename(self.root / 'original.zip')
        self.events.clear()
        self.assertEqual(self.execute()['zip_sha256'], result['zip_sha256'])
        self.assertEqual(self.output.read_bytes(), (self.root / 'original.zip').read_bytes())
        self.assert_stage_clean()

    def test_existing_destination_preflight_does_not_render(self):
        self.output.write_bytes(b'user-owned-original')
        with self.assertRaises(FileExistsError):
            self.execute()
        self.assertEqual(self.output.read_bytes(), b'user-owned-original')
        self.assertEqual(self.events, [])
        self.assert_stage_clean()

    def test_bad_input_and_rate_budgets_fail_before_renderer(self):
        for rates in (['4'], ['0', '5'], ['4', '4/1'], ['4']*7):
            with self.subTest(rates=rates), self.assertRaises(ValueError):
                direct.export_saved_compose_daw(self.project, self.output, virtual_rates_hz=rates)
        with self.assertRaises(ValueError):
            self.execute(evaluation_rate_hz=48000)
        with self.assertRaises(ValueError):
            self.execute(wait_seconds=0)
        with self.assertRaises(ValueError):
            self.execute(cancelled=True)
        with self.assertRaises(ValueError):
            direct.export_saved_compose_daw(self.project, self.root / 'wrong.wav', virtual_rates_hz=['4','5'])
        with self.assertRaises(ValueError):
            direct.export_saved_compose_daw(self.root / 'missing.zgtimeline.json', self.output,
                                            virtual_rates_hz=['4','5'])
        self.assertEqual(self.events, [])
        self.assert_stage_clean()

    def test_oversized_saved_project_does_not_render(self):
        self.project.write_bytes(b'x' * (direct.sweep.MAX_PROJECT_BYTES + 1))
        with self.assertRaisesRegex(ValueError, '2 MB'):
            self.execute()
        self.assertEqual(self.events, [])

    def test_cancel_between_render_and_archive_does_not_publish(self):
        flag = [False]
        original = self.sweep
        def cancel_after_render(*args, **kwargs):
            result = original(*args, **kwargs)
            flag[0] = True
            return result
        with mock.patch.object(direct.sweep, 'export_saved_compose_rate_sweep', side_effect=cancel_after_render):
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                self.execute(cancelled=lambda: flag[0])
        self.assertFalse(self.output.exists())
        self.assert_stage_clean()

    def test_mismatched_sweep_source_hash_rejected_before_stems(self):
        original = self.sweep
        def forged(*args, **kwargs):
            receipt = original(*args, **kwargs)
            receipt['project_file_sha256'] = '0'*64
            return receipt
        with mock.patch.object(direct.sweep, 'export_saved_compose_rate_sweep', side_effect=forged):
            with self.assertRaisesRegex(RuntimeError, 'sweep receipt'):
                self.execute()
        self.assertEqual([e[0] for e in self.events], ['sweep'])
        self.assertFalse(self.output.exists())
        self.assert_stage_clean()

    def test_mismatched_stem_archive_or_delivery_refused(self):
        original = self.stems
        def forged(*args, **kwargs):
            receipt = original(*args, **kwargs)
            receipt['delivery_hz'] = 44100
            return receipt
        with mock.patch.object(direct.stems, 'export_daw_stems', side_effect=forged):
            with self.assertRaisesRegex(RuntimeError, 'stems receipt'):
                self.execute()
        self.assertFalse(self.output.exists())
        self.assert_stage_clean()

    def test_project_mutation_after_render_prevents_publication(self):
        original = self.stems
        def mutate(*args, **kwargs):
            result = original(*args, **kwargs)
            self.project.write_bytes(b'{"a":2}')
            return result
        with mock.patch.object(direct.stems, 'export_daw_stems', side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, 'project changed'):
                self.execute()
        self.assertFalse(self.output.exists())
        self.assert_stage_clean()

    def test_competing_writer_cannot_be_overwritten(self):
        def competitor(stage, destination):
            Path(destination).write_bytes(b'other-writer')
            raise FileExistsError(destination)
        with mock.patch.object(direct.os, 'link', side_effect=competitor):
            with self.assertRaises(FileExistsError):
                self.execute()
        self.assertEqual(self.output.read_bytes(), b'other-writer')
        self.assert_stage_clean()

    def test_final_cancel_after_stem_export_cleans_staging(self):
        flag = [False]
        original = self.stems
        def cancel_after_stems(*args, **kwargs):
            result = original(*args, **kwargs)
            flag[0] = True
            return result
        with mock.patch.object(direct.stems, 'export_daw_stems', side_effect=cancel_after_stems):
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                self.execute(cancelled=lambda: flag[0])
        self.assertFalse(self.output.exists())
        self.assert_stage_clean()


    def test_final_link_window_cancellation_rolls_back_own_output(self):
        # Reproduce the independently reported gap: callback changes state
        # inside os.link, AFTER the exporter's previous final _check.
        flag = [False]
        real_link = direct.os.link

        def cancel_at_commit(source, destination):
            flag[0] = True
            return real_link(source, destination)

        with mock.patch.object(direct.os, 'link', side_effect=cancel_at_commit):
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                self.execute(cancelled=lambda: flag[0])
        self.assertFalse(self.output.exists())
        self.assert_stage_clean()

    def test_final_link_window_project_edit_rolls_back_own_output(self):
        real_link = direct.os.link

        def edit_at_commit(source, destination):
            self.project.write_bytes(b'{"a":99}')
            return real_link(source, destination)

        with mock.patch.object(direct.os, 'link', side_effect=edit_at_commit):
            with self.assertRaisesRegex(RuntimeError, 'project changed during DAW publication'):
                self.execute()
        self.assertFalse(self.output.exists())
        self.assert_stage_clean()

    def test_after_actual_link_cancellation_and_project_edit_roll_back(self):
        real_link = direct.os.link
        for change in ('cancel', 'project'):
            with self.subTest(change=change):
                flag = [False]

                def change_after_commit(source, destination):
                    real_link(source, destination)
                    if change == 'cancel':
                        flag[0] = True
                    else:
                        self.project.write_bytes(b'{"a":44}')

                with mock.patch.object(direct.os, 'link', side_effect=change_after_commit):
                    with self.assertRaisesRegex(RuntimeError, 'cancelled|project changed'):
                        self.execute(cancelled=lambda: flag[0])
                self.assertFalse(self.output.exists())
                self.assert_stage_clean()
                self.project.write_bytes(b'{"a":1}')

    def test_rollback_never_unlinks_another_writers_replacement(self):
        real_link = direct.os.link
        foreign = self.root / 'foreign.zip'

        def replace_just_after_link(source, destination):
            real_link(source, destination)
            foreign.write_bytes(b'other-writer-owned-output')
            foreign.replace(destination)
            self.project.write_bytes(b'{"a":76}')

        with mock.patch.object(direct.os, 'link', side_effect=replace_just_after_link):
            with self.assertRaisesRegex(RuntimeError, 'project changed during DAW publication'):
                self.execute()
        self.assertEqual(self.output.read_bytes(), b'other-writer-owned-output')
        self.assertFalse(foreign.exists())
        self.assert_stage_clean()


class OriginalSavedComposeDirectDaw(unittest.TestCase):
    def test_real_compose_to_original_wav_bundle(self):
        root = Path(__file__).resolve().parents[2]
        if not (root / 'zaaggenz_runtime' / 'nyquismic_offline_audition.py').is_file():
            self.skipTest('requires full original-host checkout of production NYQ chain')
        from test_nyquismic_compose_delivery import source_document
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / 'song.zgtimeline.json'
            project.write_text(json.dumps(source_document()), encoding='utf-8')
            destination = Path(folder) / 'nyq-daw.zip'
            receipt = direct.export_saved_compose_daw(
                project, destination, virtual_rates_hz=['4/1', '5/1'])
            self.assertEqual(receipt['delivery_hz'], 48000)
            self.assertEqual(receipt['project_file_sha256'], sha(project.read_bytes()))
            self.assertEqual(receipt['zip_sha256'], sha(destination.read_bytes()))
            self.assertEqual(len(receipt['stems']), 3)
            with zipfile.ZipFile(destination) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                self.assertEqual(manifest['sample_rate_hz'], 48000)
                self.assertEqual(manifest['frames'], 28800)
                self.assertEqual(manifest['source_sweep_sha256'], receipt['source_sweep_sha256'])
                self.assertEqual([i['virtual_rate_hz'] for i in manifest['stems'][1:]], ['4/1', '5/1'])
                for entry in manifest['stems']:
                    wav = archive.read(entry['file'])
                    self.assertEqual(sha(wav), entry['wav_sha256'])
            print('NYQ_DIRECT_DAW_COMPOSE ' + json.dumps({
                'frames':manifest['frames'], 'delivery_hz':48000,
                'dry_wav_sha256':manifest['stems'][0]['wav_sha256'],
                'wet_pcm_f32le_sha256':[e['pcm_f32le_sha256'] for e in manifest['stems'][1:]],
                'bundle_sha256':receipt['zip_sha256']},sort_keys=True))
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()),
                             ['nyq-daw.zip', 'song.zgtimeline.json'])


if __name__=='__main__':
    unittest.main(verbosity=2)
