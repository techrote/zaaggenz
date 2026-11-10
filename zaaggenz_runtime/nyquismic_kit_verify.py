"""Read-only cold-reopen integrity verifier for opt-in Nyquismic production kits.

This checks original 48-kHz WAV/decoded PCM, source/packet receipt consistency,
and equality with the embedded offline listener. Internal digests alone are not
cryptographic proof of provenance; an independent expected ZIP SHA and/or the
original saved Compose project can be supplied as external evidence.
"""
from __future__ import annotations

import argparse
import base64
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import zipfile

import numpy as np
from scipy.io import wavfile

FORMAT = "nyq.saved-compose-listen-and-daw-kit.v1"
LISTENER_FORMAT = "nyq.multi-rate-compare-html.v1"
MAX_ZIP = 128 * 1024 * 1024
MAX_HTML = 32 * 1024 * 1024
MAX_AUDIO = 64 * 1024 * 1024
MAX_PROJECT = 2_000_000
MAX_FRAMES = 4_000_000
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_RATE = re.compile(r"[1-9][0-9]{0,9}/[1-9][0-9]{0,9}\Z")
_PAYLOAD = re.compile(rb'<script id="nyq-compare-payload" type="application/json">(.*?)</script>', re.S)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(value) -> bool:
    return isinstance(value, str) and bool(_SHA.fullmatch(value))


def _check(cancelled):
    if cancelled is not None and cancelled():
        raise RuntimeError("NYQ production-kit verification cancelled")


def _json(raw: bytes):
    def invalid(value):
        raise ValueError("non-finite JSON constant: " + value)
    return json.loads(raw, parse_constant=invalid)


def _wav(raw: bytes, entry: dict, frames: int, channels: int):
    if not _digest(entry.get("wav_sha256")) or _hash(raw) != entry["wav_sha256"]:
        raise ValueError("kit WAV byte identity mismatch")
    if not _digest(entry.get("pcm_f32le_sha256")):
        raise ValueError("kit PCM receipt missing")
    rate, pcm = wavfile.read(io.BytesIO(raw))
    n_channels = 1 if pcm.ndim == 1 else (pcm.shape[1] if pcm.ndim == 2 else -1)
    if (rate != 48000 or pcm.dtype != np.float32 or pcm.shape[0] != frames
            or n_channels != channels or not np.isfinite(pcm).all()):
        raise ValueError("kit WAV must contain finite 48-kHz float32 PCM at declared extent")
    if _hash(np.asarray(pcm, dtype="<f4").tobytes(order="C")) != entry["pcm_f32le_sha256"]:
        raise ValueError("kit decoded PCM identity mismatch")


