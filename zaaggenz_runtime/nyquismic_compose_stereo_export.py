"""One-command saved-Compose -> controlled-clock NYQ -> stereo 48-kHz WAV.

Opt-in post-Compose full-mix path. Not a graph/rack route, ordinary final
master export, per-channel controlled clock, or #252/#253 acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from zaaggenz_runtime import nyquismic_production_kit as kit
from zaaggenz_runtime import nyquismic_dual_rate_stereo as stereo
from zaaggenz_runtime import nyquismic_audition_sweep as sweep


def _check(cancelled):
    if cancelled is not None and cancelled():
        raise RuntimeError("NYQ one-step stereo export cancelled")


def _project_sha(path: Path, cancelled) -> str:
    _check(cancelled)
    if (not path.name.endswith(".zgtimeline.json") or not path.is_file()
            or path.stat().st_size > sweep.MAX_PROJECT_BYTES):
        raise ValueError("expected bounded saved Compose project")
    with path.open("rb") as handle:
        contents = handle.read(sweep.MAX_PROJECT_BYTES + 1)
    if len(contents) > sweep.MAX_PROJECT_BYTES:
        raise ValueError("saved Compose project exceeds size budget")
    _check(cancelled)
    return hashlib.sha256(contents).hexdigest()


def export_compose_stereo(
    project_path: str | Path, output_path: str | Path, *,
    left_rate_hz: str, right_rate_hz: str, wet_percent: str = "100",
    evaluation_rate_hz: int = 192000, wait_seconds: float = 120.,
    cancelled=None,
) -> dict:
    """Publish a single source-authenticated WAV, no exposed intermediate kit.

    A retained source snapshot is checked on both sides of final no-overwrite
    publication. The temporary kit/working WAV are removed even on failure.
    Publication is not an atomic transaction with an arbitrary external writer.
    """
    if cancelled is not None and not callable(cancelled):
        raise ValueError("cancelled must be callable")
    if not isinstance(left_rate_hz, str) or not isinstance(right_rate_hz, str):
        raise ValueError("virtual rates must be strings")
    rates = sweep._rates([left_rate_hz, right_rate_hz])
    if len(rates) != 2:
        raise ValueError("two distinct virtual rates required")
    # Allow user-friendly '4' input but pass only canonical rates downstream.
    left_rate, right_rate = rates
    # Fail malformed wet controls before launching expensive Compose/clock renders.
    # Reuse the bounce policy rather than maintaining a second interpretation.
    # The downstream bounce validates again at its own trust boundary.
    stereo._wet(wet_percent)
    dest = Path(output_path).absolute()
    if (dest.suffix.lower() != ".wav" or not dest.parent.is_dir()
            or dest.exists() or dest.is_symlink()):
        raise ValueError("output must be a new WAV in an existing directory")
    project = Path(project_path).absolute()
    original_sha = _project_sha(project, cancelled)
    _check(cancelled)

    with tempfile.TemporaryDirectory(prefix=".nyq-compose-stereo-", dir=dest.parent) as folder:
        staging = Path(folder)
        interim_kit = staging / "source-kit.zip"
        interim_wav = staging / "working.wav"
        rendered = kit.export_saved_compose_kit(
            project, interim_kit, virtual_rates_hz=list(rates),
            evaluation_rate_hz=evaluation_rate_hz, wait_seconds=wait_seconds,
            cancelled=cancelled)
        if (rendered["project_file_sha256"] != original_sha
                or rendered["virtual_rates_hz"] != list(rates)
                or rendered["delivery_hz"] != 48000):
            raise RuntimeError("saved Compose source/virtual-rate receipt changed")
        _check(cancelled)
        mixed = stereo.bounce_dual_rate_stereo(
            interim_kit, interim_wav, left_rate_hz=left_rate,
            right_rate_hz=right_rate, wet_percent=wet_percent,
            project_path=project, expected_zip_sha256=rendered["zip_sha256"],
            cancelled=cancelled)
        if (mixed["source_project_sha256"] != original_sha
                or mixed["kit_sha256"] != rendered["zip_sha256"]
                or mixed["left_rate_hz"] != left_rate
                or mixed["right_rate_hz"] != right_rate
                or mixed["delivery_hz"] != 48000
                or mixed["frames"] != rendered["frames"]
                or mixed["source_channels"] != rendered["channels"]
                or mixed["channels"] != 2):
            raise RuntimeError("NYQ stereo bounce disagrees with authenticated source")
        if hashlib.sha256(interim_wav.read_bytes()).hexdigest() != mixed["wav_sha256"]:
            raise RuntimeError("staged WAV differs from authenticated PCM receipt")
        if _project_sha(project, cancelled) != original_sha:
            raise RuntimeError("saved Compose project changed before publication")
        _check(cancelled)
        own = interim_wav.stat()
        os.link(interim_wav, dest)  # no overwrite, including concurrent writers
        try:
            _check(cancelled)
            if _project_sha(project, cancelled) != original_sha:
                raise RuntimeError("saved Compose project changed during publication")
            _check(cancelled)
        except BaseException:
            # Only revoke our own hardlink; never unlink a competing replacement.
            try:
                published = dest.stat(follow_symlinks=False)
                if (published.st_dev, published.st_ino, published.st_size,
                    published.st_mtime_ns) == (own.st_dev, own.st_ino, own.st_size,
                                               own.st_mtime_ns):
                    dest.unlink()
            except FileNotFoundError:
                pass
            raise
    return {
        "format": "nyq.compose-to-stereo-wav.v1", "absolute_path": str(dest),
        "source_project_sha256": original_sha,
        "kit_sha256": rendered["zip_sha256"],
        "wav_sha256": mixed["wav_sha256"],
        "pcm_f32le_sha256": mixed["pcm_f32le_sha256"],
        "left_rate_hz": left_rate, "right_rate_hz": right_rate,
        "wet_percent": mixed["wet_percent"], "frames": mixed["frames"],
        "delivery_hz": 48000, "channels": 2,
        "source_channels": mixed["source_channels"],
        "peak_abs": mixed["peak_abs"],
        "exceeds_unity_peak": mixed["exceeds_unity_peak"],
        "scope": "Opt-in saved Compose full-mix NYQ stereo; not graph/rack/final export",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Render one saved Compose project to a NYQ stereo WAV")
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", required=True, help="New 48-kHz float32 stereo WAV")
    parser.add_argument("--left-rate", required=True, help="Left-channel NYQ virtual Hz")
    parser.add_argument("--right-rate", required=True, help="Right-channel NYQ virtual Hz")
    parser.add_argument("--wet-percent", default="100")
    parser.add_argument("--evaluation-hz", type=int, choices=sweep.EVALUATION_RATES_HZ,
                        default=192000)
    args = parser.parse_args(argv)
    try:
        result = export_compose_stereo(
            args.project, args.output, left_rate_hz=args.left_rate,
            right_rate_hz=args.right_rate, wet_percent=args.wet_percent,
            evaluation_rate_hz=args.evaluation_hz)
    except (Exception, KeyboardInterrupt) as exc:
        print("NYQ saved-Compose stereo export failed: " + str(exc), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
