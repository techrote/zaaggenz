# MBR-001: full-checkout CI reconciliation

This records the focused #239 / PR #248 corrections after initial head
`8c43bf5f6ce11c3c9605652f92d2c0a323567363`. The saved contract remains described
in `MBR001_EDITABLE_RACK.md`. This record does not accept MBR-002 runtime wiring,
MBR-004 built-in workflow acceptance or any Phase-B native hosting.

## Web-release protocol closure

Timeline run `36999922117`, Inspector run `36999922061`, studies run
`36999921989` and packaging run `36999922133` exposed the same concrete
startup error: the explicit web protocol manifest omitted three new modules.
The missing modules are `zaaggenz_contracts/rack.py`,
`zaaggenz_contracts/rack_schema.py` and `zaaggenz_project/rack_state.py`.
They are now registered in the existing contract/project protocol groups for
all four browser workspaces. The import audit, stale-client rejection and
execution-only classification are not weakened.

`tests/runtime/test_rack_protocol_identity.py` first reproduced the failure.
It now verifies that all three files participate in every workspace release,
that changing any one invalidates every affected release identity, and that
omitting any one still fails the audit and manifest construction. No audio or
factory identity is changed by this release-compatibility registration.

## Exact inherited evidence transition, not inverse-search research

The existing ZG-024a whole-implementation manifest includes contract, project
and spectral modules even when its fixtures have no rack. The added MBR-001
files therefore legitimately change that implementation identity. The frozen
calibration comparison correctly rejected the unregistered successor in run
`36999922414`, jobs `110815032264` (Ubuntu) and `110815031984` (Windows).

The exact pair is:

```text
from ff938e70ba2598d5f6f6f0bc305e01b580c373a8e5daca849e8d3f9392bee3a4
  to ae62e3d4a2faa405d0d5f6f1b6b7d79362118ec408634efa41ba1051d76b8aac
```

Before registration, both independent CI reports were downloaded, their archive
and report-envelope hashes verified, and their complete implementation manifests
compared with the corrected local checkout. They match exactly. Their portable
projections agree across platforms. Against the immutable calibration they
require only the implementation identity and the exact seven previously
reviewed #87 transient-v4 validation state/gate projections. Applying that
existing path/from/to list to this exact successor produces zero comparison
failures on both reports. No new numeric or semantic exemption is introduced.

| Platform | Artifact | Archive SHA-256 |
| --- | --- | --- |
| Ubuntu | `11223990077` | `c4e1549022cd33855cb5bba9bfebc5bb71f39bec45fb3976f69ed2af01ee6ba7` |
| Windows | `11223835998` | `0f836f6f73e1293f7359ae4f34827c2290df5f4f6e7b299f343cd4e0c321e58b` |

The new entries append to the existing implementation/validation transition
registries; every historical row is unchanged. The seven changes are copied
exactly from the accepted successor
`3d731d708e56611008532adaae091bb93d86f781935705623a344c2a887c1753`.
The calibration file itself remains SHA-256
`4dfde21014b1863177db5416c0b285c0c2648f579d0d418f80f0afd8506d2761`.
Objectives, scores, ranks, recipes, budgets, holdout objectives, comparison
tolerances, provenance checks and canonical programme states are not rewritten.

`tests/inverse/test_mbr001_transition.py` tests this exact registration and
rejects unlisted successors, wrong validation values, numeric/recipe drift and
tampered evidence hashes. Its positive fixture is explicitly a synthetic
comparator fixture, not replacement evidence. Actual cross-platform evidence
comes from the two CI artifacts above. The existing evidence and validation
transition regression suites also remain unchanged and pass.

## Source and local verification

A complete tracked checkout was recovered from this PR's existing Timeline CI
source artifact `11223057923`, run `36999922117`. The outer archive SHA-256 is
`58610e45b9871b8e8df505563742408b1f4d312eef1231f3c5ed09a3b578cfa7`.
The inner git-archive comment identifies the exact head above; reconstructing
its Git tree gives `bbca8ae39ef6dd70c511660ef9ee266dced7c2d9`, identical to the
published commit. This resolves the earlier reduced-sdist source limitation.
The authenticated materializer and full recovery tests now run locally.
Generated legacy app/cache files are not part of this corrective commit.

Local environment: Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0, jsonschema 4.26.0,
referencing 0.37.0 and threadpoolctl 3.6.0. Numerical threads are bounded to one;
`PYTHONPATH=app:.` is used for source-checkout execution. The package was
installed locally with `python -m pip install --no-deps --no-build-isolation -e .`
for installed-distribution packaging tests.

| Command (Python invocation unless noted) | Result |
| --- | --- |
| `-m unittest discover -s tests/runtime -p '*protocol_identity.py' -v` | 10 passed |
| `-m unittest discover -s tests/timeline -v` | 28 passed |
| `-m unittest discover -s tests -p test_recovery.py -v` | 8 passed |
| `tools/ci_reverse_dependencies.py --validate` | Passed |
| `-m unittest discover -s tests/programme -p test_ci_reverse_dependencies.py -v` | 9 passed |
| `-m unittest discover -s tests/packaging -v` | 19 passed after local editable installation |
| `-m unittest discover -s tests/studies -v` | 39 passed |
| `-m unittest discover -s tests/inverse -p test_mbr001_transition.py -v` | 4 passed |
| `-m unittest discover -s tests/inverse -p test_validation_transition.py -v` | 5 passed |
| `-m unittest discover -s tests/inverse -p test_evidence.py -v` | 8 passed |

The Inspector local run passed its two previously failing HTTP tests, but the
full suite exceeded the local command time limit during an analysis test. It
is not recorded as a local full-suite pass. Full exact-final-head CI, including
browser and installed-package regressions, remains mandatory before merge.
The previously passing 33-test rack suite and original numerical parity tests
are retained and rerun by their existing mapped CI owner, not bypassed here.
