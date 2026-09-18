"""Content-bound web release identity and stale-frontend fail-closed helpers.

This module is intentionally independent of the audio/render stack.  It protects
only the local browser/backend compatibility boundary and must not alter DSP,
source PCM, project identity or research provenance semantics.
"""
from __future__ import annotations

import ast
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

# Backend release identity is a deliberately bounded protocol manifest.  It
# includes complete first-party protocol packages for each workspace, but not
# execution-only DSP/analysis packages whose byte changes do not alter the
# browser request/response contract.  New cross-package dependencies fail the
# audit below until explicitly classified.
_CONTRACT_PROTOCOL_PATHS = (
    "zaaggenz_contracts/__init__.py",
    "zaaggenz_contracts/audio_schema.py",
    "zaaggenz_contracts/legacy.py",
    "zaaggenz_contracts/legacy_spec.py",
    "zaaggenz_contracts/model.py",
    "zaaggenz_contracts/multiband.py",
    "zaaggenz_contracts/music.py",
    "zaaggenz_contracts/music_schema.py",
    "zaaggenz_contracts/ownership.py",
    "zaaggenz_contracts/recipe_schema.py",
    "zaaggenz_contracts/registry.py",
    "zaaggenz_contracts/schema.py",
    "zaaggenz_contracts/tuning_rules.py",
    "zaaggenz_contracts/validation.py",
)
_JOB_PROTOCOL_PATHS = (
    "zaaggenz_jobs/__init__.py",
    "zaaggenz_jobs/api.py",
    "zaaggenz_jobs/memory.py",
    "zaaggenz_jobs/model.py",
    "zaaggenz_jobs/numeric_runtime.py",
    "zaaggenz_jobs/scheduler.py",
)
_PROJECT_PROTOCOL_PATHS = (
    "zaaggenz_project/__init__.py",
    "zaaggenz_project/cache.py",
    "zaaggenz_project/project.py",
)
_TIMELINE_PROTOCOL_PATHS = (
    "zaaggenz_timeline/__init__.py",
    "zaaggenz_timeline/model.py",
    "zaaggenz_timeline/server.py",
    "zaaggenz_timeline/service.py",
)
_LISTENING_PROTOCOL_PATHS = (
    "zaaggenz_listening/__init__.py",
    "zaaggenz_listening/archive.py",
    "zaaggenz_listening/model.py",
    "zaaggenz_listening/server.py",
    "zaaggenz_listening/service.py",
    "zaaggenz_listening/stimulus.py",
    "zaaggenz_listening/trial.py",
)
_INSPECTOR_PROTOCOL_PATHS = (
    "zaaggenz_inspector/__init__.py",
    "zaaggenz_inspector/model.py",
    "zaaggenz_inspector/server.py",
    "zaaggenz_inspector/service.py",
)
_VOCAL_PROTOCOL_PATHS = (
    "zaaggenz_vocal/__init__.py",
    "zaaggenz_vocal/analysis.py",
    "zaaggenz_vocal/edit.py",
    "zaaggenz_vocal/model.py",
    "zaaggenz_vocal/server.py",
    "zaaggenz_vocal/service.py",
    "zaaggenz_vocal/store.py",
)
_TEXTGESTURE_PROTOCOL_PATHS = (
    "zaaggenz_textgesture/__init__.py",
    "zaaggenz_textgesture/bundle.py",
    "zaaggenz_textgesture/compile.py",
    "zaaggenz_textgesture/model.py",
    "zaaggenz_textgesture/presets.py",
    "zaaggenz_textgesture/syntax.py",
)
_UNIFIED_RUNTIME_PATHS = (
    "zaaggenz_runtime/__init__.py",
    "zaaggenz_runtime/server.py",
    "zaaggenz_runtime/session.py",
)
_COMMON_PROTOCOL_PATHS = (
    _CONTRACT_PROTOCOL_PATHS
    + _JOB_PROTOCOL_PATHS
    + _PROJECT_PROTOCOL_PATHS
    + _TIMELINE_PROTOCOL_PATHS
)
_BACKEND_PATHS = {
    "timeline": _COMMON_PROTOCOL_PATHS,
    "listening": _COMMON_PROTOCOL_PATHS + _LISTENING_PROTOCOL_PATHS,
    "inspector": _COMMON_PROTOCOL_PATHS + _INSPECTOR_PROTOCOL_PATHS,
    "vocal": _COMMON_PROTOCOL_PATHS + _VOCAL_PROTOCOL_PATHS + _TEXTGESTURE_PROTOCOL_PATHS,
}
_PROTOCOL_PACKAGES = {
    "timeline": frozenset(("zaaggenz_contracts", "zaaggenz_jobs", "zaaggenz_project", "zaaggenz_timeline")),
    "listening": frozenset(("zaaggenz_contracts", "zaaggenz_jobs", "zaaggenz_project", "zaaggenz_timeline", "zaaggenz_listening")),
    "inspector": frozenset(("zaaggenz_contracts", "zaaggenz_jobs", "zaaggenz_project", "zaaggenz_timeline", "zaaggenz_inspector")),
    "vocal": frozenset(("zaaggenz_contracts", "zaaggenz_jobs", "zaaggenz_project", "zaaggenz_timeline", "zaaggenz_vocal", "zaaggenz_textgesture")),
}
_EXECUTION_ONLY_PACKAGES = {
    "timeline": frozenset(("zaaggenz_melody", "zaaggenz_tuning")),
    "listening": frozenset(("zaaggenz_melody", "zaaggenz_tuning")),
    "inspector": frozenset(("zaaggenz_melody", "zaaggenz_tuning", "zaaggenz_components", "zaaggenz_spectral")),
    "vocal": frozenset(("zaaggenz_melody", "zaaggenz_tuning", "zaaggenz_analysis", "zaaggenz_gesture")),
}
_HELPER_PATH = "zaaggenz_web_release/__init__.py"


