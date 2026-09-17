# ZG-024 transient-v4 evidence migration

**Corrective issue:** #87  
**Production diagnostic:** `zg.inverse.transient-onset-contrast.v4`  
**Frozen predecessor implementation:** `ff938e70ba2598d5f6f6f0bc305e01b580c373a8e5daca849e8d3f9392bee3a4`  
**Reviewed cumulative repaired implementation:** `6c5753173c1758beb91f3511a909bec978c77baf025004d7f3fc9e608e1f4d86`

This document records the evidence transition required by issue #87. It does not replace or rewrite historical calibration. It defines the narrow compatibility boundary between evidence generated under the derivative-anchor transient diagnostic and evidence generated under the repaired target-anchored transient-preservation policy.

## Why an explicit migration is required

The first complete Ubuntu and Windows ZG-024a runs of the repaired implementation passed the inverse unit/adversarial suite, inherited prerequisite suites and browser transport, then failed closed at the implementation-identity check. Both platforms independently measured the same repaired implementation identity shown above. At that point the comparison had not yet been permitted to inspect downstream fields because the implementation change itself was intentionally unreviewed.

After that exact implementation transition was reviewed and registered, the next full comparison exposed seven portable validation differences. This is expected for issue #87: the purpose of the repair is to change which candidates the `transient_loss` hard gate classifies as preserved or damaged when the predecessor derivative metric was carrier/level sensitive. The earlier preliminary statement that only the implementation hash differed therefore described only the first fail-closed comparison stage and is superseded by this complete migration record.

The immutable ZG-024a calibration remains unchanged. The repaired comparison may align only the seven exact validation projections below, and only for the exact predecessor/repaired implementation pair. Every other portable field must still reproduce under the existing tolerances.

## Exact ZG-024a validation deltas

The reviewed migration is stored in `examples/zg024a_validation_transitions.json` and enforced by `tools/inverse_validation_transition.py`.

| Portable path | Frozen predecessor | Repaired v4 |
| --- | --- | --- |
| `/fixtures/0/candidates/8/holdout/validation/0/state` | `accepted` | `rejected` |
| `/fixtures/0/candidates/8/holdout/validation/0/triggered_gates` | `[]` | `["transient_loss"]` |
| `/fixtures/4/candidates/0/holdout/validation/0/triggered_gates` | `["level_mismatch","energy_collapse","transient_loss","normalisation_suspect"]` | `["level_mismatch","energy_collapse","normalisation_suspect"]` |
| `/fixtures/4/candidates/0/whole_signal/validation/0/state` | `accepted` | `rejected` |
| `/fixtures/4/candidates/0/whole_signal/validation/0/triggered_gates` | `[]` | `["transient_loss"]` |
| `/fixtures/4/candidates/1/whole_signal/validation/0/state` | `rejected` | `accepted` |
| `/fixtures/4/candidates/1/whole_signal/validation/0/triggered_gates` | `["transient_loss"]` | `[]` |

These are policy-semantic changes, not tolerated numerical drift. The repaired gate can reject a case the predecessor derivative diagnostic accepted, stop attributing rejection to transient loss where the predecessor was confounded, or accept a case the predecessor falsely rejected. This is why retaining the predecessor classifications as a hard compatibility target would reintroduce the defect.

No fit loss, objective score, recipe identity, ranked ordinal, Pareto ordering, budget, proposal, parameter state, holdout objective, source identity or other portable calibration field is authorized to change by this migration.

## Fail-closed migration enforcement

`tools/inverse_validation_transition.py` deliberately cannot express a broad waiver. A record must:

- bind one exact old/new implementation SHA-256 pair;
- name a reviewed issue and stable ID;
- identify exact array-indexed validation paths;
- target only `state` or `triggered_gates` within fit, holdout or whole-signal validation;
- provide exact predecessor and successor values;
- contain no wildcard path or duplicate path; and
- be accompanied by an independently reviewed implementation-identity transition.

During comparison the helper validates both sides and changes only a disposable comparison copy back to the predecessor value. A missing path, wrong predecessor, wrong repaired value, undeclared extra drift or unreviewed implementation identity still fails CI. Actual repaired evidence is never rewritten.

## ZG-024b strategy evidence

The predecessor strategy calibration remains at `examples/zg024b_strategy_calibration.json`. It is historical evidence of search methods operating under the derivative transient gate and is intentionally retained unchanged.

The same fixed design, methods, search seeds and logical budgets were then rerun under the repaired v4 gate. The portable repaired result is frozen separately as `examples/zg024b_strategy_calibration_transient_v4.json`. Independent Ubuntu and Windows runs produced an identical portable repaired calibration under the existing `1e-7` absolute / `1e-5` relative comparison policy.

Differences between the two strategy calibrations are expected downstream effects of changed hard eligibility. They are not evidence for choosing a production optimizer, are not used to tune the 0.4 threshold, and do not feed holdout/truth information back into proposal generation. Historical strategy evidence must be interpreted with the gate version under which it was generated; repaired strategy work uses the transient-v4 calibration.

## Compatibility and protected semantics

The repair does not alter source PCM, protected-audio ownership, render topology, recipes, tuning, normalization/clipping policy, fit objectives, proposal algorithms, fit/holdout capability separation or product defaults. Rejected candidates continue to retain raw objective and diagnostic measurements. Candidate 2.0 evidence remains content-bound to its implementation/search provenance, so predecessor derivative-gate records are not reopened as though they were v4 records.

This migration makes later staged-search evidence interpretable under an explicit repaired eligibility policy while retaining the predecessor records needed to understand what changed. It is not permission to compare or combine eligibility counts across gate versions without naming the diagnostic version.
