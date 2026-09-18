# Canonical package and environment

Issue #103 established the package/environment prerequisite for ZG-045; corrective #203 hardens workflow-install enforcement and built-artifact acceptance. Neither declares ZG-045 complete or publishes a product release.

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
| build | test/dev build frontend `>=1.6,<1.7`; CI `1.6.1` | constructs audited wheel/sdist artifacts; never ordinary runtime |
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
`--with-deps chromium` on a clean Linux CI host). For development convenience, `.[dev]` includes browser tooling plus the build frontend. For bounded research setup, use `.[research]`.

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

Active workflow install policy is checked **per pip install command**, not by a file-wide marker. Direct third-party requirements must be declared by `pyproject.toml`, use the canonical exact CI pin, and consume `constraints/ci.txt` directly or through a generated requirement view. Bare/ranged canonical packages, undeclared packages, unreviewed requirement/constraint files, URLs/VCS installs and ambiguous install options fail closed. Thus one canonical command cannot authorize a second rogue command in the same workflow.

The ZG-001 recovery workflow is the only exception: its historical command may directly install exactly the recorded NumPy/SciPy CI pins and nothing else. This preserves recovery evidence without turning the exception into a general dependency escape hatch.

## Built-artifact acceptance

Corrective #203 closes the editable-install blind spot. After the authenticated v1.2.1 runtime is materialized, the packaging workflow builds an sdist and a wheel (the wheel is built through the sdist path by the standard `build` frontend). Setuptools namespace discovery intentionally includes `app*` and `web*`: this packages the already-authenticated recovered runtime files plus the tracked first-party web workspaces without copying or rewriting their bytes.

`tools/artifact_acceptance.py` installs each artifact into a fresh temporary venv, removes `PYTHONPATH`, runs Python in isolated `-I` mode from outside the checkout, validates required installed `app/` and `web/` material, exercises contracts and Timeline/unified server construction, and records the artifact SHA-256. Minimal artifact installs must not acquire Playwright. A separate Ubuntu acceptance installs the built wheel's `browser` extra and opens the installed Timeline surface in real Chromium. Wheel and sdist acceptance runs on Windows and Ubuntu for core/package coverage.

The built artifacts are still programme/pre-release evidence, not an approved public release. ZG-045/#46 retains responsibility for launcher/archive shape, rights exclusions, project licensing, release notes and explicit publication approval.

## Optional-feature diagnostics

Optional features fail at their feature boundary rather than contaminating
ordinary imports. `zaaggenz_environment.require_extra("browser")` and
`require_extra("research")` produce an explicit install command when their
modules are unavailable. The core environment has no Playwright dependency.

## External executables

`python -m zaaggenz_environment.cli --json` records Python/package identities, installed dependency licence metadata when exposed by package metadata, the detected `ffmpeg`, `ffprobe` and `node` executable/version strings, and the generated `zaaggenz-external-tool-policy/1.0.0`. Node is a `test-dev` tool with supported range `>=22 <25` and CI major 22. ffmpeg/ffprobe are optional, feature-owned reference-audit tools with `record-only` version policy: the exact detected binary is evidence for a run, not a fabricated universal support range. Missing external tools are reported as unavailable; they are not silently downloaded. Use `--require-tool ffmpeg` / `ffprobe` / `node` only in a workflow that actually requires that executable.

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