def _module_file(root: Path, module: str) -> str | None:
    base = root.joinpath(*module.split("."))
    direct = base.with_suffix(".py")
    if direct.is_file():
        return direct.relative_to(root).as_posix()
    package = base / "__init__.py"
    if package.is_file():
        return package.relative_to(root).as_posix()
    return None


def _import_modules(root: Path, relative_path: str) -> tuple[str, ...]:
    path = root / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative_path)
    file_parts = list(Path(relative_path).with_suffix("").parts)
    package_parts = file_parts[:-1]
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                up = node.level - 1
                base = package_parts[: max(0, len(package_parts) - up)]
                if node.module:
                    base += node.module.split(".")
                module = ".".join(base)
            else:
                module = node.module or ""
            if node.module is None and module:
                # "from . import child" may refer to a submodule or a symbol.
                for alias in node.names:
                    candidate = module + "." + alias.name
                    out.append(candidate if _module_file(root, candidate) else module)
            elif module:
                out.append(module)
    return tuple(out)


def protocol_dependency_errors(root: Path, *, workspace: str | None = None,
                               unified_runtime: bool = False) -> tuple[str, ...]:
    """Audit the bounded web protocol manifest and classify new dependencies.

    Every first-party import reached from declared protocol material must either
    be part of that workspace's protocol identity or be explicitly classified
    as execution-only.  Unknown first-party dependencies fail closed.
    """
    root = Path(root).resolve()
    names = (workspace,) if workspace is not None else tuple(sorted(_BACKEND_PATHS))
    errors: list[str] = []
    for name in names:
        if name not in _BACKEND_PATHS:
            errors.append(f"unknown web workspace: {name}")
            continue
        paths = set(_BACKEND_PATHS[name])
        for rel in sorted(paths):
            path = root / rel
            if not path.is_file():
                errors.append(f"{name}: missing protocol dependency {rel}")
                continue
            try:
                modules = _import_modules(root, rel)
            except (OSError, SyntaxError, UnicodeError) as exc:
                errors.append(f"{name}: cannot audit {rel}: {type(exc).__name__}: {exc}")
                continue
            for module in modules:
                if not module.startswith("zaaggenz_"):
                    continue
                package = module.split(".", 1)[0]
                if package == "zaaggenz_web_release":
                    continue
                if package in _PROTOCOL_PACKAGES[name]:
                    target = _module_file(root, module)
                    if target is not None and target not in paths:
                        errors.append(
                            f"{name}: imported protocol module {module} from {rel} is absent from manifest ({target})"
                        )
                elif package not in _EXECUTION_ONLY_PACKAGES[name]:
                    errors.append(
                        f"{name}: unclassified first-party dependency {package} imported by {rel}"
                    )

    if unified_runtime:
        runtime_paths = set(_UNIFIED_RUNTIME_PATHS)
        allowed = frozenset().union(*_PROTOCOL_PACKAGES.values()) | {
            "zaaggenz_runtime", "zaaggenz_web_release"
        }
        execution = frozenset().union(*_EXECUTION_ONLY_PACKAGES.values())
        for rel in sorted(runtime_paths):
            path = root / rel
            if not path.is_file():
                errors.append(f"runtime: missing protocol dependency {rel}")
                continue
            try:
                modules = _import_modules(root, rel)
            except (OSError, SyntaxError, UnicodeError) as exc:
                errors.append(f"runtime: cannot audit {rel}: {type(exc).__name__}: {exc}")
                continue
            for module in modules:
                if not module.startswith("zaaggenz_"):
                    continue
                package = module.split(".", 1)[0]
                if package == "zaaggenz_runtime":
                    target = _module_file(root, module)
                    if target is not None and target not in runtime_paths:
                        errors.append(
                            f"runtime: imported runtime protocol module {module} is absent from manifest ({target})"
                        )
                elif package not in allowed and package not in execution:
                    errors.append(f"runtime: unclassified first-party dependency {package} imported by {rel}")
    return tuple(sorted(set(errors)))


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
    errors = protocol_dependency_errors(root, unified_runtime=unified_runtime)
    if errors:
        raise RuntimeError("web release protocol dependency audit failed: " + "; ".join(errors))
    out: dict[str, WebReleaseIdentity] = {}
    for workspace in sorted(_FRONTEND_PATHS):
        frontend = _digest_paths(root, _FRONTEND_PATHS[workspace])
        backend_paths = list(_BACKEND_PATHS[workspace]) + [_HELPER_PATH]
        if unified_runtime:
            backend_paths.extend(_UNIFIED_RUNTIME_PATHS)
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
    "protocol_dependency_errors",
]
