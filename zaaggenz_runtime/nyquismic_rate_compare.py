"""One-page, phase-aligned offline comparison of an authenticated NYQ rate-sweep ZIP.

An opt-in postprocessor, NOT a registered Compose route. It never rerenders,
normalizes, resamples, or modifies the original 48-kHz float32 WAV bytes.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
from html import escape
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

import numpy as np
from scipy.io import wavfile

SWEEP_FORMAT = "nyq.saved-compose-rate-sweep.v1"
FORMAT = "nyq.multi-rate-compare-html.v1"
MAX_ZIP_BYTES = 128 * 1024 * 1024
MAX_PAGE_BYTES = 32 * 1024 * 1024
MAX_AUDIO_BYTES = 64 * 1024 * 1024
MAX_FRAMES = 4_000_000
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_PAYLOAD = re.compile(rb'<script id="nyq-payload" type="application/json">(.*?)</script>', re.S)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _cancel(cancelled) -> None:
    if cancelled is not None and cancelled():
        raise RuntimeError("NYQ multi-rate comparison cancelled")


def _digest(value) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _wav(raw: bytes, receipt: dict, *, frames: int, channels: int) -> None:
    if not isinstance(receipt, dict) or not _digest(receipt.get("wav_sha256")) or not _digest(receipt.get("pcm_f32le_sha256")):
        raise ValueError("invalid WAV identity receipt")
    if _sha(raw) != receipt["wav_sha256"]:
        raise ValueError("WAV byte identity mismatch")
    rate, pcm = wavfile.read(io.BytesIO(raw))
    actual_channels = 1 if pcm.ndim == 1 else (pcm.shape[1] if pcm.ndim == 2 else -1)
    if (rate != 48000 or pcm.dtype != np.float32 or pcm.shape[0] != frames
            or actual_channels != channels or not np.isfinite(pcm).all()):
        raise ValueError("nonfinite, non-float32 or wrong-clock WAV")
    if _sha(np.asarray(pcm, dtype="<f4").tobytes(order="C")) != receipt["pcm_f32le_sha256"]:
        raise ValueError("decoded PCM identity mismatch")


def _verified_sweep(path: Path, cancelled=None):
    """Read one bounded ZIP snapshot; verify each embedded original WAV against all anchors."""
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_ZIP_BYTES:
        raise ValueError("rate-sweep ZIP absent or exceeds 128 MiB")
    _cancel(cancelled)
    raw = path.read_bytes()
    if not 0 < len(raw) <= MAX_ZIP_BYTES:
        raise ValueError("rate-sweep ZIP changed size during read")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        count = len(infos) - 2
        names = ["index.html", "manifest.json"] + [f"variant-{n:02d}.html" for n in range(1, count + 1)]
        if (count not in range(2, 7) or [i.filename for i in infos] != names
                or any(i.compress_type != zipfile.ZIP_STORED or i.flag_bits & 1 for i in infos)
                or infos[0].file_size > 1024 * 1024 or infos[1].file_size > 128 * 1024
                or any(not 0 < i.file_size <= MAX_PAGE_BYTES for i in infos[2:])
                or sum(i.file_size for i in infos) > MAX_ZIP_BYTES):
            raise ValueError("unexpected or oversized rate-sweep archive contents")
        manifest = json.loads(archive.read("manifest.json"))
        if (manifest.get("format") != SWEEP_FORMAT or manifest.get("delivery_rate_hz") != 48000
                or not isinstance(manifest.get("variants"), list)
                or len(manifest["variants"]) != count):
            raise ValueError("wrong rate-sweep manifest")
        anchor = manifest.get("source")
        if not isinstance(anchor, dict) or any(not _digest(anchor.get(k)) for k in (
                "project_file_sha256", "source_asset_sha256", "source_revision_sha256",
                "compose_recipe_sha256", "dry_pcm_f32le_sha256")):
            raise ValueError("missing immutable Compose source identities")
        if manifest.get("project_file_sha256") != anchor["project_file_sha256"]:
            raise ValueError("foreign project SHA")
        frames, channels = anchor.get("frames"), anchor.get("channels")
        if (type(frames) is not int or not 0 < frames <= MAX_FRAMES
                or type(channels) is not int or channels not in (1, 2)):
            raise ValueError("invalid common audio extent")
        dry = None
        variants = []
        total_bytes = 0
        rates = set()
        for i, entry in enumerate(manifest["variants"]):
            _cancel(cancelled)
            name = names[i + 2]
            page = archive.read(name)
            if (not isinstance(entry, dict) or entry.get("page") != name
                    or not _digest(entry.get("page_sha256")) or _sha(page) != entry["page_sha256"]):
                raise ValueError("rate-sweep page identity mismatch")
            matches = _PAYLOAD.findall(page)
            if len(matches) != 1:
                raise ValueError("invalid embedded NYQ page payload")
            payload = json.loads(matches[0])
            inner = payload.get("manifest")
            if (payload.get("format") != "nyq.ab48-local-audition-html.v1"
                    or payload.get("frames") != frames or payload.get("channels") != channels
                    or not isinstance(inner, dict) or inner.get("sample_rate_hz") != 48000
                    or inner.get("frames") != frames or inner.get("channels") != channels):
                raise ValueError("foreign or non-48-kHz embedded audio")
            if any(inner.get(k) != anchor[k] for k in (
                    "project_file_sha256", "source_asset_sha256", "source_revision_sha256",
                    "compose_recipe_sha256")):
                raise ValueError("foreign Compose source in rate-sweep variant")
            rate = entry.get("virtual_rate_hz")
            if (not isinstance(rate, str) or not re.fullmatch(r"[0-9]{1,10}/[0-9]{1,10}", rate)
                    or rate in rates or inner.get("virtual_rate_hz") != rate
                    or inner.get("evaluation_rate_hz") != manifest.get("evaluation_rate_hz")
                    or inner.get("packet_sha256") != entry.get("packet_sha256")
                    or not _digest(entry.get("packet_sha256"))):
                raise ValueError("foreign or duplicate virtual-rate/packet identity")
            rates.add(rate)
            pair = {}
            for key in ("dry", "wet"):
                encoded = payload.get(key)
                if not isinstance(encoded, str) or len(encoded) > MAX_AUDIO_BYTES * 2:
                    raise ValueError("oversized or invalid embedded WAV")
                data = base64.b64decode(encoded, validate=True)
                _wav(data, inner.get(key), frames=frames, channels=channels)
                total_bytes += len(data) if key == "wet" or dry is None else 0
                pair[key] = data
            if (inner["dry"]["pcm_f32le_sha256"] != anchor["dry_pcm_f32le_sha256"]
                    or inner["wet"]["pcm_f32le_sha256"] != entry.get("wet_pcm_f32le_sha256")):
                raise ValueError("foreign source dry or Nyquismic wet PCM")
            if dry is None:
                dry = pair["dry"]
            elif pair["dry"] != dry:
                raise ValueError("different original dry WAV bytes across virtual rates")
            if total_bytes > MAX_AUDIO_BYTES:
                raise ValueError("multi-rate comparison exceeds 64 MiB of original WAVs")
            variants.append({"rate": rate, "packet_sha256": entry["packet_sha256"],
                             "wet_pcm_sha256": inner["wet"]["pcm_f32le_sha256"],
                             "wet_wav_sha256": inner["wet"]["wav_sha256"],
                             "wet": pair["wet"]})
    return {"archive_sha256": _sha(raw), "source": anchor, "frames": frames,
            "channels": channels, "dry": dry, "variants": variants}


_HTML = r'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; media-src blob: data:">
<title>ZAAGGENZ / NYQ / RATE COMPARISON</title>
<style>
:root{color-scheme:dark;background:#090d11;color:#dbe6ec;font-family:Consolas,monospace}
body{max-width:900px;margin:25px auto;padding:18px}*{box-sizing:border-box}
header,.panel{border:2px solid #718c9d;background:#121b21;padding:18px;margin-bottom:14px}
h1{font-size:22px;color:#c9ebf1;letter-spacing:.07em}p{color:#adc3cf;line-height:1.5}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:14px 0}
button,a{font:inherit;border:1px solid #849aa7;background:#1d2c36;color:#e8f5f9;padding:10px;cursor:pointer;text-decoration:none}
button[aria-pressed="true"]{background:#c9ebf1;color:#10202a;font-weight:bold}
input{width:100%}pre{overflow-wrap:anywhere;white-space:pre-wrap;font-size:12px}
</style></head><body><header><h1>NYQUISMIC / VIRTUAL RATE COMPARISON</h1>
<p>Source-matched 48-kHz original and Nyquismic renders. All tracks share one playback clock and position. No normalization, gain matching, new source render or network connection.</p></header>
<section class="panel"><div class="row"><button id="play">PLAY</button><span id="clock">00:00 / 00:00</span></div>
<input id="seek" type="range" min="0" max="1000" value="0" aria-label="Seek audio">
<div id="choices" class="row">__CHOICES__</div><p id="status">Press PLAY to decode local WAVs.</p>
<div id="downloads" class="row">__DOWNLOADS__</div></section>
<section class="panel"><h2>SOURCE / AUDIO RECEIPT</h2><pre id="receipt"></pre></section>
<p>Opt-in offline artifact, post-Compose full mix only. This is not a registered graph, rack or session export. Browser output hardware may resample playback.</p>
<script id="nyq-compare-payload" type="application/json">__PAYLOAD__</script>
<script>"use strict";(() => {
const $ = id => document.getElementById(id);
const p = JSON.parse($('nyq-compare-payload').textContent);
const duration = p.frames / 48000;
const decode = b64 => {const binary=atob(b64), b=new Uint8Array(binary.length);
  for(let i=0;i<b.length;i++)b[i]=binary.charCodeAt(i); return b;};
const raw = p.wavs.map(decode), urls = raw.map(b=>URL.createObjectURL(new Blob([b],{type:'audio/wav'})));
urls.forEach((url,i)=>{$('download-'+i).href=url;});
$('receipt').textContent = JSON.stringify(p.receipt,null,2);
let context=null,buffers=null,sources=[],gains=[],envelopes=[];
let playing=false,offset=0,startedAt=0,selected=0;
const status=$('status'),play=$('play'),seek=$('seek');
const clockText=s=>{const n=Math.max(0,Math.floor(s));return String(Math.floor(n/60)).padStart(2,'0')+':'+String(n%60).padStart(2,'0');};
async function ensure(){if(buffers)return;
 context=new (window.AudioContext||window.webkitAudioContext)();await context.resume();
 buffers=await Promise.all(raw.map(data=>context.decodeAudioData(data.buffer.slice(0))));
 if(buffers.some(b=>b.numberOfChannels!==p.channels||Math.abs(b.duration-duration)>.001))throw new Error('WAV extent differs from manifest');}
function halt(){for(const s of sources){try{s.stop()}catch(_){ }s.disconnect()}
 sources=[];for(const g of gains)g.disconnect();gains=[];}
function level(i,t){const e=envelopes[i];if(t<=e.start)return e.from;
 if(t>=e.end)return e.to;return e.from+(e.to-e.from)*(t-e.start)/(e.end-e.start);}
function start(at){halt();offset=Math.max(0,Math.min(at,duration));if(offset>=duration)offset=0;
 const when=context.currentTime+.035;startedAt=when-offset;
 envelopes=raw.map((_,i)=>{const x=i===selected?1:0;return {from:x,to:x,start:when,end:when};});
 for(let i=0;i<raw.length;i++){const s=context.createBufferSource(),g=context.createGain();
 s.buffer=buffers[i];g.gain.value=i===selected?1:0;s.connect(g);g.connect(context.destination);
 s.start(when,offset);sources.push(s);gains.push(g);}playing=true;play.textContent='PAUSE';status.textContent='Playing synchronized tracks';}
function pause(){if(!playing)return;offset=Math.max(0,Math.min(duration,context.currentTime-startedAt));halt();playing=false;play.textContent='PLAY';status.textContent='Paused';}
function choose(index){selected=index;
 p.wavs.forEach((_,i)=>{$('choice-'+i).setAttribute('aria-pressed',String(i===selected));});
 if(!playing)return;const t=context.currentTime,end=t+.008;
 for(let i=0;i<gains.length;i++){const g=gains[i].gain,from=level(i,t),to=i===selected?1:0;
 if(typeof g.cancelAndHoldAtTime==='function'){g.cancelAndHoldAtTime(t)}
 else{g.cancelScheduledValues(t);g.setValueAtTime(from,t)}
 g.linearRampToValueAtTime(to,end);envelopes[i]={from,to,start:t,end};}
 status.textContent='Playing synchronized tracks';}
p.wavs.forEach((_,i)=>{$('choice-'+i).addEventListener('click',()=>choose(i));});
play.addEventListener('click',async()=>{try{await ensure();if(playing)pause();else start(offset)}catch(e){status.textContent='Playback unavailable: '+e.message}});
seek.addEventListener('input',()=>{const at=Number(seek.value)*duration/1000;if(playing)start(at);else offset=at;});
function tick(){let t=playing?Math.max(0,context.currentTime-startedAt):offset;
 if(playing&&t>=duration){pause();offset=0;t=0}if(document.activeElement!==seek)seek.value=String(Math.round(t*1000/duration));
 $('clock').textContent=clockText(t)+' / '+clockText(duration);requestAnimationFrame(tick);}tick();
})();</script></body></html>'''


def publish_rate_comparison(sweep_zip: str | Path, output: str | Path, *, cancelled=None) -> dict:
    """Atomic, no-clobber single-page multi-rate playback from a verified saved sweep."""
    if cancelled is not None and not callable(cancelled):
        raise ValueError("cancelled must be callable")
    dest = Path(output).absolute()
    if dest.suffix.lower() != ".html" or not dest.parent.is_dir():
        raise ValueError("output must be HTML in an existing directory")
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(str(dest))
    record = _verified_sweep(Path(sweep_zip), cancelled)
    names = ["ORIGINAL"] + [v["rate"] + " Hz" for v in record["variants"]]
    choices = ''.join(f'<button id="choice-{i}" type="button" aria-pressed="{str(i==0).lower()}">{escape(n)}</button>'
                      for i,n in enumerate(names))
    downloads = ''.join(f'<a id="download-{i}" download="{escape("original" if i==0 else "nyq-rate-"+str(i),quote=True)}.wav">SAVE {escape(n)} WAV</a>'
                        for i,n in enumerate(names))
    receipt = {"format": FORMAT, "source": record["source"], "archive_sha256": record["archive_sha256"],
               "dry_wav_sha256": _sha(record["dry"]),
               "rates": [{k:v[k] for k in ("rate", "packet_sha256", "wet_pcm_sha256", "wet_wav_sha256")}
                         for v in record["variants"]]}
    wavs = [record["dry"]] + [v["wet"] for v in record["variants"]]
    payload = {"format": FORMAT, "frames": record["frames"], "channels": record["channels"],
               "wavs": [base64.b64encode(w).decode('ascii') for w in wavs], "receipt": receipt}
    safe = json.dumps(payload, separators=(',', ':'), sort_keys=True, allow_nan=False).replace('<','\\u003c')
    page = _HTML.replace('__CHOICES__', choices).replace('__DOWNLOADS__', downloads).replace('__PAYLOAD__', safe).encode()
    _cancel(cancelled)
    fd, path = tempfile.mkstemp(prefix='.nyq-rate-compare-',suffix='.partial',dir=str(dest.parent))
    tmp = Path(path)
    try:
        with os.fdopen(fd,'wb') as f:
            for at in range(0,len(page),1024*1024):
                _cancel(cancelled);f.write(page[at:at+1024*1024])
            f.flush();os.fsync(f.fileno())
        _cancel(cancelled)
        with tmp.open('rb') as f:
            h = hashlib.sha256()
            for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
        if h.hexdigest()!=_sha(page):raise RuntimeError('staged comparison HTML changed')
        _cancel(cancelled)
        os.link(tmp,dest)
    finally:
        tmp.unlink(missing_ok=True)
    return {"format":FORMAT, "absolute_path":str(dest), "html_sha256":_sha(page),
            "source_zip_sha256":record["archive_sha256"], "rates_hz":[v["rate"] for v in record["variants"]],
            "frames":record["frames"], "channels":record["channels"], "delivery_hz":48000}


def main(argv=None):
    ap=argparse.ArgumentParser(description='Build a single offline A/B/multi-rate listener from a verified NYQ sweep ZIP')
    ap.add_argument('--sweep',required=True,help='Existing #289 source-authenticated rate-sweep ZIP')
    ap.add_argument('--output',required=True,help='New offline .html; never overwritten')
    a=ap.parse_args(argv)
    try:receipt=publish_rate_comparison(a.sweep,a.output)
    except (Exception,KeyboardInterrupt) as exc:
        print('NYQ multi-rate comparison failed: '+str(exc),file=sys.stderr)
        return 130 if isinstance(exc,KeyboardInterrupt) else 1
    print(json.dumps(receipt,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
