# NYQ-001 — inherited CI provenance reconciliation

Scope: #250 / PR #260. This records an observed compatibility transition, not
Nyquismic audio acceptance, a new baseline, or a relaxed comparison policy.
Read [the foundation](NYQ001_FOUNDATION.md) for the actual opt-in capability.

## Failure observed before registration

Initial PR head `c7ff7aa673064a742179fa5d83fa02cb6be30489` contains the two new
standalone contract/clock modules. ZG-002 contract and inherited-baseline jobs
passed on Ubuntu and Windows. ZG-024a run **37020619565** completed its inverse,
prerequisite and browser regressions, then failed calibration on both platforms.
The failure was an unregistered implementation identity plus the **same seven**
#87 transient-v4 validation-state/gate changes already registered for accepted
main. No additional numerical, recipe, search or eligibility delta was reported.

The inverse manifest intentionally hashes all Python files in its declared
implementation packages, even modules not imported by inverse rendering. Do not
change that hashing policy to exclude this feature. Manifest identity before the
addition was `ae62e3d4a2faa405d0d5f6f1b6b7d79362118ec408634efa41ba1051d76b8aac`;
afterward it is
`b7109aba50744f0e192e26670d28790c17ff7c8716d5e7c63ece15ab88795ede`.

Both actual platform artifacts have identical implementation manifests, matching
the tested local source. Removing exactly these two entries yields the accepted
main manifest identity, with no inherited source entry changed:

| Added source | SHA-256 of LF-normalized source bytes |
|---|---|
| `zaaggenz_contracts/nyquismic.py` | `60be0547faba711ad93555fa3747bb5a5ad8bcc9ff1637f330f9350fde41584d` |
| `zaaggenz_contracts/nyquismic_clock.py` | `631f6d465337e433e4ce54404526bf21f3ce2dcfde83c06ba33ac7a133585330` |

The immutable calibration remains
`examples/zg024a_inverse_calibration.json.gz`, file SHA-256
`4dfde21014b1863177db5416c0b285c0c2648f579d0d418f80f0afd8506d2761`.
Its original implementation identity remains
`ff938e70ba2598d5f6f6f0bc305e01b580c373a8e5daca849e8d3f9392bee3a4`.

## Actual evidence inspected before the append

Both artifacts belong to **run 37020619565 at exact head c7ff7aa**; archive and
member hashes were verified before comparison. Each contains six fixture cases,
36 candidates and the complete implementation manifest and replay/audit records.

| Platform / artifact ID | Archive SHA-256 |
|---|---|
| Ubuntu / `11232444848` | `3b5f6cab6c1f5b1be6082eba506bfdafc5f1519850661aabbae64d29b34eebf5` |
| Windows / `11232890675` | `47a6a6b3bc52649b70f95901090bb90ed1fa108c8f8a302b534c8ecba226bf0d` |

| Evidence member | Ubuntu SHA-256 | Windows SHA-256 |
|---|---|---|
| `inverse-evidence.json` file | `21dcfdfde6dc6ba205c83d35cfec4064b137c2acd3ee661dd89d934eb8893226` | `39dad9dc0e06967363807329f89e120d47f7fc62b9d9cae042f3a682d98d9b86` |
| Report internal `evidence_sha256` | `7f880e5812140ef484498cc1de99b408f73d3c5624066886052c195323e1ffcc` | `c6c93b7739699a8c9830cd1b2e269aa9890de0ab5419ed24e61f78c3a168529d` |
| `inverse-full.json` file | `86ec94965ebe4536a54f77cd2c36a9efd9e610a0ad0f6aec48c173939d893008` | `8036d02645b7a3cc76798f15db991c98329409f7b230b5016f4478ffd8de395e` |

For each artifact, `calibration_reference(report)` was compared with the original
compressed calibration using the unchanged `compare_reports`. With the original
registries, both platforms produce exactly eight failures: the implementation
identity and the seven existing state/gate changes. A candidate registration of
only that exact successor and those same seven changes yields **zero failures**.
This comparison was performed before the checked-in registry append.

Cross-platform comparison of those actual calibration projections also produces
zero failures. Their byte content and evidence identities are **not identical**;
this does not establish bitwise cross-platform floating-point/audio equivalence.
The original inverse tolerances remain **absolute 1e-7, relative 1e-5**. These
are separate from the new Nyquismic clock fixture tolerance and are not widened.

