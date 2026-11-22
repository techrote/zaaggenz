"""Source-checked, non-destructive 48-kHz dry/wet NYQ audition WAV bounce.

An optional *preview* of one original/virtual-rate pair from a verified saved
Compose production kit. A single time-aligned timeline alternates between the
unchanged dry and wet PCM with deterministic raised-cosine crossfades. It never
modifies the source WAVs, the kit, or any ordinary Compose audio/graph settings.
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


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check(cancelled):
    if cancelled is not None and cancelled():
        raise RuntimeError("NYQ A/B WAV bounce cancelled")


def _frames_ms(value, *, low: int, high: int, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(label + " must be a finite decimal duration in milliseconds")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(label + " must be a finite decimal duration in milliseconds") from None
    if not number.is_finite() or not low <= number <= high:
        raise ValueError(f"{label} must be {low}..{high} ms")
    return int((number * 48).to_integral_value(rounding=ROUND_HALF_UP))


def _project_unchanged(path: str | Path | None, expected: str, cancelled) -> None:
    if path is None:
        return
    _check(cancelled)
    project = Path(path)
    if not project.is_file() or project.stat().st_size > MAX_PROJECT:
        raise RuntimeError("saved Compose project removed or enlarged during NYQ preview")
    if _sha(project.read_bytes()) != expected:
        raise RuntimeError("saved Compose project changed during NYQ preview")


def _weights(frames: int, period: int, fade: int, cancelled=None) -> np.ndarray:
    """Wet mix coefficient; the first segment is always 100% dry."""
    wet = np.zeros(frames, dtype=np.float64)
    for segment, start in enumerate(range(0, frames, period)):
        _check(cancelled)
        stop = min(start + period, frames)
        is_wet = segment % 2 == 1
        if is_wet:
            wet[start:stop] = 1.0
        if segment:
            length = min(fade, stop - start)
            if length > 0:
                u = np.arange(length, dtype=np.float64) / (fade - 1)
                curve = 0.5 - 0.5 * np.cos(np.pi * u)
                wet[start:start + length] = curve if is_wet else 1.0 - curve
    return wet


def bounce_ab_preview(
    kit_path: str | Path, output_wav: str | Path, *, virtual_rate_hz: str,
    period_ms: int | str | float = 1000, crossfade_ms: int | str | float = 12,
    project_path: str | Path | None = None,
    expected_zip_sha256: str | None = None, cancelled=None,
) -> dict:
    """Produce a verified, aligned A/B audition WAV with no-overwrite publication.

    Internal kit digests establish consistency, not independently trusted origin.
    Pass project_path and externally recorded expected_zip_sha256 to bind origin.
    This is a preview-only bounce; no loudness matching, clipping or master export.
    """
    if cancelled is not None and not callable(cancelled):
        raise ValueError("cancelled must be callable")
    period = _frames_ms(period_ms, low=50, high=60000, label="period")
    fade = _frames_ms(crossfade_ms, low=2, high=100, label="crossfade")
    if fade * 2 >= period:
        raise ValueError("crossfade must be shorter than half of a segment")
    dest = Path(output_wav).absolute()
    if dest.suffix.lower() != ".wav" or not dest.parent.is_dir():
        raise ValueError("output must be a new .wav in an existing directory")
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(str(dest))
    verified = verify_production_kit(
        kit_path, project_path=project_path, expected_zip_sha256=expected_zip_sha256,
        cancelled=cancelled)
    rates = verified["virtual_rates_hz"]
    if type(virtual_rate_hz) is not str or virtual_rate_hz not in rates:
        raise ValueError("virtual clock rate must exactly match one kit rate")
    selected = rates.index(virtual_rate_hz) + 1
    _check(cancelled)
    snapshot = Path(kit_path).read_bytes()
    if _sha(snapshot) != verified["zip_sha256"]:
        raise RuntimeError("NYQ production kit changed after verification")
    with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
        dry_bytes = archive.read("original.wav")
        wet_bytes = archive.read(f"nyq-rate-{selected:02d}.wav")
    if (_sha(dry_bytes) != verified["tracks"][0]["wav_sha256"]
            or _sha(wet_bytes) != verified["tracks"][selected]["wav_sha256"]):
        raise RuntimeError("NYQ WAV source differs from verified kit")
    dry_rate, dry = wavfile.read(io.BytesIO(dry_bytes))
    wet_rate, wet = wavfile.read(io.BytesIO(wet_bytes))
    if (dry_rate != SAMPLE_RATE or wet_rate != SAMPLE_RATE or dry.shape != wet.shape
            or dry.shape[0] != verified["frames"] or dry.dtype != np.float32
            or wet.dtype != np.float32 or not np.isfinite(dry).all()
            or not np.isfinite(wet).all()):
        raise RuntimeError("NYQ preview sources must be aligned finite 48-kHz float32 PCM")
    _check(cancelled)
    weights = _weights(verified["frames"], period, fade, cancelled)
    if dry.ndim == 2:
        weights = weights[:, None]
    # Float64 intermediates avoid unnecessary rounding; identical dry/wet
    # PCM produces byte-identical output PCM without a silent gain change.
    output = (dry.astype(np.float64) +
              (wet.astype(np.float64) - dry.astype(np.float64)) * weights).astype(np.float32)
    if not np.isfinite(output).all():
        raise RuntimeError("NYQ preview contains non-finite samples")
    pcm_sha = _sha(np.asarray(output, dtype="<f4").tobytes(order="C"))
    _project_unchanged(project_path, verified["source_project_sha256"], cancelled)
    _check(cancelled)
    fd, temp_name = tempfile.mkstemp(prefix=".nyq-ab-", suffix=".partial", dir=dest.parent)
    staged = Path(temp_name)
    try:
        with os.fdopen(fd, "w+b") as handle:
            wavfile.write(handle, SAMPLE_RATE, output)
            handle.flush()
            os.fsync(handle.fileno())
        wav_sha = _sha(staged.read_bytes())
        if _sha(Path(kit_path).read_bytes()) != verified["zip_sha256"]:
            raise RuntimeError("NYQ source kit changed before preview publication")
        _project_unchanged(project_path, verified["source_project_sha256"], cancelled)
        _check(cancelled)
        # No-overwrite even if a competing writer publishes after our check.
        original_stat = staged.stat()
        os.link(staged, dest)
        try:
            _check(cancelled)
            if _sha(Path(kit_path).read_bytes()) != verified["zip_sha256"]:
                raise RuntimeError("NYQ source kit changed during preview publication")
            _project_unchanged(project_path, verified["source_project_sha256"], cancelled)
            _check(cancelled)
        except BaseException:
            # Best-effort rollback only if the published inode/size/mtime still
            # identify OUR staged file; never delete another writer's output.
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
        "format": "nyq.alternating-ab-preview.v1", "absolute_path": str(dest),
        "wav_sha256": wav_sha, "pcm_f32le_sha256": pcm_sha,
        "kit_sha256": verified["zip_sha256"],
        "dry_wav_sha256": verified["tracks"][0]["wav_sha256"],
        "wet_wav_sha256": verified["tracks"][selected]["wav_sha256"],
        "virtual_rate_hz": virtual_rate_hz, "delivery_hz": SAMPLE_RATE,
        "frames": verified["frames"], "channels": verified["channels"],
        "period_frames": period, "crossfade_frames": fade,
        "period_ms": str(period_ms), "crossfade_ms": str(crossfade_ms),
        "trusted_kit_checked": verified["trusted_zip_sha_checked"],
        "source_project_checked": verified["original_project_checked"],
        "scope": "Preview-only time-aligned A/B, no gain matching, master export, or graph admission",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Create an alternating dry/NYQ A/B preview WAV from a production kit")
    parser.add_argument("--kit", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--virtual-hz", required=True, help="Exactly one rate present in the kit, e.g. 4/1")
    parser.add_argument("--period-ms", default="1000", help="Length of each dry/wet segment, 50..60000 ms")
    parser.add_argument("--crossfade-ms", default="12", help="Smooth switch time, 2..100 ms")
    parser.add_argument("--project", help="Optional original saved Compose project for binding")
    parser.add_argument("--expected-sha256", help="Externally trusted whole-kit SHA-256")
    args = parser.parse_args(argv)
    try:
        result = bounce_ab_preview(
            args.kit, args.output, virtual_rate_hz=args.virtual_hz,
            period_ms=args.period_ms, crossfade_ms=args.crossfade_ms,
            project_path=args.project, expected_zip_sha256=args.expected_sha256)
    except (Exception, KeyboardInterrupt) as exc:
        print("NYQ A/B preview failed: " + str(exc), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
