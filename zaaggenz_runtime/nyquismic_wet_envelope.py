"""Opt-in keyframed Nyquismic wet-envelope WAV from a verified saved-Compose kit.

This automates the full-mix dry/wet *mix*, not the virtual sampling clock.
The project, source tracks, rack, graph and default Compose export remain unchanged.
No gain matching, limiting, normalization, resampling or implicit clipping.
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
CHUNK_FRAMES = 65536
MAX_PROJECT = 2_000_000


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _check(cancelled) -> None:
    if cancelled is not None and cancelled():
        raise RuntimeError("NYQ wet-envelope bounce cancelled")


def _decimal(raw: str, label: str, low: int, high: int, places: int) -> Decimal:
    if type(raw) is not str:
        raise ValueError(f"{label} must be a decimal string")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"{label} must be a finite decimal") from None
    if (not value.is_finite() or not low <= value <= high
            or value.as_tuple().exponent < -places):
        raise ValueError(f"{label} must be {low}..{high} with at most {places} decimal places")
    return value


def _keyframes(points: list[str] | tuple[str, ...]) -> list[dict]:
    if not isinstance(points, (list, tuple)) or not 2 <= len(points) <= 64:
        raise ValueError("supply 2..64 explicit --point-ms TIME=WET_PERCENT keyframes")
    parsed: list[dict] = []
    for item in points:
        if type(item) is not str or item.count("=") != 1:
            raise ValueError("keyframe must use TIME_MS=WET_PERCENT")
        time_text, wet_text = item.split("=")
        time_ms = _decimal(time_text, "time milliseconds", 0, 1000000, 3)
        percent = _decimal(wet_text, "wet percent", 0, 100, 6)
        frame = int((time_ms * 48).to_integral_value(rounding=ROUND_HALF_UP))
        if parsed and frame <= parsed[-1]["frame"]:
            raise ValueError("keyframe times must resolve to strictly increasing 48-kHz frames")
        parsed.append({"frame": frame, "time_ms": str(time_ms),
                       "wet_percent": str(percent), "_percent": float(percent)})
    if parsed[0]["frame"] != 0:
        raise ValueError("first wet-envelope keyframe must begin at time 0 ms")
    return parsed


def _project_unchanged(project_path, expected_sha, cancelled) -> None:
    if project_path is None:
        return
    _check(cancelled)
    project = Path(project_path)
    if not project.is_file() or project.stat().st_size > MAX_PROJECT:
        raise RuntimeError("saved Compose project missing or enlarged during envelope bounce")
    if _sha(project.read_bytes()) != expected_sha:
        raise RuntimeError("saved Compose project changed during envelope bounce")


def _pcm(raw: bytes, expected: dict, frames: int, channels: int) -> np.ndarray:
    if _sha(raw) != expected["wav_sha256"]:
        raise RuntimeError("NYQ envelope source WAV differs from verified kit")
    hz, samples = wavfile.read(io.BytesIO(raw))
    n_channels = 1 if samples.ndim == 1 else samples.shape[1] if samples.ndim == 2 else -1
    if (hz != SAMPLE_RATE or samples.dtype != np.float32
            or samples.shape[0] != frames or n_channels != channels
            or not np.isfinite(samples).all()):
        raise RuntimeError("NYQ envelope requires aligned finite 48-kHz float32 PCM")
    return samples


def bounce_wet_envelope(
    kit_path: str | Path, output_wav: str | Path, *, virtual_rate_hz: str,
    points_ms: list[str] | tuple[str, ...],
    project_path: str | Path | None = None,
    expected_zip_sha256: str | None = None, cancelled=None,
) -> dict:
    """Render a frame-accurate linear wet envelope; never replace a destination.

    Keyframes give milliseconds (rounded half-up to 48-kHz frames) and wet percent.
    Between points, linear-amplitude interpolation is applied at every output frame;
    after the final point the final setting is held. This is offline *mix automation*.
    Internal kit hashes establish consistency, not independently trusted origin.
    Publication/source coherence under uncooperative filesystem mutation is only
    best-effort; post-link validation can revoke our own published inode.
    """
    if cancelled is not None and not callable(cancelled):
        raise ValueError("cancelled must be callable")
    keys = _keyframes(points_ms)
    dest = Path(output_wav).absolute()
    if dest.suffix.lower() != ".wav" or not dest.parent.is_dir():
        raise ValueError("output must be a new .wav in an existing directory")
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(str(dest))
    verified = verify_production_kit(
        kit_path, project_path=project_path,
        expected_zip_sha256=expected_zip_sha256, cancelled=cancelled)
    if keys[-1]["frame"] >= verified["frames"]:
        raise ValueError("wet-envelope keyframes must fall within the source WAV extent")
    rates = verified["virtual_rates_hz"]
    if type(virtual_rate_hz) is not str or virtual_rate_hz not in rates:
        raise ValueError("virtual rate must exactly match a verified kit take")
    selected = rates.index(virtual_rate_hz) + 1
    _check(cancelled)
    snapshot = Path(kit_path).read_bytes()
    if _sha(snapshot) != verified["zip_sha256"]:
        raise RuntimeError("NYQ production kit changed after verification")
    with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
        dry_bytes = archive.read("original.wav")
        wet_bytes = archive.read(f"nyq-rate-{selected:02d}.wav")
    dry = _pcm(dry_bytes, verified["tracks"][0], verified["frames"], verified["channels"])
    wet = _pcm(wet_bytes, verified["tracks"][selected], verified["frames"], verified["channels"])
    _check(cancelled)
    times = np.array([k["frame"] for k in keys], dtype=np.float64)
    amounts = np.array([k["_percent"] / 100.0 for k in keys], dtype=np.float64)
    output = np.empty_like(dry)
    for start in range(0, verified["frames"], CHUNK_FRAMES):
        _check(cancelled)
        stop = min(start + CHUNK_FRAMES, verified["frames"])
        weights = np.clip(np.interp(
            np.arange(start, stop, dtype=np.float64), times, amounts), 0.0, 1.0)
        if dry.ndim == 2:
            weights = weights[:, None]
        a, b = dry[start:stop], wet[start:stop]
        portion = (a.astype(np.float64)
                   + (b.astype(np.float64) - a.astype(np.float64)) * weights).astype(np.float32)
        # Preserve exact source PCM at both endpoints and whenever the two
        # sources agree, including float32 signed zeros.
        portion = np.where(weights == 0.0, a, portion)
        portion = np.where(weights == 1.0, b, portion)
        portion = np.where(a == b, a, portion)
        output[start:stop] = portion
    if not np.isfinite(output).all():
        raise RuntimeError("NYQ wet-envelope mix contains nonfinite PCM")
    pcm_sha = _sha(np.asarray(output, dtype="<f4").tobytes(order="C"))
    peak = float(np.max(np.abs(output.astype(np.float64))))
    _project_unchanged(project_path, verified["source_project_sha256"], cancelled)
    _check(cancelled)
    fd, temp_name = tempfile.mkstemp(prefix=".nyq-wet-env-", suffix=".partial", dir=dest.parent)
    staged = Path(temp_name)
    try:
        with os.fdopen(fd, "w+b") as handle:
            wavfile.write(handle, SAMPLE_RATE, output)
            handle.flush()
            os.fsync(handle.fileno())
        wav_sha = _sha(staged.read_bytes())
        if _sha(Path(kit_path).read_bytes()) != verified["zip_sha256"]:
            raise RuntimeError("NYQ source kit changed before envelope publication")
        _project_unchanged(project_path, verified["source_project_sha256"], cancelled)
        _check(cancelled)
        own_stat = staged.stat()
        os.link(staged, dest)  # create-if-absent; never clobber a competing output
        try:
            _check(cancelled)
            if _sha(Path(kit_path).read_bytes()) != verified["zip_sha256"]:
                raise RuntimeError("NYQ source kit changed during envelope publication")
            _project_unchanged(project_path, verified["source_project_sha256"], cancelled)
            _check(cancelled)
        except BaseException:
            try:
                published = dest.stat(follow_symlinks=False)
                if (published.st_dev, published.st_ino, published.st_size, published.st_mtime_ns) == (
                        own_stat.st_dev, own_stat.st_ino, own_stat.st_size, own_stat.st_mtime_ns):
                    dest.unlink()
            except FileNotFoundError:
                pass
            raise
    finally:
        staged.unlink(missing_ok=True)
    public_keys = [{k: v for k, v in key.items() if not k.startswith("_")} for key in keys]
    return {
        "format": "nyq.verified-wet-envelope.v1",
        "absolute_path": str(dest), "wav_sha256": wav_sha,
        "pcm_f32le_sha256": pcm_sha, "kit_sha256": verified["zip_sha256"],
        "dry_wav_sha256": verified["tracks"][0]["wav_sha256"],
        "wet_wav_sha256": verified["tracks"][selected]["wav_sha256"],
        "virtual_rate_hz": virtual_rate_hz, "keyframes": public_keys,
        "interpolation": "linear_amplitude_at_each_48khz_frame_hold_after_last",
        "delivery_hz": SAMPLE_RATE, "frames": verified["frames"],
        "channels": verified["channels"], "peak_abs": peak,
        "exceeds_unity_peak": peak > 1.0,
        "trusted_kit_checked": verified["trusted_zip_sha_checked"],
        "source_project_checked": verified["original_project_checked"],
        "scope": "Opt-in post-Compose full-mix mix automation; no graph/clock or final-export admission",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Make a keyframed dry/wet Nyquismic mix from a verified kit")
    parser.add_argument("--kit", required=True)
    parser.add_argument("--output", required=True, help="New 48-kHz float32 WAV, never overwritten")
    parser.add_argument("--virtual-hz", required=True, help="Exact verified kit virtual rate")
    parser.add_argument("--point-ms", required=True, action="append", dest="points",
                        help="TIME_MS=WET_PERCENT, repeat 2..64 times; first time must be 0")
    parser.add_argument("--project", help="Optional original saved Compose project")
    parser.add_argument("--expected-sha256", help="Externally trusted complete kit ZIP SHA-256")
    args = parser.parse_args(argv)
    try:
        result = bounce_wet_envelope(
            args.kit, args.output, virtual_rate_hz=args.virtual_hz, points_ms=args.points,
            project_path=args.project, expected_zip_sha256=args.expected_sha256)
    except (Exception, KeyboardInterrupt) as exc:
        print("NYQ wet-envelope bounce failed: " + str(exc), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
