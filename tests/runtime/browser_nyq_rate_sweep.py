"""Original-browser acceptance of the saved-Compose NYQ rate-sweep ZIP.

This optional executable test does not register a new Compose product route.
It rejects a foreign/tampered variant before opening any audio in Chromium.
"""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import tempfile
import zipfile

MAX_ARCHIVE_BYTES = 513 * 1024 * 1024
MAX_INDEX_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 128 * 1024
MAX_PAGE_BYTES = 128 * 1024 * 1024


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class IndexLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.append(dict(attrs).get("href"))


def read_verified_sweep(archive_path: Path, root: Path, *, verify_page=None):
    """Verify exact archive and per-page source/audio hashes before navigation."""
    if verify_page is None:
        from browser_nyq_direct_audition import validate_page
        verify_page = validate_page
    if not archive_path.is_file() or not 0 < archive_path.stat().st_size <= MAX_ARCHIVE_BYTES:
        raise ValueError("missing or oversized NYQ rate-sweep archive")
    initial_sha = None
    with archive_path.open("rb") as stream:
        hash_value = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hash_value.update(chunk)
        initial_sha = hash_value.hexdigest()
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if not 4 <= len(infos) <= 8:
            raise ValueError("NYQ sweep must contain index, manifest and 2–6 pages")
        expected = ["index.html", "manifest.json"] + [
            f"variant-{i:02d}.html" for i in range(1, len(infos) - 1)
        ]
        if ([info.filename for info in infos] != expected
                or any(info.compress_type != zipfile.ZIP_STORED
                       or info.flag_bits & 1 for info in infos)
                or infos[0].file_size > MAX_INDEX_BYTES
                or infos[1].file_size > MAX_MANIFEST_BYTES
                or any(not 0 < info.file_size <= MAX_PAGE_BYTES for info in infos[2:])):
            raise ValueError("unexpected, encrypted, compressed or oversized sweep entries")
        index = archive.read("index.html")
        manifest = json.loads(archive.read("manifest.json"))
        if (manifest.get("format") != "nyq.saved-compose-rate-sweep.v1"
                or manifest.get("delivery_rate_hz") != 48000
                or len(manifest.get("variants", [])) != len(infos) - 2):
            raise ValueError("wrong sweep manifest format, clock or variant count")
        links = IndexLinks()
        links.feed(index.decode("utf-8"))
        if links.hrefs != expected[2:]:
            raise ValueError("offline index links do not identify the exact variant pages")
        if b"default-src 'none'" not in index:
            raise ValueError("offline index lacks its network-blocking CSP")
        source = manifest["source"]
        if manifest["project_file_sha256"] != source["project_file_sha256"]:
            raise ValueError("project source anchor mismatch")
        records = []
        for i, entry in enumerate(manifest["variants"]):
            name = expected[i + 2]
            page_bytes = archive.read(name)
            if entry.get("page") != name or entry.get("page_sha256") != sha(page_bytes):
                raise ValueError("variant page identity mismatch")
            path = root / name
            path.write_bytes(page_bytes)
            payload, measured, measured_sha = verify_page(path)
            inner = payload["manifest"]
            for field in ("project_file_sha256", "source_asset_sha256",
                          "source_revision_sha256", "compose_recipe_sha256"):
                if inner.get(field) != source.get(field):
                    raise ValueError("foreign variant Compose source: " + field)
            if (inner["dry"]["pcm_f32le_sha256"] != source["dry_pcm_f32le_sha256"]
                    or payload["frames"] != source["frames"]
                    or payload["channels"] != source["channels"]
                    or measured["wet"]["pcm_f32le_sha256"] != entry.get("wet_pcm_f32le_sha256")
                    or inner.get("packet_sha256") != entry.get("packet_sha256")
                    or inner.get("virtual_rate_hz") != entry.get("virtual_rate_hz")
                    or inner.get("evaluation_rate_hz") != manifest["evaluation_rate_hz"]
                    or measured_sha != entry["page_sha256"]):
                raise ValueError("foreign clock, dry PCM, wet PCM or packet in sweep variant")
            records.append((entry, path, payload, measured))
        (root / "index.html").write_bytes(index)
    current = hashlib.sha256()
    with archive_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            current.update(chunk)
    if current.hexdigest() != initial_sha:
        raise ValueError("rate sweep archive changed during validation")
    return initial_sha, records


def exercise_index(index: Path, records):
    """Actually follow every index anchor through the local file:// browser."""
    from playwright.sync_api import sync_playwright

    failures, requests = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("ZAAGGENZ_CHROMIUM") or None,
            headless=True, args=["--no-sandbox", "--mute-audio"],
        )
        try:
            page = browser.new_page()
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.on("request", lambda request: requests.append(request.url)
                    if request.url.startswith(("http:", "https:", "ws:", "wss:")) else None)
            page.goto(index.resolve().as_uri(), wait_until="load")
            assert page.locator("h1").inner_text() == "Nyquismic virtual-clock rate sweep"
            assert page.locator("ol a").count() == len(records)
            for i, (entry, path, _payload, _measured) in enumerate(records):
                link = page.locator("ol a").nth(i)
                assert link.get_attribute("href") == path.name
                assert entry["virtual_rate_hz"] in link.inner_text()
                link.click()
                page.wait_for_url(path.resolve().as_uri())
                assert page.locator("#nyq-payload").count() == 1
                assert page.locator("#download-dry").count() == 1
                assert page.locator("#download-wet").count() == 1
                page.go_back(wait_until="load")
                assert page.locator("ol a").count() == len(records)
            assert not failures, "index/variant browser JS errors: " + repr(failures)
            assert not requests, "offline navigation made external requests: " + repr(requests)
            return browser.version
        finally:
            browser.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", action="store_true", help="render real saved Compose two-rate fixture")
    source.add_argument("--zip", type=Path, help="verify and browse an existing local rate-sweep ZIP")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="nyq-sweep-browser-") as temp:
        root = Path(temp)
        if args.fixture:
            from test_nyquismic_compose_delivery import source_document
            from zaaggenz_runtime.nyquismic_audition_sweep import export_saved_compose_rate_sweep
            project = root / "song.zgtimeline.json"
            project.write_text(json.dumps(source_document()), encoding="utf-8")
            archive = root / "sweep.zip"
            export_saved_compose_rate_sweep(
                project, archive, virtual_rates_hz=["4/1", "5/1"])
        else:
            archive = args.zip.resolve()
        archive_sha, records = read_verified_sweep(archive, root)
        chromium = exercise_index(root / "index.html", records)
        from browser_nyq_direct_audition import verify_in_chromium

        details = []
        for entry, path, payload, measured in records:
            browser_result = verify_in_chromium(path.resolve().as_uri(), payload, measured)
            details.append({
                "rate_hz": entry["virtual_rate_hz"],
                "page_sha256": entry["page_sha256"],
                "dry_pcm_sha256": measured["dry"]["pcm_f32le_sha256"],
                "wet_pcm_sha256": measured["wet"]["pcm_f32le_sha256"],
                "browser": browser_result,
            })
        print("NYQ_RATE_SWEEP_BROWSER " + json.dumps({
            "archive_sha256": archive_sha,
            "chromium_version": chromium,
            "index_navigation": "PASS", "delivery_hz": 48000,
            "variants": details,
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
