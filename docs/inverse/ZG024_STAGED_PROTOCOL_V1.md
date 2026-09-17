# ZG-024d preregistered staged deterministic search protocol v1

Issue #92 tests a narrow research hypothesis from the accepted ZG-024b handoff: deterministic global low-discrepancy coverage followed by transparent local coordinate refinement can outperform the strongest existing deterministic search baselines at the same logical evaluation budget without using holdout or target-truth feedback.

This document is committed before the first ZG-024d outcome is inspected. It is a research protocol, not a product-optimizer selection.

## Frozen methods and budgets

Baselines are the accepted ZG-024b `uniform-splitmix`, `halton-shifted`, and `coordinate-refine` methods. Three staged allocations are tested: 1/3, 1/2, and 2/3 of the exact logical budget go to shifted-Halton global coverage. The remainder goes to fit-selected coordinate sweeps with radii 0.25, 0.125, 0.0625, 0.03125, 0.015625 and 0.0078125 of each parameter range. Duplicate or clipped local states do not consume logical budget; an explicitly labelled continuation of the same global sequence fills any otherwise-unused evaluations. Every cold logical candidate retains the existing exact repeated-render verification semantics.

The methods may inspect only `FitEvaluator`. Ground-truth recipes and `AuditEvaluator` are unavailable to the proposal code. Holdout results are computed only after the fit-selected candidate is frozen and cannot rerank it.

Search seeds are `41`, `211`, and `2027`. Each paired method receives the same fixture, seed and logical budget with fresh evaluator caches.

## Frozen targets

`staged-calibration-nonlinear` is the sole calibration target. It is an off-grid drive/wet target with an 18-evaluation budget. Calibration selects the staged allocation with the lowest median fit score across the three seeds, but only if that method has an eligible selected candidate for every calibration seed.

`staged-audit-envelope` and `staged-audit-timbre3` are independent confirmatory targets with budgets of 18 and 30 respectively. Their ground-truth values and search seeds differ from the published ZG-024b fixtures. The audit targets are not allowed to influence staged-method selection.

## Preregistered success and failure criteria

The calibration-selected staged method must strictly improve the median fit score over the best of the three baseline methods on the calibration target under the pre-existing absolute `1e-7` / relative `1e-5` comparison policy.

Without changing that selected method, independent confirmation requires it to beat or tie the best baseline median fit on at least one audit target and to remain within 5% of the best baseline median fit on both audit targets. Failure is retained and reported as a no-go; thresholds, transient eligibility, fixtures, seeds or budgets must not be edited after seeing outcomes to manufacture a pass.

Parameter error is a post-selection research diagnostic only. It never enters optimizer selection. Holdout scores are likewise post-selection diagnostics and never enter proposal, calibration selection or fit ranking.

## Evidence and semantics

The compact report records every method/fixture/seed selected fit, holdout, parameter diagnostic, eligible count, exact budget, physical render count and result digest. The full CI artifact retains all candidates, decomposed objective/validation records, proposal lineage and selected audit records. Host timing is separate telemetry and excluded from evidence identity.

No source PCM, protected source/audio ownership, renderer/DSP topology, tuning, normalization/clipping policy, objective weights, transient-v4 eligibility threshold, project defaults or provenance ownership may change in this pass. The staged code is layered under `research/zg024d` so the accepted ZG-024a/b implementations and their frozen evidence remain reproducible.
