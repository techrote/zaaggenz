"""One-shot saved-Compose NYQ listening + DAW WAV kit.

Opt-in post-Compose full-mix artifact. Uses accepted-source adapters; does not
register a graph node, change rack defaults or qualify application final export.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

from zaaggenz_runtime import nyquismic_audition_sweep as sweep
from zaaggenz_runtime import nyquismic_daw_stems as stems
from zaaggenz_runtime import nyquismic_rate_compare as compare
from zaaggenz_runtime import nyquismic_compose_daw as direct

FORMAT = "nyq.saved-compose-listen-and-daw-kit.v1"
MAX_STEMS_ZIP = 80 * 1024 * 1024
MAX_LISTENER = 32 * 1024 * 1024
MAX_FINAL_ZIP = 128 * 1024 * 1024
_PAYLOAD = re.compile(rb'<script id="nyq-compare-payload" type="application/json">(.*?)</script>', re.S)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _cancel(cancelled):
    if cancelled is not None and cancelled():
        raise RuntimeError("NYQ production kit cancelled")


def _read_verified_stems(path: Path, receipt: dict, sweep_sha: str, anchor: dict, rates: tuple[str, ...], cancelled):
    if not 0 < path.stat().st_size <= MAX_STEMS_ZIP:
        raise ValueError("NYQ WAV archive exceeds 80 MiB")
    names = ["original.wav"] + [f"nyq-rate-{i:02d}.wav" for i in range(1, len(rates) + 1)]
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if ([i.filename for i in infos] != ["manifest.json", *names]
                or any(i.compress_type != zipfile.ZIP_STORED or i.flag_bits & 1 for i in infos)
                or sum(i.file_size for i in infos) > MAX_STEMS_ZIP):
            raise ValueError("invalid NYQ WAV archive layout")
        manifest = json.loads(archive.read("manifest.json"))
        if (manifest.get("format") != stems.FORMAT
                or manifest.get("source_sweep_sha256") != sweep_sha
                or manifest.get("source") != anchor
                or manifest.get("sample_rate_hz") != 48000
                or manifest.get("stems") != receipt.get("stems")
                or receipt.get("source_sweep_sha256") != sweep_sha
                or receipt.get("delivery_hz") != 48000):
            raise RuntimeError("foreign NYQ DAW manifest/receipt")
        items = manifest["stems"]
        if len(items) != len(names):
            raise RuntimeError("wrong number of NYQ WAV tracks")
        if (items[0].get("pcm_f32le_sha256") != anchor["dry_pcm_f32le_sha256"]
                or items[0].get("virtual_rate_hz") is not None):
            raise RuntimeError("foreign original dry PCM")
        for index, rate in enumerate(rates, 1):
            if items[index].get("virtual_rate_hz") != rate:
                raise RuntimeError("foreign NYQ virtual rate")
        wavs = []
        for entry, name in zip(items, names):
            _cancel(cancelled)
            if entry.get("file") != name:
                raise RuntimeError("foreign NYQ WAV filename")
            wav = archive.read(name)
            if _sha(wav) != entry.get("wav_sha256"):
                raise RuntimeError("NYQ WAV byte identity mismatch")
            wavs.append(wav)
    return names, wavs, items, manifest


def export_saved_compose_kit(
    project_path: str | Path,
    output_path: str | Path,
    *,
    virtual_rates_hz: tuple[str, ...] | list[str],
    evaluation_rate_hz: int = 192000,
    wait_seconds: float = 120.,
    cancelled=None,
) -> dict:
    """Render once per rate and publish one no-overwrite offline listener/DAW ZIP.

    Cold-reopen output contains listen.html and original, unmodified 48-kHz
    float32 WAVs. Publication detects controlled late edits/cancellation but
    cannot transact against arbitrary concurrent source/directory writers.
    """
    if cancelled is not None and not callable(cancelled):
        raise ValueError("cancelled must be callable")
    rates = sweep._rates(virtual_rates_hz)
    if type(evaluation_rate_hz) is not int or evaluation_rate_hz not in sweep.EVALUATION_RATES_HZ:
        raise ValueError("unsupported evaluation rate")
    if type(wait_seconds) not in (int, float) or not 0 < wait_seconds <= 3600:
        raise ValueError("invalid render timeout")
    dest = Path(output_path).absolute()
    project = Path(project_path)
    if dest.suffix.lower() != ".zip" or not dest.parent.is_dir():
        raise ValueError("output must be a ZIP in an existing directory")
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(str(dest))
    if not project.name.endswith(".zgtimeline.json") or not project.is_file():
        raise ValueError("expected saved Compose .zgtimeline.json")
    project_sha = direct._sha_file(project, cancelled, max_bytes=sweep.MAX_PROJECT_BYTES)
    _cancel(cancelled)

    with tempfile.TemporaryDirectory(prefix=".nyq-production-kit-", dir=str(dest.parent)) as folder:
        root = Path(folder)
        sweep_path, stems_path = root / "sweep.zip", root / "stems.zip"
        html_path, bundle = root / "listen.html", root / "kit.partial"
        sr = sweep.export_saved_compose_rate_sweep(
            project, sweep_path, virtual_rates_hz=list(rates),
            evaluation_rate_hz=evaluation_rate_hz, wait_seconds=wait_seconds,
            cancelled=cancelled)
        _cancel(cancelled)
        if (sr.get("project_file_sha256") != project_sha
                or sr.get("rates_hz") != list(rates)
                or sr.get("archive_sha256") != direct._sha_file(sweep_path, cancelled)):
            raise RuntimeError("NYQ sweep source/receipt mismatch")
        anchor = compare._verified_sweep(sweep_path, cancelled)
        if (anchor["archive_sha256"] != sr["archive_sha256"]
                or anchor["source"]["project_file_sha256"] != project_sha
                or anchor["source"]["dry_pcm_f32le_sha256"] != sr.get("dry_pcm_f32le_sha256")
                or [x["rate"] for x in anchor["variants"]] != list(rates)):
            raise RuntimeError("NYQ sweep PCM/packet authentication failed")

        dr = stems.export_daw_stems(sweep_path, stems_path, cancelled=cancelled)
        cr = compare.publish_rate_comparison(sweep_path, html_path, cancelled=cancelled)
        _cancel(cancelled)
        if (dr.get("zip_sha256") != direct._sha_file(stems_path, cancelled)
                or cr.get("html_sha256") != direct._sha_file(html_path, cancelled)
                or cr.get("source_zip_sha256") != sr["archive_sha256"]
                or cr.get("delivery_hz") != 48000
                or cr.get("rates_hz") != list(rates)):
            raise RuntimeError("NYQ listener/DAW publication receipt mismatch")
        names, wavs, items, dm = _read_verified_stems(
            stems_path, dr, sr["archive_sha256"], anchor["source"], rates, cancelled)
        if (dm["frames"] != anchor["frames"] or dm["channels"] != anchor["channels"]
                or cr.get("frames") != anchor["frames"] or cr.get("channels") != anchor["channels"]):
            raise RuntimeError("NYQ audio extent mismatch")
        for index, variant in enumerate(anchor["variants"], 1):
            if (items[index]["pcm_f32le_sha256"] != variant["wet_pcm_sha256"]
                    or items[index]["packet_sha256"] != variant["packet_sha256"]):
                raise RuntimeError("foreign NYQ wet PCM/clock packet")
        if _sha(wavs[0]) != _sha(anchor["dry"]) or any(
                _sha(wavs[i]) != _sha(anchor["variants"][i - 1]["wet"])
                for i in range(1, len(wavs))):
            raise RuntimeError("DAW track bytes differ from verified sweep")

        if not 0 < html_path.stat().st_size <= MAX_LISTENER:
            raise ValueError("listener exceeds 32 MiB")
        page = html_path.read_bytes()
        matches = _PAYLOAD.findall(page)
        if len(matches) != 1:
            raise RuntimeError("missing NYQ listener payload")
        payload = json.loads(matches[0])
        if (payload.get("receipt", {}).get("archive_sha256") != sr["archive_sha256"]
                or payload["receipt"].get("source") != anchor["source"]
                or payload.get("frames") != anchor["frames"]
                or payload.get("channels") != anchor["channels"]
                or len(payload.get("wavs", [])) != len(wavs)):
            raise RuntimeError("foreign NYQ listening receipt")
        for expected, encoded in zip(wavs, payload["wavs"]):
            _cancel(cancelled)
            if not isinstance(encoded, str) or base64.b64decode(encoded, validate=True) != expected:
                raise RuntimeError("listener WAV differs from DAW WAV")

        manifest = {
            "format": FORMAT, "source": anchor["source"],
            "source_sweep_sha256": sr["archive_sha256"],
            "project_file_sha256": project_sha, "evaluation_rate_hz": evaluation_rate_hz,
            "sample_rate_hz": 48000, "frames": anchor["frames"],
            "channels": anchor["channels"], "listen_html_sha256": _sha(page),
            "tracks": items,
            "scope": "Opt-in post-Compose full mix; not graph/rack/final-export admission",
        }
        body = (json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
            stems._entry(archive, "manifest.json", body)
            stems._entry(archive, "listen.html", page)
            for name, wav in zip(names, wavs):
                _cancel(cancelled)
                stems._entry(archive, name, wav)
        if not 0 < bundle.stat().st_size <= MAX_FINAL_ZIP:
            raise ValueError("production kit exceeds 128 MiB")
        with bundle.open("r+b") as handle:
            os.fsync(handle.fileno())
        bundle_sha = direct._sha_file(bundle, cancelled)
        if direct._sha_file(sweep_path, cancelled) != sr["archive_sha256"]:
            raise RuntimeError("NYQ sweep changed before publication")
        if direct._sha_file(project, cancelled, max_bytes=sweep.MAX_PROJECT_BYTES) != project_sha:
            raise RuntimeError("saved Compose project changed before publication")
        _cancel(cancelled)
        staged = bundle.stat()
        os.link(bundle, dest)
        try:
            _cancel(cancelled)
            if direct._sha_file(project, cancelled, max_bytes=sweep.MAX_PROJECT_BYTES) != project_sha:
                raise RuntimeError("saved Compose project changed during publication")
            _cancel(cancelled)
        except BaseException:
            try:
                published = dest.stat(follow_symlinks=False)
                if (published.st_dev, published.st_ino, published.st_size, published.st_mtime_ns) == (
                        staged.st_dev, staged.st_ino, staged.st_size, staged.st_mtime_ns):
                    dest.unlink()
            except FileNotFoundError:
                pass
            raise
    return {
        "format": FORMAT, "absolute_path": str(dest),
        "zip_sha256": bundle_sha, "project_file_sha256": project_sha,
        "source_sweep_sha256": sr["archive_sha256"], "delivery_hz": 48000,
        "frames": anchor["frames"], "channels": anchor["channels"],
        "virtual_rates_hz": list(rates), "tracks": items,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Saved Compose to offline NYQ listening + DAW WAV kit")
    parser.add_argument("--project", required=True, help="Existing saved Compose .zgtimeline.json")
    parser.add_argument("--output", required=True, help="New self-contained .zip; never overwritten")
    parser.add_argument("--virtual-hz", action="append", required=True, help="Repeat for 2–6 rational Hz rates")
    parser.add_argument("--evaluation-hz", type=int, choices=sweep.EVALUATION_RATES_HZ, default=192000)
    args = parser.parse_args(argv)
    try:
        result = export_saved_compose_kit(
            args.project, args.output, virtual_rates_hz=args.virtual_hz,
            evaluation_rate_hz=args.evaluation_hz)
    except (Exception, KeyboardInterrupt) as exc:
        print("NYQ production kit failed: " + str(exc), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
