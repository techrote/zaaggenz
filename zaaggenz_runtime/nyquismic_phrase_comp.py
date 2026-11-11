"""Opt-in, source-verified multirate phrase comp from a saved Compose NYQ kit.

Arrange whole-mix render alternatives on the original 48-kHz timeline.
Each transition crossfades aligned pre-rendered PCM; this does NOT modulate
the underlying sampler clock, insert an effect into the graph, normalize
levels, or change ordinary Compose export. No audio/source is uploaded.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
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

from zaaggenz_runtime.nyquismic_kit_verify import verify_production_kit

SAMPLE_RATE = 48000
MAX_PROJECT = 2_000_000
MAX_CUES = 64
CHUNK_FRAMES = 65536


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _check(cancelled) -> None:
    if cancelled is not None and cancelled():
        raise RuntimeError("NYQ phrase comp cancelled")


def _milliseconds(value: str, *, minimum: int = 0, maximum: int = 100000) -> tuple[Decimal, int]:
    if type(value) is not str:
        raise ValueError("time must be a finite decimal millisecond string")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError("time must be a finite decimal millisecond string") from None
    if (not number.is_finite() or not minimum <= number <= maximum
            or number.as_tuple().exponent < -6):
        raise ValueError(f"time must be {minimum}..{maximum} ms (up to six decimal places)")
    frames = int((number * Decimal(48)).to_integral_value(rounding=ROUND_HALF_UP))
    return number, frames


def _cues(raw_cues: list[str], rates: list[str], frames: int, fade: int) -> list[dict]:
    if type(raw_cues) is not list or not 2 <= len(raw_cues) <= MAX_CUES:
        raise ValueError("provide 2..64 ordered --cue TIME_MS=original|RATE entries")
    permitted = {"original", *rates}
    out: list[dict] = []
    for index, value in enumerate(raw_cues):
        if type(value) is not str or value.count("=") != 1:
            raise ValueError("each cue must have TIME_MS=original|RATE syntax")
        when, source = value.split("=", 1)
        decimal_time, frame = _milliseconds(when)
        if source not in permitted:
            raise ValueError("cue target must match original or an exact kit virtual rate")
        if frame >= frames:
            raise ValueError("cue lies outside the saved Compose phrase")
        if index == 0:
            if frame != 0 or decimal_time != 0:
                raise ValueError("the first cue must start at 0 ms")
        else:
            if frame <= out[-1]["frame"]:
                raise ValueError("cue frames must increase strictly after quantization")
            if source == out[-1]["source"]:
                raise ValueError("consecutive cues cannot repeat the same source")
            if frame + fade > frames:
                raise ValueError("crossfade extends beyond the phrase")
            if index > 1 and frame < out[-1]["frame"] + fade:
                raise ValueError("crossfades overlap")
        out.append({"time_ms": str(decimal_time), "frame": frame, "source": source})
    return out


def _project_unchanged(path, expected: str, cancelled) -> None:
    if path is None:
        return
    _check(cancelled)
    project = Path(path)
    if not project.is_file() or project.stat().st_size > MAX_PROJECT:
        raise RuntimeError("saved Compose project removed or enlarged during phrase comp")
    if _hash(project.read_bytes()) != expected:
        raise RuntimeError("saved Compose project changed during phrase comp")


def _read_pcm(raw: bytes, record: dict, frames: int, channels: int) -> np.ndarray:
    if _hash(raw) != record["wav_sha256"]:
        raise RuntimeError("NYQ phrase comp WAV differs from verified kit")
    rate, pcm = wavfile.read(io.BytesIO(raw))
    actual_channels = 1 if pcm.ndim == 1 else pcm.shape[1] if pcm.ndim == 2 else -1
    if (rate != SAMPLE_RATE or pcm.dtype != np.float32
            or pcm.shape[0] != frames or actual_channels != channels
            or not np.isfinite(pcm).all()
            or _hash(np.asarray(pcm, dtype="<f4").tobytes(order="C")) != record["pcm_f32le_sha256"]):
        raise RuntimeError("NYQ phrase comp requires source-verified aligned 48-kHz float32 PCM")
    return pcm


def _copy_chunks(target, source, begin: int, end: int, cancelled) -> None:
    for start in range(begin, end, CHUNK_FRAMES):
        _check(cancelled)
        stop = min(start + CHUNK_FRAMES, end)
        target[start:stop] = source[start:stop]


def _assemble(tracks: dict[str, np.ndarray], cues: list[dict], fade: int, cancelled) -> np.ndarray:
    frames = len(next(iter(tracks.values())))
    result = np.empty_like(next(iter(tracks.values())))
    previous = cues[0]["source"]
    cursor = 0
    for cue in cues[1:]:
        boundary, following = cue["frame"], cue["source"]
        _copy_chunks(result, tracks[previous], cursor, boundary, cancelled)
        for start in range(boundary, boundary + fade, CHUNK_FRAMES):
            _check(cancelled)
            stop = min(start + CHUNK_FRAMES, boundary + fade)
            relative = np.arange(start - boundary, stop - boundary, dtype=np.float64)
            weight = 0.5 - 0.5 * np.cos(np.pi * relative / (fade - 1))
            if result.ndim == 2:
                weight = weight[:, None]
            a = tracks[previous][start:stop]
            b = tracks[following][start:stop]
            mixed = (a.astype(np.float64) +
                     (b.astype(np.float64) - a.astype(np.float64)) * weight).astype(np.float32)
            mixed[a == b] = a[a == b]  # exact unchanged samples, including signed zero
            result[start:stop] = mixed
        result[boundary] = tracks[previous][boundary]
        result[boundary + fade - 1] = tracks[following][boundary + fade - 1]
        cursor = boundary + fade
        previous = following
    _copy_chunks(result, tracks[previous], cursor, frames, cancelled)
    if not np.isfinite(result).all():
        raise RuntimeError("nonfinite NYQ phrase comp output")
    return result


def bounce_phrase_comp(
    kit_path: str | Path, output_wav: str | Path, *, cues: list[str],
    crossfade_ms: str = "12", project_path: str | Path | None = None,
    expected_zip_sha256: str | None = None, cancelled=None,
) -> dict:
    """Produce a deterministic offline rate-arranged 48-kHz float32 WAV.

    Optional external kit SHA and original saved project authenticate origin;
    internal checks alone establish consistency. Source/destination mutation
    by hostile concurrent writers is not a globally atomic transaction.
    """
    if cancelled is not None and not callable(cancelled):
        raise ValueError("cancelled must be callable")
    _, fade = _milliseconds(str(crossfade_ms), minimum=2, maximum=100)
    dest = Path(output_wav).absolute()
    if dest.suffix.lower() != ".wav" or not dest.parent.is_dir():
        raise ValueError("output must be a new WAV in an existing directory")
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(str(dest))
    verified = verify_production_kit(
        kit_path, expected_zip_sha256=expected_zip_sha256,
        project_path=project_path, cancelled=cancelled)
    timeline = _cues(cues, verified["virtual_rates_hz"], verified["frames"], fade)
    _check(cancelled)
    snapshot = Path(kit_path).read_bytes()
    if _hash(snapshot) != verified["zip_sha256"]:
        raise RuntimeError("NYQ production kit changed after verification")
    labels = {item["source"] for item in timeline}
    identities = {"original": 0}
    identities.update({rate: i + 1 for i, rate in enumerate(verified["virtual_rates_hz"])})
    tracks = {}
    source_hashes = {}
    with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
        for label in sorted(labels):
            _check(cancelled)
            index = identities[label]
            raw = archive.read("original.wav" if index == 0 else f"nyq-rate-{index:02d}.wav")
            tracks[label] = _read_pcm(raw, verified["tracks"][index],
                                      verified["frames"], verified["channels"])
            source_hashes[label] = verified["tracks"][index]["wav_sha256"]
    output = _assemble(tracks, timeline, fade, cancelled)
    pcm_sha = _hash(np.asarray(output, dtype="<f4").tobytes(order="C"))
    peak = float(np.max(np.abs(output.astype(np.float64))))
    _project_unchanged(project_path, verified["source_project_sha256"], cancelled)
    _check(cancelled)
    fd, filename = tempfile.mkstemp(prefix=".nyq-phrase-", suffix=".partial", dir=dest.parent)
    staged = Path(filename)
    try:
        with os.fdopen(fd, "w+b") as handle:
            wavfile.write(handle, SAMPLE_RATE, output)
            handle.flush()
            os.fsync(handle.fileno())
        wav_sha = _hash(staged.read_bytes())
        if _hash(Path(kit_path).read_bytes()) != verified["zip_sha256"]:
            raise RuntimeError("NYQ source kit changed before phrase comp publication")
        _project_unchanged(project_path, verified["source_project_sha256"], cancelled)
        _check(cancelled)
        own = staged.stat()
        os.link(staged, dest)
        try:
            _check(cancelled)
            if _hash(Path(kit_path).read_bytes()) != verified["zip_sha256"]:
                raise RuntimeError("NYQ source kit changed during phrase comp publication")
            _project_unchanged(project_path, verified["source_project_sha256"], cancelled)
            _check(cancelled)
        except BaseException:
            # Never remove a competing writer's replacement.
            try:
                published = dest.stat(follow_symlinks=False)
                if (published.st_dev, published.st_ino, published.st_size, published.st_mtime_ns) == (
                        own.st_dev, own.st_ino, own.st_size, own.st_mtime_ns):
                    dest.unlink()
            except FileNotFoundError:
                pass
            raise
    finally:
        staged.unlink(missing_ok=True)
    return {
        "format": "nyq.multirate-phrase-comp.v1", "absolute_path": str(dest),
        "wav_sha256": wav_sha, "pcm_f32le_sha256": pcm_sha,
        "kit_sha256": verified["zip_sha256"], "source_wav_sha256": source_hashes,
        "cues": timeline, "crossfade_frames": fade, "crossfade_ms": str(crossfade_ms),
        "interpolation": "raised_cosine_aligned_source_pcm",
        "frames": verified["frames"], "channels": verified["channels"],
        "delivery_hz": SAMPLE_RATE, "peak_abs": peak, "exceeds_unity_peak": peak > 1.0,
        "trusted_kit_checked": verified["trusted_zip_sha_checked"],
        "source_project_checked": verified["original_project_checked"],
        "scope": "Opt-in post-Compose full-mix rate arrangement, not modulated clock, graph or master export",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sequence verified NYQ rate takes into an aligned offline phrase WAV")
    parser.add_argument("--kit", required=True, help="Saved listening + DAW kit ZIP")
    parser.add_argument("--output", required=True, help="New 48-kHz float32 WAV; never overwrite")
    parser.add_argument("--cue", action="append", required=True,
                        help="Repeat in time order: 0=original 150=4/1 300=5/1")
    parser.add_argument("--crossfade-ms", default="12", help="Raised cosine transition, 2..100 ms")
    parser.add_argument("--project", help="Optional original saved Compose project")
    parser.add_argument("--expected-sha256", help="Externally recorded trusted kit SHA-256")
    args = parser.parse_args(argv)
    try:
        result = bounce_phrase_comp(
            args.kit, args.output, cues=args.cue, crossfade_ms=args.crossfade_ms,
            project_path=args.project, expected_zip_sha256=args.expected_sha256)
    except (Exception, KeyboardInterrupt) as exc:
        print("NYQ phrase comp failed: " + str(exc), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
