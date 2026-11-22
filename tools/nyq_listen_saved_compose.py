"""One-command, offline NYQ audition of an already saved Compose project.

This is a convenience entry point for the existing source-verified production kit,
not a rack node, modulation UI or substitute for physical Windows acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import subprocess
import sys
import uuid
import webbrowser
import zipfile

from zaaggenz_runtime import nyquismic_audition_sweep as sweep

RATES = ("256/1", "512/1")  # Bounded real-source comparison, not unrestricted 16-kHz event packets.
SHA = re.compile(r"[0-9a-f]{64}\Z")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _command(args: list[str], *, name: str) -> dict:
    done = subprocess.run([sys.executable, *args], text=True, capture_output=True,
                          check=False)
    if done.returncode:
        raise RuntimeError(f"{name} failed (exit {done.returncode}):\n{done.stderr or done.stdout}")
    try:
        value = json.loads(done.stdout)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"{name} did not return its required JSON receipt") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{name} did not return an object receipt")
    return value


def _publish_verified_directory(staging: Path, destination: Path) -> None:
    """Publish a complete kit atomically without replacing any existing path.

    Windows directory rename already rejects an occupied destination. Linux needs
    renameat2(RENAME_NOREPLACE): os.rename/Path.rename can silently replace an
    empty directory created by another process after a preflight exists() check.
    Fail closed on other platforms or kernels without a safe primitive.
    """
    if sys.platform == "win32":
        staging.rename(destination)
        return
    if sys.platform != "linux":
        raise RuntimeError("atomic no-replace directory publication is unavailable on this platform")
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename_noreplace = libc.renameat2
    except AttributeError as exc:
        raise RuntimeError("Linux renameat2(RENAME_NOREPLACE) is required for safe publication") from exc
    rename_noreplace.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                                 ctypes.c_char_p, ctypes.c_uint]
    rename_noreplace.restype = ctypes.c_int
    # AT_FDCWD=-100, RENAME_NOREPLACE=1; source and target stay in one parent.
    if rename_noreplace(-100, os.fsencode(staging), -100, os.fsencode(destination), 1):
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(destination))


def audition(project: Path, output_dir: Path, *, open_browser: bool = True) -> dict:
    project = project.resolve()
    if not project.is_file() or not project.name.endswith(".zgtimeline.json"):
        raise ValueError("select an existing saved Compose .zgtimeline.json project")
    if not 0 < project.stat().st_size <= sweep.MAX_PROJECT_BYTES:
        raise ValueError("saved Compose project must be 1 byte to 2,000,000 bytes")
    source_sha = _sha(project)
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing NYQ listener: {output_dir}")
    # Do not expose unverified WAVs or poison an explicit destination on failure.
    # A same-parent staging directory preserves final rename semantics on both hosts.
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}-nyq-stage-", dir=output_dir.parent))
    try:
        kit = staging / "nyq-listen.zip"
        exported = _command(["-m", "zaaggenz_runtime.nyquismic_production_kit",
                             "--project", str(project), "--output", str(kit),
                             *(v for rate in RATES for v in ("--virtual-hz", rate))], name="NYQ export")
        kit_sha = exported.get("zip_sha256")
        if (not isinstance(kit_sha, str) or not SHA.fullmatch(kit_sha)
                or exported.get("project_file_sha256") != source_sha
                or exported.get("virtual_rates_hz") != list(RATES)
                or exported.get("delivery_hz") != 48000
                or not kit.is_file() or _sha(kit) != kit_sha):
            raise RuntimeError("NYQ exporter source/rate/ZIP identity mismatch")
        verified = _command(["-m", "zaaggenz_runtime.nyquismic_kit_verify",
                             "--kit", str(kit), "--project", str(project),
                             "--expected-sha256", kit_sha], name="NYQ cold-reopen verification")
        if (verified.get("zip_sha256") != kit_sha
                or verified.get("source_project_sha256") != source_sha
                or verified.get("virtual_rates_hz") != list(RATES)
                or verified.get("delivery_hz") != 48000
                or verified.get("trusted_zip_sha_checked") is not True
                or verified.get("original_project_checked") is not True
                or len(verified.get("tracks", [])) != 3):
            raise RuntimeError("NYQ verifier did not independently confirm the saved project and WAVs")
        if _sha(project) != source_sha or _sha(kit) != kit_sha:
            raise RuntimeError("source or kit changed after independent verification")

        names = ["manifest.json", "listen.html", "original.wav",
                 "nyq-rate-01.wav", "nyq-rate-02.wav"]
        with zipfile.ZipFile(kit) as archive:
            if archive.namelist() != names:
                raise RuntimeError("unexpected Nyquismic kit members; refusing extraction")
            for name in names:
                with (staging / name).open("xb") as handle:
                    handle.write(archive.read(name))
        if _sha(project) != source_sha or _sha(kit) != kit_sha:
            raise RuntimeError("source or kit changed during extraction")
        listener = (output_dir / "listen.html").resolve()
        receipt = {"status": "PASS", "project_sha256": source_sha,
                   "kit_sha256": kit_sha, "delivery_hz": 48000,
                   "virtual_rates_hz": list(RATES), "listener": str(listener),
                   "wavs": [str(output_dir / name) for name in names[2:]],
                   "cold_reopen_verified": True, "scope": "offline post-Compose full-mix"}
        (staging / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                                                   encoding="utf-8")
        _publish_verified_directory(staging, output_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    if open_browser and not webbrowser.open(listener.as_uri()):
        raise RuntimeError(f"browser did not open; launch the verified listener manually: {listener}")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="Compose-saved .zgtimeline.json file")
    parser.add_argument("--output-dir", type=Path, help="New directory; must not exist")
    parser.add_argument("--no-open", action="store_true", help="Verify and extract without opening a browser")
    args = parser.parse_args(argv)
    output_dir = args.output_dir or Path.cwd() / ("nyq-listen-" + uuid.uuid4().hex[:12])
    try:
        receipt = audition(args.project, output_dir, open_browser=not args.no_open)
    except (Exception, KeyboardInterrupt) as exc:
        print(f"NYQ audition failed: {exc}", file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
