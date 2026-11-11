"""One-command saved Compose -> controlled NYQ -> published stereo WAV."""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
from scipy.io import wavfile
from zaaggenz_runtime import nyquismic_compose_stereo_export as direct


def sha(contents):
    return hashlib.sha256(contents).hexdigest()


class IsolatedOneCommandStereo(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = self.root / "source.zgtimeline.json"
        self.project.write_bytes(b'{"name":"source"}')
        self.dest = self.root / "audition.wav"
        self.wav_pcm = np.column_stack((
            np.full(1200, .25, np.float32),
            np.full(1200, -.5, np.float32)))
        buf = io.BytesIO()
        wavfile.write(buf, 48000, self.wav_pcm)
        self.wav_bytes = buf.getvalue()
        self.events = []
        for module, method, stub in (
            (direct.kit, "export_saved_compose_kit", self.kit),
            (direct.stereo, "bounce_dual_rate_stereo", self.bounce),
        ):
            patcher = mock.patch.object(module, method, side_effect=stub)
            patcher.start()
            self.addCleanup(patcher.stop)

    def kit(self, project, path, *, virtual_rates_hz, evaluation_rate_hz,
            wait_seconds, cancelled):
        self.events.append("kit")
        self.assertEqual(Path(project), self.project)
        self.assertEqual(virtual_rates_hz, ["4/1", "5/1"])
        Path(path).write_bytes(b"ephemeral-kit")
        return {
            "project_file_sha256": sha(self.project.read_bytes()),
            "virtual_rates_hz": virtual_rates_hz,
            "zip_sha256": sha(b"ephemeral-kit"),
            "delivery_hz": 48000, "frames": 1200, "channels": 1,
        }

    def bounce(self, kit_path, path, *, left_rate_hz, right_rate_hz,
               wet_percent, project_path, expected_zip_sha256, cancelled):
        self.events.append("bounce")
        self.assertEqual(Path(kit_path).read_bytes(), b"ephemeral-kit")
        self.assertEqual((left_rate_hz, right_rate_hz), ("4/1", "5/1"))
        self.assertEqual(Path(project_path), self.project)
        self.assertEqual(expected_zip_sha256, sha(b"ephemeral-kit"))
        Path(path).write_bytes(self.wav_bytes)
        return {
            "source_project_sha256": sha(self.project.read_bytes()),
            "kit_sha256": sha(b"ephemeral-kit"),
            "left_rate_hz": left_rate_hz, "right_rate_hz": right_rate_hz,
            "delivery_hz": 48000, "frames": 1200,
            "source_channels": 1, "channels": 2,
            "wav_sha256": sha(self.wav_bytes),
            "pcm_f32le_sha256": sha(self.wav_pcm.astype("<f4").tobytes()),
            "wet_percent": wet_percent, "peak_abs": .5,
            "exceeds_unity_peak": False,
        }

    def export(self, **kwargs):
        args = {"left_rate_hz": "4", "right_rate_hz": "5/1"}
        args.update(kwargs)
        return direct.export_compose_stereo(self.project, self.dest, **args)

    def assert_clean(self):
        self.assertFalse(any(x.name.startswith(".nyq-compose-stereo-")
                             for x in self.root.iterdir()))

    def test_real_source_contract_to_published_wav_and_cleanup(self):
        receipt = self.export(wet_percent="37.5")
        self.assertEqual(self.events, ["kit", "bounce"])
        self.assertEqual(self.dest.read_bytes(), self.wav_bytes)
        self.assertEqual(receipt["source_project_sha256"], sha(self.project.read_bytes()))
        self.assertEqual(receipt["wav_sha256"], sha(self.wav_bytes))
        self.assertEqual(receipt["channels"], 2)
        self.assertEqual(receipt["delivery_hz"], 48000)
        self.assertEqual((receipt["left_rate_hz"], receipt["right_rate_hz"]),
                         ("4/1", "5/1"))
        self.assert_clean()
        with self.assertRaises(ValueError):
            self.export()
        self.assertEqual(self.dest.read_bytes(), self.wav_bytes)

    def test_duplicate_invalid_rates_and_existing_destination_refuse_before_render(self):
        for kwargs in (
            {"left_rate_hz": "4", "right_rate_hz": "4/1"},
            {"left_rate_hz": "0"}, {"right_rate_hz": "5/0"},
            {"left_rate_hz": "NaN"}, {"left_rate_hz": 4},
            {"cancelled": "no"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises((ValueError, TypeError)):
                self.export(**kwargs)
        self.assertEqual(self.events, [])
        self.dest.write_bytes(b"user owned")
        with self.assertRaises(ValueError):
            self.export()
        self.assertEqual(self.dest.read_bytes(), b"user owned")
        self.assert_clean()

    def test_malformed_kit_receipt_prevents_publication(self):
        original = self.kit
        def forged(*args, **kwargs):
            receipt = original(*args, **kwargs)
            receipt["project_file_sha256"] = "0" * 64
            return receipt
        with mock.patch.object(direct.kit, "export_saved_compose_kit", side_effect=forged):
            with self.assertRaisesRegex(RuntimeError, "source/virtual-rate receipt"):
                self.export()
        self.assertEqual(self.events, ["kit"])
        self.assertFalse(self.dest.exists())
        self.assert_clean()

    def test_malformed_stereo_receipt_and_modified_staged_wav_refuse(self):
        original = self.bounce
        def mismatched(*args, **kwargs):
            receipt = original(*args, **kwargs)
            receipt["source_project_sha256"] = "0" * 64
            return receipt
        with mock.patch.object(direct.stereo, "bounce_dual_rate_stereo", side_effect=mismatched):
            with self.assertRaisesRegex(RuntimeError, "disagrees"):
                self.export()
        self.assertFalse(self.dest.exists())
        self.assert_clean()
        self.events.clear()
        def corrupted(*args, **kwargs):
            receipt = original(*args, **kwargs)
            Path(args[1]).write_bytes(b"modified after render")
            return receipt
        with mock.patch.object(direct.stereo, "bounce_dual_rate_stereo", side_effect=corrupted):
            with self.assertRaisesRegex(RuntimeError, "staged WAV differs"):
                self.export()
        self.assertFalse(self.dest.exists())
        self.assert_clean()

    def test_project_mutation_between_stages_cannot_publish(self):
        original = self.kit
        def stale(*args, **kwargs):
            receipt = original(*args, **kwargs)
            self.project.write_bytes(b"changed")
            return receipt
        with mock.patch.object(direct.kit, "export_saved_compose_kit", side_effect=stale):
            with self.assertRaisesRegex(RuntimeError, "source/virtual-rate receipt|disagrees|project changed"):
                self.export()
        self.assertFalse(self.dest.exists())
        self.assert_clean()

    def test_cancel_after_link_retracts_own_publication(self):
        linked = [False]
        os_link = os.link
        def after_link(a, b):
            os_link(a, b)
            linked[0] = True
        with mock.patch.object(direct.os, "link", side_effect=after_link):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.export(cancelled=lambda: linked[0])
        self.assertTrue(linked[0])
        self.assertFalse(self.dest.exists())
        self.assert_clean()

    def test_project_edit_after_link_retracts_own_publication(self):
        os_link = os.link
        def after_link(a, b):
            os_link(a, b)
            self.project.write_bytes(b"changed after link")
        with mock.patch.object(direct.os, "link", side_effect=after_link):
            with self.assertRaisesRegex(RuntimeError, "project changed during publication"):
                self.export()
        self.assertFalse(self.dest.exists())
        self.assert_clean()

    def test_competing_replacement_is_preserved(self):
        os_link = os.link
        def foreign(a, b):
            os_link(a, b)
            replacement = self.root / "foreign.wav"
            replacement.write_bytes(b"rival writer")
            os.replace(replacement, b)
            self.project.write_bytes(b"changed")
        with mock.patch.object(direct.os, "link", side_effect=foreign):
            with self.assertRaisesRegex(RuntimeError, "project changed"):
                self.export()
        self.assertEqual(self.dest.read_bytes(), b"rival writer")
        self.assert_clean()

    def test_competing_file_at_link_is_not_overwritten(self):
        def competing(a, b):
            Path(b).write_bytes(b"rival writer")
            raise FileExistsError(b)
        with mock.patch.object(direct.os, "link", side_effect=competing):
            with self.assertRaises(FileExistsError):
                self.export()
        self.assertEqual(self.dest.read_bytes(), b"rival writer")
        self.assert_clean()


class OriginalSavedComposeToStereoWav(unittest.TestCase):
    def test_real_compose_packet_sampler_to_stereo_output(self):
        root = Path(__file__).resolve().parents[2]
        if not (root / "zaaggenz_runtime" / "nyquismic_offline_audition.py").is_file():
            self.skipTest("original full source-backed NYQ runtime required")
        from test_nyquismic_compose_delivery import source_document
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "real.zgtimeline.json"
            project.write_text(json.dumps(source_document()), encoding="utf-8")
            target = Path(folder) / "live-stereo.wav"
            receipt = direct.export_compose_stereo(
                project, target, left_rate_hz="4", right_rate_hz="5",
                wet_percent="100")
            rate, pcm = wavfile.read(target)
            self.assertEqual(rate, 48000)
            self.assertEqual(pcm.dtype, np.float32)
            self.assertEqual(pcm.shape, (28800, 2))
            self.assertEqual(receipt["frames"], 28800)
            self.assertEqual(receipt["source_channels"], 1)
            self.assertEqual(receipt["source_project_sha256"], sha(project.read_bytes()))
            self.assertEqual(receipt["wav_sha256"], sha(target.read_bytes()))
            self.assertEqual(receipt["pcm_f32le_sha256"], sha(pcm.astype("<f4").tobytes()))
            self.assertNotEqual(sha(pcm[:, 0].tobytes()), sha(pcm[:, 1].tobytes()))
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()),
                             ["live-stereo.wav", "real.zgtimeline.json"])
            print("NYQ_COMPOSE_STEREO_ONE_STEP_PCM " + json.dumps({
                "source_project_sha256": receipt["source_project_sha256"],
                "kit_sha256": receipt["kit_sha256"],
                "wav_sha256": receipt["wav_sha256"],
                "pcm_f32le_sha256": receipt["pcm_f32le_sha256"],
                "frames": receipt["frames"], "delivery_hz": rate,
                "left_rate_hz": receipt["left_rate_hz"],
                "right_rate_hz": receipt["right_rate_hz"],
            }, sort_keys=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
