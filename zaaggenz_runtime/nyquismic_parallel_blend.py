"""Opt-in, source-verified Nyquismic parallel dry/wet WAV bounce.

An offline musical production control for an already rendered saved-Compose
listening/DAW kit: choose a virtual-rate take and blend it with the original
full mix at a constant linear-amplitude wet percentage. This is not an
upstream graph insert, a replacement for Compose export, or mastering.
No gain compensation, normalisation, limiting, clipping or resampling.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
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
CHUNK_FRAMES = 65536


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _check(cancelled) -> None:
    if cancelled is not None and cancelled():
        raise RuntimeError("NYQ parallel blend cancelled")


def _percentage(value) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("wet percent must be finite, 0..100")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("wet percent must be finite, 0..100") from None
    if not number.is_finite() or not Decimal(0) <= number <= Decimal(100):
        raise ValueError("wet percent must be finite, 0..100")
    if number.as_tuple().exponent < -6:
        raise ValueError("wet percent supports at most six decimal places")
    return number


def _project_unchanged(path: str | Path | None, expected: str, cancelled) -> None:
    if path is None:
        return
    _check(cancelled)
    project = Path(path)
    if not project.is_file() or project.stat().st_size > MAX_PROJECT:
        raise RuntimeError("saved Compose project missing or enlarged during NYQ blend")
    if _sha(project.read_bytes()) != expected:
        raise RuntimeError("saved Compose project changed during NYQ blend")


def _pcm(source: bytes, entry: dict, frames: int, channels: int) -> np.ndarray:
    if _sha(source) != entry["wav_sha256"]:
        raise RuntimeError("NYQ blend input WAV differs from verified kit")
    rate, pcm = wavfile.read(io.BytesIO(source))
    actual_channels = 1 if pcm.ndim == 1 else pcm.shape[1] if pcm.ndim == 2 else -1
    if (rate != SAMPLE_RATE or pcm.dtype != np.float32
            or pcm.shape[0] != frames or actual_channels != channels
            or not np.isfinite(pcm).all()):
        raise RuntimeError("NYQ blend requires aligned finite 48-kHz float32 PCM")
    return pcm


def bounce_parallel_blend(
    kit_path: str | Path, output_wav: str | Path, *, virtual_rate_hz: str,
    wet_percent: str | int | float = "50",
    project_path: str | Path | None = None,
    expected_zip_sha256: str | None = None, cancelled=None,
) -> dict:
    """Publish one verified full-length float32 WAV without replacing any file.

    A supplied original project and externally trusted complete kit SHA-256
    authenticate origin. Without them, kit verification proves only internal
    consistency. Source/destination mutation by an uncooperative writer cannot
    be made fully transactional; post-link validation permits bounded rollback.
    """
    if cancelled is not None and not callable(cancelled):
        raise ValueError("cancelled must be callable")
    percent = _percentage(wet_percent)
    alpha = float(percent / Decimal(100))
    dest = Path(output_wav).absolute()
    if dest.suffix.lower() != ".wav" or not dest.parent.is_dir():
        raise ValueError("output must be a new .wav in an existing directory")
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(str(dest))
    verified = verify_production_kit(
        kit_path, project_path=project_path,
        expected_zip_sha256=expected_zip_sha256, cancelled=cancelled)
    rates = verified["virtual_rates_hz"]
    if type(virtual_rate_hz) is not str or virtual_rate_hz not in rates:
        raise ValueError("virtual rate must exactly match a source kit rate")
    selected = rates.index(virtual_rate_hz) + 1
    _check(cancelled)
    snapshot = Path(kit_path).read_bytes()
    if _sha(snapshot) != verified["zip_sha256"]:
        raise RuntimeError("NYQ production kit changed after verification")
    with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
        original = archive.read("original.wav")
        processed = archive.read(f"nyq-rate-{selected:02d}.wav")
    dry = _pcm(original, verified["tracks"][0], verified["frames"], verified["channels"])
    wet = _pcm(processed, verified["tracks"][selected], verified["frames"], verified["channels"])
    _check(cancelled)
    if percent == 0:
        output = dry.copy()
    elif percent == 100:
        output = wet.copy()
    else:
        output = np.empty_like(dry)
        # Chunked float64 intermediates; fixed-rate, frame-aligned mixing,
        # never a virtual clock change or a fresh sampler/analysis invocation.
        for start in range(0, verified["frames"], CHUNK_FRAMES):
            _check(cancelled)
            stop = min(start + CHUNK_FRAMES, verified["frames"])
            a = dry[start:stop].astype(np.float64)
            b = wet[start:stop].astype(np.float64)
            output[start:stop] = (a + (b - a) * alpha).astype(np.float32)
            # Exact-equal sources remain sample-identical at any setting.
            same = dry[start:stop] == wet[start:stop]
            output[start:stop][same] = dry[start:stop][same]
    if not np.isfinite(output).all():
        raise RuntimeError("nonfinite NYQ blend PCM")
    pcm_sha = _sha(np.asarray(output, dtype="<f4").tobytes(order="C"))
    peak = float(np.max(np.abs(output.astype(np.float64))))
    _project_unchanged(project_path, verified["source_project_sha256"], cancelled)
    _check(cancelled)
    fd, filename = tempfile.mkstemp(prefix=".nyq-blend-", suffix=".partial", dir=dest.parent)
    staged = Path(filename)
    try:
        with os.fdopen(fd, "w+b") as handle:
            wavfile.write(handle, SAMPLE_RATE, output)
            handle.flush()
            os.fsync(handle.fileno())
        wav_sha = _sha(staged.read_bytes())
        if _sha(Path(kit_path).read_bytes()) != verified["zip_sha256"]:
            raise RuntimeError("NYQ source kit changed before blend publication")
        _project_unchanged(project_path, verified["source_project_sha256"], cancelled)
        _check(cancelled)
        original_stat = staged.stat()
        os.link(staged, dest)  # atomic create-if-absent; no implicit replacement
        try:
            _check(cancelled)
            if _sha(Path(kit_path).read_bytes()) != verified["zip_sha256"]:
                raise RuntimeError("NYQ source kit changed during blend publication")
            _project_unchanged(project_path, verified["source_project_sha256"], cancelled)
            _check(cancelled)
        except BaseException:
            # Refuse to unlink another writer's replaced output.
            try:
                published = dest.stat(follow_symlinks=False)
                if (published.st_dev, published.st_ino, published.st_size, published.st_mtime_ns) == (
                        original_stat.st_dev, original_stat.st_ino,
                        original_stat.st_size, original_stat.st_mtime_ns):
                    dest.unlink()
            except FileNotFoundError:
                pass
            raise
    finally:
        staged.unlink(missing_ok=True)
    return {
        "format": "nyq.verified-parallel-blend.v1",
        "absolute_path": str(dest), "wav_sha256": wav_sha,
        "pcm_f32le_sha256": pcm_sha, "kit_sha256": verified["zip_sha256"],
        "dry_wav_sha256": verified["tracks"][0]["wav_sha256"],
        "wet_wav_sha256": verified["tracks"][selected]["wav_sha256"],
        "virtual_rate_hz": virtual_rate_hz, "wet_percent": str(percent),
        "mix_law": "linear_amplitude_dry_1_minus_wet",
        "frames": verified["frames"], "channels": verified["channels"],
        "delivery_hz": SAMPLE_RATE, "peak_abs": peak,
        "exceeds_unity_peak": peak > 1.0,
        "trusted_kit_checked": verified["trusted_zip_sha_checked"],
        "source_project_checked": verified["original_project_checked"],
        "scope": "Opt-in post-Compose full-mix bounce; no graph/rack/final-export admission",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Blend a saved Compose original mix with one verified NYQ take")
    parser.add_argument("--kit", required=True, help="Cold-reopened listening/DAW kit ZIP")
    parser.add_argument("--output", required=True, help="New float32 48-kHz WAV, never overwritten")
    parser.add_argument("--virtual-hz", required=True, help="An exact kit rate, e.g. 4/1")
    parser.add_argument("--wet-percent", default="50", help="Linear-amplitude NYQ wet, 0..100 percent")
    parser.add_argument("--project", help="Optional original saved Compose .zgtimeline.json")
    parser.add_argument("--expected-sha256", help="Externally trusted complete source kit SHA-256")
    args = parser.parse_args(argv)
    try:
        result = bounce_parallel_blend(
            args.kit, args.output, virtual_rate_hz=args.virtual_hz,
            wet_percent=args.wet_percent, project_path=args.project,
            expected_zip_sha256=args.expected_sha256)
    except (Exception, KeyboardInterrupt) as exc:
        print("NYQ parallel blend failed: " + str(exc), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
