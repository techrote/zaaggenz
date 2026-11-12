"""Standalone acceptance tests for the one-command offline NYQ listener."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import nyq_listen_saved_compose as cli


class OfflineListenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "phrase.zgtimeline.json"
        self.project.write_text('{"notes":[]}', encoding="utf-8")
        self.output = self.root / "audition"
        self.names = ["manifest.json", "listen.html", "original.wav",
                      "nyq-rate-01.wav", "nyq-rate-02.wav"]

    def _commands(self, *, bad_sha=False, bad_source=False, changed_project=False,
                  bad_archive=False, bad_verifier=False):
        received = []

        def fake(args, *, name):
            received.append((name, args))
            if name == "NYQ export":
                kit = Path(args[args.index("--output") + 1])
                with zipfile.ZipFile(kit, "w") as archive:
                    for member in self.names:
                        archive.writestr(member, member.encode())
                    if bad_archive:
                        archive.writestr("../foreign-file", b"not allowed")
                if changed_project:
                    self.project.write_bytes(b"changed after source capture")
                return {"zip_sha256": "0" * 64 if bad_sha else cli._sha(kit),
                        "project_file_sha256": "f" * 64 if bad_source else self.source_sha,
                        "virtual_rates_hz": list(cli.RATES), "delivery_hz": 48000}
            kit = Path(args[args.index("--kit") + 1])
            return {"zip_sha256": cli._sha(kit),
                    "source_project_sha256": "f" * 64 if bad_verifier else self.source_sha,
                    "virtual_rates_hz": list(cli.RATES), "delivery_hz": 48000,
                    "trusted_zip_sha_checked": True, "original_project_checked": True,
                    "tracks": [{}, {}, {}]}
        self.source_sha = cli._sha(self.project)
        return fake, received

    def test_one_command_extracts_verified_source_and_opens_listener(self):
        fake, received = self._commands()
        with patch.object(cli, "_command", fake), patch.object(cli.webbrowser, "open", return_value=True) as browser:
            receipt = cli.audition(self.project, self.output)
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["project_sha256"], self.source_sha)
        self.assertEqual(receipt["virtual_rates_hz"], ["256/1", "512/1"])
        self.assertEqual([name for name, _ in received], ["NYQ export", "NYQ cold-reopen verification"])
        self.assertIn("--expected-sha256", received[1][1])
        self.assertEqual(browser.call_args.args, ((self.output / "listen.html").resolve().as_uri(),))
        self.assertTrue(all((self.output / name).read_bytes() == name.encode() for name in self.names))
        self.assertTrue((self.output / "receipt.json").is_file())


    def test_oversized_project_rejected_before_directory_or_export(self):
        limit = cli.sweep.MAX_PROJECT_BYTES
        self.project.write_bytes(b"{}" + b" " * (limit - 1))
        with patch.object(cli, "_command") as backend:
            with self.assertRaisesRegex(ValueError, "2,000,000"):
                cli.audition(self.project, self.output, open_browser=False)
        backend.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_exact_producer_project_limit_accepted(self):
        limit = cli.sweep.MAX_PROJECT_BYTES
        self.project.write_bytes(b"{}" + b" " * (limit - 2))
        fake, received = self._commands()
        with patch.object(cli, "_command", fake):
            receipt = cli.audition(self.project, self.output, open_browser=False)
        self.assertEqual(receipt["project_sha256"], self.source_sha)
        self.assertEqual(len(received), 2)
        self.assertTrue((self.output / "listen.html").is_file())

    def test_no_overwrite_of_existing_directory(self):
        self.output.mkdir()
        (self.output / "listen.html").write_text("do-not-touch")
        with self.assertRaises(FileExistsError):
            cli.audition(self.project, self.output)
        self.assertEqual((self.output / "listen.html").read_text(), "do-not-touch")

    def test_bad_project_rejected_before_publication(self):
        with self.assertRaises(ValueError):
            cli.audition(self.root / "fake.txt", self.output)
        self.assertFalse(self.output.exists())

    def test_foreign_export_receipts_and_modified_source_fail(self):
        for kind in ("bad_sha", "bad_source", "changed_project"):
            with self.subTest(kind=kind):
                self.project.write_text('{"notes":[]}', encoding="utf-8")
                if self.output.exists():
                    import shutil
                    shutil.rmtree(self.output)
                fake, _ = self._commands(**{kind: True})
                with patch.object(cli, "_command", fake):
                    with self.assertRaises(RuntimeError):
                        cli.audition(self.project, self.output, open_browser=False)

    def test_foreign_verifier_fails_without_extraction(self):
        fake, _ = self._commands(bad_verifier=True)
        with patch.object(cli, "_command", fake):
            with self.assertRaises(RuntimeError):
                cli.audition(self.project, self.output, open_browser=False)
        self.assertFalse((self.output / "listen.html").exists())

    def test_foreign_archive_member_fails_without_extraction(self):
        fake, _ = self._commands(bad_archive=True)
        with patch.object(cli, "_command", fake):
            with self.assertRaises(RuntimeError):
                cli.audition(self.project, self.output, open_browser=False)
        self.assertFalse((self.root / "foreign-file").exists())
        self.assertFalse((self.output / "listen.html").exists())

    def test_export_failure_does_not_publish_unverified_output(self):
        def fail_after_writing(args, *, name):
            kit = Path(args[args.index("--output") + 1])
            kit.write_bytes(b"unverified export")
            raise RuntimeError("interrupted NYQ export")

        with patch.object(cli, "_command", fail_after_writing):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                cli.audition(self.project, self.output, open_browser=False)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".audition-nyq-stage-*")), [])

    def test_verifier_failure_does_not_poison_explicit_destination(self):
        bad, _ = self._commands(bad_verifier=True)
        with patch.object(cli, "_command", bad):
            with self.assertRaises(RuntimeError):
                cli.audition(self.project, self.output, open_browser=False)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".audition-nyq-stage-*")), [])
        good, received = self._commands()
        with patch.object(cli, "_command", good):
            receipt = cli.audition(self.project, self.output, open_browser=False)
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(len(received), 2)

    def test_competing_empty_destination_at_publication_is_never_replaced(self):
        fake, _ = self._commands()
        raced = False

        if cli.os.name == "nt":
            # Windows rename must reject a target created at the boundary.
            original = Path.rename

            def competing_rename(stage, destination):
                nonlocal raced
                if Path(destination) == self.output and not raced:
                    raced = True
                    self.output.mkdir()
                return original(stage, destination)

            publication_patch = patch.object(Path, "rename", competing_rename)
        else:
            # POSIX rename would overwrite an empty target. Inject the other
            # creator exactly at exclusive publication reservation.
            original = Path.mkdir

            def competing_mkdir(path, *args, **kwargs):
                nonlocal raced
                if path == self.output and not raced:
                    raced = True
                    original(path)
                return original(path, *args, **kwargs)

            publication_patch = patch.object(Path, "mkdir", competing_mkdir)

        with patch.object(cli, "_command", fake), publication_patch:
            with self.assertRaises(FileExistsError):
                cli.audition(self.project, self.output, open_browser=False)
        self.assertTrue(raced)
        self.assertTrue(self.output.is_dir())
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(list(self.root.glob(".audition-nyq-stage-*")), [])

    def test_failed_rename_removes_only_our_empty_reservation(self):
        fake, _ = self._commands()
        with patch.object(cli, "_command", fake), patch.object(
            Path, "rename", side_effect=OSError("simulated publication failure")
        ):
            with self.assertRaisesRegex(OSError, "publication failure"):
                cli.audition(self.project, self.output, open_browser=False)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".audition-nyq-stage-*")), [])

    def test_no_open_still_verifies_and_saves_wavs(self):
        fake, _ = self._commands()
        with patch.object(cli, "_command", fake), patch.object(cli.webbrowser, "open") as browser:
            receipt = cli.audition(self.project, self.output, open_browser=False)
        browser.assert_not_called()
        self.assertTrue(receipt["cold_reopen_verified"])


if __name__ == "__main__":
    unittest.main()
