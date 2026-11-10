"""NYQ rate-sweep: source equality, 48-kHz receipts and adversarial archive publication."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock
import zipfile

from zaaggenz_runtime import nyquismic_audition_sweep as sweep


def sha(data):
    return hashlib.sha256(data).hexdigest()


class RateSweepTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = self.root / "song.zgtimeline.json"
        self.project.write_bytes(b'{"fixture":"source"}')
        self.output = self.root / "variants.zip"
        self.calls = []
        self.fake = types.ModuleType("zaaggenz_runtime.nyquismic_offline_audition")
        self.fake.export_saved_compose_audition = self.produce
        patcher = mock.patch.dict(sys.modules, {
            "zaaggenz_runtime.nyquismic_offline_audition": self.fake,
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def produce(self, project, target, *, virtual_rate_hz, evaluation_rate_hz, wait_seconds, cancelled):
        self.calls.append(virtual_rate_hz)
        page = ("<!doctype html><title>synthetic " + virtual_rate_hz + "</title>").encode()
        Path(target).write_bytes(page)
        return {
            "absolute_path": str(Path(target).absolute()),
            "html_sha256": sha(page),
            "project_file_sha256": sha(Path(project).read_bytes()),
            "virtual_rate_hz": virtual_rate_hz,
            "evaluation_rate_hz": evaluation_rate_hz,
            "delivery_hz": 48000, "frames": 28800, "channels": 1,
            "source_asset_sha256": "1" * 64,
            "source_revision_sha256": "2" * 64,
            "compose_recipe_sha256": "3" * 64,
            "dry_pcm_f32le_sha256": "4" * 64,
            "wet_pcm_f32le_sha256": sha(virtual_rate_hz.encode()),
            "packet_sha256": sha(("packet" + virtual_rate_hz).encode()),
            "source_bundle_sha256": "5" * 64,
        }

    def run_sweep(self, **kwargs):
        return sweep.export_saved_compose_rate_sweep(
            self.project, self.output, virtual_rates_hz=["4", "5/1"], **kwargs)

    def assert_clean(self):
        self.assertEqual(sorted(self.root.iterdir()), [self.project])

    def test_same_source_exact_page_bytes_and_readable_offline_index(self):
        result = self.run_sweep()
        self.assertEqual(self.calls, ["4/1", "5/1"])
        self.assertEqual(result["archive_sha256"], sha(self.output.read_bytes()))
        with zipfile.ZipFile(self.output) as z:
            self.assertEqual(z.namelist(), [
                "index.html", "manifest.json", "variant-01.html", "variant-02.html"])
            manifest = json.loads(z.read("manifest.json"))
            self.assertEqual(manifest["format"], sweep.FORMAT)
            self.assertEqual(manifest["source"]["dry_pcm_f32le_sha256"], "4" * 64)
            self.assertEqual(manifest["source"]["project_file_sha256"],
                             sha(self.project.read_bytes()))
            self.assertEqual([v["virtual_rate_hz"] for v in manifest["variants"]],
                             ["4/1", "5/1"])
            self.assertIn(b'variant-01.html', z.read("index.html"))
            self.assertIn(b'variant-02.html', z.read("index.html"))
            self.assertIn(b"default-src 'none'", z.read("index.html"))
            for v in manifest["variants"]:
                self.assertEqual(sha(z.read(v["page"])), v["page_sha256"])
        self.assertEqual(sorted(self.root.iterdir()), sorted([self.project, self.output]))

    def test_cold_reopen_same_host_bundle_bytes(self):
        first = self.run_sweep()
        self.output.rename(self.root / "first.zip")
        second = self.run_sweep()
        self.assertEqual(first["archive_sha256"], second["archive_sha256"])
        self.assertEqual((self.root / "first.zip").read_bytes(), self.output.read_bytes())

    def test_bad_rates_and_bad_evaluation_do_not_start_renderer(self):
        bad = [["4"], ["4", "4/1"], ["0", "4"], ["1/0", "4"],
               ["nan", "4"], ["0.4", "4"], ["1000001", "4"], ["4"] * 7]
        for case in bad:
            with self.subTest(case=case), self.assertRaises(ValueError):
                sweep.export_saved_compose_rate_sweep(
                    self.project, self.output, virtual_rates_hz=case)
        with self.assertRaises(ValueError):
            self.run_sweep(evaluation_rate_hz=12345)
        self.assertEqual(self.calls, [])
        self.assert_clean()

    def test_collision_rejected_before_any_render(self):
        self.output.write_bytes(b"original owner data")
        with self.assertRaises(FileExistsError):
            self.run_sweep()
        self.assertEqual(self.output.read_bytes(), b"original owner data")
        self.assertEqual(self.calls, [])

    def test_change_of_project_after_first_render_aborts_unpublished(self):
        actual = self.produce
        def mutate(*args, **kwargs):
            result = actual(*args, **kwargs)
            self.project.write_bytes(b"changed project")
            return result
        self.fake.export_saved_compose_audition = mutate
        with self.assertRaisesRegex(RuntimeError, "changed"):
            self.run_sweep()
        self.assertEqual(len(self.calls), 1)
        self.assert_clean()

    def test_changed_baseline_dry_pcm_aborts_entire_batch(self):
        actual = self.produce
        def altered(*args, **kwargs):
            result = actual(*args, **kwargs)
            if len(self.calls) == 2:
                result["dry_pcm_f32le_sha256"] = "9" * 64
            return result
        self.fake.export_saved_compose_audition = altered
        with self.assertRaisesRegex(RuntimeError, "different Compose source"):
            self.run_sweep()
        self.assert_clean()

    def test_corrupted_html_before_receipt_check_aborts(self):
        actual = self.produce
        def corrupt(*args, **kwargs):
            result = actual(*args, **kwargs)
            Path(result["absolute_path"]).write_bytes(b"tampered page")
            return result
        self.fake.export_saved_compose_audition = corrupt
        with self.assertRaisesRegex(RuntimeError, "page changed"):
            self.run_sweep()
        self.assert_clean()

    def test_cancellation_between_variants_cleans_everything(self):
        signal = [False]
        actual = self.produce
        def trigger(*args, **kwargs):
            result = actual(*args, **kwargs)
            signal[0] = True
            return result
        self.fake.export_saved_compose_audition = trigger
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.run_sweep(cancelled=lambda: signal[0])
        self.assert_clean()

    def test_cancel_after_archive_fsync_cleans_staging(self):
        signal = [False]
        actual = sweep.os.fsync
        def trigger(fd):
            actual(fd)
            signal[0] = True
        with mock.patch.object(sweep.os, "fsync", side_effect=trigger):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.run_sweep(cancelled=lambda: signal[0])
        self.assert_clean()

    def test_competing_writer_is_not_overwritten(self):
        def competitor(staging, dest):
            Path(dest).write_bytes(b"competing owner")
            raise FileExistsError(str(dest))
        with mock.patch.object(sweep.os, "link", side_effect=competitor):
            with self.assertRaises(FileExistsError):
                self.run_sweep()
        self.assertEqual(self.output.read_bytes(), b"competing owner")
        self.assertEqual(sorted(self.root.iterdir()), sorted([self.project, self.output]))

    def test_cli_exact_receipt(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = sweep.main([
                "--project", str(self.project), "--output", str(self.output),
                "--virtual-hz", "4", "--virtual-hz", "5"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["archive_sha256"],
                         sha(self.output.read_bytes()))


class OriginalComposeRateSweepTests(unittest.TestCase):
    def test_real_compose_two_rates_identical_dry_pcm_and_distinct_wet(self):
        # On a full source tree, fail if any original fixture or DSP import breaks.
        if not (Path(__file__).resolve().parents[2] /
                "zaaggenz_runtime" / "nyquismic_offline_audition.py").is_file():
            self.skipTest("isolated local publisher test, without full NYQ source tree")
        from test_nyquismic_compose_delivery import source_document
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "song.zgtimeline.json"
            project.write_text(json.dumps(source_document()), encoding="utf-8")
            archive = root / "rates.zip"
            result = sweep.export_saved_compose_rate_sweep(
                project, archive, virtual_rates_hz=["4/1", "5/1"])
            with zipfile.ZipFile(archive) as z:
                manifest = json.loads(z.read("manifest.json"))
                self.assertEqual(len(manifest["variants"]), 2)
                self.assertEqual(manifest["source"]["dry_pcm_f32le_sha256"],
                                 result["dry_pcm_f32le_sha256"])
                self.assertEqual(manifest["source"]["frames"], 28800)
                wet = [v["wet_pcm_f32le_sha256"] for v in manifest["variants"]]
                self.assertNotEqual(wet[0], wet[1])
                for v in manifest["variants"]:
                    page = z.read(v["page"])
                    self.assertEqual(sha(page), v["page_sha256"])
                    self.assertIn(b'nyq-payload', page)
            print("NYQ_RATE_SWEEP_ORIGINAL_NUMERICS " + json.dumps({
                "project_sha256": result["project_file_sha256"],
                "dry_pcm_sha256": result["dry_pcm_f32le_sha256"],
                "wet_pcm_sha256_by_rate": wet,
                "archive_sha256": result["archive_sha256"],
                "frames": 28800, "sample_rate_hz": 48000,
            }, sort_keys=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
