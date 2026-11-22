"""Local opt-in, source-authenticated Web Audio audition of an existing NYQ A/B ZIP.

Consumes the actual #281 saved-Compose dry/wet bundle; never rerenders,
modifies accepted audio, opens network connections or mutates shared sessions.
This is a portable local listening artifact, NOT a registered Compose UI.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

import numpy as np
from scipy.io import wavfile

FORMAT = "nyq.saved-compose-ab48-zip.v1"
PAGE_FORMAT = "nyq.ab48-local-audition-html.v1"
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
NAMES = ("compose-dry.wav", "compose-nyquismic.wav", "manifest.json")
_CHUNK = 1024 * 1024

_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; img-src data:; media-src blob: data:">
<title>NYQ / LOCAL A-B AUDITION</title>
<style>
:root{color-scheme:dark;background:#090d11;color:#dbe6ec;font-family:Consolas,monospace}
*{box-sizing:border-box}
body{max-width:820px;margin:0 auto;padding:26px 18px}
header{border:2px solid #6b8393;padding:17px;background:#111a20}
h1{font-size:22px;letter-spacing:.1em;margin:0 0 7px;color:#c9ebf1}
p{line-height:1.5;color:#9bb2c1;margin:8px 0}
.panel{margin-top:16px;border:1px solid #5d7787;padding:20px;background:#121b21}
.tag{font-size:11px;letter-spacing:.14em;color:#b2cbd5}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:16px 0}
button,a.download{background:#1b2d36;color:#e1eef4;border:1px solid #7493a4;border-radius:0;padding:11px 17px;font:inherit;cursor:pointer;text-decoration:none}
button[aria-pressed="true"]{background:#d0eaf1;color:#11191d;font-weight:bold}
button:focus-visible,a:focus-visible,input:focus-visible{outline:2px solid #f4d785;outline-offset:3px}
input[type=range]{width:100%;accent-color:#b5d9e5}
#status{min-height:24px;color:#c9dbe4}
#clock{font-variant-numeric:tabular-nums}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;color:#aec4d0}
footer{font-size:12px;margin-top:15px}
</style>
</head>
<body>
<header>
<div class="tag">ZAAGGENZ / NYQUISMIC / OFFLINE / READ-ONLY</div>
<h1>DRY : NYQ / 48 KHz</h1>
<p>Both tracks come from the same original Compose render. Dry means no additional
Nyquismic stage; the existing Compose rack remains in both. Audio never leaves this file.</p>
</header>
<section class="panel" aria-label="Audio comparison">
<div class="tag">SYNCHRONIZED A/B AUDITION</div>
<div class="row">
<button id="play" type="button">PLAY</button>
<button id="dry" aria-pressed="true" type="button">A / ORIGINAL</button>
<button id="wet" aria-pressed="false" type="button">B / NYQUISMIC</button>
<span id="clock">00:00 / 00:00</span>
</div>
<input id="seek" type="range" min="0" max="1000" value="0" aria-label="Seek through audio">
<p id="status" role="status">Press PLAY to decode local 48-kHz WAVs.</p>
<div class="row">
<a id="download-dry" class="download" download="compose-dry.wav">SAVE A WAV</a>
<a id="download-wet" class="download" download="compose-nyquismic.wav">SAVE B WAV</a>
</div>
</section>
<section class="panel">
<div class="tag">SOURCE & NUMERICAL PROVENANCE</div>
<pre id="receipt"></pre>
</section>
<footer>Opt-in listening only. No gain matching or normalization. Crossfades last 8 ms
to avoid switching clicks; source and WAV samples are never rewritten. Browser
output devices may resample the 48-kHz WAVs. Not a registered Compose export/UI.</footer>
<script id="nyq-payload" type="application/json">__PAYLOAD__</script>
<script>
"use strict";
(function () {
  const payload = JSON.parse(document.getElementById("nyq-payload").textContent);
  const $ = id => document.getElementById(id);
  let context = null, buffers = null, sources = [], gains = [];
  let playing = false, offset = 0, startedAt = 0, selected = 0;
  // AudioParam.value is the intrinsic value, not the live mid-ramp gain.
  // Retain the analytic envelope for engines without cancelAndHoldAtTime.
  let envelopes = [{from:1, to:1, start:0, end:0},
                   {from:0, to:0, start:0, end:0}];
  function envelopeAt(i, time) {
    const e = envelopes[i];
    if (time >= e.end) return e.to;
    if (time <= e.start) return e.from;
    return e.from + (e.to - e.from) * (time - e.start) / (e.end - e.start);
  }
  const status = $("status"), play = $("play"), seek = $("seek");
  const duration = payload.frames / 48000;
  const clockText = seconds => {
    const n = Math.max(0, Math.floor(seconds));
    return String(Math.floor(n / 60)).padStart(2, "0") + ":" +
      String(n % 60).padStart(2, "0");
  };
  function bytes(value) {
    const binary = atob(value);
    const data = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) data[i] = binary.charCodeAt(i);
    return data;
  }
  const raw = [bytes(payload.dry), bytes(payload.wet)];
  const urls = raw.map(data => URL.createObjectURL(new Blob([data], {type:"audio/wav"})));
  $("download-dry").href = urls[0];
  $("download-wet").href = urls[1];
  $("receipt").textContent = JSON.stringify({
    format: payload.format, project_sha256: payload.manifest.project_file_sha256,
    source_asset_sha256: payload.manifest.source_asset_sha256,
    source_revision_sha256: payload.manifest.source_revision_sha256,
    packet_sha256: payload.manifest.packet_sha256,
    dry_pcm_sha256: payload.manifest.dry.pcm_f32le_sha256,
    wet_pcm_sha256: payload.manifest.wet.pcm_f32le_sha256,
    frames: payload.frames, channels: payload.channels, sample_rate_hz: 48000
  }, null, 2);
  async function ensureAudio() {
    if (buffers) return;
    context = new (window.AudioContext || window.webkitAudioContext)();
    await context.resume();
    buffers = await Promise.all(raw.map(data => context.decodeAudioData(data.buffer.slice(0))));
    if (buffers.some(b => b.numberOfChannels !== payload.channels ||
                          Math.abs(b.duration - duration) > .001)) {
      throw new Error("Browser-decoded audio extent or channel count differs from WAV");
    }
  }
  function halt() {
    for (const source of sources) {
      try { source.stop(); } catch (_) {}
      source.disconnect();
    }
    sources = [];
    for (const gain of gains) gain.disconnect();
    gains = [];
  }
  function start(at) {
    halt();
    offset = Math.max(0, Math.min(at, duration));
    if (offset >= duration) offset = 0;
    const when = context.currentTime + .035;
    startedAt = when - offset;
    envelopes = [0, 1].map(i => {
      const level = i === selected ? 1 : 0;
      return {from:level, to:level, start:when, end:when};
    });
    for (let i = 0; i < 2; i++) {
      const source = context.createBufferSource();
      const gain = context.createGain();
      source.buffer = buffers[i];
      gain.gain.value = i === selected ? 1 : 0;
      source.connect(gain);
      gain.connect(context.destination);
      // Both inputs have exactly one scheduled Web Audio start timestamp.
      source.start(when, offset);
      sources.push(source);
      gains.push(gain);
    }
    playing = true;
    play.textContent = "PAUSE";
    status.textContent = "Playing synchronized sources; selection " + (selected ? "B" : "A");
  }
  function pause() {
    if (!playing) return;
    offset = Math.max(0, Math.min(duration, context.currentTime - startedAt));
    halt();
    playing = false;
    play.textContent = "PLAY";
    status.textContent = "Paused";
  }
  function choose(which) {
    selected = which;
    $("dry").setAttribute("aria-pressed", String(which === 0));
    $("wet").setAttribute("aria-pressed", String(which === 1));
    if (playing) {
      // Parallel sources stay on the same playback timeline. Brief, click-safe ramps.
      const t = context.currentTime, end = t + .008;
      for (let i = 0; i < 2; i++) {
        const g = gains[i].gain;
        const from = envelopeAt(i, t);
        const to = i === selected ? 1 : 0;
        if (typeof g.cancelAndHoldAtTime === "function") {
          // Preserve the computed automation value, including a mid-ramp edit.
          g.cancelAndHoldAtTime(t);
        } else {
          // Firefox/older engines: reconstruct the actual in-progress gain.
          g.cancelScheduledValues(t);
          g.setValueAtTime(from, t);
        }
        g.linearRampToValueAtTime(to, end);
        envelopes[i] = {from:from, to:to, start:t, end:end};
      }
      status.textContent = "Playing synchronized sources; selection " + (selected ? "B" : "A");
    }
  }
  play.addEventListener("click", async () => {
    try {
      await ensureAudio();
      if (playing) pause();
      else start(offset);
    } catch (error) {
      status.textContent = "Playback unavailable: " + error.message;
    }
  });
  $("dry").addEventListener("click", () => choose(0));
  $("wet").addEventListener("click", () => choose(1));
  seek.addEventListener("input", () => {
    const at = Number(seek.value) * duration / 1000;
    if (playing) start(at); else offset = at;
  });
  function tick() {
    let time = playing ? Math.max(0, context.currentTime - startedAt) : offset;
    if (playing && time >= duration) { pause(); offset = 0; time = 0; }
    if (document.activeElement !== seek) seek.value = String(Math.round(time * 1000 / duration));
    $("clock").textContent = clockText(time) + " / " + clockText(duration);
    requestAnimationFrame(tick);
  }
  tick();
})();
</script>
</body></html>
"""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _cancel(cancelled) -> None:
    if cancelled is not None and cancelled():
        raise RuntimeError("local audition was cancelled")


