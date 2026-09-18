# Canonical package and environment

Issue #103 establishes the package/environment prerequisite for ZG-045. It does
**not** declare ZG-045 complete or publish a product release.

## Authority and identities

`pyproject.toml` is the authoritative Python package/dependency declaration.
`tools/sync_environment.py` derives the exact CI constraint file, legacy root
requirement views, research requirement view and the Node engine declaration.
CI runs `python tools/sync_environment.py --check`; generated files are not
independent sources of truth.

The repository package version is currently `0.1.0.dev0`. This is a pre-release
identity for the post-v1.2.1 programme package, **not** a relabelling of the
authenticated recovered v1.2.1 source. `baseline/recovered_source/README.md`
and its recorded hashes remain the provenance authority for that compatibility
input.

The #102 web-release identity remains the content-derived frontend/backend
handshake. The canonical package version is independently consumable via
`zaaggenz_environment.VERSION` or `importlib.metadata.version("zaaggenz")` and
is reserved for ZG-045 release output; this repair does not reinterpret the
accepted #102 content hashes.

## Supported environment

| Surface | Supported / canonical state | Why it is present |
| --- | --- | --- |
| Python | `>=3.13,<3.14`; CI uses 3.13 | all current accepted Python workflows are on the 3.13 line |
| NumPy | supported `>=2.3,<2.4`; CI `2.3.5` | runtime DSP/analysis and recovered baseline compatibility |
| SciPy | supported `>=1.17,<1.18`; CI `1.17.0` | runtime signal processing |
| threadpoolctl | supported `>=3.6,<4`; CI `3.6.0` | bounded numerical worker ownership |
| jsonschema | supported `>=4.26,<5`; CI `4.26.0` | executable Draft 2020-12 contract validation |
| referencing | supported `>=0.37,<0.38`; CI `0.37.0` | local-only JSON-Schema reference registry |
| Playwright | browser/dev extra `>=1.57,<1.58`; CI `1.57.0` | real-Chromium acceptance only; never ordinary runtime |
| Node | `>=22 <25`; canonical new-CI major 22 | contract/browser helper scripts; not Python runtime |
| ffmpeg/ffprobe | external, version-probed when present | private/reference audit paths; never installed by pip |

Historical accepted workflows used both Node 22 and 24. Both are inside the
explicit supported test-tool range; new environment validation uses Node 22.
The recovered v1.2.1 application itself declared `numpy>=2.0` and
`scipy>=1.14`. Those historical requirements remain evidence about the
recovered payload, not the dependency authority for the evolved repository.

`research` is a distinct optional dependency group even though its current
Python requirements are the same NumPy/SciPy numerical stack already required
by runtime modules. New research-only libraries must be added to that group
instead of becoming runtime dependencies by convenience. Historical
`research/**/requirements*.txt` evidence is never regenerated; the checker only
verifies that any exact canonical-package pins recorded there have not drifted.

## Fresh checkout

From the repository root:

```text
python baseline/recovered_source/materialize_v2.py --out .
python -m venv .venv
# activate .venv using the platform's normal command
python -m pip install -c constraints/ci.txt -e .
python -m zaaggenz_environment.cli --json
python -m zaaggenz_runtime --no-browser
```

For contract/test work use `-e ".[test]"`; for browser acceptance use
`-e ".[browser]"` followed by `python -m playwright install chromium` (or
`--with-deps chromium` on a clean Linux CI host). For development convenience,
`.[dev]` currently includes the browser tooling. For bounded research setup,
use `.[research]`.

The runtime remains loopback/offline. Package installation does not add a cloud
service, telemetry service, model download or GPU requirement. Browser binaries
are an explicit developer/acceptance action and are not needed for ordinary
local runtime operation.

## Range and pin policy

Supported ranges live in PEP 621 dependency metadata. Exact accepted CI
versions live alongside them under `[tool.zaaggenz.environment.ci-pins]`.
`constraints/ci.txt` is generated from those exact pins. This deliberately
separates “versions the package supports” from “versions used to reproduce an
accepted CI run.”

To update a dependency:

1. change the supported range and/or exact pin in `pyproject.toml`;
2. run `python tools/sync_environment.py`;
3. review the generated diff;
4. run `python tools/sync_environment.py --check`;
5. run the affected numerical, contract, browser or research gates on Windows
   and Ubuntu before accepting the update.

Legacy workflows may retain redundant exact version text for evidentiary
readability, but their root requirement fragments now consume
`constraints/ci.txt`, and the sync checker rejects any conflicting inline
NumPy/SciPy/threadpoolctl/jsonschema/referencing/Playwright pin. The ZG-001
recovery workflow is the deliberate exception: it retains its recorded
baseline-install command as provenance evidence, while the checker still
requires its NumPy/SciPy pins to agree with the accepted canonical CI pins.

## Optional-feature diagnostics

Optional features fail at their feature boundary rather than contaminating
ordinary imports. `zaaggenz_environment.require_extra("browser")` and
`require_extra("research")` produce an explicit install command when their
modules are unavailable. The core environment has no Playwright dependency.

## External executables

`python -m zaaggenz_environment.cli --json` records Python/package identities,
installed dependency licence metadata when exposed by package metadata, and
the detected `ffmpeg`, `ffprobe` and `node` executable/version strings. Missing
external tools are reported as unavailable; they are not silently downloaded.
Use `--require-tool ffmpeg` / `ffprobe` / `node` only in a workflow that
actually requires that executable.

The historical preflight recorded FFmpeg `7.1.5-0+deb13u1`; that is evidence
for that run, not a universal runtime pin. FFmpeg redistribution/licensing is
build-configuration dependent, so ZG-045 must audit the exact binary if a
future release bundles one. This repository does not bundle one here.

## Licence and provenance audit boundary

Dependency licence information is traceable in two places: the inventory in
`docs/packaging/DEPENDENCIES_AND_LICENCES.md`, and the installed-distribution
metadata captured by the environment report. The latter is evidence for the
exact installed wheels and is preferred when static prose and package metadata
differ.

No repository-level licence file existed when #103 was investigated. This
repair therefore makes **no invented project licence claim** in PEP 621
metadata. ZG-045 must resolve project-level redistribution terms before any
public package publication. That release-policy blocker is separate from the
authenticated v1.2.1 source provenance and from third-party dependency
licences.

## What this repair does not change

It does not change PCM, DSP topology/order, tuning, phase/reset/tail semantics,
source preservation, protected presets, master policy, project/artifact
identity, reference rights, or research provenance. The recovered payload is
still materialized and hash-checked as a separate compatibility input.
