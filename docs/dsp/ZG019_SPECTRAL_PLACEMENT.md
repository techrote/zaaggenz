# ZG-019 spectral placement around nonlinear stages

ZG-019 makes the position of the accepted ZG-017 partial-domain retune stage an explicit research axis around real ZG-016 nonlinear graph stages. It does not turn spectral analysis into an opaque graph node: the graph and spectral transform retain their accepted ownership boundaries while the placement runner persists their exact execution order.

## Fixed family

Every comparison uses the same source, sample rate, spectral request and two nonlinear stage specifications. Only the spectral stage position changes:

- `pre`: spectral → nonlinear A → nonlinear B
- `inter`: nonlinear A → spectral → nonlinear B
- `post`: nonlinear A → nonlinear B → spectral

`PlacementRequest.to_dict()` records the order, complete ZG-017 request, both registered node IDs/parameters, oversampling/filter policy, master gain and normalization policy. Output master gain is fixed at 0 dB and normalization is `none`.

## Nonlinear modes

`NonlinearStageSpec(mode='legacy', oversample=1)` selects the unchanged ZG-016 `core.tanh.v1` / `core.hard_clip.v1` direct-rate behavior. This is the explicit alias-character preservation path.

`mode='antialiased'` selects the ZG-019 `*_aa.v1` node IDs. Production oversampling is validated to 1×, 2× or 4×. The reconstruction/filter decision is recorded in `ZG019_ANTIALIAS_ADR.md`; 4× is the engineering comparison baseline, not a listening-approved product default.

The AA nodes intentionally do not accept automation in v1. Placement research first requires a stable nonlinear method with no hidden interpolation-rate change. Existing ZG-016 automatable direct-rate nodes remain available.

## Timing and bypass

All current placement stages are offline, shape-preserving and declare zero sample latency. The polyphase AA method is output-aligned offline and therefore reports zero declared latency, while its symmetric pre/post ringing is explicitly disclosed.

With spectral amount zero and both shaper mixes zero, all three placement variants take an exact source identity path. This is the gain/timing positive control.

## Evidence interpretation

The frozen benchmark recipe records:

- exact PCM hashes;
- RMS/peak/crest engineering level (not perceptual loudness);
- target-harmonic and non-target spectral power fractions;
- spectral centroid;
- a fixed transient-window peak/RMS/derivative measure;
- pairwise output differences;
- exact identity/latency checks;
- 1×/2×/4× nonlinear reconstruction error against an evidence-only 8× reference.

These measurements establish that order and antialiasing choices create controlled, reproducible differences. They do not establish which sound is preferable. Any product/default placement remains subject to explicit owner listening.

## Reproducibility

The benchmark input and processing parameters are frozen in `examples/zg019_placement_benchmarks.json`. `tools/spectral_placement_report.py` consumes that file rather than embedding a second mutable copy of the recipe. CI runs the same evidence on Windows and Ubuntu.