def verify_production_kit(path: str | Path, *, expected_zip_sha256: str | None = None,
                          project_path: str | Path | None = None, cancelled=None) -> dict:
    """Verify one immutable ZIP snapshot; never write or repair source/output files."""
    if cancelled is not None and not callable(cancelled):
        raise ValueError("cancelled must be callable")
    if expected_zip_sha256 is not None and not _digest(expected_zip_sha256):
        raise ValueError("expected ZIP SHA-256 must be 64 lowercase hexadecimal characters")
    source = Path(path)
    if not source.is_file() or not 0 < source.stat().st_size <= MAX_ZIP:
        raise ValueError("production kit missing or exceeds 128 MiB")
    _check(cancelled)
    raw = source.read_bytes()
    if not 0 < len(raw) <= MAX_ZIP:
        raise ValueError("production kit changed size while reading")
    zip_sha = _hash(raw)
    if expected_zip_sha256 is not None and zip_sha != expected_zip_sha256:
        raise ValueError("production kit does not match trusted ZIP SHA-256")
    _check(cancelled)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        count = len(infos) - 3
        names = ["manifest.json", "listen.html", "original.wav"] + [
            f"nyq-rate-{i:02d}.wav" for i in range(1, count + 1)]
        if (count not in range(2, 7) or [i.filename for i in infos] != names
                or any(i.compress_type != zipfile.ZIP_STORED or i.flag_bits & 1 for i in infos)
                or infos[0].file_size > 128 * 1024
                or not 0 < infos[1].file_size <= MAX_HTML
                or sum(i.file_size for i in infos[2:]) > MAX_AUDIO
                or sum(i.file_size for i in infos) > MAX_ZIP):
            raise ValueError("invalid production kit ZIP structure or size")
        manifest = _json(archive.read("manifest.json"))
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
            raise ValueError("wrong production kit manifest format")
        anchor = manifest.get("source")
        source_keys = ("project_file_sha256", "source_asset_sha256",
                       "source_revision_sha256", "compose_recipe_sha256",
                       "dry_pcm_f32le_sha256")
        if not isinstance(anchor, dict) or any(not _digest(anchor.get(k)) for k in source_keys):
            raise ValueError("missing immutable Compose provenance identifiers")
        frames, channels = manifest.get("frames"), manifest.get("channels")
        if (type(frames) is not int or not 0 < frames <= MAX_FRAMES
                or type(channels) is not int or channels not in (1, 2)
                or anchor.get("frames") != frames or anchor.get("channels") != channels
                or manifest.get("sample_rate_hz") != 48000
                or manifest.get("project_file_sha256") != anchor["project_file_sha256"]
                or not _digest(manifest.get("source_sweep_sha256"))
                or not _digest(manifest.get("listen_html_sha256"))):
            raise ValueError("invalid source, clocks, or extent in kit manifest")
        tracks = manifest.get("tracks")
        if not isinstance(tracks, list) or len(tracks) != count + 1:
            raise ValueError("invalid kit track count")
        if (tracks[0].get("virtual_rate_hz") is not None
                or tracks[0].get("packet_sha256") is not None
                or tracks[0].get("pcm_f32le_sha256") != anchor["dry_pcm_f32le_sha256"]):
            raise ValueError("invalid original dry track provenance")
        rates = []
        for i, entry in enumerate(tracks[1:], 1):
            if not isinstance(entry, dict):
                raise ValueError("invalid Nyquismic track record")
            rate = entry.get("virtual_rate_hz")
            if not isinstance(rate, str) or not _RATE.fullmatch(rate):
                raise ValueError("invalid virtual-rate identity")
            fraction = Fraction(rate)
            if (not 0 < fraction <= 1_000_000
                    or rate != f"{fraction.numerator}/{fraction.denominator}"
                    or rate in rates or not _digest(entry.get("packet_sha256"))):
                raise ValueError("duplicate, noncanonical or foreign clock packet")
            rates.append(rate)
        wavs = []
        for name, entry in zip(names[2:], tracks):
            _check(cancelled)
            if not isinstance(entry, dict) or entry.get("file") != name:
                raise ValueError("kit track name mismatch")
            wav = archive.read(name)
            _wav(wav, entry, frames, channels)
            wavs.append(wav)
        _check(cancelled)
        page = archive.read("listen.html")
        if _hash(page) != manifest["listen_html_sha256"]:
            raise ValueError("kit listener HTML SHA-256 mismatch")
    matches = _PAYLOAD.findall(page)
    if len(matches) != 1:
        raise ValueError("kit listening page payload absent or ambiguous")
    payload = _json(matches[0])
    receipt = payload.get("receipt") if isinstance(payload, dict) else None
    if (not isinstance(receipt, dict)
            or payload.get("format") != LISTENER_FORMAT
            or payload.get("frames") != frames or payload.get("channels") != channels
            or receipt.get("format") != LISTENER_FORMAT
            or receipt.get("source") != anchor
            or receipt.get("archive_sha256") != manifest["source_sweep_sha256"]
            or receipt.get("dry_wav_sha256") != tracks[0]["wav_sha256"]):
        raise ValueError("kit listening receipt does not match archived source")
    live_rates = receipt.get("rates")
    encoded = payload.get("wavs")
    if (not isinstance(live_rates, list) or len(live_rates) != count
            or not isinstance(encoded, list) or len(encoded) != len(wavs)):
        raise ValueError("kit listener track count differs from DAW files")
    for i, record in enumerate(live_rates, 1):
        entry = tracks[i]
        if (not isinstance(record, dict)
                or record.get("rate") != entry["virtual_rate_hz"]
                or record.get("packet_sha256") != entry["packet_sha256"]
                or record.get("wet_pcm_sha256") != entry["pcm_f32le_sha256"]
                or record.get("wet_wav_sha256") != entry["wav_sha256"]):
            raise ValueError("kit listener rate/PCM/packet differs from DAW manifest")
    for actual, b64 in zip(wavs, encoded):
        _check(cancelled)
        if not isinstance(b64, str) or len(b64) > (MAX_AUDIO * 4 // 3 + 4):
            raise ValueError("invalid embedded listener WAV")
        if base64.b64decode(b64, validate=True) != actual:
            raise ValueError("kit listener WAV differs from DAW WAV")
    _check(cancelled)
    if project_path is not None:
        project = Path(project_path)
        if (not project.name.endswith(".zgtimeline.json") or not project.is_file()
                or project.stat().st_size > MAX_PROJECT):
            raise ValueError("expected original saved Compose project <=2MB")
        _check(cancelled)
        original = project.read_bytes()
        if len(original) > MAX_PROJECT or _hash(original) != anchor["project_file_sha256"]:
            raise ValueError("kit not bound to supplied saved Compose project bytes")
    _check(cancelled)
    return {"format": FORMAT, "zip_sha256": zip_sha, "delivery_hz": 48000,
            "frames": frames, "channels": channels, "virtual_rates_hz": rates,
            "source_project_sha256": anchor["project_file_sha256"],
            "source_sweep_sha256": manifest["source_sweep_sha256"],
            "tracks": [{"file": x["file"], "wav_sha256": x["wav_sha256"],
                        "pcm_f32le_sha256": x["pcm_f32le_sha256"]} for x in tracks],
            "trusted_zip_sha_checked": expected_zip_sha256 is not None,
            "original_project_checked": project_path is not None,
            "qualification": "self-consistent cold-reopened audio; not independent proof of graph routing or source generation"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only integrity audit of an offline Nyquismic production kit")
    parser.add_argument("--kit", required=True, help="Saved listening + DAW .zip")
    parser.add_argument("--expected-sha256", help="Trusted externally recorded complete ZIP SHA-256")
    parser.add_argument("--project", help="Optional original saved Compose .zgtimeline.json")
    args = parser.parse_args(argv)
    try:
        result = verify_production_kit(args.kit, expected_zip_sha256=args.expected_sha256,
                                       project_path=args.project)
    except (Exception, KeyboardInterrupt) as exc:
        print("NYQ production kit verification failed: " + str(exc), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
