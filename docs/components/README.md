# ZG-013 harmonic-component analysis and reconstruction

`zaaggenz_components` converts measured mono/stereo audio into versioned `PartialTrackBundle` contracts while retaining explicit transient and residual ownership. It is an analysis foundation for later spectral tuning; it is **not** a completed spectral Auto-Tune or a quality metric.

## Analysis

The tracker uses a periodic-Hann STFT with explicit support, zero-padded FFT interpolation and bounded peak selection. Candidate frequencies are refined in log magnitude, then all candidates in a frame are fit simultaneously in the time domain with weighted cosine/sine least squares. Stereo uses one frequency trajectory with independent per-channel amplitude/phase coefficients, so antiphase material is not collapsed by mono summation.

Frame confidence combines peak-to-floor evidence, spectral flatness and fit conditioning. High-flatness/noisy frames can abstain. Tracks use predicted log-frequency motion plus a bounded Hungarian assignment. Candidate merges/crossings that are compatible with more than one trajectory mark the affected track continuity `unknown`; the contract then forbids automatic transformation for that track rather than pretending local frequency accuracy proves identity through the crossing.

## Phase convention

Each exported phase is the cosine phase at the frame's declared anchor sample. Supports are half-open sample intervals with explicit zero padding. `continuous`, `reanchored` and `unknown` are distinct. Later transformation code must respect each frame's `action` and may not infer permission from reconstruction quality alone.

## Transient and remainder ownership

A conservative transient mask is derived from short-resolution spectral flux plus a robust sample-derivative sentinel. Sinusoidal reconstruction is removed inside the protected transient region. The transient asset owns the original audio under that mask; the residual is defined as source minus protected sinusoidal and transient ownership. Their float32 PCM identities are embedded in the bundle.

Transient analysis uses the versioned `zg013-transient-detector-fail-closed-v1` policy. A successfully computed short-resolution timeline with at least one full-support spectral-flux observation runs in `multiresolution-flux-plus-derivative-v1` mode. The sample derivative is a second conservative sentinel; it is not an exception-recovery path.

There is deliberately **no exception-based derivative-only fallback**. `analyse_multiresolution()` programming errors, dependency failures and resource failures propagate with their original exception type; cancellation-style `BaseException` failures are not intercepted. The tracker adds context to ordinary propagated exceptions stating that no derivative-only fallback was used. A successful timeline that contains no full-support short-resolution flux observations is the only degraded non-empty mode: `derivative-only-degraded-v1`. This is recorded as a `data-level-abstention` with reason `no-full-support-short-flux`, and **all component frames are forced to `preserve`**. The derivative sentinel may still increase transient protection in that state, but missing primary confidence can never become transform permission. Empty input similarly records `empty-source-v1` with preserve-all eligibility.

Detector policy, primary detector, sentinel, mode, failure class/reason and transform-eligibility policy are copied into both `ComponentAnalysis.diagnostics["transient_detector"]` and the `PartialTrackBundle.method.configuration` fields prefixed `transient_`. This makes any supported degraded analysis provenance-visible without changing the v1 contract shape or audio identity domain.

This gives two deliberately separate checks:

1. **Exact bypass:** `exact_bypass()` is a float32 source copy and must be sample-identical.
2. **Analysis/reconstruction:** sinusoidal + transient + residual is measured against the normalized source. Small arithmetic error is reported; passing it does not prove the components are safe to move.

The separation directly addresses the preflight counterexample where an algebraically perfect residual reconstruction could still produce severe ghost energy after retuning a slightly wrong component.

## Aggregate identity boundary

A `ComponentAnalysis` is accepted only when its contract and concrete arrays describe the same source observation. The caller supplies the trusted sample rate separately from the bundle. The bundle's `asset`, `transient_asset`, and `residual_asset` must all use `pcm-f32le-interleaved-v1`; each is checked against the corresponding finite array for exact frame count, channel count, mono/stereo layout, sample rate, and SHA-256 of canonical C-order little-endian float32 PCM bytes. This is the same PCM content-identity rule used by the artifact cache; component analysis does not introduce a second audio-identity interpretation.

Source, sinusoidal, transient, and residual arrays must have exactly the same shape and contain only finite numeric values. The transient mask is one-dimensional, finite, and exactly source-length. No aggregate constructor path truncates, pads, reshapes, or silently repairs mismatches. One-dimensional mono and `N×1` mono intentionally have the same canonical PCM content identity (`channels=1`, `channel_layout=mono`), but an already-formed aggregate does not coerce between those shapes.

`reconstruct_components()` retains portable bundle-only reconstruction for a validated `PartialTrackBundle`. When a concrete source is available, callers pass it together with its trusted sample rate; the source asset is then bound before any output allocation and the allocation extent comes from the concrete source, not untrusted bundle metadata. Tracker and spectral-retune paths use this bound form.

## Known limits

This v1 tracker is aimed at resolved or moderately overlapping sinusoidal structure. It does not claim robust decomposition of a fully mastered zaag wall, arbitrary polyphonic mixtures, or perceptually correct identity through all crossings. Dense/noisy frames are allowed to abstain. Later ZG-017 must test transformed ghost energy, not merely bypass reconstruction.

## Validation

```sh
python -m pip install numpy==2.3.5 scipy==1.17.0 -r requirements-contracts.txt
python -m unittest discover -s tests/components -v
python tools/component_fixture_report.py --out component-fixtures.json
```

Fixtures cover stable tones, chirps, amplitude modulation, crossings, white noise, impulses, empty/short signals and stereo antiphase. Transient-failure regressions additionally cover normal detector provenance, the supported no-primary-observation degraded mode, programming/dependency/resource exception propagation, cancellation propagation, preserve-all eligibility under degradation, and transient-protected frame ownership. Aggregate identity regressions additionally cover forged frame/channel/sample-rate/content identity, transient/residual provenance, non-finite arrays, concrete-source allocation bounds, mono canonicalization, zero-track inputs, and large legitimate zero-track inputs. The report is deterministic synthetic evidence, not a listening result.
