"""Original-host bridge: real Chromium UI-saved Compose -> actual NYQ kit -> Chromium.

Run only after tests/timeline/browser_ui.py has saved the project and WAVs.
This is opt-in post-Compose full-mix acceptance, not graph/rack registration
or physical Windows operator qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_kit_source_matches_ui(manifest: dict, ui_export: dict, project_sha: str) -> None:
    """Falsify a self-consistent kit with a different UI revision/recipe/PCM.

    Both receipts must refer to the *same* independently captured UI output;
    kit-internal manifest/listener agreement alone is insufficient.
    """
    source = manifest.get("source") if isinstance(manifest, dict) else None
    if not isinstance(source, dict):
        raise RuntimeError("NYQ kit lacks a source-authentication anchor")
    expected = {
        "project_file_sha256": project_sha,
        "source_revision_sha256": ui_export.get("revision_id"),
        "compose_recipe_sha256": ui_export.get("recipe_sha256"),
        "dry_pcm_f32le_sha256": ui_export.get("pcm_sha256"),
    }
    for key, value in expected.items():
        if (not isinstance(value, str) or len(value) != 64
                or source.get(key) != value):
            raise RuntimeError(f"NYQ kit {key} differs from actual Compose UI evidence")
    for key in ("frames", "channels"):
        if (type(ui_export.get(key)) is not int
                or source.get(key) != ui_export[key]):
            raise RuntimeError(f"NYQ kit source {key} differs from actual Compose UI")



def run(args: list[str], *, prefix: str) -> dict:
    done = subprocess.run([sys.executable, *args], capture_output=True, text=True, check=False)
    if done.returncode:
        raise RuntimeError(f"{prefix} exit={done.returncode}\n{done.stdout}\n{done.stderr}")
    lines = [s.strip() for s in done.stdout.splitlines() if s.strip()]
    if prefix == "browser":
        marker = "NYQ_PRODUCTION_KIT_CHROMIUM "
        lines = [s[len(marker):] for s in lines if s.startswith(marker)]
    if len(lines) != 1:
        raise RuntimeError(f"{prefix} must return one JSON receipt: {done.stdout!r}")
    receipt = json.loads(lines[0])
    if not isinstance(receipt, dict):
        raise RuntimeError(f"{prefix} returned non-object JSON")
    return receipt


def check(out: Path) -> dict:
    project = out / "one-bar-spectral.zgtimeline.json"
    before = out / "before-reopen.wav"
    after = out / "after-reopen.wav"
    ui_report = out / "report.json"
    kit = out / "ui-saved-nyq-kit.zip"
    for path in (project, before, after, ui_report):
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"missing actual Chromium UI evidence: {path}")
    if kit.exists():
        raise RuntimeError(f"refusing to replace existing kit: {kit}")
    source_sha = digest(project)
    report = json.loads(ui_report.read_text(encoding="utf-8"))
    ui = report.get("exports", [])
    if report.get("checks") != "passed" or len(ui) != 2:
        raise RuntimeError("actual Compose UI render/cold-reopen report not successful")
    if (ui[0].get("frames") != 57600 or ui[0].get("sample_rate_hz") != 48000
            or ui[0].get("recipe_sha256") != ui[1].get("recipe_sha256")
            or ui[0].get("revision_id") != ui[1].get("revision_id")
            or digest(before) != digest(after)
            or digest(before) != ui[0].get("wav_sha256")
            or digest(after) != ui[1].get("wav_sha256")):
        raise RuntimeError("UI-saved project cold-reopen WAV/revision/recipe differs")

    produced = run(["-m", "zaaggenz_runtime.nyquismic_production_kit",
                    "--project", str(project), "--output", str(kit),
                    "--virtual-hz", "4/1", "--virtual-hz", "5/1"], prefix="export")
    expected = produced.get("zip_sha256")
    if (produced.get("project_file_sha256") != source_sha
            or produced.get("frames") != ui[0]["frames"]
            or produced.get("delivery_hz") != 48000
            or produced.get("virtual_rates_hz") != ["4/1", "5/1"]
            or expected != digest(kit)):
        raise RuntimeError("NYQ export is not bound to this actual saved UI source")
    (out / "ui-nyq-export-receipt.json").write_text(
        json.dumps(produced, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    verify_args = ["--kit", str(kit), "--project", str(project),
                   "--expected-sha256", expected]
    verified = run(["-m", "zaaggenz_runtime.nyquismic_kit_verify", *verify_args],
                   prefix="verify")
    if (verified.get("source_project_sha256") != source_sha
            or verified.get("zip_sha256") != expected
            or verified.get("frames") != ui[0]["frames"]
            or verified.get("delivery_hz") != 48000
            or verified.get("trusted_zip_sha_checked") is not True
            or verified.get("original_project_checked") is not True
            or len(verified.get("tracks", [])) != 3):
        raise RuntimeError("independent-process NYQ cold-reopen check is incomplete")
    # This host's actual UI WAV, not a different test fixture or OS.
    with zipfile.ZipFile(kit) as archive:
        original = archive.read("original.wav")
        manifest = json.loads(archive.read("manifest.json"))
    assert_kit_source_matches_ui(manifest, ui[0], source_sha)
    if (hashlib.sha256(original).hexdigest() != ui[0]["wav_sha256"]
            or verified["tracks"][0]["wav_sha256"] != ui[0]["wav_sha256"]):
        raise RuntimeError("kit's original audio differs from actual same-host UI WAV")
    (out / "ui-nyq-verify-receipt.json").write_text(
        json.dumps(verified, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    browser = run(["tests/runtime/browser_nyq_production_kit.py", *verify_args],
                  prefix="browser")
    if (browser.get("project_sha256") != source_sha
            or browser.get("kit_sha256") != expected
            or browser.get("frames") != ui[0]["frames"]
            or browser.get("file_uri_qualified") is not True
            or browser.get("project_anchor_checked") is not True
            or browser.get("trusted_kit_sha_checked") is not True
            or browser.get("audio_decode") != "PASS"
            or browser.get("download_identity") != "PASS"
            or browser.get("seek_pause_resume") != "PASS"
            or browser.get("rapid_switch_ramps") != 9
            or browser.get("unexpected_network_requests") != 0
            or browser.get("page_errors") != 0):
        raise RuntimeError("native Chromium did not authenticate real UI-saved NYQ listener")
    if digest(project) != source_sha:
        raise RuntimeError("source Compose project mutated during kit publication/playback")
    (out / "ui-nyq-browser-receipt.json").write_text(
        json.dumps(browser, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = {"status": "PASS", "source": "actual Chromium Compose save",
              "project_sha256": source_sha, "ui_wav_sha256": ui[0]["wav_sha256"],
              "kit_sha256": expected, "frames": ui[0]["frames"], "delivery_hz": 48000,
              "virtual_rates_hz": ["4/1", "5/1"], "file_origin_native_chromium": True,
              "ui_source_anchor_checked": True,
              "source_revision_sha256": ui[0]["revision_id"],
              "compose_recipe_sha256": ui[0]["recipe_sha256"],
              "scope": "opt-in post-Compose full mix; not physical Windows acceptance"}
    (out / "ui-nyq-end-to-end.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("nyq-compose-ui-evidence"))
    args = parser.parse_args()
    print("NYQ_UI_SAVED_KIT " + json.dumps(check(args.out), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
