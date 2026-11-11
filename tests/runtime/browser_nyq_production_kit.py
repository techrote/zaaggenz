"""Native Chromium proof for the actual #296/#299 saved Compose listener + DAW ZIP.

Run: PYTHONPATH=.:tests/runtime python tests/runtime/browser_nyq_production_kit.py --fixture
on a source tree that includes #296 and #299. This is independent browser
qualification, not human audibility, ordinary graph export or #242 acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile

from playwright.sync_api import expect, sync_playwright
from zaaggenz_runtime.nyquismic_kit_verify import verify_production_kit


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# Observe native audio scheduling; do not mock decodeAudioData, sources, gain,
# downloads, clocks or the sample data fed to Chromium.
INSTRUMENT = r"""
(() => {
  window.__nyqStarts = [];
  window.__nyqRamps = [];
  window.__nyqHolds = [];
  const start = AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start = function(when, offset) {
    window.__nyqStarts.push({when, offset});
    return start.apply(this, arguments);
  };
  const ramp = AudioParam.prototype.linearRampToValueAtTime;
  AudioParam.prototype.linearRampToValueAtTime = function(value, time) {
    window.__nyqRamps.push({value, time});
    return ramp.apply(this, arguments);
  };
  const hold = AudioParam.prototype.cancelAndHoldAtTime;
  if (typeof hold === 'function') {
    AudioParam.prototype.cancelAndHoldAtTime = function(at) {
      window.__nyqHolds.push(at);
      return hold.apply(this, arguments);
    };
  }
})();
"""


def run_browser(html: Path, tracks: list[dict], frames: int) -> dict:
    errors, requests = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ.get("ZAAGGENZ_CHROMIUM") or None,
            headless=True,
            args=["--autoplay-policy=no-user-gesture-required", "--mute-audio", "--no-sandbox"],
        )
        try:
            page = browser.new_page(accept_downloads=True)
            page.add_init_script(INSTRUMENT)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: requests.append(request.url)
                    if request.url.startswith(("http:", "https:", "ws:", "wss:")) else None)
            page.goto(html.resolve().as_uri(), wait_until="load")
            page.set_default_timeout(20000)
            n = len(tracks)
            assert n >= 3, "multi-rate fixture requires original plus at least two rates"
            expect(page.locator("#status")).to_contain_text("Press PLAY")
            assert page.locator("#nyq-compare-payload").count() == 1
            assert page.locator("[id^='choice-']").count() == n
            assert page.locator("[id^='download-']").count() == n
            receipt = page.locator("#receipt").inner_text()
            assert "nyq.multi-rate-compare-html.v1" in receipt
            for track in tracks:
                assert track["wav_sha256"] in (receipt + page.locator("#nyq-compare-payload").inner_text())

            # Actual native Web Audio WAV decode and synchronized source starts.
            page.locator("#play").click()
            expect(page.locator("#status")).to_contain_text("Playing synchronized tracks")
            original = page.evaluate("window.__nyqStarts.slice()")
            assert len(original) == n, "PLAY did not schedule every source"
            assert all(abs(x["when"]-original[0]["when"]) < 1e-9
                       and abs(x["offset"]-original[0]["offset"]) < 1e-9
                       for x in original), "initial Web Audio sources are misaligned"

            # Three successive choices must ramp existing sources, never restart.
            swapped = page.evaluate("""() => {
              document.querySelector('#choice-1').click();
              document.querySelector('#choice-2').click();
              document.querySelector('#choice-0').click();
              return {starts: window.__nyqStarts.length,
                      ramps: window.__nyqRamps.slice(),
                      holds: window.__nyqHolds.slice(),
                      selected: document.querySelector('#choice-0').getAttribute('aria-pressed')};
            }""")
            assert swapped["selected"] == "true"
            assert swapped["starts"] == n, "choice changes restarted sources"
            assert len(swapped["ramps"]) == 3*n, "not every source received each ramp"
            assert [x["value"] for x in swapped["ramps"]] == (
                [int(i==1) for i in range(n)]
                + [int(i==2) for i in range(n)]
                + [int(i==0) for i in range(n)]), "gain-routing targets are wrong"
            supports_hold = page.evaluate(
                "typeof AudioParam.prototype.cancelAndHoldAtTime === 'function'")
            if supports_hold:
                assert len(swapped["holds"]) == 3*n, "rapid switches lost gain holds"

            # Real seek must restart all original buffers on the same physical
            # timeline. Use an early offset to keep the 0.6 s fixture running.
            seeked = page.evaluate("""() => {
              const slider = document.querySelector('#seek');
              slider.value='100'; slider.dispatchEvent(new Event('input', {bubbles:true}));
              return window.__nyqStarts.slice();
            }""")
            assert len(seeked) == 2*n, "seek failed to restart all tracks"
            expected = frames / 48000 * .1
            assert all(abs(x["offset"]-expected) < 1e-6
                       and abs(x["when"]-seeked[n]["when"]) < 1e-9
                       for x in seeked[n:]), "seek changed per-track clock or offset"
            page.locator("#play").click()
            expect(page.locator("#status")).to_contain_text("Paused")
            page.locator("#play").click()
            expect(page.locator("#status")).to_contain_text("Playing synchronized tracks")
            resumed = page.evaluate("window.__nyqStarts.slice()")
            assert len(resumed) == 3*n, "resume failed to schedule every track"
            assert all(abs(x["when"]-resumed[2*n]["when"]) < 1e-9
                       and abs(x["offset"]-resumed[2*n]["offset"]) < 1e-9
                       for x in resumed[2*n:]), "resume desynchronized tracks"

            # Native Chromium download bytes, not a re-encoding or fake click.
            with tempfile.TemporaryDirectory(prefix="nyq-kit-chromium-download-") as folder:
                for index, track in enumerate(tracks):
                    with page.expect_download() as download:
                        page.locator(f"#download-{index}").click()
                    dest = Path(folder) / f"download-{index}.wav"
                    download.value.save_as(dest)
                    assert sha(dest.read_bytes()) == track["wav_sha256"], (
                        f"Chromium WAV download differs for track {index}")
            assert not errors, f"Chromium JavaScript errors: {errors!r}"
            assert not requests, f"Unexpected network requests: {requests!r}"
            return {"chromium": browser.version, "audio_decode": "PASS",
                    "synchronized_tracks": n, "rapid_switch_ramps": 3*n,
                    "seek_pause_resume": "PASS", "download_identity": "PASS",
                    "unexpected_network_requests": len(requests), "page_errors": len(errors),
                    "file_uri_qualified": True}
        finally:
            browser.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--kit", type=Path, help="Existing, verified production kit ZIP")
    source.add_argument("--fixture", action="store_true", help="Render a genuine saved Compose project")
    parser.add_argument("--project", type=Path, help="Original saved project for source binding")
    parser.add_argument("--expected-sha256", help="Independently recorded kit ZIP SHA-256")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="nyq-kit-chromium-") as tmp:
        root = Path(tmp)
        project, kit = args.project, args.kit
        if args.fixture:
            if args.project or args.expected_sha256:
                parser.error("--fixture cannot be combined with external anchors")
            from test_nyquismic_compose_delivery import source_document
            from zaaggenz_runtime.nyquismic_production_kit import export_saved_compose_kit
            project, kit = root / "song.zgtimeline.json", root / "production-kit.zip"
            project.write_text(json.dumps(source_document()), encoding="utf-8")
            produced = export_saved_compose_kit(
                project, kit, virtual_rates_hz=["4/1", "5/1"])
            assert produced["frames"] == 28800, "real saved Compose fixture extent changed"
            expected_sha = produced["zip_sha256"]
        else:
            expected_sha = args.expected_sha256
        verified = verify_production_kit(
            kit, expected_zip_sha256=expected_sha, project_path=project)
        zip_raw = kit.read_bytes()
        assert sha(zip_raw) == verified["zip_sha256"], "kit changed after verification"
        with zipfile.ZipFile(io.BytesIO(zip_raw)) as archive:
            raw_html = archive.read("listen.html")
            manifest = json.loads(archive.read("manifest.json"))
            assert sha(raw_html) == manifest["listen_html_sha256"]
        html = root / "listen.html"
        html.write_bytes(raw_html)
        result = run_browser(html, verified["tracks"], verified["frames"])
        print("NYQ_PRODUCTION_KIT_CHROMIUM " + json.dumps({
            "kit_sha256": verified["zip_sha256"],
            "html_sha256": sha(raw_html),
            "project_sha256": verified["source_project_sha256"],
            "wav_sha256": [x["wav_sha256"] for x in verified["tracks"]],
            "pcm_f32le_sha256": [x["pcm_f32le_sha256"] for x in verified["tracks"]],
            "frames": verified["frames"], "delivery_hz": 48000,
            "project_anchor_checked": verified["original_project_checked"],
            "trusted_kit_sha_checked": verified["trusted_zip_sha_checked"],
            **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