def _read_verified_bundle(path: Path, cancelled) -> tuple[dict, bytes, bytes, str]:
    _cancel(cancelled)
    if path.stat().st_size > MAX_BUNDLE_BYTES:
        raise ValueError("audition bundle exceeds 64 MiB limit")
    # Parse and identify one immutable byte snapshot, not two racing disk reads.
    archive_bytes = path.read_bytes()
    if len(archive_bytes) > MAX_BUNDLE_BYTES:
        raise ValueError("audition bundle exceeds 64 MiB limit")
    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as archive:
        infos = archive.infolist()
        if tuple(item.filename for item in infos) != NAMES:
            raise ValueError("unexpected NYQ A/B bundle entries or order")
        if any(item.compress_type != zipfile.ZIP_STORED or
               item.flag_bits & 1 or item.file_size > MAX_BUNDLE_BYTES
               for item in infos):
            raise ValueError("audition bundle requires bounded, unencrypted stored entries")
        if sum(item.file_size for item in infos) > MAX_BUNDLE_BYTES:
            raise ValueError("uncompressed audition bundle exceeds 64 MiB limit")
        dry, wet, manifest_data = (archive.read(name) for name in NAMES)
    _cancel(cancelled)
    manifest = json.loads(manifest_data.decode("utf-8"))
    if manifest.get("format") != FORMAT:
        raise ValueError("wrong NYQ A/B manifest format")
    if manifest.get("sample_rate_hz") != 48000:
        raise ValueError("A/B manifest delivery clock must be 48 kHz")
    for name, data, row in (("dry", dry, manifest["dry"]),
                            ("wet", wet, manifest["wet"])):
        if _sha(data) != row["wav_sha256"]:
            raise ValueError(name + " WAV SHA does not match source manifest")
        rate, pcm = wavfile.read(io.BytesIO(data))
        if (rate != 48000 or pcm.dtype != np.float32 or pcm.ndim not in (1, 2)
                or not np.isfinite(pcm).all()):
            raise ValueError(name + " is not valid finite 48-kHz float32 WAV")
        channels = 1 if pcm.ndim == 1 else pcm.shape[1]
        if (channels not in (1, 2) or pcm.shape[0] <= 0
                or channels != manifest["channels"]
                or pcm.shape[0] != manifest["frames"]
                or _sha(np.asarray(pcm, dtype="<f4").tobytes(order="C"))
                != row["pcm_f32le_sha256"]):
            raise ValueError(name + " decoded PCM or source extent differs from manifest")
    return manifest, dry, wet, _sha(archive_bytes)


