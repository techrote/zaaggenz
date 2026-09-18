"""Canonical package/environment metadata for ZaagGenZ.

This module is deliberately standard-library-only so environment diagnostics
remain available before optional tooling is installed.
"""
from ._version import VERSION
from .runtime import (
    MissingExtraError,
    external_tool_report,
    package_identity,
    require_extra,
)

__version__ = VERSION

__all__ = [
    "VERSION",
    "__version__",
    "MissingExtraError",
    "external_tool_report",
    "package_identity",
    "require_extra",
]
