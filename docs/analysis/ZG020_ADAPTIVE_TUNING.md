# ZG-020 timbre-dependent dissonance maps and bounded adaptive tuning

ZG-020 adds two related but deliberately separate analysis layers: a versioned engineering interaction model for pairs of timbre spectra, and a bounded proposal engine that may use those predictions to suggest pitch offsets. Neither layer claims to predict liking, style, consonance preference, or scale truth.

## Timbre spectrum input

`TimbreSpectrum` stores explicit partial frequencies, amplitudes, confidence and source metadata. Synthetic harmonic/stretched spectra are available for reproducible fixtures, while `spectrum_from_partial_bundle()` adapts an accepted ZG-013 `PartialTrackBundle` window by taking the nearest frame per track.

Component amplitudes are not multiplied by confidence. Confidence remains separate metadata and becomes an abstention/uncertainty input rather than an amplitude control.

## Interaction model

The registered method is `zg.timbre_interaction_roughness.v1`. It uses a pairwise roughness kernel with all assumptions persisted in `DissonanceModelSpec`:

- audible band defaults to 20–20,000 Hz;
- the exponential kernel and bandwidth constants are explicit;
- each spectrum is L1-normalised after the configured amplitude exponent;
- partials outside the audible model band reduce coverage/confidence;
- a spectrum with no audible partials yields an invalid/abstained observation rather than a fabricated zero.

Per-spectrum L1 normalisation makes the interaction score invariant to global gain on either voice. This is intentional: lowering a voice cannot make the pitch optimiser appear better merely by muting it.

The result remains an engineering interaction value. It is not a perceptual-loudness model or a universal dissonance truth.

## Interval curves and candidate minima

`IntervalGrid` defines an explicit bounded cents scan. `dissonance_curve()` shifts the second spectrum and evaluates the same versioned model at every grid point. `local_minima()` reports candidate minima with local prominence and confidence.

The grid endpoint policy is `zg-interval-grid-endpoint-v1`. The arithmetic progression begins at `start_cents`, and the exact requested `stop_cents` is represented once. If the final stepped value is at, above because of floating-point rounding, or within `1e-9` cents below the stop, that final value is canonicalised to the exact stop. Otherwise the stop is appended once. The realised sequence after this endpoint decision must contain 2 through 2401 points. Constructor validation, `IntervalGrid.point_count`, `values()` and serialized `grid.points` all use that same cardinality rule, and `values()` revalidates before allocation so a tampered or otherwise over-bound grid fails before curve work.

This closes the historical case where the pre-append estimate could equal 2401 while endpoint inclusion produced 2402 evaluations. The repair does not increase the limit, alter the requested step, drop an endpoint, or silently coarsen a grid. Existing accepted grids retain their points except that a stepped endpoint already within the documented nanocent tolerance is now emitted as the exact requested stop rather than a nearly equal floating-point value.

`sensitivity_candidates()` repeats the scan across declared bandwidth scales and amplitude exponents. A base minimum is retained only when nearby minima recur in a configured fraction of sensitivity scenarios. The returned stability fraction and scenario counts describe robustness to these assumptions only. Its cost diagnostics use the realised bounded cardinality: `grid_point_count` is the exact grid size, `scenario_point_evaluations` is that size times the number of sensitivity scenarios, and `total_point_evaluations` also includes the base curve. These are engineering work counts, not musical-quality measures.

Synthetic fixtures deliberately demonstrate timbre dependence: an eight-partial harmonic spectrum has a stable fifth-region candidate near 702 cents, while a mildly stretched spectrum moves the corresponding candidate upward. These are candidate interval hypotheses, not automatically generated scale degrees.

The roughness method remains version `1.0.0`: the endpoint/cardinality change is a fail-closed resource-bound correction to the existing grid contract, not a change to roughness, tuning, amplitude, confidence, candidate ordering or preference semantics. The additive sensitivity work-count diagnostics do not change numerical candidate evidence for previously valid grids.

## Adaptive tuning request

`AdaptiveTuningRequest` contains the complete proposal policy:

- named voices with nominal cents, timbre spectra and `voice` / `root` / `pedal` roles;
- a visible candidate-interval set;
- desired tension;
- root lock policy;
- hard cumulative offset-from-nominal drift bound;
- per-step cents bound and search resolution;
- minimum voice separation;
- source-confidence threshold;
- objective coefficients;
- the exact dissonance-model version and assumptions.

Amplitudes are immutable in the adaptive layer. The optimiser can change pitch only.

## Hard constraints and objective

