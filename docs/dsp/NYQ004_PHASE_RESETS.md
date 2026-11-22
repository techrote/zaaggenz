# NYQ-004 — source-independent physical-time LFO phase reset

**Draft-only:** #253, PR #267. Method `nyq.triangle-lfo-physical-phase-reset-pair.v1`.
This is executable opt-in modulation feeding the existing exact controlled
physical-event/native-grid PCM proof renderer; it is not a registered product
SamplerPlan, real Compose graph insert, delivery-rate export or owner audition.

## Musical behavior and preserved authority

`PhaseResetLfoSource` saves a versioned `SampledLfoSource` plus one or more
exact rational `Reset(time_s, phase_cycles)` records, strictly ordered after
zero. The reset changes **only the triangle LFO phase** at its physical
timestamp. The independently integrated virtual capture-clock phase, its
crossing IDs, epoch, output duration and stable project/output times do not
reset. Free-Hz and cumulative beat-sync tempo maps are both supported.
The original LFO source and reset records must be saved for editing intent.

A reset can jump from any old LFO level to any new level. A single linear
control lane cannot express this without inventing an epsilon gap or
corrupting the pre-reset segment. The compiler instead freezes two ordered
additive-Hz lanes:

1. A right-continuous **step** lane holding the cumulative value jumps at
   reset timestamps.
2. A **continuous piecewise-linear** lane equal to the triangular oscillator
   minus those cumulative jumps. Its derivative changes at original triangle
   peaks, troughs, tempo boundaries and resets; all such times are exact
   rational physical coordinates.

The lanes sum exactly to the requested oscillator level on both sides of
each reset, without a clock-phase discontinuity or hidden smoothing.
Power-of-two normalization bounds each lane to [-1,1] and keeps the depth
products exact in binary floating-point representation. The unmodified
ClockSpec conservatively checks the **individual** rate bounds: a correlated
high-depth request may fail closed even when the summed curve is safe.

## Boundaries and evidence

Version 1 requires LFO physical origin zero and at least one ordered reset.
For a delayed nonzero onset, use the separately versioned
`nyquismic_lfo_onset.py` route-pair policy instead; these policies are not
silently compounded. Phase-reset records at or after the requested end are
retained in source identity, but have no effect in that short region. Extend
the render only by recompiling from original source intent. Per-route
256-point and existing exact-event/positive-clock/cancellation budgets apply;
there is no automatic decimation or hidden release of a rejected request.
The compiler admits additive-Hz controls only; log2, arbitrary sinusoidal
oscillators and live graph registry binding remain separate capabilities.

Test:

```sh
python -m unittest discover -s tests/dsp -p 'test_nyquismic_lfo_phase_reset_pcm.py' -v
```

The independent physical-time oracle uses a 1 Hz triangle, a 40 Hz depth
and a 600 Hz capture clock. At t=1/2 s, the LFO resets from phase 1/2 to 0,
forcing an instantaneous **640 → 560 Hz** rate change while physical capture
phase remains **300**. The exact phase integral is
`560*u + 80*u**2` in each half-second, predicting **600 events**
through t=1 s and a post-reset event at
`1/2 + 2/(560 + sqrt(560**2 + 320))` seconds.
The fixture compares this independently derived root with event geometry,
checks real frozen 8 kHz PCM before and after reset, region and saved-spec
replay, and proves no source-time changes. A second fixture exercises
off-grid 120→180 BPM, an independent phase reset and a future-reset
short-preview invariant. Zero depth, invalid/unsorted resets, nonfinite
depth, cancellation and budget refusals are tested.

This does **not** establish cross-evaluation-rate audio convergence, general
input/feature authenticity, non-native PCM conversion, production sampler
adapter, packaged Windows/Compose acceptance, ZG-024a identity admission or
human musical preference. #266 retains exclusive sampler implementation
ownership. Integration retains shared inverse-transition ledgers. Keep
#267 Draft and #253/#254 dependency gates unchanged until independent
review and qualified acceptance.
