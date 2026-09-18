"""Content-bound web release identity and stale-frontend fail-closed helpers.

This module is intentionally independent of the audio/render stack.  It protects
only the local browser/backend compatibility boundary and must not alter DSP,
source PCM, project identity or research provenance semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

WEB_API_VERSION = "1.0.0"
RELEASE_HEADER = "X-Zaaggenz-Frontend-Release"
RELEASE_QUERY = "zg-release"
NO_STORE = "no-store, max-age=0, must-revalidate"
MISMATCH_MESSAGE = "frontend release mismatch; reload this workspace"

# Static material is exhaustive for the four accepted browser workspaces.  The
# shared timeline transport is part of the Compose frontend bundle even though
# its file lives one directory above the timeline assets.
_FRONTEND_PATHS = {
    "timeline": (
        "web/timeline/index.html",
        "web/timeline/app.mjs",
        "web/timeline/editor.mjs",
        "web/timeline/style.css",
        "web/jobs_transport.mjs",
    ),
    "listening": (
        "web/listening/index.html",
        "web/listening/app.mjs",
        "web/listening/style.css",
    ),
    "inspector": (
        "web/inspector/index.html",
        "web/inspector/app.mjs",
        "web/inspector/style.css",
    ),
    "vocal": (
        "web/vocal/index.html",
        "web/vocal/app.mjs",
        "web/vocal/editor.mjs",
        "web/vocal/style.css",
    ),
}

# Hash the HTTP protocol owner as backend material.  Sidecars inherit Timeline
# routes, so the Timeline server is intentionally part of their backend domain.
_BACKEND_PATHS = {
    "timeline": ("zaaggenz_timeline/server.py",),
    "listening": ("zaaggenz_timeline/server.py", "zaaggenz_listening/server.py"),
    "inspector": ("zaaggenz_timeline/server.py", "zaaggenz_inspector/server.py"),
    "vocal": ("zaaggenz_timeline/server.py", "zaaggenz_vocal/server.py"),
}
_HELPER_PATH = "zaaggenz_web_release/__init__.py"


@dataclass(frozen=True)
class WebReleaseIdentity:
    workspace: str
    api_version: str
    frontend_sha256: str
    backend_sha256: str
    release_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "format": "zaaggenz-web-release",
            "version": "1.0.0",
            "workspace": self.workspace,
            "api_version": self.api_version,
            "frontend_sha256": self.frontend_sha256,
            "backend_sha256": self.backend_sha256,
            "release_id": self.release_id,
        }


def _digest_paths(root: Path, paths: tuple[str, ...]) -> str:
    h = sha256()
    h.update(b"zaaggenz-content-set-v1\0")
    for rel in sorted(paths):
        data = (root / rel).read_bytes()
        encoded = rel.encode("utf-8")
        h.update(len(encoded).to_bytes(4, "big"))
        h.update(encoded)
        h.update(len(data).to_bytes(8, "big"))
        h.update(data)
    return h.hexdigest()


def build_web_releases(root: Path, *, unified_runtime: bool = False) -> dict[str, WebReleaseIdentity]:
    """Build deterministic identities from the bytes that define each web/API pair.

    The unified runtime contributes its own route owner to every workspace's
    backend digest.  Therefore a runtime protocol edit invalidates already-open
    pages even when an individual workspace's static files did not change.
    """
    root = Path(root).resolve()
    out: dict[str, WebReleaseIdentity] = {}
    for workspace in sorted(_FRONTEND_PATHS):
        frontend = _digest_paths(root, _FRONTEND_PATHS[workspace])
        backend_paths = list(_BACKEND_PATHS[workspace]) + [_HELPER_PATH]
        if unified_runtime:
            backend_paths.append("zaaggenz_runtime/server.py")
        backend = _digest_paths(root, tuple(backend_paths))
        h = sha256()
        h.update(b"zaaggenz-web-release-v1\0")
        for value in (workspace, WEB_API_VERSION, frontend, backend):
            raw = value.encode("ascii")
            h.update(len(raw).to_bytes(4, "big"))
            h.update(raw)
        out[workspace] = WebReleaseIdentity(
            workspace=workspace,
            api_version=WEB_API_VERSION,
            frontend_sha256=frontend,
            backend_sha256=backend,
            release_id=h.hexdigest(),
        )
    return out


def cache_headers(release: WebReleaseIdentity) -> dict[str, str]:
    return {
        "Cache-Control": NO_STORE,
        "Pragma": "no-cache",
        "Expires": "0",
        "X-Content-Type-Options": "nosniff",
        "X-Zaaggenz-API-Version": release.api_version,
        RELEASE_HEADER: release.release_id,
    }


def requested_release_id(request_target: str) -> str | None:
    values = parse_qs(urlparse(request_target).query, keep_blank_values=True).get(RELEASE_QUERY)
    if not values:
        return None
    return values[-1]


def asset_request_matches(request_target: str, release: WebReleaseIdentity) -> bool:
    requested = requested_release_id(request_target)
    return requested is None or requested == release.release_id


def fingerprint_html(raw: bytes, release: WebReleaseIdentity, url_prefix: str) -> bytes:
    """Return no-store HTML whose first-party JS/CSS URLs bind this release."""
    text = raw.decode("utf-8")
    marker = f'<meta name="zaaggenz-web-release" content="{release.release_id}"><meta name="zaaggenz-api-version" content="{release.api_version}">'
    if "</head>" in text:
        text = text.replace("</head>", marker + "</head>", 1)
    for name in ("app.mjs", "style.css"):
        url = f"{url_prefix}/{name}"
        text = text.replace(url, f"{url}?{RELEASE_QUERY}={release.release_id}")
    return text.encode("utf-8")


def _fingerprint_relative_imports(source: str, release: WebReleaseIdentity) -> str:
    # Top-level app modules import only local first-party modules.  Binding those
    # imports prevents a stale editor/transport module from being paired with a
    # current entry module even under an aggressively retained browser cache.
    pattern = re.compile(r"(?P<prefix>\bfrom\s+['\"])(?P<path>\./[^'\"?]+)(?P<suffix>['\"])")
    return pattern.sub(
        lambda m: f"{m.group('prefix')}{m.group('path')}?{RELEASE_QUERY}={release.release_id}{m.group('suffix')}",
        source,
    )


def instrument_entry_module(raw: bytes, release: WebReleaseIdentity) -> bytes:
    """Bind browser mutations to the exact JS/backend release that issued them."""
    source = _fingerprint_relative_imports(raw.decode("utf-8"), release)
    rid = json.dumps(release.release_id)
    api = json.dumps(release.api_version)
    header = json.dumps(RELEASE_HEADER)
    prelude = f"""// zaaggenz web-release gate; injected by the local server.\nconst __zgReleaseId={rid},__zgApiVersion={api};\nif(typeof window!=='undefined'&&typeof window.fetch==='function'){{\n  const __zgNativeFetch=window.fetch.bind(window);\n  window.__ZAAGGENZ_WEB_RELEASE__=Object.freeze({{release_id:__zgReleaseId,api_version:__zgApiVersion}});\n  window.fetch=(input,init=undefined)=>{{\n    const request=(typeof Request!=='undefined'&&input instanceof Request)?input:null;\n    const method=String((init&&init.method)||(request&&request.method)||'GET').toUpperCase();\n    let url;try{{url=new URL(request?request.url:String(input),window.location.href);}}catch(_e){{return __zgNativeFetch(input,init);}}\n    if(url.origin===window.location.origin&&!['GET','HEAD','OPTIONS'].includes(method)){{\n      const headers=new Headers(request?request.headers:undefined);\n      if(init&&init.headers)new Headers(init.headers).forEach((value,key)=>headers.set(key,value));\n      headers.set({header},__zgReleaseId);\n      init={{...(init||{{}}),headers}};\n    }}\n    return __zgNativeFetch(input,init);\n  }};\n}}\n"""
    return (prelude + source).encode("utf-8")


def browser_mutation_requires_release(headers) -> bool:
    """Distinguish browser-originated requests from headless/API clients.

    Existing local API clients remain compatible. Browsers expose Origin and/or
    Fetch Metadata, while the repaired frontend also sends RELEASE_HEADER.
    """
    return any(
        headers.get(name) is not None
        for name in ("Origin", "Sec-Fetch-Site", "Sec-Fetch-Mode", RELEASE_HEADER)
    )


def frontend_release_matches(headers, release: WebReleaseIdentity) -> bool:
    if not browser_mutation_requires_release(headers):
        return True
    supplied = headers.get(RELEASE_HEADER)
    return supplied == release.release_id


__all__ = [
    "WEB_API_VERSION",
    "RELEASE_HEADER",
    "RELEASE_QUERY",
    "NO_STORE",
    "MISMATCH_MESSAGE",
    "WebReleaseIdentity",
    "build_web_releases",
    "cache_headers",
    "asset_request_matches",
    "fingerprint_html",
    "instrument_entry_module",
    "browser_mutation_requires_release",
    "frontend_release_matches",
]