Every candidate state must satisfy hard constraints before scoring:

- absolute offset for every voice remains inside `max_total_drift_cents`;
- every realised voice movement is inside `max_step_cents` relative to the exact previous committed state;
- locked voices and pedal voices remain fixed;
- a settled root is fixed at zero when `root_lock=True`; a non-zero previously unlocked root enters the staged lock transition described below;
- nominal voice ordering cannot cross;
- adjacent adjusted voices cannot violate `min_separation_cents`.

The configured objective exposes separate terms for desired-tension error, voice-leading movement, cumulative drift and proximity to visible candidate intervals. Desired tension is explicit, so the system may intentionally prefer a rougher proposal rather than always minimizing interaction roughness.

The scalar total is only a deterministic search objective for the supplied configuration. Lower is not a general musical-quality or preference score.

## Root-lock state transitions

Root locking uses the explicit policy `staged-zero-convergence-v1`. The previous committed root offset is authoritative state: enabling `root_lock` no longer rewrites a non-zero value to zero before search.

If a request enables root lock while the committed root is non-zero, the proposal has one mandatory root target for that step:

`sign(previous) * max(0, abs(previous) - max_step_cents)`.

Thus the root moves monotonically toward the hard locked target of 0 cents, by no more than `max_step_cents` per accepted proposal. At an exact step boundary it reaches zero exactly. Repeated manual commits converge deterministically; rejection keeps the previous state byte-for-byte/field-for-field unchanged. Once zero is reached, ordinary root-lock semantics resume and the root remains fixed there.

The lock transition does not weaken any other constraint. If the staged target would violate voice ordering, minimum separation, a separate explicit voice lock/pedal lock, or another hard constraint, the proposal abstains rather than teleporting or silently relaxing the rule. A non-zero root combined with `max_step_cents == 0` likewise returns the explicit `root-lock-transition-zero-step` abstention: zero is still the required eventual target, but the current request provides no legal motion budget.

Low-confidence abstention occurs before any staged movement is published, so it cannot mutate the root or any other voice. Disabling `root_lock` has no inverse transition/reset: the previous root remains the baseline and may only move through the ordinary bounded adaptive search.

Every proposal's `search.root_lock_transition` diagnostic records the policy, previous offset, zero target, staged target, planned and realised step, remaining distance, completion state and any blocking reason. `candidate_tuning_set()` and `ab_recipe()` carry the same realised transition record so A/B material cannot describe a zero-locked root while actually rendering an intermediate bounded step.

## Confidence and abstention

Low-confidence source spectra cause an immediate abstention. Pair predictions also carry confidence; if a candidate state contains a pair below the request threshold, that state is not accepted for optimization.

This preserves the existing ZaagGenZ policy that uncertainty remains visible rather than being converted into a forced transformation.

## Proposal, commit and rejection

`propose_adaptive_tuning()` never mutates the prior state. It returns an `AdaptiveProposal` containing offsets, adjusted cents, pair predictions, objective terms, search metadata and a `manual_review_required` flag.

`commit_proposal()` is the only state-advance operation. `reject_proposal()` returns the prior state exactly. Repeated commits cannot accumulate unbounded drift because every proposal remains constrained relative to the original nominal pitches as well as relative to the previous step.

## Export and A/B evidence

`candidate_tuning_set()` exports the proposed offsets in a compact manually reviewable form, including any active root-lock transition and its remaining distance. `ab_recipe()` records baseline and candidate states, the same transition diagnostics, immutable-timbre/amplitude controls and a canonical SHA-256 recipe identity.

`examples/zg020_adaptive_tuning.json` freezes the synthetic evidence recipe. `tools/adaptive_tuning_report.py` reports harmonic/stretched minima, sensitivity metadata, global-gain invariance, low/high desired-tension proposals, a twenty-step bounded sequence, low-confidence abstention, moving-root operation, the staged non-zero-root lock sequence, and reproducible A/B recipes.

The report is synthetic engineering evidence. It does not establish that a candidate tuning sounds better; that decision remains available for manual listening/acceptance.

## Scheduler integration

Dissonance-map searches run as bounded `JobClass.RESEARCH` tasks and adaptive proposals as `JobClass.ANALYSIS` tasks through the existing ZG-004 scheduler. Both preserve cooperative cancellation and return typed inspectable results rather than applying tuning changes automatically. The scheduler's existing memory reservation remains separate from the exact sensitivity point-evaluation counts; any consumer budgeting CPU/search work must use the realised `IntervalGrid.point_count`, never the old pre-endpoint estimate.
