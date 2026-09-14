# ZG-024 — recovered inverse baseline characterisation

## Provenance and preservation

Inspected `main` **6e0153d824608d6a9899c5ea8e8c0b9a29688c98**, including accepted
ZG-003/004/005/014/018/019/020 source, tests and evidence (mapped in this directory's
README). The actual predecessor is **`app/uptempo_harmony/inverse.py`**, recovered
from the owner's v1.2.1 source, not reconstructed from screenshots or research
notes. `baseline/recovered_source/materialize_v2.py` validates the compact runtime;
`materialize.py` delegates to the repaired verifier. Upstream recovery records and
`baseline/V1_2_1_CONTRACT.json` remain authoritative.

Original uploaded archive: 9,498,941 bytes, SHA256
`90be319a4660a637077df935a8ebcbd1bb4c3a629e28e2f6d4bfe62d88dfe8a8`.
Authenticated compact runtime: SHA256
`eaf5d3ab822dfa121cd3b795d62619af9e62c041fb02de19f8dbeafb0014c919`.
The executable inverse source SHA256 and actual benchmark output are also recorded
by `tools/inverse_foundation_report.py` in `examples/zg024a_inverse_baseline.json`.

**No recovered application file is modified by this pass.** Both the historical
single-stage and multi-stage smoke tests still run. Their scores remain separate
benchmarks: the new laboratory does not replace the old implementation invisibly.

## Searched parameters and bounds

`INVERSE_PROFILES` and `BASE_BOUNDS` in the recovered module are the source of
truth. Quick searches 11 values: f0, sweep semitones/tau, harmonic decay, odd/even
ratio, roughness, noise level, drive, asymmetry, hard-clip mix and decay.
Balanced/multistage expose 21 values, adding jitter, harmonic lock/capture time,
ERB roughness width, noise decay/synchronisation, hard-clip level, preemphasis,
sustain and transient click. Full arrays are exported directly in the evidence.

| Parameter | Recovered inclusive search bounds |
|---|---|
| f0_hz | 20..120 Hz, further restricted to measured terminal f0 +/-2.5 semitones |
| sweep_semitones / sweep_tau_ms | -12..18 semitones / 8..180 ms |
| pitch_jitter_cents | 0..100 cents |
| harmonic_decay / odd_even_ratio | 0.5..2.2 / 0.3..7.5 |
| harmonic_lock_cents / harmonic_lock_tau_ms | 0..160 cents / 8..260 ms |
| roughness / roughness_erb_fraction | 0..0.9 / 0.04..0.8 |
| noise_level / noise_decay_ms / noise_sync | 0..0.65 / 15..600 ms / 0..1 |
| drive_db / asymmetry | 2..34 dB / -0.5..0.5 |
| hard_clip_mix / hard_clip_level | 0..1 / 0.15..1.35 |
| preemphasis / decay_ms / sustain / transient_click | 0..0.8 / 35..620 ms / 0..0.3 / 0..0.42 |

Remaining `KickParams` values are inherited from the base preset; feature analysis
also uses target-authoritative BPM/terminal pitch and one-beat duration. This is
not full recovery of arbitrary DSP topology or all production controls.

## Objective and preprocessing

Reference preparation crops one beat, optionally aligns onset, resamples,
pads/crops, **removes DC and peak-normalises**. Feature extraction normalises too.
The existing synthesiser applies its own final peak scaling to `params.peak`.
There is no trustworthy pre-normalisation output tap to invent retroactively.
Absolute level and polarity cannot be judged from this historical scalar alone.

`feature_distance` returns component losses and a weighted root-mean-square:

| Component | Recovered scaling | Default weight |
|---|---|---:|
| pitch | RMS of cents/180 clipped to [-6, 6] | 2.4 |
| spectrum | RMS spectral dB difference /20 | 2.0 |
| envelope | RMS envelope dB difference /14 | 1.15 |
| flatness | RMS log10-flatness difference /1.15 | 0.75 |
| hf | RMS square-root HF-share difference /0.30 | 0.80 |
| harmonics | RMS harmonic dB difference /14 | 1.40 |

Candidate pitch uses the synthesiser's debug f0 trajectory; reference pitch is
estimated from audio. That asymmetry is useful historically but not a general
observable-only inverse objective. Scores are engineering discrepancies, not
perceptual accuracy or proof that the original production chain was recovered.

## Method, budgets, determinism and caching

`inverse_optimize` uses SciPy `differential_evolution`: explicit seed, single worker,
`updating='immediate'`, `polish=False`, warm initial state, `atol=1e-4`, `tol=0.008`,
minimum population multiplier 3 and minimum iteration count 1. It evaluates the
returned vector once more after the optimiser. Target features are precomputed;
there is no content-addressed candidate feature/render cache. It retains a best
state and component losses, not a Pareto candidate catalogue.

`multistage_inverse` runs macro (5 parameters, nominal 12 kHz), structure (13,
24 kHz), and surface (21, 32 kHz), with actual sample-rate capping, warm starts,
bounds narrowing and covariance-recovery floors. Iteration scales are
0.45 / 0.70 / 0.58; narrowing factors 1 / 0.30 / 0.16; seeds are
`root + stage_index * 7919`. These existing heuristics are preserved, **not**
adopted as the new pass's optimiser design.

Seeded execution is reproducible within the pinned numerical environment; no
cross-platform bit-identity promise is established. `maxiter`/`popsize` are not an
exact evaluation budget: early convergence, stage dimensionality and the final
extra evaluation affect cost. The new bounded enumeration is intentionally more
transparent, not claimed faster or better.

## Cancellation, checkpoint and known limitations

Cancellation is checked cooperatively before objective/generation work; callbacks
publish progress and the current best under a lock. Cancellation retains the best
so far, but cancellation before the first evaluation can leave an infinite score.
There is no durable exact population/RNG checkpoint, resume identity, revision-
bound provenance or verified prefix lineage.

Only one prepared excerpt is optimised. No independent holdouts or post-freeze
selection boundary exists. Peak normalisation can conceal gain errors; clipping,
transient removal, bandwidth loss and silence are not independently gated. Pitch
estimation, phase-insensitive spectra, parameter covariance and nonlinear
saturation create ambiguity. A low historical score does not imply a unique
recipe, correct absolute level, matched transients, or held-out generalisation.

The foundation benchmark deliberately runs the original quick smoke target
(`swept_mixed`, 16 kHz, neutral initial state, seed 7, maxiter 3, popsize 3) unchanged.
It records exact bounds/parameters, before/after component losses and actual
evaluations. `app/tests/multistage_smoke.py` independently preserves staged
behaviour. Compare either only under its documented historical loss semantics;
never subtract its score from the new raw-level laboratory score.
