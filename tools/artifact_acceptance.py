"""Install a built ZaagGenZ artifact outside the checkout and exercise it in isolation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv


def _run(args, *, cwd, env=None, timeout=300):
    merged = os.environ.copy()
    merged.pop("PYTHONPATH", None)
    if env:
        merged.update(env)
    return subprocess.run(
        [str(x) for x in args],
        cwd=cwd,
        env=merged,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _single_artifact(dist: Path, kind: str) -> Path:
    pattern = "*.whl" if kind == "wheel" else "*.tar.gz"
    matches = sorted(dist.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {kind} in {dist}, found {[p.name for p in matches]}")
    return matches[0].resolve()


_SMOKE = r"""
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sys

import zaaggenz_environment
from zaaggenz_environment import installed_asset_report
from zaaggenz_contracts import validate
from zaaggenz_contracts.examples import examples
from zaaggenz_runtime import ZaaggenzServer
from zaaggenz_timeline.server import ROOT, TimelineServer
from zaaggenz_web_release import build_web_releases

validate(examples()["RenderRecipe"], "RenderRecipe")
assert importlib.metadata.version("zaaggenz") == zaaggenz_environment.VERSION
root = Path(ROOT).resolve()
assets = installed_asset_report(root)
releases = build_web_releases(root, unified_runtime=True)
assert set(releases) == {"timeline", "listening", "inspector", "vocal"}
timeline = TimelineServer(0, 12000)
timeline.server_close()
runtime = ZaaggenzServer(0, 12000)
runtime.server_close()
print(json.dumps({
    "version": zaaggenz_environment.VERSION,
    "installed_root": str(root),
    "installed_assets": assets,
    "timeline_html_sha256": hashlib.sha256((root / "web" / "timeline" / "index.html").read_bytes()).hexdigest(),
    "recovered_webapp_sha256": hashlib.sha256((root / "app" / "webapp.py").read_bytes()).hexdigest(),
    "playwright_present": importlib.util.find_spec("playwright") is not None,
    "release_ids": {k: v.release_id for k, v in releases.items()},
}, sort_keys=True))
"""

_BROWSER_SMOKE = r"""
import json
import threading
from playwright.sync_api import sync_playwright
from zaaggenz_timeline.server import TimelineServer

server = TimelineServer(0, 12000)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
base = f"http://127.0.0.1:{server.server_port}"
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        response = page.goto(base + "/timeline", wait_until="networkidle")
        assert response is not None and response.status == 200
        release = page.locator('meta[name="zaaggenz-web-release"]').get_attribute("content")
        assert release and len(release) == 64
        assert page.locator("body").count() == 1
        browser.close()
    print(json.dumps({"browser": "chromium", "timeline_release": release}, sort_keys=True))
finally:
    server.shutdown()
    server.server_close()
    thread.join(5)
"""


def verify(dist: Path, kind: str, constraints: Path, *, browser: bool) -> dict:
    artifact = _single_artifact(dist, kind)
    work = Path(tempfile.mkdtemp(prefix=f"zaaggenz-{kind}-"))
    try:
        env_dir = work / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(env_dir)
        python = _venv_python(env_dir)
        if browser:
            if kind != "wheel":
                raise RuntimeError("browser acceptance is intentionally wheel-only")
            spec = f"zaaggenz[browser] @ {artifact.as_uri()}"
        else:
            spec = str(artifact)
        _run(
            [python, "-m", "pip", "install", "-c", constraints.resolve(), spec],
            cwd=work,
            timeout=600,
        )
        smoke = _run([python, "-I", "-c", _SMOKE], cwd=work, timeout=180)
        payload = json.loads(smoke.stdout.strip().splitlines()[-1])
        if browser:
            _run(
                [python, "-m", "playwright", "install", "--with-deps", "chromium"],
                cwd=work,
                timeout=600,
            )
            result = _run([python, "-I", "-c", _BROWSER_SMOKE], cwd=work, timeout=180)
            payload["browser"] = json.loads(result.stdout.strip().splitlines()[-1])
        elif payload["playwright_present"]:
            raise RuntimeError("minimal built artifact unexpectedly installed Playwright")
        payload.update(
            artifact=artifact.name,
            artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
            artifact_bytes=artifact.stat().st_size,
            kind=kind,
        )
        return payload
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--kind", choices=("wheel", "sdist"), required=True)
    parser.add_argument("--constraints", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    report = verify(args.dist.resolve(), args.kind, args.constraints.resolve(), browser=args.browser)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