The seven allowed JSON paths remain exactly those of the previously accepted
`ae62e3d...` validation transition:

```text
/fixtures/0/candidates/8/holdout/validation/0/state
/fixtures/0/candidates/8/holdout/validation/0/triggered_gates
/fixtures/4/candidates/0/holdout/validation/0/triggered_gates
/fixtures/4/candidates/0/whole_signal/validation/0/state
/fixtures/4/candidates/0/whole_signal/validation/0/triggered_gates
/fixtures/4/candidates/1/whole_signal/validation/0/state
/fixtures/4/candidates/1/whole_signal/validation/0/triggered_gates
```

Both `from` and `to` values are carried forward verbatim. No score, objective,
recipe, rank, budget, threshold, eligible flag or protected source is adjusted.

## Repair and adversarial checks

Append one exact #250 successor to each existing implementation/validation
transition registry, preserving all original rows and their compact encoding.
No comparator, runtime, renderer, registry reader, source manifest policy or
compressed calibration file changes. This narrow evidence append was coordinated
with #240; it grants no ownership of its render/runtime/API/export surfaces.

`tests/inverse/test_nyq001_transition.py` verifies the unique successor and exact
changed paths, unchanged seven validation deltas, rejection of unlisted successors
and unreviewed states, rejection of numerical/recipe drift and tampered evidence,
and preservation of all preexisting registry rows. Its synthetic comparator
fixture is explicitly **not** replacement render evidence. All 14 existing/new
transition tests pass locally; the real platform artifact comparison above is
what justifies the metadata, not a synthetic fixture alone.

A later implementation, including #240, must obtain its own exact successor and
actual evidence. Do not reuse `b7109aba...` for different source or infer universal
compatibility from this registration. Historical calibration and transition rows
remain frozen; unknown successors still fail closed.

## Reproduction and final merge gate

Use the existing ZG-024a workflow commands and pinned numerical environment:

```sh
python -m unittest discover -s tests/inverse -p '*transition*.py' -v
python tools/inverse_foundation_report.py \
  --out inverse-evidence.json --full-out inverse-full.json \
  --telemetry-out inverse-timing.json \
  --check examples/zg024a_inverse_calibration.json.gz \
  --implementation-transitions examples/zg024a_implementation_transitions.json \
  --validation-transitions examples/zg024a_validation_transitions.json
```

The existing native workflow already owns both metadata files and the new inverse
test path; no new workflow, dependency, private runner or manual duplicate job is
needed. Exact-final-head native and reverse checks must pass **after** this repair,
and main must be verified after merge, before #250 can be accepted or #251 begun.
The initial-head artifacts support the narrow provenance decision; they are not a
substitute for final-head CI. This record makes no claim that PR #260 has merged.


## Continuation: sampler read-admission correction

Review of candidate `3ad7de65190f11b94e2c601508c081abada3577d` reproduced a
source-read admission defect: a sampler at 2 Hz with `max_read_s=1` admitted a
three-second plan, while the equivalent playback map rejected. Corrective
commit **`12dc6a68547e38e5a0b0335c08dcc2cbc2ab22fe`**, tree
`d171c944832816fcb833a2632e7995aeca0d9cde`, applies the existing unprojected
source-time authority to every stage before constructing its ClockPlan. Six
regressions cover the equality/fractional boundary, nonzero clock/source origins,
latent bypass/zero wet, independent stereo, cascade stages, preallocation and
preserved playback speed/loop projection. The corrected foundation/validation
docs specify the same finite limit; no event-geometry or sonic-schema change.

The amended contract suite passes **58 Nyquismic / 243 total contract tests**.
As a negative control, executing these tests against the authenticated pre-fix
module in memory yields eight failing subtests across five new methods, without
errors. The sixth preserves playback semantics. All 17 contract-check commands,
33 rack, 21 CI-routing and 10 runtime-protocol identity tests pass locally.
The frozen oracle generator, analytic data and legacy anchor bytes are unchanged.

