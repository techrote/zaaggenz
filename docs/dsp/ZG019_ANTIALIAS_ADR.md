# ADR — ZG-019 nonlinear antialiasing baseline

**Status:** accepted for engineering comparison; product/default sound remains listening-gated  
**Decision scope:** ZG-019 placement experiments and future opt-in clean nonlinear nodes

## Context

ZG-016 deliberately preserved the existing direct-rate `core.tanh.v1` and `core.hard_clip.v1` behavior. ZG-019 needs a cleaner comparison path without rewriting that legacy alias character or allowing placement measurements to be confounded by changing nonlinear algorithms between variants.

A nonlinear waveshaper creates energy above the input Nyquist frequency. At direct rate, those products fold back into the audible band. Oversampling pushes the folding boundary upward, but the reconstruction filter itself becomes part of the method and therefore must be fixed, versioned and disclosed.

## Decision

1. Keep `core.tanh.v1` and `core.hard_clip.v1` unchanged as the explicit legacy/direct-rate option.
2. Add opt-in `core.tanh_aa.v1` and `core.hard_clip_aa.v1` nodes with validated production factors **1×, 2× and 4× only**.
3. Use `zg.kaiser_polyphase_zero_phase.v1` for 2×/4× reconstruction:
   - symmetric FIR;
   - Kaiser beta 8.6;
   - tap count `2 * 16 * factor + 1` (65 taps at 2×, 129 taps at 4×);
   - cutoff `1/factor` of the oversampled Nyquist;
   - offline zero-phase compensation through polyphase resampling;
   - declared sample latency 0 because the offline method aligns output samples to the input timeline;
   - symmetric pre/post ringing remains part of the disclosed filter behavior and is not hidden as a zero-cost causal process.
4. Use an internal **8×** render only as a high-rate engineering reference. It is not a registered production factor.
5. Treat **4× as the preferred engineering antialiasing baseline** for ZG-019 measurements and clean-mode validation because it is materially closer to the 8× reference than 1×/2× on the frozen alias stress fixture.
6. Do **not** promote 4×, 2×, or any spectral placement to the product/default sound from metrics alone. Existing legacy/direct-rate behavior remains available and unchanged until explicit owner listening approves a default change.

## Consequences

- Placement comparisons can hold the nonlinear implementation and reconstruction method fixed while moving only the spectral stage.
- 1× inside the AA node is useful as a method-control path but does not alter or replace the legacy node IDs.
- 2× is an explicit lower-cost clean option; 4× is the engineering baseline; 8× is evidence-only.
- The filter has zero declared offline latency but noncausal symmetric ringing. A future real-time/causal implementation must use a different node/version and disclose its actual delay and phase behavior.
- Output normalization is prohibited in the ZG-019 comparison family. Master gain is fixed at 0 dB so level differences remain evidence rather than being normalized away.

## Evidence

`examples/zg019_placement_benchmarks.json` freezes the source and alias-stress recipes. `tools/spectral_placement_report.py` records 1×/2×/4× error against the 8× reference, placement hashes, level/spectral/transient metrics, exact identity checks, and pairwise placement deltas on Windows and Ubuntu CI.
