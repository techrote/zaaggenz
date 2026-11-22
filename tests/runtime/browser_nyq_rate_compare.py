"""Real file:// Chromium acceptance for NYQ #292's one-page 2–6-rate player.

Opt-in post-Compose full-mix acceptance. This does not certify a registered
graph route, a human listening test, or physical Windows acceptance.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile

import numpy as np
from scipy.io import wavfile
from playwright.sync_api import expect, sync_playwright

from zaaggenz_runtime.nyquismic_rate_compare import (
    _verified_sweep, publish_rate_comparison,
)

PAYLOAD = re.compile(
    r'<script id="nyq-compare-payload" type="application/json">(.*?)</script>',
    re.DOTALL,
)
INSTRUMENT = r"""
(() => {
  window.__nyq_starts = [];
  window.__nyq_ramps = [];
  window.__nyq_holds = [];
  window.__nyq_sets = [];
  const start = AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start = function(when, offset) {
    window.__nyq_starts.push({when, offset});
    return start.apply(this, arguments);
  };
  const ramp = AudioParam.prototype.linearRampToValueAtTime;
  AudioParam.prototype.linearRampToValueAtTime = function(target, at) {
    window.__nyq_ramps.push({target, at});
    return ramp.apply(this, arguments);
  };
  const hold = AudioParam.prototype.cancelAndHoldAtTime;
  if (typeof hold === "function") {
    AudioParam.prototype.cancelAndHoldAtTime = function(at) {
      window.__nyq_holds.push(at);
      return hold.apply(this, arguments);
    };
  }
  const set = AudioParam.prototype.setValueAtTime;
  AudioParam.prototype.setValueAtTime = function(value, at) {
    window.__nyq_sets.push({value, at});
    return set.apply(this, arguments);
  };
})();
"""


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def verify_bytes(html: Path, sweep: Path):
    """Validate browser fixture against the original WAVs and decoded PCM."""
    exact = html.read_bytes()
    matches = PAYLOAD.findall(exact.decode("utf-8", errors="strict"))
    if len(matches) != 1:
        raise ValueError("missing or duplicate comparison payload")
    payload = json.loads(matches[0])
    source = _verified_sweep(sweep)
    if payload.get("format") != "nyq.multi-rate-compare-html.v1":
        raise ValueError("wrong comparison format")
    if payload["frames"] != source["frames"] or payload["channels"] != source["channels"]:
        raise ValueError("comparison audio extent mismatch")
    wavs = [source["dry"]] + [r["wet"] for r in source["variants"]]
    if len(payload["wavs"]) != len(wavs):
        raise ValueError("comparison track count mismatch")
    receipt = payload["receipt"]
    if receipt["archive_sha256"] != sha(sweep.read_bytes()) or receipt["source"] != source["source"]:
        raise ValueError("foreign comparison source receipt")
    if [r["rate"] for r in receipt["rates"]] != [r["rate"] for r in source["variants"]]:
        raise ValueError("wrong virtual clock sequence")
    measured = []
    for i, original in enumerate(wavs):
        embedded = base64.b64decode(payload["wavs"][i], validate=True)
        if embedded != original:
            raise ValueError("browser-embedded WAV differs from original producer")
        hz, pcm = wavfile.read(io.BytesIO(embedded))
        if (hz != 48000 or pcm.dtype != np.float32
                or pcm.shape[0] != payload["frames"]
                or (1 if pcm.ndim == 1 else pcm.shape[1]) != payload["channels"]
                or not np.isfinite(pcm).all()):
            raise ValueError("embedded WAV format/PCM mismatch")
        measured.append({"wav_sha256": sha(original),
                         "pcm_sha256": sha(np.asarray(pcm, dtype="<f4").tobytes())})
    if receipt["dry_wav_sha256"] != measured[0]["wav_sha256"]:
        raise ValueError("dry WAV receipt mismatch")
    for row, meta in zip(measured[1:], receipt["rates"]):
        if (row["wav_sha256"] != meta["wet_wav_sha256"]
                or row["pcm_sha256"] != meta["wet_pcm_sha256"]):
            raise ValueError("wet WAV/PCM receipt mismatch")
    if "connect-src 'none'" not in exact.decode("utf-8"):
        raise ValueError("missing outbound-network prohibition")
    return payload, measured, sha(exact)


def accept_browser(html: Path, payload, measured):
    """Run against the actual generated local file URL; no test-page rehosting."""
    errors, requests = [], []
    with sync_playwright() as engine:
        browser = engine.chromium.launch(
            executable_path=os.environ.get("ZAAGGENZ_CHROMIUM") or None,
            headless=True,
            args=["--autoplay-policy=no-user-gesture-required",
                  "--mute-audio", "--no-sandbox"],
        )
        try:
            page = browser.new_page(accept_downloads=True)
            page.set_default_timeout(20000)
            page.add_init_script(INSTRUMENT)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("request", lambda r: requests.append(r.url)
                    if r.url.startswith(("http:", "https:", "ws:", "wss:")) else None)
            page.goto(html.resolve().as_uri(), wait_until="load")
            tracks = len(measured)
            assert page.locator('button[id^="choice-"]').count() == tracks
            assert page.locator('a[id^="download-"]').count() == tracks
            assert payload["frames"] == 28800 and tracks == 3, "fixture changed"
            receipt_text = page.locator("#receipt").inner_text()
            for meta in measured[1:]:
                assert meta["pcm_sha256"] in receipt_text
            page.locator("#play").click()
            expect(page.locator("#status")).to_contain_text("Playing synchronized tracks")
            starts = page.evaluate("window.__nyq_starts")
            assert len(starts) == tracks, "PLAY did not schedule all original sources"
            assert max(r["when"] for r in starts) - min(r["when"] for r in starts) < 1e-9
            assert max(r["offset"] for r in starts) - min(r["offset"] for r in starts) < 1e-9

            # Switch twice in a single browser task, before the short fixture ends.
            switching = page.evaluate("""() => {
                document.getElementById('choice-2').click();
                document.getElementById('choice-1').click();
                return {starts: window.__nyq_starts.length,
                        ramps: window.__nyq_ramps.slice(),
                        holds: window.__nyq_holds.slice(),
                        chosen: document.getElementById('choice-1').getAttribute('aria-pressed')};
            }""")
            assert switching["starts"] == tracks, "rate change restarted audio"
            assert switching["chosen"] == "true"
            assert [r["target"] for r in switching["ramps"]] == [0, 0, 1, 0, 1, 0], (
                "two rate switches did not schedule three-track crossfades")
            if page.evaluate('typeof AudioParam.prototype.cancelAndHoldAtTime === "function"'):
                assert len(switching["holds"]) == 2 * tracks

            # Seeking restarts *all* sources on one physical-time axis.
            page.evaluate("""() => {
                const s=document.getElementById('seek');
                s.value='250'; s.dispatchEvent(new Event('input', {bubbles:true}));
            }""")
            seek = page.evaluate("window.__nyq_starts")
            assert len(seek) == 2 * tracks
            assert all(abs(s["offset"] - payload["frames"] / 48000 * .25) < 1e-6
                       for s in seek[tracks:])
            assert max(r["when"] for r in seek[tracks:]) - min(r["when"] for r in seek[tracks:]) < 1e-9
            page.locator("#play").click()
            expect(page.locator("#status")).to_contain_text("Paused")
            page.locator("#play").click()
            expect(page.locator("#status")).to_contain_text("Playing synchronized tracks")
            resume = page.evaluate("window.__nyq_starts")
            assert len(resume) == 3 * tracks, "resume did not restart every track"
            assert max(r["when"] for r in resume[-tracks:]) - min(r["when"] for r in resume[-tracks:]) < 1e-9

            with tempfile.TemporaryDirectory(prefix="nyq-multirate-download-") as folder:
                for i, identity in enumerate(measured):
                    with page.expect_download() as pending:
                        page.locator("#download-" + str(i)).click()
                    dest = Path(folder) / (str(i) + ".wav")
                    pending.value.save_as(dest)
                    assert sha(dest.read_bytes()) == identity["wav_sha256"], (
                        "browser WAV download was modified")
            assert not errors, "page errors: " + repr(errors)
            assert not requests, "outbound browser requests: " + repr(requests)

            # Exercise the alternate Web Audio path, not a claim of Firefox execution.
            fallback = browser.new_page()
            fallback_errors = []
            fallback.add_init_script("""
                AudioParam.prototype.cancelAndHoldAtTime = undefined;
                window.__fallback_set_values = [];
                const set = AudioParam.prototype.setValueAtTime;
                AudioParam.prototype.setValueAtTime = function(value, t) {
                    window.__fallback_set_values.push({value, t});
                    return set.apply(this, arguments);
                };
            """)
            fallback.on("pageerror", lambda e: fallback_errors.append(str(e)))
            try:
                fallback.goto(html.resolve().as_uri(), wait_until="load")
                fallback.locator("#play").click()
                expect(fallback.locator("#status")).to_contain_text(
                    "Playing synchronized tracks")
                values = fallback.evaluate("""() => {
                    document.getElementById('choice-2').click();
                    document.getElementById('choice-1').click();
                    return window.__fallback_set_values;
                }""")
                assert len(values) == 2 * tracks, "missing gain-envelope fallback"
                assert all(0 <= v["value"] <= 1 for v in values), (
                    "fallback gain level outside original 0..1 envelope")
                assert not fallback_errors, "fallback page errors: " + repr(fallback_errors)
            finally:
                fallback.close()
            return {"chromium": browser.version, "file_origin": "PASS",
                    "sources_per_start": tracks, "source_starts": len(resume),
                    "rapid_switch_ramps": len(switching["ramps"]),
                    "seek_resume": "PASS", "downloads": tracks,
                    "fallback_gain_events": 2 * tracks, "outbound_requests": 0}
        finally:
            browser.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument("--fixture", action="store_true",
                         help="render an actual saved Compose project and two-rate sweep")
    options.add_argument("--sweep", type=Path, help="existing local two-rate sweep")
    a = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="nyq-multirate-browser-") as folder:
        root = Path(folder)
        if a.fixture:
            from test_nyquismic_compose_delivery import source_document
            from zaaggenz_runtime.nyquismic_audition_sweep import export_saved_compose_rate_sweep
            project = root / "source.zgtimeline.json"
            project.write_text(json.dumps(source_document()), encoding="utf-8")
            sweep = root / "rates.zip"
            export_saved_compose_rate_sweep(project, sweep, virtual_rates_hz=["4/1", "5/1"])
        else:
            sweep = a.sweep.resolve()
        html = root / "compare.html"
        receipt = publish_rate_comparison(sweep, html)
        payload, measured, html_sha = verify_bytes(html, sweep)
        assert receipt["html_sha256"] == html_sha
        output = accept_browser(html, payload, measured)
        print("NYQ_MULTI_RATE_BROWSER " + json.dumps({
            "html_sha256": html_sha, "frames": payload["frames"],
            "channels": payload["channels"], "delivery_hz": 48000,
            "audio": measured, **output}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
