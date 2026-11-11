"""Opt-in stereo width from two authenticated post-Compose NYQ virtual-rate takes.

This is an offline 48-kHz full-mix production bounce, not a per-channel sampler
clock, registered graph route, application final export, or NYQ-003/004 admission.
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

RATE_HZ = 48000
MAX_PROJECT_BYTES = 2_000_000


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _check(cancelled) -> None:
    if cancelled is not None and cancelled():
        raise RuntimeError("NYQ dual-rate stereo bounce cancelled")


def _wet(raw: str) -> float:
    if not isinstance(raw, str):
        raise ValueError("wet percentage must be a decimal string")
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid wet percentage") from exc
    if not amount.is_finite() or not Decimal(0) <= amount <= Decimal(100):
        raise ValueError("wet percentage must be finite and in [0,100]")
    if amount.as_tuple().exponent < -3:
        raise ValueError("wet percentage supports at most three decimal places")
    return float(amount / Decimal(100))


def _read_pcm(raw: bytes, receipt: dict, frames: int, channels: int) -> np.ndarray:
    if _sha(raw) != receipt["wav_sha256"]:
        raise RuntimeError("NYQ source track WAV bytes changed")
    rate, pcm = wavfile.read(io.BytesIO(raw))
    actual_channels = 1 if pcm.ndim == 1 else (pcm.shape[1] if pcm.ndim == 2 else -1)
    if (rate != RATE_HZ or pcm.dtype != np.float32
            or len(pcm) != frames or actual_channels != channels
            or not np.isfinite(pcm).all()):
        raise ValueError("NYQ stereo bounce requires finite aligned 48-kHz float32 WAV")
    if _sha(np.asarray(pcm, dtype="<f4").tobytes(order="C")) != receipt["pcm_f32le_sha256"]:
        raise RuntimeError("NYQ source decoded PCM identity changed")
    return pcm


def _project_unchanged(path, original_sha: str, cancelled) -> None:
    if path is None:
        return
    _check(cancelled)
    project = Path(path)
    if (not project.name.endswith(".zgtimeline.json") or not project.is_file()
            or project.stat().st_size > MAX_PROJECT_BYTES
            or _sha(project.read_bytes()) != original_sha):
        raise RuntimeError("saved Compose project changed after source verification")
    _check(cancelled)


def bounce_dual_rate_stereo(
    kit_path: str | Path, output_path: str | Path, *,
    left_rate_hz: str, right_rate_hz: str, wet_percent: str = "100",
    project_path: str | Path | None = None,
    expected_zip_sha256: str | None = None, cancelled=None,
) -> dict:
    """Compose left and right from distinct verified NYQ takes, retaining dry at 0%.

    Mono source is explicitly widened to stereo. A stereo source retains its
    original left/right channel mapping; no channel swap or phase inversion.
    """
    if cancelled is not None and not callable(cancelled):
        raise ValueError("cancelled must be callable")
    amount = _wet(wet_percent)
    if (not isinstance(left_rate_hz, str) or not isinstance(right_rate_hz, str)
            or left_rate_hz == right_rate_hz):
        raise ValueError("two distinct canonical virtual rates are required")
    dest = Path(output_path)
    if dest.suffix.lower() != ".wav" or not dest.parent.is_dir() or dest.exists():
        raise ValueError("output must be a new WAV in an existing directory")
    if dest.is_symlink():
        raise ValueError("output may not be an existing symlink")
    _check(cancelled)
    verified = verify_production_kit(
        kit_path, expected_zip_sha256=expected_zip_sha256,
        project_path=project_path, cancelled=cancelled)
    rates = verified["virtual_rates_hz"]
    if left_rate_hz not in rates or right_rate_hz not in rates:
        raise ValueError("requested rate is not in the authenticated NYQ kit")
    left_index = rates.index(left_rate_hz) + 1
    right_index = rates.index(right_rate_hz) + 1
    kit = Path(kit_path)
    snapshot = kit.read_bytes()
    if _sha(snapshot) != verified["zip_sha256"]:
        raise RuntimeError("NYQ source kit changed after verification")
    with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
        dry_raw = archive.read("original.wav")
        left_raw = archive.read(f"nyq-rate-{left_index:02d}.wav")
        right_raw = archive.read(f"nyq-rate-{right_index:02d}.wav")
    frames, channels = verified["frames"], verified["channels"]
    dry = _read_pcm(dry_raw, verified["tracks"][0], frames, channels)
    left = _read_pcm(left_raw, verified["tracks"][left_index], frames, channels)
    right = _read_pcm(right_raw, verified["tracks"][right_index], frames, channels)
    _check(cancelled)

    # Full-mix source is mono or stereo; a mono source is explicitly expanded
    # to two channels. Only each rate's corresponding original channel is used.
    source_l = dry if channels == 1 else dry[:, 0]
    source_r = dry if channels == 1 else dry[:, 1]
    treatment_l = left if channels == 1 else left[:, 0]
    treatment_r = right if channels == 1 else right[:, 1]
    mix = np.empty((frames, 2), dtype=np.float32)
    for i, (source, treatment) in enumerate(
            ((source_l, treatment_l), (source_r, treatment_r))):
        _check(cancelled)
        if amount == 0.0:
            mix[:, i] = source
        elif amount == 1.0:
            mix[:, i] = treatment
        else:
            value = (source.astype(np.float64)
                     + (treatment.astype(np.float64) - source.astype(np.float64)) * amount)
            mix[:, i] = np.where(source == treatment, source, value.astype(np.float32))
    if not np.isfinite(mix).all():
        raise RuntimeError("NYQ two-rate stereo mix has nonfinite PCM")
    peak = float(np.max(np.abs(mix.astype(np.float64))))
    pcm_sha = _sha(np.asarray(mix, dtype="<f4").tobytes(order="C"))
    _project_unchanged(project_path, verified["source_project_sha256"], cancelled)
    _check(cancelled)

    fd, partial = tempfile.mkstemp(prefix=".nyq-dual-stereo-", suffix=".partial", dir=dest.parent)
    staged = Path(partial)
    try:
        with os.fdopen(fd, "w+b") as handle:
            wavfile.write(handle, RATE_HZ, mix)
            handle.flush()
            os.fsync(handle.fileno())
        wav_sha = _sha(staged.read_bytes())
        if _sha(kit.read_bytes()) != verified["zip_sha256"]:
            raise RuntimeError("NYQ source kit changed before stereo publication")
        _project_unchanged(project_path, verified["source_project_sha256"], cancelled)
        _check(cancelled)
        own = staged.stat()
        os.link(staged, dest)  # create-if-absent, including against concurrent writers
        try:
            _check(cancelled)
            if _sha(kit.read_bytes()) != verified["zip_sha256"]:
                raise RuntimeError("NYQ source kit changed during stereo publication")
            _project_unchanged(project_path, verified["source_project_sha256"], cancelled)
            _check(cancelled)
        except BaseException:
            try:
                published = dest.stat(follow_symlinks=False)
                if (published.st_dev, published.st_ino, published.st_size,
                    published.st_mtime_ns) == (own.st_dev, own.st_ino, own.st_size,
                                               own.st_mtime_ns):
                    dest.unlink()
            except FileNotFoundError:
                pass
            raise
    finally:
        staged.unlink(missing_ok=True)

    return {
        "format": "nyq.dual-rate-stereo-width.v1",
        "absolute_path": str(dest), "delivery_hz": RATE_HZ,
        "frames": frames, "channels": 2, "source_channels": channels,
        "left_rate_hz": left_rate_hz, "right_rate_hz": right_rate_hz,
        "wet_percent": wet_percent, "kit_sha256": verified["zip_sha256"],
        "source_project_sha256": verified["source_project_sha256"],
        "dry_wav_sha256": verified["tracks"][0]["wav_sha256"],
        "left_wav_sha256": verified["tracks"][left_index]["wav_sha256"],
        "right_wav_sha256": verified["tracks"][right_index]["wav_sha256"],
        "wav_sha256": wav_sha, "pcm_f32le_sha256": pcm_sha,
        "peak_abs": peak, "exceeds_unity_peak": peak > 1,
        "trusted_kit_checked": verified["trusted_zip_sha_checked"],
        "source_project_checked": verified["original_project_checked"],
        "scope": "Opt-in post-Compose full-mix two-rate stereo bounce; not per-channel sampler clocks, graph or final export",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Widen a verified saved-Compose NYQ kit with distinct left/right virtual-rate takes")
    parser.add_argument("--kit", required=True)
    parser.add_argument("--output", required=True, help="New float32 48-kHz stereo WAV; never overwritten")
    parser.add_argument("--left-rate", required=True, help="Exact canonical NYQ rate for left")
    parser.add_argument("--right-rate", required=True, help="Exact canonical NYQ rate for right")
    parser.add_argument("--wet-percent", default="100", help="0 to 100 inclusive (default 100)")
    parser.add_argument("--project", help="Optional original saved Compose project for provenance anchoring")
    parser.add_argument("--expected-sha256", help="Externally trusted kit ZIP SHA-256")
    args = parser.parse_args(argv)
    try:
        receipt = bounce_dual_rate_stereo(
            args.kit, args.output, left_rate_hz=args.left_rate,
            right_rate_hz=args.right_rate, wet_percent=args.wet_percent,
            project_path=args.project, expected_zip_sha256=args.expected_sha256)
    except (Exception, KeyboardInterrupt) as exc:
        print("NYQ dual-rate stereo bounce failed: " + str(exc), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