Only `zaaggenz_contracts/nyquismic_clock.py` changes in the preceding NYQ
implementation manifest. Its LF-normalized source SHA-256 becomes
`a47027c1a9c75e1851a4a9d52aa9607580de082b8d83a87391b26a1949c5a196`;
all other entries, including `nyquismic.py`, stay byte-identical. Replacing this
one entry with its previous hash reconstructs `b7109aba...` exactly. Removing the
two NYQ entries still reconstructs accepted main's `ae62e3d...` manifest.
The corrected implementation identity is
**`f562faec6d279b090ff0da28b7c73fc24082d875e2fa3d9c87cc50d95072bcd3`**.
The original compressed calibration and its `ff938e70...` identity remain frozen.

### New actual evidence, inspected before registration

Existing ZG-024a run **37027834283** checked exact head `12dc6a6`. Both platform
reports below were downloaded and their ZIP/member/report identities verified
before appending any new registration. Their complete implementation manifests
match each other and the tested local source exactly. Each contains all six
fixtures and 36 candidates, with complete replay records, not a fabricated
identity-substituted report.

| Platform / artifact ID | Archive SHA-256 |
|---|---|
| Ubuntu / `11236157190` | `4cc1e978723d2c82b874a943c3f1dca554e6f21ca5dc85403b0608b461c9845c` |
| Windows / `11236032532` | `36716413a912e4c83e989c8d05460434156dbfc486264000fb4710173ff3aa58` |

| Evidence member | Ubuntu SHA-256 | Windows SHA-256 |
|---|---|---|
| `inverse-evidence.json` file | `bac934e70fa9db2666a60f3a80044d85c088813e16effdb550a6dc58c90fc883` | `1044651fdef27e0b3d4e5e8610e104ddbd456bff25247c3439766ce61fba29b2` |
| `inverse-full.json` file | `8a9eb494df55cc0d445e77656a75bc7618e334c3928419c80ae2fda798dfdd17` | `05b0be7a3b5cadd8929ec7d2d1706a7de9139487963b18f4cb3738902dab26ee` |
| `inverse-timing.json` file | `daf9f8edd5910622b021e1aea612fd0d93502d5e388cb10f366bc059f2e5904b` | `b647399efcae7eb5f989eef0d5c32179202749ceb90b34d5202ce11166c8a8e8` |
| Report internal `evidence_sha256` | `71a08012fe8c7853fdc5f27cec63d1f52b6dfc986cad5a425faa450e4c63b4b5` | `d4a2ba7c8df43d1a1e1d68794497bb33b906c8c4202a77644272f68197bc6ad5` |

For each actual report, the unchanged calibration comparator and historical
registries produce precisely eight failures: the unregistered `ff938e70...` to
`f562faec...` implementation transition plus the same seven listed state/gate
paths. A proposed in-memory registration of only that identity and the exact
existing path/from/to values produces **zero failures** on both platforms.
Cross-platform comparison and comparison with the independently run local
calibration also pass. Original **ATOL 1e-7 / RTOL 1e-5** are unchanged; report
bytes differ across platforms, so this is not a bitwise audio-equivalence claim.

The new registry append is based on that actual evidence. The implementation
row's `from` remains the original calibration basis, while its single
`changed_paths` entry records the correction relative to the preceding registered
NYQ implementation. The corresponding validation row carries the seven old
changes verbatim, not a new relaxation. No comparator, calibration, numeric
score, recipe, rank, source/hash policy, old DSP, factory or accepted rack schema
is changed. This narrow append was reconfirmed with #240 in comment 5955890794;
its runtime/render/API/export ownership remains separate.

`tests/inverse/test_nyq001_read_transition.py` inherits the existing comparator
adversarial cases for this new exact successor and adds checks for its one
changed source path and every historical registry row. Before this append the
31 implementation rows had canonical digest
`da2ca8d0e1d4dcd701d454b8ad5c9c3161ce5f05ca91d8e8fc4017c48bb7214e`,
and the six validation rows had digest
`16ff06fee56318399c69f3c7ddae2706916d05ee170096ef79a5b5a8359dd488`.
Both prefixes and their existing compact UTF-8 encoding are preserved. These
synthetic test fixtures are comparator tests only; the real platform reports
above justify registration. All **19 transition tests** pass locally.

Metadata/test/documentation changes do not change the corrected implementation
manifest. The final PR head must independently pass all mapped native and
reverse-dependency checks after this append. Previous-head green jobs and this
artifact audit cannot authorize merge, issue closure or #251 by themselves.
No automatic merge, duplicate dispatch or new workflow is introduced.