def publish_ab48_audition(
    bundle_path: str | Path,
    output_path: str | Path,
    *,
    cancelled=None,
) -> dict:
    """Create a self-contained offline A/B listening page; never overwrite."""
    if cancelled is not None and not callable(cancelled):
        raise ValueError("cancelled must be callable or None")
    dest = Path(output_path).absolute()
    if dest.suffix.lower() != ".html" or not dest.parent.is_dir():
        raise ValueError("output must be a .html file in an existing directory")
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(str(dest))
    bundle = Path(bundle_path).absolute()
    manifest, dry, wet, source_hash = _read_verified_bundle(bundle, cancelled)
    payload = {
        "format": PAGE_FORMAT,
        "frames": manifest["frames"],
        "channels": manifest["channels"],
        "manifest": manifest,
        "dry": base64.b64encode(dry).decode("ascii"),
        "wet": base64.b64encode(wet).decode("ascii"),
    }
    # Encoded WAVs are inert. Escape user-controlled metadata before script embedding.
    json_payload = json.dumps(payload, sort_keys=True, allow_nan=False,
                              separators=(",", ":")).replace("<", "\\u003c")
    page = _HTML.replace("__PAYLOAD__", json_payload).encode("utf-8")
    _cancel(cancelled)
    fd, temp = tempfile.mkstemp(prefix=".nyq-audition-", suffix=".partial",
                                dir=str(dest.parent))
    staging = Path(temp)
    try:
        with os.fdopen(fd, "wb") as output:
            for i in range(0, len(page), _CHUNK):
                _cancel(cancelled)
                output.write(page[i:i + _CHUNK])
            output.flush()
            os.fsync(output.fileno())
        _cancel(cancelled)
        h = hashlib.sha256()
        with staging.open("rb") as staged:
            for chunk in iter(lambda: staged.read(_CHUNK), b""):
                h.update(chunk)
        if h.hexdigest() != _sha(page):
            raise RuntimeError("staged audition HTML changed")
        _cancel(cancelled)
        os.link(staging, dest)
    finally:
        staging.unlink(missing_ok=True)
    return {
        "format": PAGE_FORMAT,
        "absolute_path": str(dest),
        "html_sha256": _sha(page),
        "source_zip_sha256": source_hash,
        "source_asset_sha256": manifest["source_asset_sha256"],
        "frames": manifest["frames"],
        "channels": manifest["channels"],
        "delivery_hz": 48000,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Local no-network NYQ dry/wet A/B audio audition page")
    parser.add_argument("--bundle", required=True, help="#281 source-matched A/B .zip")
    parser.add_argument("--output", required=True, help="New .html; never overwritten")
    args = parser.parse_args(argv)
    try:
        receipt = publish_ab48_audition(args.bundle, args.output)
    except (Exception, KeyboardInterrupt) as error:
        print("NYQ audition generation failed: " + str(error), file=sys.stderr)
        return 130 if isinstance(error, KeyboardInterrupt) else 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
