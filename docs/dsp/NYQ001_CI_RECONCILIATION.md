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
