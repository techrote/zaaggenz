from __future__ import annotations

import argparse
import json
import sys

from .runtime import MissingExtraError, external_tool_report, require_extra


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Report the canonical ZaagGenZ local environment")
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p.add_argument(
        "--check-extra",
        action="append",
        choices=("browser", "research"),
        default=[],
        help="require an optional feature dependency group",
    )
    p.add_argument(
        "--require-tool",
        action="append",
        choices=("ffmpeg", "ffprobe", "node"),
        default=[],
        help="fail if the named external executable is unavailable",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    errors: list[str] = []
    for extra in args.check_extra:
        try:
            require_extra(extra)
        except MissingExtraError as exc:
            errors.append(str(exc))
    report = external_tool_report()
    tools = report["external_tools"]
    for name in args.require_tool:
        if not tools[name]["available"]:
            errors.append(f"required external tool {name!r} is unavailable")
    report["checks"] = {"ok": not errors, "errors": errors}
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"ZaagGenZ package: {report['package']['source_version']}")
        print(f"Python: {report['python']['version']}")
        for name, row in tools.items():
            status = row["version"] if row["available"] else "unavailable"
            print(f"{name}: {status}")
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
