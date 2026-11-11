"""Real Chromium playback acceptance for an opt-in NYQ saved-Compose A/B HTML.

This is a standalone test, not part of automatic ZG-041 Chromium admission.
No human listening, GUI/graph registration or NYQ #252/#253 acceptance is claimed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import tempfile
import threading

import numpy as np
from scipy.io import wavfile
from playwright.sync_api import expect, sync_playwright

PAGE_FORMAT = "nyq.ab48-local-audition-html.v1"
PAYLOAD = re.compile(
    r'<script id="nyq-payload" type="application/json">(.*?)</script>',
    re.DOTALL,
)
MAX_PAGE_BYTES = 128 * 1024 * 1024


def validate_page(path: Path):
    """Independently verify the exact WAV and decoded PCM bytes before Chrome."""
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_PAGE_BYTES:
        raise ValueError("NYQ HTML missing or exceeds 128 MiB")
    match = PAYLOAD.search(raw.decode("utf-8", errors="strict"))
    if match is None:
        raise ValueError("NYQ payload script missing")
    payload = json.loads(match.group(1))
    if payload.get("format") != PAGE_FORMAT:
        raise ValueError("wrong NYQ audition HTML format")
    manifest = payload["manifest"]
    frames, channels = payload["frames"], payload["channels"]
    if (manifest.get("sample_rate_hz") != 48000
            or manifest.get("frames") != frames
            or manifest.get("channels") != channels
            or channels not in (1, 2) or not isinstance(frames, int)
            or frames <= 0):
        raise ValueError("manifest and physical-time audio extent differ")
    measured = {}
    for key in ("dry", "wet"):
        wav_bytes = base64.b64decode(payload[key], validate=True)
        wav_sha = hashlib.sha256(wav_bytes).hexdigest()
        if wav_sha != manifest[key]["wav_sha256"]:
            raise ValueError(key + " WAV SHA mismatch")
        hz, pcm = wavfile.read(io.BytesIO(wav_bytes))
        actual_channels = 1 if pcm.ndim == 1 else pcm.shape[1]
        pcm_sha = hashlib.sha256(np.asarray(pcm, dtype="<f4").tobytes()).hexdigest()
        if (hz != 48000 or pcm.dtype != np.dtype("float32")
                or pcm.ndim not in (1, 2)
                or pcm.shape[0] != frames or actual_channels != channels
                or not np.isfinite(pcm).all()
                or pcm_sha != manifest[key]["pcm_f32le_sha256"]):
            raise ValueError(key + " decoded PCM or extent mismatch")
        measured[key] = {
            "wav_sha256": wav_sha, "pcm_f32le_sha256": pcm_sha,
        }
    return payload, measured, hashlib.sha256(raw).hexdigest()


# Observes the actual Web Audio calls. Does not replace decoding, sources,
# scheduling, gain control, output processing or playback clocks.
INSTRUMENT = r"""
(() => {
  window.__nyq_browser_starts = [];
  window.__nyq_browser_ramps = [];
  window.__nyq_browser_holds = [];
  const start = AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start = function(when, offset, duration) {
    window.__nyq_browser_starts.push({when, offset, duration});
    return start.apply(this, arguments);
  };
  const hold = AudioParam.prototype.cancelAndHoldAtTime;
  if (typeof hold === "function") {
    AudioParam.prototype.cancelAndHoldAtTime = function(at) {
      window.__nyq_browser_holds.push(at);
      return hold.apply(this, arguments);
    };
  }
  const ramp = AudioParam.prototype.linearRampToValueAtTime;
  AudioParam.prototype.linearRampToValueAtTime = function(target, at) {
    window.__nyq_browser_ramps.push({target, at});
    return ramp.apply(this, arguments);
  };
})();
"""


def verify_in_chromium(url, payload, measured, *, loopback=False):
    errors, external_requests = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("ZAAGGENZ_CHROMIUM") or None,
            headless=True,
            args=["--autoplay-policy=no-user-gesture-required",
                  "--mute-audio", "--no-sandbox"],
        )
        try:
            page = browser.new_page(
                viewport={"width": 1200, "height": 950},
                accept_downloads=True,
            )
            page.add_init_script(INSTRUMENT)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: external_requests.append(request.url)
                    if request.url.startswith(("http:", "https:", "ws:", "wss:"))
                    and request.url != url else None)
            page.goto(url, wait_until="load")
            page.set_default_timeout(20000)
            expect(page.locator("#status")).to_contain_text("Press PLAY")
            receipt = page.locator("#receipt").inner_text()
            assert measured["dry"]["pcm_f32le_sha256"] in receipt
            assert measured["wet"]["pcm_f32le_sha256"] in receipt

            # Real Chrome must decode the float32 WAVs and schedule both
            # sources at the same Web Audio context time and physical offset.
            page.locator("#play").click()
            expect(page.locator("#status")).to_contain_text(
                "Playing synchronized sources", timeout=20000)
            initial = page.evaluate("window.__nyq_browser_starts")
            assert len(initial) == 2, "PLAY did not start two sources"
            assert abs(initial[0]["when"] - initial[1]["when"]) < 1e-9
            assert abs(initial[0]["offset"] - initial[1]["offset"]) < 1e-9

            # The rapid switch exercises the overlapping 8-ms gain ramps,
            # and must not reschedule or offset either source.
            switched = page.evaluate("""() => {
              document.querySelector('#wet').click();
              const b = document.querySelector('#wet').getAttribute('aria-pressed');
              document.querySelector('#dry').click();
              const a = document.querySelector('#dry').getAttribute('aria-pressed');
              return {a, b, starts:window.__nyq_browser_starts.length,
                      ramps:window.__nyq_browser_ramps.slice()};
            }""")
            assert (switched["a"], switched["b"], switched["starts"]) == (
                "true", "true", 2), "A/B switch restarted playback"
            assert [event["target"] for event in switched["ramps"]] == [
                0, 1, 1, 0], "A/B switch did not schedule click-avoidance ramps"
            # Chromium must hold the actual scheduled mid-ramp value instead
            # of restarting from AudioParam.value (an intrinsic parameter).
            # Other engines use the tracked linear envelope fallback.
            supports_hold = page.evaluate(
                'typeof AudioParam.prototype.cancelAndHoldAtTime === "function"')
            if supports_hold:
                held = page.evaluate("window.__nyq_browser_holds")
                assert len(held) == 4, (
                    "rapid A/B did not hold in-progress Web Audio automation")
                assert all(isinstance(at, (float, int)) for at in held)

            # Seeking must restart both sources at the identical *physical*
            # 25%-of-duration offset without touching the source WAVs.
            page.evaluate("""() => {
              const seek = document.querySelector('#seek');
              seek.value = '250';
              seek.dispatchEvent(new Event('input', {bubbles:true}));
            }""")
            after_seek = page.evaluate("window.__nyq_browser_starts")
            assert len(after_seek) == 4, "SEEK did not restart both sources"
            expected = payload["frames"] / 48000 * .25
            assert abs(after_seek[2]["offset"] - expected) < 1e-6
            assert abs(after_seek[3]["offset"] - expected) < 1e-6
            assert abs(after_seek[2]["when"] - after_seek[3]["when"]) < 1e-9

            page.locator("#play").click()
            expect(page.locator("#status")).to_contain_text("Paused")
            page.locator("#play").click()
            expect(page.locator("#status")).to_contain_text(
                "Playing synchronized sources")
            resumed = page.evaluate("window.__nyq_browser_starts")
            assert len(resumed) == 6, "resume did not restart both sources"
            assert abs(resumed[4]["when"] - resumed[5]["when"]) < 1e-9

            # Browser-visible WAV downloads must preserve the validated
            # published bytes, not re-encode, normalize or clip the audio.
            with tempfile.TemporaryDirectory(prefix="nyq-browser-downloads-") as folder:
                for key in ("dry", "wet"):
                    with page.expect_download() as info:
                        page.locator("#download-" + key).click()
                    copied = Path(folder) / (key + ".wav")
                    info.value.save_as(copied)
                    assert hashlib.sha256(copied.read_bytes()).hexdigest() == (
                        measured[key]["wav_sha256"]), key + " WAV download changed"
            assert not errors, "Chromium page errors: " + repr(errors)
            assert not external_requests, "unexpected network: " + repr(external_requests)

            # Force the no-cancelAndHold browser branch on an isolated copy
            # of the *actual generated page*. This is a compatibility probe,
            # not a claim that Firefox was physically executed here.
            fallback = browser.new_page()
            fallback_errors = []
            fallback.on("pageerror", lambda e: fallback_errors.append(str(e)))
            fallback.add_init_script(r"""
