"""Real 48-kHz Compose UI regression, not physical Windows acceptance.

Geometry is checked before Playwright can scroll a buried transport into view.
Spectral controls must open through normal user actions, without DOM shortcuts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

import numpy as np
from playwright.sync_api import expect, sync_playwright
from scipy.io import wavfile

from zaaggenz_runtime import ZaaggenzServer


PALETTE_KEYS = (
    "--bg", "--panel", "--panel2", "--line", "--line2", "--text", "--muted",
    "--phosphor", "--cyan", "--amber", "--danger", "--control", "--focus",
)
THEMES = ("earth", "phosphor", "amber", "ice", "plum", "mono")
TRANSPORT = ("#render", "#preview", "#play", "#download", "#status")


def palette(page):
    return page.evaluate("""keys => {
        const css = getComputedStyle(document.documentElement);
        return Object.fromEntries(keys.map(key => [key, css.getPropertyValue(key).trim()]));
    }""", list(PALETTE_KEYS))


def in_view(page, selectors):
    """Do not scroll: reject a DOM element outside the usable viewport."""
    bounds = page.evaluate("""selectors => Object.fromEntries(selectors.map(selector => {
        const node = document.querySelector(selector);
        if (!node) return [selector, {missing: true}];
        const rect = node.getBoundingClientRect(), css = getComputedStyle(node);
        return [selector, {x: rect.x, y: rect.y, width: rect.width, height: rect.height,
            right: rect.right, bottom: rect.bottom, viewportWidth: innerWidth,
            viewportHeight: innerHeight, display: css.display, visibility: css.visibility}];
    }))""", list(selectors))
    for selector, rect in bounds.items():
        assert not rect.get("missing"), (selector, rect)
        assert rect["width"] > 0 and rect["height"] > 0, (selector, rect)
        assert rect["display"] != "none" and rect["visibility"] == "visible", (selector, rect)
        assert rect["x"] >= -1 and rect["y"] >= -1, (selector, rect)
        assert rect["right"] <= rect["viewportWidth"] + 1, (selector, rect)
        assert rect["bottom"] <= rect["viewportHeight"] + 1, (selector, rect)
    return bounds


def no_document_overflow(page):
    extent = page.evaluate("""() => ({width: innerWidth,
        document: document.documentElement.scrollWidth, body: document.body.scrollWidth})""")
    assert max(extent["document"], extent["body"]) <= extent["width"] + 1, extent
    return extent


def save_project(page, path):
    expect(page.locator("#save")).to_be_enabled()
    with page.expect_download() as pending:
        page.locator("#save").click()
    pending.value.save_as(path)
    return json.loads(path.read_text(encoding="utf-8"))


def download_wav(page, server, path):
    expect(page.locator("#download")).to_have_attribute("aria-disabled", "false")
    with page.expect_download() as pending:
        page.locator("#download").click()
    pending.value.save_as(path)
    rate, pcm = wavfile.read(path)
    job_id = page.locator("#outputs").input_value()
    result = server.timeline.artifact(job_id)
    metadata = result.metadata()
    # Revision is deliberately inside a collapsed technical-details panel.\n    # inner_text() is visibility-dependent and returns an empty string there.\n    revision = page.locator("#revision").text_content().strip()
    assert metadata["revision_id"] == revision, {"job_id": job_id, "job_revision": metadata["revision_id"], "editor_revision": revision, "playback_revision": page.locator("#playback-revision").inner_text(), "session": server.session.snapshot(), "selected_output": page.locator("#outputs").input_value()}
    assert page.locator("#playback-revision").inner_text() == revision
    assert rate == 48000 == metadata["asset"]["sample_rate_hz"]
    assert pcm.dtype == np.float32 and np.isfinite(pcm).all()
    assert pcm.ndim == 1 and len(pcm) == metadata["asset"]["frame_count"] > 0
    assert np.any(pcm != 0), "The UI exported silence for its musical example"
    raw = np.asarray(pcm, dtype="<f4").tobytes()
    assert raw == result.audio_bytes, "Downloaded WAV differs from the selected render"
    assert hashlib.sha256(raw).hexdigest() == metadata["asset"]["content_sha256"]
    return raw, {
        "file": path.name, "job_id": job_id, "revision_id": revision,
        "recipe_sha256": metadata["recipe_sha256"], "sample_rate_hz": rate,
        "frames": len(pcm), "channels": 1, "encoding": "float32",
        "pcm_sha256": hashlib.sha256(raw).hexdigest(),
        "wav_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    server = ZaaggenzServer(0, 48000)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    errors = []
    report = {"method": "compose-visible-instrument-ui-v1", "sample_rate_hz": 48000}
    page = None
    playwright = None
    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("ZAAGGENZ_CHROMIUM") or None,
            headless=True,
            args=["--autoplay-policy=no-user-gesture-required", "--mute-audio", "--no-sandbox"],
        )
        context = browser.new_context(viewport={"width": 1366, "height": 768}, accept_downloads=True)
        synth = context.new_page()
        synth.on("pageerror", lambda error: errors.append("synth: " + str(error)))
        synth.goto(base + "/")
        expect(synth.locator("#version")).not_to_have_text("")
        synth.screenshot(path=args.out / "synth-earth-reference.png")
        synth.locator("#openUtility").click()
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append("compose: " + str(error)))
        page.set_default_timeout(30000)

        def ready():
            expect(page.locator("#render")).to_be_enabled(timeout=60000)
            expect(page.locator("#preview")).to_be_enabled(timeout=60000)

        # The existing synth is the independent palette oracle. All six
        # selections must survive a Compose reload on the same origin.
        theme_evidence = {}
        for theme in THEMES:
            synth.locator("#themePreset").select_option(theme)
            reference = palette(synth)
            assert all(reference.values()), reference
            page.goto(base + "/timeline")
            ready()
            expect(page.locator("#themePreset")).to_have_value(theme)
            assert palette(page) == reference, (theme, reference, palette(page))
            page.reload()
            ready()
            assert palette(page) == reference, (theme, "reload lost palette")
            theme_evidence[theme] = reference
        # Reverse direction uses the real Compose picker.
        page.locator("#appearance-panel > summary").click()
        page.locator("#themePreset").select_option("earth")
        page.locator("#appearance-panel > summary").click()
        synth.reload()
        expect(synth.locator("#themePreset")).to_have_value("earth")
        assert palette(page) == palette(synth)
        report["themes"] = theme_evidence

        styles = page.locator("#render").evaluate("""node => {
            const button = getComputedStyle(node), body = getComputedStyle(document.body);
            return {font: body.fontFamily, buttonFont: button.fontFamily,
                radius: button.borderRadius, height: node.getBoundingClientRect().height};
        }""")
        assert "mono" in styles["font"].lower() and "mono" in styles["buttonFont"].lower(), styles
        assert styles["radius"] == "0px" and styles["height"] <= 36, styles
        report["instrument_style"] = styles
        report["initial_transport"] = in_view(page, TRANSPORT)
        no_document_overflow(page)
        page.screenshot(path=args.out / "compose-earth-initial.png")

        # A wide SVG has horizontal letterboxing under its default aspect
        # policy. Pointer editing must follow painted beats, not the outer box.
        page.set_viewport_size({"width": 1920, "height": 1080})
        position = page.locator("#roll").evaluate("""svg => {
            const matrix = svg.getScreenCTM();
            const point = new DOMPoint(48 + 1140 * 2 / 16, 270).matrixTransform(matrix);
            return {x: point.x, y: point.y, beatWidth: matrix.a * 1140 / 16};
        }""")
        page.mouse.dblclick(position["x"], position["y"])
        ready()
        wide = save_project(page, args.out / "wide-pointer-add.zgtimeline.json")
        assert wide["notes"][0]["beat"] == "2/1", wide["notes"]
        box = page.locator("#roll .note").first.bounding_box()
        assert box
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + position["beatWidth"], y)
        page.mouse.up()
        ready()
        wide = save_project(page, args.out / "wide-pointer-move.zgtimeline.json")
        assert wide["notes"][0]["beat"] == "3/1", wide["notes"]
        report["wide_pointer_edit"] = {"width": 1920, "added_beat": "2/1", "moved_beat": "3/1"}
        page.set_viewport_size({"width": 1366, "height": 768})

        # Reproduce the default-length spectral rejection. Its explanation
        # must remain visible; rejection must preserve the saved source.
        page.locator("#example4").click()
        ready()
        page.get_by_role("button", name="Enable four-band rack", exact=True).click()
        ready()
        before = save_project(page, args.out / "before-rejected-spectral.zgtimeline.json")
        before_identity = server.session.snapshot()
        lowmid = page.locator("#rack-editor .rack-band").nth(1)
        started = time.monotonic()
        lowmid.get_by_role("button", name="Add spectral", exact=True).click()
        expect(page.locator("#rack-status")).to_contain_text("Shorten", timeout=60000)
        ready()
        expect(page.locator("#status")).to_contain_text("Shorten")
        report["rejected_edit_seconds"] = round(time.monotonic() - started, 3)
        in_view(page, ("#rack-status", "#status"))
        assert lowmid.locator(".rack-spectral").count() == 0
        assert server.session.snapshot() == before_identity
        page.screenshot(path=args.out / "compose-spectral-budget-feedback.png")
        assert save_project(page, args.out / "after-rejected-spectral.zgtimeline.json") == before

        # Use the visible one-bar example, not a hand-edited imported
        # fixture. Successful add must expose the target controls itself.
        page.locator("#example1").click()
        ready()
        expect(page.locator("#length")).to_have_value("4/1")
        lowmid = page.locator("#rack-editor .rack-band").nth(1)
        lowmid.get_by_role("button", name="Add spectral", exact=True).click()
        ready()
        expect(lowmid.locator(".rack-spectral")).to_have_attribute("open", "")
        expect(lowmid.get_by_label("Primary target degree")).to_be_visible()
        project = save_project(page, args.out / "one-bar-spectral.zgtimeline.json")
        assert project["end_beat"] == "4/1" and project["notes"]
        assert project["project"]["revisions"][0] == before["project"]["revisions"][0]

        responsive = []
        for width, height in ((1366, 768), (900, 800), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            page.locator("#rack-editor .rack-band").last.scroll_into_view_if_needed()
            responsive.append({"width": width, "height": height,
                "extent": no_document_overflow(page), "transport": in_view(page, TRANSPORT)})
            page.screenshot(path=args.out / f"compose-rack-{width}.png")
        report["responsive"] = responsive
        page.set_viewport_size({"width": 1366, "height": 768})
        page.locator("#rack-editor .rack-band").last.scroll_into_view_if_needed()
        in_view(page, TRANSPORT)

        page.locator("#preview").click()
        expect(page.locator("#play")).to_be_enabled(timeout=120000)
        page.wait_for_function("!document.getElementById('audio').paused", timeout=120000)
        page.locator("#play").click()
        page.wait_for_function("document.getElementById('audio').paused")
        page.locator("#play").click()
        page.wait_for_function("!document.getElementById('audio').paused")
        selected = page.locator("#outputs").input_value()
        download = page.locator("#download").get_attribute("href")
        page.locator("#stop").click()
        page.wait_for_function("document.getElementById('audio').paused && document.getElementById('audio').currentTime===0")
        expect(page.locator("#play")).to_be_enabled()
        assert page.locator("#outputs").input_value() == selected
        assert page.locator("#download").get_attribute("href") == download
        pcm, first = download_wav(page, server, args.out / "before-reopen.wav")
        assert first["frames"] == 57600, first  # 4 beats at unchanged 200 BPM / 48 kHz.
        page.screenshot(path=args.out / "compose-rendered-ready.png")

        # Reopen the actual downloaded project and render through ordinary
        # controls. Reload also clears the browser's previous output slots.
        page.reload()
        ready()
        page.locator("#open").set_input_files(args.out / "one-bar-spectral.zgtimeline.json")
        ready()
        page.locator("#render").click()
        expect(page.locator("#play")).to_be_enabled(timeout=120000)
        reopened_pcm, second = download_wav(page, server, args.out / "after-reopen.wav")
        assert reopened_pcm == pcm, "Saved/reopened project changed decoded PCM"
        assert first["revision_id"] == second["revision_id"]
        assert first["recipe_sha256"] == second["recipe_sha256"]
        report["exports"] = [first, second]
        report["web_release"] = page.evaluate("() => window.__ZAAGGENZ_WEB_RELEASE__")
        assert not errors, errors
        report.update(checks="passed", page_errors=errors,
                      scope="Local Chromium UI and numerical WAV; not physical Windows acceptance")
        (args.out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, sort_keys=True))
        browser.close()
    except Exception:
        if page is not None:
            try:
                page.screenshot(path=args.out / "failure.png", full_page=True)
                print("Browser status:", page.locator("#status").inner_text(), errors, flush=True)
            except Exception:
                pass
        raise
    finally:
        if playwright is not None:
            playwright.stop()
        server.shutdown()
        server.server_close()
        thread.join(3)


if __name__ == "__main__":
    main()
