from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import importlib.metadata
import importlib.util
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Callable, Iterable

from ._version import VERSION

_DISTRIBUTION = "zaaggenz"
_AUDITED_DISTRIBUTIONS = (
    "numpy",
    "scipy",
    "threadpoolctl",
    "jsonschema",
    "referencing",
    "playwright",
    "build",
)
_EXTRA_MODULES: dict[str, tuple[str, ...]] = {
    "browser": ("playwright",),
    "research": ("numpy", "scipy"),
}


class MissingExtraError(RuntimeError):
    """Raised when an explicitly requested optional feature is unavailable."""


def package_identity() -> dict[str, object]:
    """Return source and installed distribution identity without guessing."""
    try:
        installed = importlib.metadata.version(_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        installed = None
    if installed is not None and installed != VERSION:
        raise RuntimeError(
            f"installed {_DISTRIBUTION} version {installed!r} disagrees with source version {VERSION!r}"
        )
    return {
        "distribution": _DISTRIBUTION,
        "source_version": VERSION,
        "installed_version": installed,
    }


def require_extra(
    extra: str,
    modules: Iterable[str] | None = None,
    *,
    finder: Callable[[str], object | None] | None = None,
) -> None:
    """Fail with an actionable extra-install diagnostic.

    No optional import is performed here. Callers use this at the boundary where
    a browser/research feature is explicitly requested, so ordinary local
    imports remain free of optional-only dependencies.
    """
    if not isinstance(extra, str) or not extra:
        raise ValueError("extra must be a non-empty string")
    required = tuple(_EXTRA_MODULES.get(extra, ()) if modules is None else modules)
    if not required:
        raise ValueError(f"unknown or dependency-free extra {extra!r}")
    probe = importlib.util.find_spec if finder is None else finder
    missing = tuple(name for name in required if probe(name) is None)
    if missing:
        joined = ", ".join(missing)
        raise MissingExtraError(
            f"ZaagGenZ optional feature {extra!r} is unavailable; missing module(s): {joined}. "
            f"Install with: python -m pip install -e '.[{extra}]'"
        )


@dataclass(frozen=True)
class _Tool:
    name: str
    path: str | None
    version: str | None
    available: bool
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _probe_tool(
    name: str,
    args: tuple[str, ...],
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> _Tool:
    path = which(name)
    if path is None:
        return _Tool(name, None, None, False)
    try:
        result = runner(
            [path, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _Tool(name, path, None, False, f"{type(exc).__name__}: {exc}")
    text = (result.stdout or result.stderr or "").strip().splitlines()
    version = text[0].strip() if text else None
    error = None if result.returncode == 0 else f"exit status {result.returncode}"
    return _Tool(name, path, version, result.returncode == 0, error)


def _distribution_metadata(name: str) -> dict[str, object]:
    try:
        metadata = importlib.metadata.metadata(name)
        version = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return {
            "distribution": name,
            "installed": False,
            "version": None,
            "license_expression": None,
            "license": None,
        }
    return {
        "distribution": name,
        "installed": True,
        "version": version,
        "license_expression": metadata.get("License-Expression"),
        "license": metadata.get("License"),
        "home_page": metadata.get("Home-page"),
    }


def external_tool_policy() -> dict[str, object]:
    """Return the generated machine-readable external executable policy."""
    path = Path(__file__).with_name("tool_policy.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("canonical external tool policy is unavailable") from exc
    if (
        type(value) is not dict
        or value.get("format") != "zaaggenz-external-tool-policy"
        or value.get("version") != "1.0.0"
        or type(value.get("tools")) is not dict
    ):
        raise RuntimeError("invalid canonical external tool policy")
    return value


def external_tool_report() -> dict[str, object]:
    """Record package/executable identities; never install, download or mutate."""
    tools = {
        "ffmpeg": _probe_tool("ffmpeg", ("-version",)).as_dict(),
        "ffprobe": _probe_tool("ffprobe", ("-version",)).as_dict(),
        "node": _probe_tool("node", ("--version",)).as_dict(),
    }
    dependencies = {
        name: _distribution_metadata(name)
        for name in _AUDITED_DISTRIBUTIONS
    }
    return {
        "format": "zaaggenz-environment-report",
        "version": "1.0.0",
        "package": package_identity(),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "python_distributions": dependencies,
        "external_tools": tools,
        "external_tool_policy": external_tool_policy(),
    }
