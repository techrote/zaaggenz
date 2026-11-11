"""Opt-in spatially selective Nyquismic mix from authenticated 48-kHz Compose WAVs.

The fixed-rate, aligned source pair is already rendered by the NYQ production kit.
This applies wet audio to stereo mid, side, left, right, or both channels;
it does not rerender or modulate the virtual clock, graph, or default output.
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

RATE = 48000
CHUNK = 65536
MAX_PROJECT = 2_000_000
MODES = ("both", "mid", "side", "left", "right")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check(cancelled) -> None:
    if cancelled is not None and cancelled():
        raise RuntimeError("NYQ stereo-wet bounce cancelled")


def _percent(value: str) -> float:
    if type(value) is not str:
        raise ValueError("wet percent must be a decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError("wet percent must be a finite decimal") from None
    if not number.is_finite() or not 0 <= number <= 100 or number.as_tuple().exponent < -6:
        raise ValueError("wet percent must be finite 0..100 with at most six decimal places")
    return float(number / 100)


def _project(path, expected, cancelled) -> None:
    if path is None:
        return
    _check(cancelled)
    project = Path(path)
    if not project.is_file() or project.stat().st_size > MAX_PROJECT or _sha(project.read_bytes()) != expected:
        raise RuntimeError("saved Compose project changed during stereo-wet bounce")


def _load(raw: bytes, entry: dict, frames: int, channels: int) -> np.ndarray:
    if _sha(raw) != entry["wav_sha256"]:
        raise RuntimeError("NYQ stereo-wet WAV differs from verified kit")
    hz, samples = wavfile.read(io.BytesIO(raw))
    count = 1 if samples.ndim == 1 else samples.shape[1] if samples.ndim == 2 else -1
    if (hz != RATE or samples.dtype != np.float32 or len(samples) != frames
            or count != channels or not np.isfinite(samples).all()
            or _sha(np.asarray(samples, dtype="<f4").tobytes(order="C")) != entry["pcm_f32le_sha256"]):
        raise RuntimeError("NYQ stereo-wet requires authenticated aligned finite 48-kHz float32 PCM")
    return samples


def _mix(dry: np.ndarray, wet: np.ndarray, amount: float, mode: str, cancelled) -> np.ndarray:
    """Apply a projected wet-minus-dry delta, keeping dry identity at zero wet.

    Mid projection is (deltaL+deltaR)/2 on *both* channels. Side projection
    is (deltaL-deltaR)/2 on L and its negative on R. This preserves the
    untargeted M or S component in real arithmetic, subject to f32 rounding.
    """
    if amount == 0:
        return dry.copy()
    if amount == 1 and mode == "both":
        return wet.copy()
    if np.array_equal(dry, wet) and mode not in ("left", "right"):
        return dry.copy()
    result = np.empty_like(dry)
    for start in range(0, len(dry), CHUNK):
        _check(cancelled)
        stop = min(start + CHUNK, len(dry))
        a, b = dry[start:stop], wet[start:stop]
        delta = b.astype(np.float64) - a.astype(np.float64)
        if mode == "mid":
            projected = np.mean(delta, axis=1)[:, None]
        elif mode == "side":
            side = (delta[:, 0] - delta[:, 1]) * .5
            projected = np.column_stack((side, -side))
        elif mode == "left":
            projected = delta.copy()
            projected[:, 1] = 0
        elif mode == "right":
            projected = delta.copy()
            projected[:, 0] = 0
        else:
            projected = delta
        portion = (a.astype(np.float64) + projected * amount).astype(np.float32)
        if mode == "both":
            portion = np.where(a == b, a, portion)
        elif mode == "left":
            portion[:, 1] = a[:, 1]
            if amount == 1:
                portion[:, 0] = b[:, 0]
        elif mode == "right":
            portion[:, 0] = a[:, 0]
            if amount == 1:
                portion[:, 1] = b[:, 1]
        result[start:stop] = portion
    if not np.isfinite(result).all():
        raise RuntimeError("NYQ stereo-wet produced nonfinite PCM")
    return result


def bounce_stereo_wet(
    kit_path: str | Path, output_wav: str | Path, *, virtual_rate_hz: str,
    wet_percent: str, mode: str = "both", project_path: str | Path | None = None,
    expected_zip_sha256: str | None = None, cancelled=None,
) -> dict:
    """Render a separately published opt-in spatial Nyquismic 48-kHz WAV.

    `--project` and `--expected-sha256` are optional external provenance anchors.
    Internal hashes alone only prove consistency. Arbitrary concurrent source/
    destination writers are outside the bounded post-link rollback guarantee.
    """
    if cancelled is not None and not callable(cancelled):
        raise ValueError("cancelled must be callable")
    if type(mode) is not str or mode not in MODES:
        raise ValueError("mode must be both, mid, side, left or right")
    amount = _percent(wet_percent)
    dest = Path(output_wav).absolute()
    if dest.suffix.lower() != ".wav" or not dest.parent.is_dir():
        raise ValueError("output must be a new WAV in an existing directory")
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(str(dest))
    verified = verify_production_kit(kit_path, project_path=project_path,
                                     expected_zip_sha256=expected_zip_sha256, cancelled=cancelled)
    if verified["channels"] != 2 and mode != "both":
        raise ValueError("spatial selection requires stereo PCM; mono supports only both")
    rates = verified["virtual_rates_hz"]
    if type(virtual_rate_hz) is not str or virtual_rate_hz not in rates:
        raise ValueError("virtual rate must exactly match a verified kit take")
    selected = rates.index(virtual_rate_hz) + 1
    _check(cancelled)
    snapshot = Path(kit_path).read_bytes()
    if _sha(snapshot) != verified["zip_sha256"]:
        raise RuntimeError("NYQ source kit changed after verification")
    with zipfile.ZipFile(io.BytesIO(snapshot)) as archive:
        a = archive.read("original.wav")
        b = archive.read(f"nyq-rate-{selected:02d}.wav")
    dry = _load(a, verified["tracks"][0], verified["frames"], verified["channels"])
    wet = _load(b, verified["tracks"][selected], verified["frames"], verified["channels"])
    _check(cancelled)
    output = _mix(dry, wet, amount, mode, cancelled)
    peak = float(np.max(np.abs(output.astype(np.float64))))
    pcm_sha = _sha(np.asarray(output, dtype="<f4").tobytes(order="C"))
    _project(project_path, verified["source_project_sha256"], cancelled)
    _check(cancelled)
    fd, name = tempfile.mkstemp(prefix=".nyq-stereo-wet-", suffix=".partial", dir=dest.parent)
    stage = Path(name)
    try:
        with os.fdopen(fd, "w+b") as handle:
            wavfile.write(handle, RATE, output)
            handle.flush()
            os.fsync(handle.fileno())
        wav_sha = _sha(stage.read_bytes())
        if _sha(Path(kit_path).read_bytes()) != verified["zip_sha256"]:
            raise RuntimeError("NYQ source kit changed before stereo-wet publication")
        _project(project_path, verified["source_project_sha256"], cancelled)
        _check(cancelled)
        own = stage.stat()
        os.link(stage, dest)
        try:
            _check(cancelled)
            if _sha(Path(kit_path).read_bytes()) != verified["zip_sha256"]:
                raise RuntimeError("NYQ source kit changed during stereo-wet publication")
            _project(project_path, verified["source_project_sha256"], cancelled)
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
        stage.unlink(missing_ok=True)
    return {
        "format": "nyq.spatial-selective-wet.v1", "absolute_path": str(dest),
        "wav_sha256": wav_sha, "pcm_f32le_sha256": pcm_sha,
        "kit_sha256": verified["zip_sha256"],
        "dry_wav_sha256": verified["tracks"][0]["wav_sha256"],
        "wet_wav_sha256": verified["tracks"][selected]["wav_sha256"],
        "virtual_rate_hz": virtual_rate_hz, "mode": mode, "wet_percent": wet_percent,
        "frames": verified["frames"], "channels": verified["channels"],
        "delivery_hz": RATE, "peak_abs": peak, "exceeds_unity_peak": peak > 1,
        "trusted_kit_checked": verified["trusted_zip_sha_checked"],
        "source_project_checked": verified["original_project_checked"],
        "scope": "Opt-in full-mix stereo projection, not native NYQ graph, rack or master export",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Spatially selective wet NYQ 48-kHz WAV")
    parser.add_argument("--kit", required=True)
    parser.add_argument("--output", required=True, help="New WAV, never overwritten")
    parser.add_argument("--virtual-hz", required=True, help="Exact virtual-rate take in verified kit")
    parser.add_argument("--wet-percent", required=True, help="0..100, up to six decimal places")
    parser.add_argument("--mode", choices=MODES, default="both")
    parser.add_argument("--project", help="Optional original saved Compose project")
    parser.add_argument("--expected-sha256", help="Externally recorded trusted kit SHA-256")
    args = parser.parse_args(argv)
    try:
        result = bounce_stereo_wet(args.kit, args.output, virtual_rate_hz=args.virtual_hz,
                                   wet_percent=args.wet_percent, mode=args.mode,
                                   project_path=args.project, expected_zip_sha256=args.expected_sha256)
    except (Exception, KeyboardInterrupt) as exc:
        print("NYQ stereo-wet bounce failed: " + str(exc), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
