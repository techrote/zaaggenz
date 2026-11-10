"""One-shot NYQ listening and DAW kit: source/PCM identity and final-link regressions."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from zaaggenz_runtime import nyquismic_production_kit as kit


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class IsolatedProductionKit(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = self.root / "song.zgtimeline.json"
        self.project.write_bytes(b'{"a":1}')
        self.output = self.root / "kit.zip"
        self.sweep_raw = b"source-authenticated-sweep"
        self.audio = [b"dry-original", b"nyq-4-hz", b"nyq-5-hz"]
        self.rates = ["4/1", "5/1"]
        self.calls = []
        self.anchor = {
            "project_file_sha256": sha(self.project.read_bytes()),
            "source_asset_sha256": "1" * 64,
            "source_revision_sha256": "2" * 64,
            "compose_recipe_sha256": "3" * 64,
            "dry_pcm_f32le_sha256": sha(self.audio[0]),
            "frames": 28800, "channels": 1,
        }
        self.items = [
            {"file": "original.wav", "wav_sha256": sha(self.audio[0]),
             "pcm_f32le_sha256": sha(self.audio[0]),
             "virtual_rate_hz": None, "packet_sha256": None},
        ]
        for i, rate in enumerate(self.rates, 1):
            self.items.append({
                "file": f"nyq-rate-{i:02d}.wav", "wav_sha256": sha(self.audio[i]),
                "pcm_f32le_sha256": sha(self.audio[i]), "virtual_rate_hz": rate,
                "packet_sha256": sha(("packet" + rate).encode()),
            })
        for module, name, method in (
                (kit.sweep, "export_saved_compose_rate_sweep", self.sweep),
                (kit.compare, "_verified_sweep", self.verify),
                (kit.stems, "export_daw_stems", self.stems),
                (kit.compare, "publish_rate_comparison", self.listener)):
            patcher = mock.patch.object(module, name, side_effect=method)
            patcher.start()
            self.addCleanup(patcher.stop)

    def sweep(self, project, output, *, virtual_rates_hz, evaluation_rate_hz, wait_seconds, cancelled):
        self.calls.append("sweep")
        self.assertEqual(virtual_rates_hz, self.rates)
        Path(output).write_bytes(self.sweep_raw)
        return {
            "project_file_sha256": sha(Path(project).read_bytes()),
            "source_asset_sha256": self.anchor["source_asset_sha256"],
            "dry_pcm_f32le_sha256": self.anchor["dry_pcm_f32le_sha256"],
            "archive_sha256": sha(self.sweep_raw), "rates_hz": virtual_rates_hz,
        }

    def verify(self, path, cancelled=None):
        self.calls.append("verify")
        self.assertEqual(Path(path).read_bytes(), self.sweep_raw)
        return {
            "archive_sha256": sha(self.sweep_raw), "source": self.anchor,
            "frames": 28800, "channels": 1, "dry": self.audio[0],
            "variants": [
                {"rate": rate, "wet": self.audio[i],
                 "wet_pcm_sha256": self.items[i]["pcm_f32le_sha256"],
                 "packet_sha256": self.items[i]["packet_sha256"]}
                for i, rate in enumerate(self.rates, 1)
            ],
        }

    def stems(self, source, target, *, cancelled=None):
        self.calls.append("stems")
        manifest = {
            "format": kit.stems.FORMAT, "source_sweep_sha256": sha(self.sweep_raw),
            "source": self.anchor, "sample_rate_hz": 48000,
            "frames": 28800, "channels": 1, "stems": self.items,
        }
        with zipfile.ZipFile(target, "w") as archive:
            kit.stems._entry(archive, "manifest.json", json.dumps(manifest).encode())
            for entry, wav in zip(self.items, self.audio):
                kit.stems._entry(archive, entry["file"], wav)
        return {
            "source_sweep_sha256": sha(self.sweep_raw),
            "zip_sha256": sha(Path(target).read_bytes()),
            "delivery_hz": 48000, "stems": self.items,
        }

    def listener(self, source, target, *, cancelled=None):
        self.calls.append("listener")
        receipt = {"archive_sha256": sha(self.sweep_raw), "source": self.anchor}
        payload = {"receipt": receipt, "frames": 28800, "channels": 1,
                   "wavs": [base64.b64encode(x).decode() for x in self.audio]}
        page = ('<html><script id="nyq-compare-payload" type="application/json">'
                + json.dumps(payload) + '</script></html>').encode()
        Path(target).write_bytes(page)
        return {
            "html_sha256": sha(page), "source_zip_sha256": sha(self.sweep_raw),
            "delivery_hz": 48000, "rates_hz": self.rates,
            "frames": 28800, "channels": 1,
        }

    def export(self, **kw):
        return kit.export_saved_compose_kit(
            self.project, self.output, virtual_rates_hz=["4", "5/1"], **kw)

    def assert_clean(self):
        self.assertFalse(any(x.name.startswith(".nyq-production-kit-") for x in self.root.iterdir()))

    def test_one_render_per_rate_cold_reopen_and_audio_identity(self):
        receipt = self.export()
        self.assertEqual(receipt["delivery_hz"], 48000)
        self.assertEqual(self.calls, ["sweep", "verify", "stems", "listener"])
        self.assertEqual(receipt["zip_sha256"], sha(self.output.read_bytes()))
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.namelist(), [
                "manifest.json", "listen.html", "original.wav",
                "nyq-rate-01.wav", "nyq-rate-02.wav"])
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["source"], self.anchor)
            self.assertEqual(manifest["sample_rate_hz"], 48000)
            for entry, audio in zip(manifest["tracks"], self.audio):
                self.assertEqual(archive.read(entry["file"]), audio)
        first = self.output.read_bytes()
        self.output.rename(self.root / "previous.zip")
        self.calls.clear()
        self.assertEqual(self.export()["zip_sha256"], sha(first))
        self.assertEqual(self.output.read_bytes(), first)
        self.assert_clean()

    def test_invalid_request_and_collision_abort_before_render(self):
        for values in (["4"], ["4", "4/1"], ["4", "0"], ["4"] * 7):
            with self.subTest(values=values), self.assertRaises(ValueError):
                kit.export_saved_compose_kit(self.project, self.output, virtual_rates_hz=values)
        with self.assertRaises(ValueError):
            self.export(evaluation_rate_hz=44100)
        with self.assertRaises(ValueError):
            self.export(cancelled=1)
        self.output.write_bytes(b"user-owned")
        with self.assertRaises(FileExistsError):
            self.export()
        self.assertEqual(self.output.read_bytes(), b"user-owned")
        self.assertEqual(self.calls, [])

    def test_changed_project_after_render_aborts(self):
        real = self.listener
        def edit(*args, **kwargs):
            result = real(*args, **kwargs)
            self.project.write_bytes(b'{"a":2}')
            return result
        with mock.patch.object(kit.compare, "publish_rate_comparison", side_effect=edit):
            with self.assertRaisesRegex(RuntimeError, "project changed"):
                self.export()
        self.assertFalse(self.output.exists())
        self.assert_clean()

    def test_corrupt_source_pcm_and_packet_cannot_publish(self):
        original = self.stems
        def forged(*args, **kwargs):
            result = original(*args, **kwargs)
            self.items[1]["packet_sha256"] = "9" * 64
            return result
        with mock.patch.object(kit.stems, "export_daw_stems", side_effect=forged):
            with self.assertRaisesRegex(RuntimeError, "wet PCM/clock packet"):
                self.export()
        self.assertFalse(self.output.exists())
        self.assert_clean()

    def test_listener_wav_differing_from_daw_is_rejected(self):
        original = self.listener
        def forged(*args, **kwargs):
            result = original(*args, **kwargs)
            target = Path(args[1])
            page = target.read_text().replace(base64.b64encode(self.audio[1]).decode(),
                                              base64.b64encode(b"wrong-wav").decode())
            target.write_text(page)
            result["html_sha256"] = sha(target.read_bytes())
            return result
        with mock.patch.object(kit.compare, "publish_rate_comparison", side_effect=forged):
            with self.assertRaisesRegex(RuntimeError, "listener WAV differs"):
                self.export()
        self.assertFalse(self.output.exists())
        self.assert_clean()

    def test_cancellation_before_stem_processing_aborts(self):
        cancelled = [False]
        original = self.sweep
        def signal(*args, **kwargs):
            receipt = original(*args, **kwargs)
            cancelled[0] = True
            return receipt
        with mock.patch.object(kit.sweep, "export_saved_compose_rate_sweep", side_effect=signal):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.export(cancelled=lambda: cancelled[0])
        self.assertFalse(self.output.exists())
        self.assert_clean()

    def test_cancellation_inside_atomic_link_rolls_back(self):
        cancelled = [False]
        real_link = kit.os.link
        def link(source, target):
            real_link(source, target)
            cancelled[0] = True
        with mock.patch.object(kit.os, "link", side_effect=link):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.export(cancelled=lambda: cancelled[0])
        self.assertFalse(self.output.exists())
        self.assert_clean()

    def test_project_edit_inside_atomic_link_rolls_back(self):
        real_link = kit.os.link
        def link(source, target):
            self.project.write_bytes(b'{"a":123}')
            real_link(source, target)
        with mock.patch.object(kit.os, "link", side_effect=link):
            with self.assertRaisesRegex(RuntimeError, "project changed"):
                self.export()
        self.assertFalse(self.output.exists())
        self.assert_clean()

    def test_foreign_destination_created_at_link_survives(self):
        def competitor(source, target):
            Path(target).write_bytes(b"another-writer")
            raise FileExistsError(str(target))
        with mock.patch.object(kit.os, "link", side_effect=competitor):
            with self.assertRaises(FileExistsError):
                self.export()
        self.assertEqual(self.output.read_bytes(), b"another-writer")
        self.assert_clean()

    def test_foreign_replacement_after_link_survives_rollback(self):
        real_link = kit.os.link
        def replacement(source, target):
            real_link(source, target)
            foreign = self.root / "foreign.zip"
            foreign.write_bytes(b"another-writer")
            foreign.replace(target)
            self.project.write_bytes(b'{"a":123}')
        with mock.patch.object(kit.os, "link", side_effect=replacement):
            with self.assertRaisesRegex(RuntimeError, "project changed"):
                self.export()
        self.assertEqual(self.output.read_bytes(), b"another-writer")
        self.assert_clean()


class OriginalSavedComposeKit(unittest.TestCase):
    def test_real_saved_compose_numerical_listen_and_daw(self):
        root = Path(__file__).resolve().parents[2]
        if not (root / "zaaggenz_runtime" / "nyquismic_offline_audition.py").is_file():
            self.skipTest("full original-host production NYQ chain required")
        from test_nyquismic_compose_delivery import source_document
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / "song.zgtimeline.json"
            project.write_text(json.dumps(source_document()), encoding="utf-8")
            destination = Path(folder) / "listen-and-daw.zip"
            receipt = kit.export_saved_compose_kit(
                project, destination, virtual_rates_hz=["4/1", "5/1"])
            self.assertEqual(receipt["delivery_hz"], 48000)
            self.assertEqual(receipt["zip_sha256"], sha(destination.read_bytes()))
            with zipfile.ZipFile(destination) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest["frames"], 28800)
                self.assertEqual(manifest["sample_rate_hz"], 48000)
                self.assertEqual(manifest["project_file_sha256"], sha(project.read_bytes()))
                self.assertEqual(len(manifest["tracks"]), 3)
                for entry in manifest["tracks"]:
                    self.assertEqual(sha(archive.read(entry["file"])), entry["wav_sha256"])
                self.assertIn(b"nyq-compare-payload", archive.read("listen.html"))
            print("NYQ_PRODUCTION_KIT_PCM " + json.dumps({
                "frames": manifest["frames"], "delivery_hz": 48000,
                "dry_wav_sha256": manifest["tracks"][0]["wav_sha256"],
                "wet_pcm_f32le_sha256": [x["pcm_f32le_sha256"] for x in manifest["tracks"][1:]],
                "kit_sha256": receipt["zip_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
