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

`sensitivity_candidates()` repeats the scan across declared bandwidth scales and amplitude exponents. A base minimum is retained only when nearby minima recur in a configured fraction of sensitivity scenarios. The returned stability fraction and scenario counts describe robustness to these assumptions only.

Synthetic fixtures deliberately demonstrate timbre dependence: an eight-partial harmonic spectrum has a stable fifth-region candidate near 702 cents, while a mildly stretched spectrum moves the corresponding candidate upward. These are candidate interval hypotheses, not automatically generated scale degrees.

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
- each accepted step is inside `max_step_cents` relative to the previous state;
- locked voices and pedal voices remain fixed;
- the root is fixed when `root_lock=True` and can participate normally when `root_lock=False`;
- nominal voice ordering cannot cross;
- adjacent adjusted voices cannot violate `min_separation_cents`.

The configured objective exposes separate terms for desired-tension error, voice-leading movement, cumulative drift and proximity to visible candidate intervals. Desired tension is explicit, so the system may intentionally prefer a rougher proposal rather than always minimizing interaction roughness.

The scalar total is only a deterministic search objective for the supplied configuration. Lower is not a general musical-quality or preference score.

## Confidence and abstention

Low-confidence source spectra cause an immediate abstention. Pair predictions also carry confidence; if a candidate state contains a pair below the request threshold, that state is not accepted for optimization.

This preserves the existing ZaagGenZ policy that uncertainty remains visible rather than being converted into a forced transformation.

## Proposal, commit and rejection

`propose_adaptive_tuning()` never mutates the prior state. It returns an `AdaptiveProposal` containing offsets, adjusted cents, pair predictions, objective terms, search metadata and a `manual_review_required` flag.

`commit_proposal()` is the only state-advance operation. `reject_proposal()` returns the prior state exactly. Repeated commits cannot accumulate unbounded drift because every proposal remains constrained relative to the original nominal pitches as well as relative to the previous step.

## Export and A/B evidence

`candidate_tuning_set()` exports the proposed offsets in a compact manually reviewable form. `ab_recipe()` records baseline and candidate states, immutable-timbre/amplitude controls and a canonical SHA-256 recipe identity.

`examples/zg020_adaptive_tuning.json` freezes the synthetic evidence recipe. `tools/adaptive_tuning_report.py` reports harmonic/stretched minima, sensitivity metadata, global-gain invariance, low/high desired-tension proposals, a twenty-step bounded sequence, low-confidence abstention, moving-root operation and reproducible A/B recipes.

The report is synthetic engineering evidence. It does not establish that a candidate tuning sounds better; that decision remains available for manual listening/acceptance.

## Scheduler integration

Dissonance-map searches run as bounded `JobClass.RESEARCH` tasks and adaptive proposals as `JobClass.ANALYSIS` tasks through the existing ZG-004 scheduler. Both preserve cooperative cancellation and return typed inspectable results rather than applying tuning changes automatically.
