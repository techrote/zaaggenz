"""Opt-in rate-sweep audition: one saved Compose source, multiple verified NYQ A/B pages.

This is a cold-reopened *batch* of the existing source-bound direct-audition
pipeline, not a graph node, live session or registered Compose export action.
Every wet variant is compared with the identical original post-rack dry PCM.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

FORMAT = "nyq.saved-compose-rate-sweep.v1"
RATE_MIN = 2
RATE_MAX = 6
MAX_PROJECT_BYTES = 2_000_000
MAX_PAGE_BYTES = 128 * 1024 * 1024
MAX_BUNDLE_PAYLOAD_BYTES = 512 * 1024 * 1024
EVALUATION_RATES_HZ = (192000, 384000, 768000)
_CHUNK = 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check(cancelled) -> None:
    if cancelled is not None and cancelled():
        raise RuntimeError("NYQ rate sweep cancelled")


def _rates(values) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)) or not RATE_MIN <= len(values) <= RATE_MAX:
        raise ValueError("sweep requires 2 to 6 virtual sampling rates")
    normalized = []
    for value in values:
        if not isinstance(value, str) or len(value) > 32 or not re.fullmatch(r"[0-9]+(?:/[0-9]+)?", value):
            raise ValueError("virtual rates must be positive integer or rational Hz strings")
        try:
            ratio = Fraction(value)
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError("invalid virtual sampling rate") from exc
        if not 0 < ratio <= 1_000_000:
            raise ValueError("virtual sampling rate outside positive 1-MHz admission ceiling")
        normalized.append(f"{ratio.numerator}/{ratio.denominator}")
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate virtual sampling rates")
    return tuple(normalized)


def _zip_write(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o600 << 16
    archive.writestr(info, content)


def _index(entries: list[dict]) -> bytes:
    rows = []
    for entry in entries:
        href = html.escape(entry["page"], quote=True)
        rate = html.escape(entry["virtual_rate_hz"], quote=True)
        rows.append(f'<li><a href="{href}">Virtual clock {rate} Hz — open dry / Nyquismic A/B player</a></li>')
    content = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
               "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
               "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
               "<title>ZaagGenZ Nyquismic rate sweep</title>"
               "<style>body{font:16px system-ui,sans-serif;max-width:58rem;margin:3rem auto;padding:0 1rem;line-height:1.65}"
               "li{margin:1.1rem 0}a{color:#2871b9}code{font-size:.95em}</style></head><body>"
               "<h1>Nyquismic virtual-clock rate sweep</h1>"
               "<p>Unzip the entire bundle first, then open a variant. Each page independently switches"
               " between unchanged post-Compose dry PCM and its chosen Nyquismic treatment."
               " No files are uploaded and no level matching is applied.</p><ol>"
               + "".join(rows) + "</ol><p>See <code>manifest.json</code> for verified"
               " source, revision, dry/wet PCM and page hashes. Offline listening is opt-in."
               " This is not a registered Compose graph/rack route.</p></body></html>")
    return content.encode("utf-8")


def export_saved_compose_rate_sweep(
    project_path: str | Path,
    output_path: str | Path,
    *,
    virtual_rates_hz: tuple[str, ...] | list[str],
    evaluation_rate_hz: int = 192000,
    wait_seconds: float = 120.,
    cancelled=None,
) -> dict:
    """Publish a no-overwrite ZIP of independent source-equal 48-kHz A/B pages.

    Sequential independent render jobs reopen one same saved project path. The
    per-variant source asset, revision, recipe, *and dry PCM* identities must all
    match: source edits or nondeterministic baseline renders abort the *entire*
    bundle before publication. No persistent live session is claimed.
    """
    rates = _rates(virtual_rates_hz)
    if type(evaluation_rate_hz) is not int or evaluation_rate_hz not in EVALUATION_RATES_HZ:
        raise ValueError("unsupported evaluation rate")
    if type(wait_seconds) not in (float, int) or not 0 < wait_seconds <= 3600:
        raise ValueError("invalid per-variant render timeout")
    if cancelled is not None and not callable(cancelled):
        raise ValueError("cancelled must be a callable or None")
    dest = Path(output_path).absolute()
    if dest.suffix.lower() != ".zip" or not dest.parent.is_dir():
        raise ValueError("output must be a ZIP in an existing directory")
    if dest.exists() or dest.is_symlink():
        raise FileExistsError(str(dest))
    project = Path(project_path)
    if not project.name.endswith(".zgtimeline.json") or not project.is_file():
        raise ValueError("project must be an existing saved Compose .zgtimeline.json")
    if project.stat().st_size > MAX_PROJECT_BYTES:
        raise ValueError("Compose project exceeds 2 MB")
    raw_project = project.read_bytes()
    if len(raw_project) > MAX_PROJECT_BYTES:
        raise ValueError("Compose project exceeds 2 MB")
    project_sha = _sha(raw_project)
    _check(cancelled)

    # Avoid importing heavy audio engines before all bounded preflight checks.
    from zaaggenz_runtime.nyquismic_offline_audition import export_saved_compose_audition

    entries = []
    anchor = None
    total_page_bytes = 0
    with tempfile.TemporaryDirectory(prefix=".nyq-rate-sweep-", dir=str(dest.parent)) as temp:
        root = Path(temp)
        for index, rate in enumerate(rates, start=1):
            _check(cancelled)
            if _sha(project.read_bytes()) != project_sha:
                raise RuntimeError("saved Compose project changed during rate sweep")
            page_name = f"variant-{index:02d}.html"
            page_path = root / page_name
            receipt = export_saved_compose_audition(
                project, page_path, virtual_rate_hz=rate,
                evaluation_rate_hz=evaluation_rate_hz,
                wait_seconds=wait_seconds, cancelled=cancelled)
            _check(cancelled)
            if receipt.get("absolute_path") != str(page_path.absolute()):
                raise RuntimeError("unexpected audition output identity")
            if receipt.get("project_file_sha256") != project_sha or receipt.get("virtual_rate_hz") != rate:
                raise RuntimeError("audition receipt does not match requested immutable project/rate")
            if receipt.get("evaluation_rate_hz") != evaluation_rate_hz or receipt.get("delivery_hz") != 48000:
                raise RuntimeError("audition clocks do not match declared evaluation/output rates")
            current_anchor = {key: receipt.get(key) for key in (
                "project_file_sha256", "source_asset_sha256", "source_revision_sha256",
                "compose_recipe_sha256", "dry_pcm_f32le_sha256", "frames", "channels")}
            if (not all(current_anchor.values()) or
                    any(not isinstance(current_anchor[k], str) or not _SHA256.fullmatch(current_anchor[k])
                        for k in ("project_file_sha256", "source_asset_sha256",
                                  "source_revision_sha256", "compose_recipe_sha256",
                                  "dry_pcm_f32le_sha256")) or
                    type(receipt.get("frames")) is not int or receipt["frames"] <= 0 or
                    receipt.get("channels") not in (1, 2)):
                raise RuntimeError("invalid source/dry PCM numerical receipt")
            if anchor is None:
                anchor = current_anchor
            elif current_anchor != anchor:
                raise RuntimeError("different Compose source, revision or dry PCM among variants")
            if not _SHA256.fullmatch(str(receipt.get("wet_pcm_f32le_sha256", ""))):
                raise RuntimeError("missing Nyquismic wet PCM identity")
            size = page_path.stat().st_size
            if not 0 < size <= MAX_PAGE_BYTES or total_page_bytes + size > MAX_BUNDLE_PAYLOAD_BYTES:
                raise ValueError("rate sweep audition exceeds bounded bundle size")
            page_bytes = page_path.read_bytes()
            if len(page_bytes) != size or _sha(page_bytes) != receipt.get("html_sha256"):
                raise RuntimeError("authentic audition page changed after export")
            total_page_bytes += size
            entries.append({
                "page": page_name, "page_sha256": _sha(page_bytes),
                "virtual_rate_hz": rate, "packet_sha256": receipt.get("packet_sha256"),
                "wet_pcm_f32le_sha256": receipt["wet_pcm_f32le_sha256"],
                "source_bundle_sha256": receipt.get("source_bundle_sha256"),
            })
        _check(cancelled)
        if _sha(project.read_bytes()) != project_sha:
            raise RuntimeError("saved Compose project changed before sweep publication")
        manifest = {
            "format": FORMAT, "project_file_sha256": project_sha,
            "source": anchor, "evaluation_rate_hz": evaluation_rate_hz,
            "delivery_rate_hz": 48000, "variants": entries,
            "note": "Same saved-project source and unchanged dry PCM per variant; post-Compose full-mix only",
        }
        index_bytes = _index(entries)
        manifest_bytes = (json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        archive_path = root / "staged.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
            _zip_write(archive, "index.html", index_bytes)
            _zip_write(archive, "manifest.json", manifest_bytes)
            for entry in entries:
                _check(cancelled)
                path = root / entry["page"]
                data = path.read_bytes()
                if _sha(data) != entry["page_sha256"]:
                    raise RuntimeError("rate sweep page mutated before final packaging")
                _zip_write(archive, entry["page"], data)
        with archive_path.open("rb") as f:
            os.fsync(f.fileno())
        _check(cancelled)
        if _sha(project.read_bytes()) != project_sha:
            raise RuntimeError("saved Compose project changed before atomic commit")
        archive_sha = hashlib.sha256()
        with archive_path.open("rb") as file:
            for chunk in iter(lambda: file.read(_CHUNK), b""):
                archive_sha.update(chunk)
        _check(cancelled)
        os.link(archive_path, dest)  # atomic create-if-absent, never os.replace
    return {
        "format": FORMAT, "absolute_path": str(dest),
        "archive_sha256": archive_sha.hexdigest(),
        "project_file_sha256": project_sha,
        "source_asset_sha256": anchor["source_asset_sha256"],
        "dry_pcm_f32le_sha256": anchor["dry_pcm_f32le_sha256"],
        "rates_hz": list(rates), "variants": entries,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline saved-Compose NYQ virtual-rate audition sweep")
    parser.add_argument("--project", required=True, help="Saved .zgtimeline.json")
    parser.add_argument("--output", required=True, help="New .zip; never overwrites")
    parser.add_argument("--virtual-hz", action="append", required=True,
                        help="Repeat for 2–6 positive rational virtual rates in Hz")
    parser.add_argument("--evaluation-hz", type=int, choices=EVALUATION_RATES_HZ, default=192000)
    args = parser.parse_args(argv)
    try:
        result = export_saved_compose_rate_sweep(
            args.project, args.output, virtual_rates_hz=args.virtual_hz,
            evaluation_rate_hz=args.evaluation_hz)
    except (Exception, KeyboardInterrupt) as exc:
        print("NYQ rate sweep failed: " + str(exc), file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
