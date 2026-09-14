# ZG-017 partial-domain spectral retune

ZG-017 is the first retune-only implementation of the spectral-harmony brief. It consumes the accepted ZG-013 `PartialTrackBundle` through `ComponentAnalysis` and an accepted ZG-007 `TuningSpec`; it does not define a second component or tuning representation.

## Request and target lattice

`SpectralRetuneRequest` is a bounded authoring wrapper outside the frozen shared contract registry. Its `to_dict()` representation records the method version, tuning, amount, confidence/displacement/slew bounds, base voices and any sample-addressed target segments.

Each `LatticeVoice` contains an explicit tuning degree and an ordered set of positive partial ratios. Integer ratios therefore describe harmonic teeth, while arbitrary increasing positive ratios describe explicitly inharmonic teeth. No chord, key, genre or listener-preference meaning is inferred from a target comb.

The base lattice begins at sample 0. Optional `LatticeSegment` entries replace the active voices at strictly increasing positive sample indices. This provides a deterministic target-change fixture without adding timing semantics to the frozen `TuningSpec`.

## Transform eligibility and assignment

ZG-013 retains ownership of confidence and continuity. A frame is transform-eligible only when its component row is already marked `transform`, it meets the request confidence threshold, and—by default—the track remains `continuous`. Ambiguous/reanchored material, transient-owned frames and other ZG-013 preserves remain unchanged rather than receiving guessed targets.

Eligible frames select the nearest target tooth in log-frequency/cents space. Assignment hysteresis can retain the previous tooth when the old assignment remains close enough. A target beyond the displacement budget is rejected for that frame.

## Frequency and phase trajectory

Requested correction is scaled by `amount`, clipped by the displacement budget and rate-limited by `max_correction_slew_cents_per_second`. The realised frequency, requested target, source estimate, confidence, decision/reason and target-segment identity are retained per frame for inspection.

Phase correction integrates the realised source-to-target frequency delta between component anchors. The same correction is added to every channel phase for a track frame, preserving the ZG-013 inter-channel phase relationship rather than independently retuning left and right phase.

A preserved frame returns to the unmodified component row. Subsequent transformation resumes from the identity correction state; transient material remains under the existing ZG-013 ownership/mask rather than being spectrally retuned.

## Reconstruction and identity

Only transformed sinusoidal ownership is resynthesised. The accepted ZG-013 transient and residual arrays are copied unchanged into the result and added back after the transformed sinusoidal component.

If `amount == 0`, or if no frame receives a non-zero correction, output audio takes the declared exact `exact_bypass(source)` path. It does not reconstruct components and claim approximate nulling as bypass.

The transformed `PartialTrackBundle` remains schema-valid. The result exposes source, transformed sinusoidal ownership, unchanged transient/residual ownership, final audio, engineering diagnostics and an inspection payload.

## Bounded job adapter

`submit_retune_job()` submits the transform as a normal bounded `JobClass.RENDER` job. The executor checks cooperative cancellation during planning and before publication of the typed result, and reports monotonic progress through the existing scheduler.

## Acceptance evidence

`tests/spectral/test_spectral_retune.py` covers exact bypass, harmonic/inharmonic target construction, isolated retuning, scheduled target changes and slew limits, crossing-track abstention, unchanged transient/residual arrays, stereo antiphase preservation, request validation and bounded job execution.

`tools/spectral_retune_report.py` generates deterministic 48 kHz engineering evidence on CI. It records exact-bypass PCM identity, realised-target error, transformed-output target/source-bin power, inter-channel phase error, transient/residual identities and target-change slew excess. These are synthetic engineering controls, not listening results or claims about musical preference.

## Deliberate exclusions

ZG-017 does **not** implement amplitude reweighting, hybrid/Chordness optimisation, adaptive tuning, automatic sonority inference, pre/post/inter-nonlinearity placement, or a new DSP graph. Those remain downstream work (notably ZG-018 and ZG-019). Existing `locked_bloom` defaults and DSP ordering are unchanged.
