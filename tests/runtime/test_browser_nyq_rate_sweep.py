"""Source/PCM archive-boundary tests for the optional rate-sweep browser runner."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from browser_nyq_rate_sweep import read_verified_sweep


def sha(data):
    return hashlib.sha256(data).hexdigest()


class SweepBrowserPackageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.archive = self.root / "test-sweep.zip"
        self.stage = self.root / "opened"
        self.stage.mkdir()
        self.source = {
            "project_file_sha256": "0" * 64,
            "source_asset_sha256": "1" * 64,
            "source_revision_sha256": "2" * 64,
            "compose_recipe_sha256": "3" * 64,
            "dry_pcm_f32le_sha256": "4" * 64,
            "frames": 28800, "channels": 1,
        }
        self.pages = [b"inert authenticated page A", b"inert authenticated page B"]
        self.variants = [{
            "page": f"variant-{i+1:02d}.html",
            "page_sha256": sha(page),
            "virtual_rate_hz": f"{i+4}/1",
            "packet_sha256": sha(b"packet" + page),
            "wet_pcm_f32le_sha256": sha(b"wet" + page),
            "source_bundle_sha256": sha(b"bundle" + page),
        } for i, page in enumerate(self.pages)]
        self.original_source = copy.deepcopy(self.source)
        self.original_variants = copy.deepcopy(self.variants)
        self.index = ("<!doctype html><meta http-equiv=\"Content-Security-Policy\" "
                      "content=\"default-src 'none'\"><h1>Nyquismic virtual-clock "
                      "rate sweep</h1><ol>" + "".join(
                          f'<li><a href="{v["page"]}">{v["virtual_rate_hz"]}</a></li>'
                          for v in self.variants) + "</ol>").encode()
        self.manifest = {
            "format": "nyq.saved-compose-rate-sweep.v1",
            "delivery_rate_hz": 48000, "evaluation_rate_hz": 192000,
            "source": self.source,
            "project_file_sha256": self.source["project_file_sha256"],
            "variants": self.variants,
        }

    def archive_write(self, extra=None):
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_STORED) as z:
            z.writestr("index.html", self.index)
            z.writestr("manifest.json", json.dumps(self.manifest))
            for i, page in enumerate(self.pages):
                z.writestr(f"variant-{i+1:02d}.html", page)
            if extra:
                z.writestr(extra, b"unexpected")

    def verify_page(self, path):
        index = int(path.stem.split("-")[1]) - 1
        entry = self.original_variants[index]
        inner = {
            **self.original_source,
            "dry": {"pcm_f32le_sha256": self.original_source["dry_pcm_f32le_sha256"]},
            "packet_sha256": entry["packet_sha256"],
            "virtual_rate_hz": entry["virtual_rate_hz"],
            "evaluation_rate_hz": 192000,
        }
        return ({"manifest": inner, "frames": 28800, "channels": 1},
                {"dry": {"pcm_f32le_sha256": self.original_source["dry_pcm_f32le_sha256"]},
                 "wet": {"pcm_f32le_sha256": entry["wet_pcm_f32le_sha256"]}},
                sha(path.read_bytes()))

    def accept(self):
        return read_verified_sweep(self.archive, self.stage, verify_page=self.verify_page)

    def test_two_variant_source_authenticated_archive(self):
        self.archive_write()
        digest, records = self.accept()
        self.assertEqual(digest, sha(self.archive.read_bytes()))
        self.assertEqual(len(records), 2)
        self.assertEqual([v[0]["virtual_rate_hz"] for v in records], ["4/1", "5/1"])
        self.assertEqual((self.stage / "index.html").read_bytes(), self.index)

    def test_page_byte_tampering_rejected_before_browser(self):
        self.variants[1]["page_sha256"] = "f" * 64
        self.archive_write()
        with self.assertRaisesRegex(ValueError, "page identity"):
            self.accept()

    def test_index_retarget_or_foreign_href_rejected(self):
        self.index = self.index.replace(b"variant-02.html", b"https://example.org")
        self.archive_write()
        with self.assertRaisesRegex(ValueError, "index links"):
            self.accept()

    def test_foreign_pcm_and_packet_rejected(self):
        self.archive_write()
        for key, value in (("wet_pcm_f32le_sha256", "c" * 64),
                           ("packet_sha256", "d" * 64)):
            original = self.variants[0][key]
            self.variants[0][key] = value
            self.archive_write()
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "foreign clock"):
                self.accept()
            self.variants[0][key] = original

    def test_foreign_source_revision_rejected(self):
        self.source["source_revision_sha256"] = "b" * 64
        self.archive_write()
        with self.assertRaisesRegex(ValueError, "foreign variant Compose source"):
            self.accept()

    def test_unexpected_path_is_rejected_before_extraction(self):
        self.archive_write(extra="../outside.html")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            self.accept()
        self.assertFalse((self.root / "outside.html").exists())


if __name__ == "__main__":
    unittest.main()
