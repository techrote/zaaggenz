"""Opt-in, source-verified two-rate Nyquismic timbre morph.

Morphs BETWEEN two already rendered virtual-rate 48-kHz full-mix WAVs.
It does not modulate a sampler clock, add a graph node, or replace the
ordinary Compose master. This never alters the saved project or default audio.
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

RATE_HZ = 48000
CHUNK_FRAMES = 65536
MAX_PROJECT_BYTES = 2_000_000
CURVES = ("linear", "equal-power")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _check(cancelled) -> None:
    if cancelled is not None and cancelled():
        raise RuntimeError("NYQ two-rate morph cancelled")


def _decimal(text: str, label: str, low: int, high: int, places: int) -> Decimal:
    if type(text) is not str:
        raise ValueError(f"{label} must be a decimal string")
    try:
        n = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"{label} must be finite decimal") from None
    if not n.is_finite() or not low <= n <= high or n.as_tuple().exponent < -places:
        raise ValueError(f"{label} must be {low}..{high}, at most {places} decimal places")
    return n


def _points(raw: list[str] | tuple[str, ...]) -> list[dict]:
    if not isinstance(raw, (list, tuple)) or not 2 <= len(raw) <= 64:
        raise ValueError("provide 2..64 --point-ms TIME=RATE_B_PERCENT keyframes")
    result = []
    for item in raw:
        if type(item) is not str or item.count("=") != 1:
            raise ValueError("keyframe must be TIME_MS=RATE_B_PERCENT")
        time_text, percent_text = item.split("=")
        millis = _decimal(time_text, "keyframe ms", 0, 1000000, 3)
        percent = _decimal(percent_text, "rate B percent", 0, 100, 6)
        frame = int((millis * 48).to_integral_value(rounding=ROUND_HALF_UP))
        if result and frame <= result[-1]["frame"]:
            raise ValueError("keyframes must resolve to strictly increasing frames")
        result.append({"frame": frame, "time_ms": str(millis),
                       "rate_b_percent": str(percent), "_weight": float(percent) / 100})
    if result[0]["frame"] != 0:
        raise ValueError("first morph keyframe must be at 0 ms")
    return result


def _project_unchanged(path, expected_sha, cancelled) -> None:
    if path is None:
        return
    _check(cancelled)
    project = Path(path)
    if (not project.is_file() or project.stat().st_size > MAX_PROJECT_BYTES
            or _sha(project.read_bytes()) != expected_sha):
        raise RuntimeError("saved Compose project changed during two-rate morph")


def _read_wav(raw: bytes, entry: dict, frames: int, channels: int) -> np.ndarray:
    if _sha(raw) != entry["wav_sha256"]:
        raise RuntimeError("source WAV differs from verified NYQ kit")
    hz, pcm = wavfile.read(io.BytesIO(raw))
    count = 1 if pcm.ndim == 1 else pcm.shape[1] if pcm.ndim == 2 else -1
    if (hz != RATE_HZ or pcm.dtype != np.float32 or len(pcm) != frames
            or count != channels or not np.isfinite(pcm).all()
            or _sha(np.asarray(pcm, dtype="<f4").tobytes(order="C"))
               != entry["pcm_f32le_sha256"]):
        raise RuntimeError("two-rate morph requires source-matched finite 48-kHz float32 PCM")
    return pcm


def _mix(a: np.ndarray, b: np.ndarray, keyframes: list[dict],
         curve: str, cancelled) -> np.ndarray:
    times = np.asarray([x["frame"] for x in keyframes], dtype=np.float64)
    values = np.asarray([x["_weight"] for x in keyframes], dtype=np.float64)
    out = np.empty_like(a)
    for begin in range(0, len(a), CHUNK_FRAMES):
        _check(cancelled)
        stop = min(begin + CHUNK_FRAMES, len(a))
        weight = np.interp(np.arange(begin, stop, dtype=np.float64), times, values)
        x, y = a[begin:stop], b[begin:stop]
        xa, yb = x.astype(np.float64), y.astype(np.float64)
        if curve == "linear":
            weight_view = weight[:, None] if a.ndim == 2 else weight
            segment = (xa + (yb - xa) * weight_view).astype(np.float32)
            # Signed-zero and unchanged-sample identity are meaningful receipts.
            segment = np.where(x == y, x, segment)
        else:
            theta = weight * (np.pi / 2)
            ga, gb = np.cos(theta), np.sin(theta)
            if a.ndim == 2:
                ga, gb = ga[:, None], gb[:, None]
            segment = (xa * ga + yb * gb).astype(np.float32)
            # Equal-power on correlated takes may increase level, deliberately.
        w0 = (weight == 0)[:, None] if a.ndim == 2 else (weight == 0)
        w1 = (weight == 1)[:, None] if a.ndim == 2 else (weight == 1)
        segment = np.where(w0, x, segment)
        segment = np.where(w1, y, segment)
        out[begin:stop] = segment
    if not np.isfinite(out).all():
        raise RuntimeError("two-rate morph produced nonfinite PCM")
    return out


def bounce_rate_morph(
    kit_path: str | Path, output_wav: str | Path, *,
    rate_a_hz: str, rate_b_hz: str,
    points_ms: list[str] | tuple[str, ...],
    curve: str = "linear",
    project_path: str | Path | None = None,
    expected_zip_sha256: str | None = None, cancelled=None,
) -> dict:
    """Make a new 48-kHz full-mix WAV; never replace a preexisting destination.

    Sources are cold-reopened and checked against the complete kit receipts.
    An external trusted kit SHA or original project optionally binds origin.
    Source/project identity is sampled before and immediately after no-overwrite
    hardlink publication; arbitrary concurrent writers are not transactional.
    """
    if cancelled is not None and not callable(cancelled):
        raise ValueError("cancelled must be callable")
    if type(curve) is not str or curve not in CURVES:
        raise ValueError("curve must be linear or equal-power")
    keys = _points(points_ms)
    dest = Path(output_wav).absolute()
    if dest.suffix.lower() != ".wav" or not dest.parent.is_dir():
        raise ValueError("output must be a new .wav file in an existing directory")
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(str(dest))
    verified = verify_production_kit(
        kit_path, project_path=project_path,
        expected_zip_sha256=expected_zip_sha256, cancelled=cancelled)
    if keys[-1]["frame"] >= verified["frames"]:
        raise ValueError("keyframes must fall strictly inside source WAV extent")
    rates = verified["virtual_rates_hz"]
    if (type(rate_a_hz) is not str or type(rate_b_hz) is not str
            or rate_a_hz == rate_b_hz or rate_a_hz not in rates or rate_b_hz not in rates):
        raise ValueError("select two distinct exact canonical rates from the verified kit")
    idx_a, idx_b = rates.index(rate_a_hz) + 1, rates.index(rate_b_hz) + 1
    _check(cancelled)
    kit = Path(kit_path)
    snapshot = kit.read_bytes()
    if _sha(snapshot) != verified["zip_sha256"]:
        raise RuntimeError("NYQ production kit changed after verification")
    with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
        raw_a = archive.read(f"nyq-rate-{idx_a:02d}.wav")
        raw_b = archive.read(f"nyq-rate-{idx_b:02d}.wav")
    a = _read_wav(raw_a, verified["tracks"][idx_a], verified["frames"], verified["channels"])
    b = _read_wav(raw_b, verified["tracks"][idx_b], verified["frames"], verified["channels"])
    _check(cancelled)
    output = _mix(a, b, keys, curve, cancelled)
    peak = float(np.max(np.abs(output.astype(np.float64))))
    pcm_sha = _sha(np.asarray(output, dtype="<f4").tobytes(order="C"))
    _project_unchanged(project_path, verified["source_project_sha256"], cancelled)
    _check(cancelled)

    fd, temp_path = tempfile.mkstemp(prefix=".nyq-rate-morph-", suffix=".partial",
                                     dir=dest.parent)
    staged = Path(temp_path)
    try:
        with os.fdopen(fd, "w+b") as handle:
            wavfile.write(handle, RATE_HZ, output)
            handle.flush()
            os.fsync(handle.fileno())
        wav_sha = _sha(staged.read_bytes())
        if _sha(kit.read_bytes()) != verified["zip_sha256"]:
            raise RuntimeError("NYQ production kit changed before morph publication")
        _project_unchanged(project_path, verified["source_project_sha256"], cancelled)
        _check(cancelled)
        own = staged.stat()
        os.link(staged, dest)
        try:
            _check(cancelled)
            if _sha(kit.read_bytes()) != verified["zip_sha256"]:
                raise RuntimeError("NYQ production kit changed during morph publication")
            _project_unchanged(project_path, verified["source_project_sha256"], cancelled)
            _check(cancelled)
        except BaseException:
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

    public_keys = [{k: v for k, v in p.items() if not k.startswith("_")} for p in keys]
    return {
        "format": "nyq.two-rate-morph.v1", "absolute_path": str(dest),
        "wav_sha256": wav_sha, "pcm_f32le_sha256": pcm_sha,
        "kit_sha256": verified["zip_sha256"],
        "rate_a_hz": rate_a_hz, "rate_b_hz": rate_b_hz,
        "rate_a_wav_sha256": verified["tracks"][idx_a]["wav_sha256"],
        "rate_b_wav_sha256": verified["tracks"][idx_b]["wav_sha256"],
        "keyframes": public_keys, "curve": curve,
        "interpolation": "48khz_frame_linear_keyframes_hold_last",
        "delivery_hz": RATE_HZ, "frames": verified["frames"],
        "channels": verified["channels"], "peak_abs": peak,
        "exceeds_unity_peak": peak > 1,
        "trusted_kit_checked": verified["trusted_zip_sha_checked"],
        "source_project_checked": verified["original_project_checked"],
        "scope": "Opt-in post-Compose two-render timbre blend; no native clock modulation, graph or final-export admission",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Morph two verified NYQ 48-kHz takes on one physical timeline")
    parser.add_argument("--kit", required=True)
    parser.add_argument("--output", required=True, help="New WAV; never overwritten")
    parser.add_argument("--rate-a", required=True, help="First exact verified virtual rate")
    parser.add_argument("--rate-b", required=True, help="Second distinct exact verified virtual rate")
    parser.add_argument("--point-ms", required=True, action="append", dest="points",
                        help="TIME_MS=RATE_B_PERCENT, 2..64, beginning at 0 ms")
    parser.add_argument("--curve", choices=CURVES, default="linear")
    parser.add_argument("--project", help="Optional original saved Compose project")
    parser.add_argument("--expected-sha256", help="Externally trusted entire kit ZIP hash")
    args = parser.parse_args(argv)
    try:
        receipt = bounce_rate_morph(
            args.kit, args.output, rate_a_hz=args.rate_a, rate_b_hz=args.rate_b,
            points_ms=args.points, curve=args.curve,
            project_path=args.project, expected_zip_sha256=args.expected_sha256)
    except (Exception, KeyboardInterrupt) as exc:
        print("NYQ two-rate morph failed: " + str(exc), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