(() => {
  AudioParam.prototype.cancelAndHoldAtTime = undefined;
  window.__nyq_fallback_sets = [];
  const original = AudioParam.prototype.setValueAtTime;
  AudioParam.prototype.setValueAtTime = function(value, when) {
    window.__nyq_fallback_sets.push({value, when});
    return original.apply(this, arguments);
  };
})();
""")
            try:
                fallback.goto(url, wait_until="load")
                fallback.locator("#play").click()
                expect(fallback.locator("#status")).to_contain_text(
                    "Playing synchronized sources")
                fallback.evaluate("""async () => {
                  document.querySelector('#wet').click();
                  await new Promise(resolve => setTimeout(resolve, 3));
                  document.querySelector('#dry').click();
                }""")
                sets = fallback.evaluate("window.__nyq_fallback_sets")
                assert len(sets) == 4, (
                    "no-hold browser path did not reconstruct both gain ramps")
                delta = sets[2]["when"] - sets[0]["when"]
                fraction = max(0., min(1., delta / .008))
                assert abs(sets[2]["value"] - (1. - fraction)) < .025, (
                    "fallback dry gain is not the current interpolated ramp")
                assert abs(sets[3]["value"] - fraction) < .025, (
                    "fallback wet gain is not the current interpolated ramp")
                assert not fallback_errors, (
                    "fallback browser errors: " + repr(fallback_errors))
            finally:
                fallback.close()
            return {
                "chromium_version": browser.version,
                "entry": "loopback-only" if loopback else "file://",
                "web_audio_decode": "PASS",
                "synchronized_source_starts": 6,
                "rapid_switch_gain_ramps": len(switched["ramps"]),
                "seek_and_pause_resume": "PASS",
                "dry_wet_download_identity": "PASS",
                "unexpected_external_requests": 0,
                "page_errors": 0,
            }
        finally:
            browser.close()


def local_url(path: Path):
    """Optional HTTP fallback when the host forbids file:// Chromium navigation.

    Restricted to a single read-only HTML URL on 127.0.0.1. A loopback PASS
    does not qualify file:// behaviour or physical human listening.
    """
    source = path.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/audition.html":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(source)))
            self.end_headers()
            self.wfile.write(source)

        def log_message(self, format, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--html", type=Path, help="existing trusted NYQ HTML, read-only")
    source.add_argument("--fixture", action="store_true",
                        help="generate a genuine synthetic saved Compose project/HTML")
    parser.add_argument("--loopback", action="store_true",
                        help="explicit HTTP localhost fallback; file:// is not qualified")
    options = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="nyq-browser-acceptance-") as folder:
        if options.fixture:
            from test_nyquismic_compose_delivery import source_document
            from zaaggenz_runtime.nyquismic_offline_audition import (
                export_saved_compose_audition,
            )
            project = Path(folder) / "song.zgtimeline.json"
            project.write_text(json.dumps(source_document()), encoding="utf-8")
            html = Path(folder) / "audition.html"
            receipt = export_saved_compose_audition(
                project, html, virtual_rate_hz="4/1")
            assert receipt["html_sha256"] == hashlib.sha256(
                html.read_bytes()).hexdigest()
        else:
            html = options.html
        payload, measured, page_sha = validate_page(html)
        server = None
        try:
            if options.loopback:
                server = local_url(html)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                url = "http://127.0.0.1:" + str(server.server_port) + "/audition.html"
            else:
                url = html.resolve().as_uri()
            browser_receipt = verify_in_chromium(
                url, payload, measured, loopback=options.loopback)
        finally:
            if server:
                server.shutdown()
                server.server_close()
        print("NYQ_BROWSER_AUDITION " + json.dumps({
            "page_sha256": page_sha,
            "frames": payload["frames"], "channels": payload["channels"],
            "delivery_hz": 48000, "audio": measured, **browser_receipt,
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
