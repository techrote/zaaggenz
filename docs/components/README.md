# ZG-013 harmonic-component analysis and reconstruction

`zaaggenz_components` converts measured mono/stereo audio into versioned `PartialTrackBundle` contracts while retaining explicit transient and residual ownership. It is an analysis foundation for later spectral tuning; it is **not** a completed spectral Auto-Tune or a quality metric.

## Analysis

The tracker uses a periodic-Hann STFT with explicit support, zero-padded FFT interpolation and bounded peak selection. Candidate frequencies are refined in log magnitude, then all candidates in a frame are fit simultaneously in the time domain with weighted cosine/sine least squares. Stereo uses one frequency trajectory with independent per-channel amplitude/phase coefficients, so antiphase material is not collapsed by mono summation.

Frame confidence combines peak-to-floor evidence, spectral flatness and fit conditioning. High-flatness/noisy frames can abstain. Tracks use predicted log-frequency motion plus a bounded Hungarian assignment. Candidate merges/crossings that are compatible with more than one trajectory mark the affected track continuity `unknown`; the contract then forbids automatic transformation for that track rather than pretending local frequency accuracy proves identity through the crossing.

## Phase convention

Each exported phase is the cosine phase at the frame's declared anchor sample. Supports are half-open sample intervals with explicit zero padding. `continuous`, `reanchored` and `unknown` are distinct. Later transformation code must respect each frame's `action` and may not infer permission from reconstruction quality alone.

## Transient and remainder ownership

A conservative transient mask is derived from short-resolution spectral flux plus a robust sample-derivative sentinel. Sinusoidal reconstruction is removed inside the protected transient region. The transient asset owns the original audio under that mask; the residual is defined as source minus protected sinusoidal and transient ownership. Their float32 PCM identities are embedded in the bundle.

This gives two deliberately separate checks:

1. **Exact bypass:** `exact_bypass()` is a float32 source copy and must be sample-identical.
2. **Analysis/reconstruction:** sinusoidal + transient + residual is measured against the normalized source. Small arithmetic error is reported; passing it does not prove the components are safe to move.

The separation directly addresses the preflight counterexample where an algebraically perfect residual reconstruction could still produce severe ghost energy after retuning a slightly wrong component.

## Known limits

This v1 tracker is aimed at resolved or moderately overlapping sinusoidal structure. It does not claim robust decomposition of a fully mastered zaag wall, arbitrary polyphonic mixtures, or perceptually correct identity through all crossings. Dense/noisy frames are allowed to abstain. Later ZG-017 must test transformed ghost energy, not merely bypass reconstruction.

## Validation

```sh
python -m pip install numpy==2.3.5 scipy==1.17.0 -r requirements-contracts.txt
python -m unittest discover -s tests/components -v
python tools/component_fixture_report.py --out component-fixtures.json
```

Fixtures cover stable tones, chirps, amplitude modulation, crossings, white noise, impulses, empty/short signals and stereo antiphase. The report is deterministic synthetic evidence, not a listening result.
