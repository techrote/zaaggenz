"""MBR-004 physical Windows evidence verifier; never claims product admission.

Run this using the installed-wheel Python, from outside the repository checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from scipy.io import wavfile

MAX_BYTES = 256 * 1024 * 1024


def inspected_file(raw: str, *, wav: bool = False) -> dict:
    path = Path(raw).expanduser().resolve(strict=True)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("evidence file must be nonempty and at most 256 MiB")
    if path.suffix.lower() in (".png", ".jpg", ".jpeg"):
        with path.open("rb") as handle:
            signature = handle.read(8)
        if not (path.suffix.lower() == ".png" and signature == b"\x89PNG\r\n\x1a\n" or
                path.suffix.lower() in (".jpg", ".jpeg") and signature.startswith(b"\xff\xd8\xff")):
            raise ValueError(f"{path.name}: screenshot signature invalid")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {"name": path.name, "bytes": path.stat().st_size, "sha256": digest}
    if wav:
        rate, pcm = wavfile.read(path)
        if rate != 48000 or pcm.dtype != np.dtype("float32"):
            raise ValueError(f"{path.name}: expected 48000 Hz IEEE float32 WAV")
        if pcm.ndim not in (1, 2) or (pcm.ndim == 2 and pcm.shape[1] not in (1, 2)) or len(pcm) == 0:
            raise ValueError(f"{path.name}: invalid mono/stereo frame shape")
        if not np.isfinite(pcm).all():
            raise ValueError(f"{path.name}: NaN or infinite PCM")
        result.update(rate=rate, frames=int(len(pcm)), channels=1 if pcm.ndim == 1 else int(pcm.shape[1]),
                      peak_abs=float(np.max(np.abs(pcm.astype(np.float64)))),
                      rms=float(np.sqrt(np.mean(pcm.astype(np.float64)**2))),
                      pcm_sha256=hashlib.sha256(np.ascontiguousarray(pcm).tobytes()).hexdigest())
    return result


def _read_json(path: str) -> dict:
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("expected JSON object")
    return obj


def _write_json(path: str, obj: dict) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def snapshot(args) -> dict:
    files = {key: inspected_file(getattr(args, key), wav=key in ("before", "dry", "bypass"))
             for key in ("project", "preset", "before", "dry", "bypass", "screenshot_first", "wheel")}
    if files["dry"]["pcm_sha256"] != files["bypass"]["pcm_sha256"]:
        raise ValueError("full bypass does not match dry decoded PCM")
    if (files["dry"]["frames"], files["dry"]["channels"]) != (files["bypass"]["frames"], files["bypass"]["channels"]):
        raise ValueError("dry/bypass shape mismatch")
    if files["screenshot_first"]["name"].lower().rsplit(".", 1)[-1] not in ("png", "jpg", "jpeg"):
        raise ValueError("first-session screenshot must be PNG/JPEG")
    result = {"schema": "zg242-physical-snapshot-v1", "accepted_main_sha": args.accepted_main_sha,
              "harness_sha": args.harness_sha, "files": files}
    _write_json(args.output, result)
    return result


def finalize(args) -> dict:
    snap = _read_json(args.snapshot)
    if snap.get("schema") != "zg242-physical-snapshot-v1":
        raise ValueError("wrong or missing snapshot schema")
    known = snap.get("files", {})
    if not isinstance(known, dict):
        raise ValueError("invalid snapshot files")
    files = {key: inspected_file(getattr(args, key), wav=key in ("before", "after", "dry", "bypass"))
             for key in ("project", "preset", "before", "after", "dry", "bypass", "screenshot_second", "wheel")}
    for key in ("project", "preset", "before", "dry", "bypass", "wheel"):
        if files[key] != known.get(key):
            raise ValueError(f"{key} evidence changed after first-session snapshot")
    first = known.get("screenshot_first", {})
    if not first.get("sha256") or not first.get("name"):
        raise ValueError("missing first screenshot")
    if files["screenshot_second"]["name"].lower().rsplit(".", 1)[-1] not in ("png", "jpg", "jpeg"):
        raise ValueError("second-session screenshot must be PNG/JPEG")
    before = files["before"]
    after = files["after"]
    if (before["rate"], before["frames"], before["channels"]) != (after["rate"], after["frames"], after["channels"]):
        raise ValueError("before/after WAV shape or rate mismatch")
    if before["pcm_sha256"] != after["pcm_sha256"]:
        _, x = wavfile.read(args.before)
        _, y = wavfile.read(args.after)
        delta = x.astype(np.float64) - y.astype(np.float64)
        raise ValueError(f"cold-reopen PCM not identical: RMS={np.sqrt(np.mean(delta**2)):.9g}, "
                         f"peak={np.max(np.abs(delta)):.9g}")
    if files["dry"]["pcm_sha256"] != files["bypass"]["pcm_sha256"]:
        raise ValueError("dry/full-bypass PCM not identical")
    session = _read_json(args.sessions)
    if session.get("schema") != "zg242-physical-session-v1":
        raise ValueError("missing session evidence schema")
    stages = session.get("stages")
    if not isinstance(stages, list) or len(stages) != 2:
        raise ValueError("exactly two runtime sessions required")
    for index, stage in enumerate(stages, 1):
        if not isinstance(stage, dict) or stage.get("exit_code") != 0 or not all(stage.get(k) for k in ("ready", "process_exited", "operator_attested_ctrl_c", "operator_attested_workflow", "startup_utc", "shutdown_utc", "console_log_sha256")):
            raise ValueError(f"session {index}: missing startup, shutdown, console or operator evidence")
    identity = _read_json(args.identity)
    if identity.get("schema") != "zg242-installed-identity-v1" or not identity.get("release_ids") or not identity.get("package_version"):
        raise ValueError("missing installed wheel frontend/backend identity")
    result = {"schema": "zg242-physical-receipt-v1", "status": "operator-attested; independent review pending",
              "admission": False, "accepted_main_sha": snap.get("accepted_main_sha"),
              "harness_sha": snap.get("harness_sha"), "identity": identity,
              "artifacts": {**files, "screenshot_first": first},
              "sessions": stages,
              "checks": {"same_host_cold_reopen_pcm_exact": True, "full_bypass_equals_dry_pcm_exact": True,
                         "project_and_preset_files_unchanged": True, "two_real_processes_operator_attested": True},
              "limitations": ["GUI actions and graceful Ctrl+C are operator-attested, not independently automated",
                              "Gate B cross-host spectral portability separately pending",
                              "Integrator must examine original files/screenshots before Gate A admission"]}
    _write_json(args.output, result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("snapshot", help="record first-session immutable evidence")
    b = sub.add_parser("finalize", help="verify two sessions and publish redacted receipt")
    for p in (a, b):
        p.add_argument("--project", required=True)
        p.add_argument("--preset", required=True)
        p.add_argument("--before", required=True)
        p.add_argument("--dry", required=True)
        p.add_argument("--bypass", required=True)
        p.add_argument("--wheel", required=True)
        p.add_argument("--output", required=True)
    a.add_argument("--screenshot-first", required=True)
    a.add_argument("--accepted-main-sha", required=True)
    a.add_argument("--harness-sha", required=True)
    b.add_argument("--screenshot-second", required=True)
    b.add_argument("--after", required=True)
    b.add_argument("--snapshot", required=True)
    b.add_argument("--sessions", required=True)
    b.add_argument("--identity", required=True)
    args = parser.parse_args(argv)
    try:
        data = snapshot(args) if args.command == "snapshot" else finalize(args)
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"ZG242 EVIDENCE FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"schema": data["schema"], "output": str(Path(args.output).name), "admission": data.get("admission", False)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
