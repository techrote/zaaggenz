# Recovered inverse baseline: retained benchmark

Inspection base: `6e0153d824608d6a9899c5ea8e8c0b9a29688c98`. Authority is the authenticated recovered v1.2.1 payload and its materialization manifests, not a reconstruction from screenshots. This pass does not edit recovered source, its smoke tests, CLI or HTTP entry points.

## Provenance

- Original owner archive: `zaaggenz-v1.2.1.zip`, SHA-256 `90be319a4660a637077df935a8ebcbd1bb4c3a629e28e2f6d4bfe62d88dfe8a8`.
- Runtime payload SHA-256: `eaf5d3ab822dfa121cd3b795d62619af9e62c041fb02de19f8dbeafb0014c919`.
- `baseline/recovered_source/materialize_v2.py` recreates `app/uptempo_harmony/inverse.py`, `synth.py` and `app/tests/inverse_smoke.py`; exact file checksums are emitted by `zaaggenz_inverse.legacy.provenance()` and the calibration artifact.
- The current predecessor is that recovered implementation, not a new inverse-only synthesizer. `run_recovered_benchmark()` adapts it read-only and reproduces its original smoke setup.

## Parameters and bounds

Quick searches 11 parameters; balanced and multistage expose the 21-parameter set below. Other source settings remain fixed by the base preset. Bounds below are read from the actual `BASE_BOUNDS`, not the broader modern registry. `f0_hz` additionally intersects its absolute range with the measured terminal pitch ±2.5 semitones. Multistage uses later warm-start narrowing.

| Parameter | Inclusive absolute bounds | Quick profile |
|---|---:|---|
| `f0_hz` | 20 … 120 | yes |
| `sweep_semitones` | -12 … 18 | yes |
| `sweep_tau_ms` | 8 … 180 | yes |
| `pitch_jitter_cents` | 0 … 100 | no |
| `harmonic_decay` | 0.5 … 2.2 | yes |
| `odd_even_ratio` | 0.3 … 7.5 | yes |
| `harmonic_lock_cents` | 0 … 160 | no |
| `harmonic_lock_tau_ms` | 8 … 260 | no |
| `roughness` | 0 … 0.9 | yes |
| `roughness_erb_fraction` | 0.04 … 0.8 | no |
| `noise_level` | 0 … 0.65 | yes |
| `noise_decay_ms` | 15 … 600 | no |
| `noise_sync` | 0 … 1 | no |
| `drive_db` | 2 … 34 | yes |
| `asymmetry` | -0.5 … 0.5 | yes |
| `hard_clip_mix` | 0 … 1 | yes |
| `hard_clip_level` | 0.15 … 1.35 | no |
| `preemphasis` | 0 … 0.8 | no |
| `decay_ms` | 35 … 620 | yes |
| `sustain` | 0 … 0.3 | no |
| `transient_click` | 0 … 0.42 | no |

## Objective and method

The target is a single feature field. Reference preparation removes DC and peak-normalizes audio; frame spectra and envelopes are relative. Candidate pitch uses the synthesizer's debug f0 trajectory, while reference pitch is acoustically estimated (the smoke supplies a known f0 hint). This asymmetry and discarded absolute level are important limitations.

Individual dimensionless RMS terms are pitch cents / 180 (clipped to ±6), spectrum dB / 20, envelope dB / 14, flatness log / 1.15, square-root HF ratio / 0.30, and harmonic dB / 14. The aggregate is weighted RMS: pitch 2.4, spectrum 2.0, envelope 1.15, flatness 0.75, HF 0.8, harmonics 1.4. This is neither a waveform objective nor a validated perceptual score.

Search is SciPy seeded differential evolution, `polish=False`, one worker, immediate updating, `tol=0.008`, `atol=1e-4`, at least one iteration and population multiplier at least three. The parameter seed makes it reproducible in a pinned numerical environment, not necessarily byte-identical across platforms. A final best-candidate evaluation contributes to the evaluation count.

Recovered multistage is already present and is preserved, not reimplemented as the new baseline: macro at 12 kHz / five dimensions, structure at 24 kHz / thirteen dimensions, surface at 32 kHz / twenty-one dimensions. Iteration scales are 0.45 / 0.70 / 0.58, later narrowing fractions 0.30 / 0.16, and stage seed is `seed + stage_index*7919`. Exact per-stage keys, feature resolution and weights are emitted by the provenance adapter.

## Cache, cancellation and checkpoint behavior

The reference feature field is precomputed. The recovered module does not provide a content-addressed candidate render/feature cache, a durable optimizer-population checkpoint, or a Pareto/lineage archive. It cooperatively checks cancellation in objectives/generation callbacks and preserves the best candidate available in memory. Very early cancellation may leave no finite best score. Existing web jobs/previews are not equivalent to a durable optimizer resume state.

There is no independent holdout, whole-signal audit split, anti-silence/transient/final-clipping gate or absolute-level guarantee. Do not retrospectively describe legacy best scores as passing the new gates. Keep it as a useful historical comparator without quietly altering its normalization or objective.

## Executed benchmark

The original smoke's target is `swept_mixed`, one beat at 16 kHz, padded/truncated to that beat. Initial preset is `neutral`; profile `quick`, `maxiter=3`, `popsize=3`, seed 7. The inherited target-f0 hint is explicitly recorded and is **not supplied to the new synthetic searches**.

On the recorded Linux / CPython 3.13.5 / NumPy 2.3.5 / SciPy 1.17.0 environment, initial score **0.35859315904669287** becomes **0.3501547174956158**, with **133 evaluations**. Exact initial/best components, actual dynamic bounds, parameters and target identity are in the reproducible evidence output. This small improvement is reported, not optimized away. The new cyclic-grid fixtures use different targets, objectives and budgets, so these numbers are **not an optimizer league table**.
