# ZG-014 calibrated acoustic / harmonic / target-comb descriptors

ZG-014 provides **separate, evidence-labelled measurements** for signal periodicity, modulation, spectral occupancy, component harmonicity, relative pairwise roughness and target-comb fit. No single score is presented as musical quality, consonance, pleasure, arousal, dopamine or preference.

## Contract boundary

ZG-002 `FeatureBundle` version `1.0.0` is frozen and its feature enum is not widened in place. ZG-014 therefore publishes a separate immutable `zaaggenz-descriptors` `1.0.0` bundle. Each observation stores:

- metric and human-facing evidence label;
- exact method ID and method version;
- unit;
- `measurement` versus `estimate` role;
- `valid`, `unknown` or `abstained` state;
- explicit confidence for estimates;
- half-open sample support and padding policy;
- bounded method details/assumptions.

For every non-empty source, `anchor_sample` is always a real source frame: `0 <= anchor_sample < frame_count`, including when `padding` is `zero` or `reflect`. Padding may extend `start_sample` below zero or `end_sample` beyond `frame_count`; it does not move the anchor outside the source. With `padding: none`, the entire half-open support must remain inside the source. This is deliberately the same anchor rule enforced by frozen `FeatureBundle` v1, so a DescriptorBundle admitted for a non-empty asset cannot later fail compatibility projection merely because of padded support geometry.

A zero-frame source has no in-source anchor. DescriptorBundle `1.0.0` therefore retains its existing explicit padded placeholder support for empty-source measurements/abstentions, while `feature_projection()` emits no FeatureBundle observations for that source. It does not invent an anchor to satisfy the frozen contract. This is a validator correction within the existing descriptor format: unaffected valid bundles keep identical serialization and hashes, while previously admitted padded observations with an out-of-source anchor are rejected at DescriptorBundle construction.

`feature_projection()` deliberately projects only the four measurements already representable in frozen FeatureBundle v1: RMS, f0 candidate, relative roughness and balanced target-comb fit. Unknown/abstained estimates are converted to the frozen v1 null-value/null-confidence convention. Rich metrics stay in the descriptor bundle.

## Audio-domain measurements

### RMS level — `zg.rms.v1`

All source samples/channels have equal weight. RMS is a measured linear amplitude and is intentionally level-dependent.

### Periodicity and f0 candidate — `zg.periodicity.acf.v1`

The highest-energy channel is analysed rather than summing stereo, so antiphase material cannot cancel into false silence. DC is removed. An overlap-corrected FFT autocorrelation is searched over the configured f0 band. Local lag peaks are parabolically interpolated. Near-equal periodic maxima prefer the shortest lag and the report records alternate candidates plus an octave-ambiguity flag.

A low autocorrelation peak becomes `unknown` rather than a forced f0. Silence/constant-after-DC-removal and insufficient support abstain. The estimator is deliberately a candidate generator, not a universal pitch tracker for arbitrary mastered noise walls.

### Envelope modulation — `zg.envelope.rmsmod.v1`

A 20 ms RMS envelope at a 5 ms hop is measured on the highest-energy channel. Modulation depth is `std(envelope)/mean(envelope)`. A Hann-windowed envelope spectrum searches 0.5–30 Hz for a dominant modulation candidate. Near-constant envelopes abstain from modulation frequency instead of reporting 0 Hz.

### Spectral occupancy — `zg.spectral.occupancy.v1`

Welch power spectra are computed per channel and averaged in power (again avoiding stereo cancellation). In the 20 Hz to min(20 kHz, Nyquist) band, occupancy is

`exp(Shannon entropy of normalized power) / number of analysed bins`.

The result is in [0,1], is invariant to global gain in exact arithmetic, and distinguishes concentrated spectra from broadly occupied spectra. It is **not** a brightness or quality score.

## Component-domain measurements

ZG-013 partial tracks are reduced to a bounded anchor-time snapshot: for each track, the frame nearest the requested support anchor is selected; amplitude is channel RMS; analysis weight is amplitude × component confidence. Only the highest-weight `component_cap` components are used and both used/available counts are reported.

### Harmonic-comb fit — `zg.components.harmonicity.v1`

Given an explicit f0, each component is compared with its nearest positive integer harmonic. Absolute cents mismatch is converted to a Gaussian match with configurable cents tolerance and averaged by amplitude × confidence. This is a component/comb alignment measure. It does not imply pleasantness, key, chord identity or listener preference.

### Relative pairwise roughness — `zg.components.roughness.v1`

For each component pair, ZG-014 uses a Sethares-style two-exponential interaction kernel with frequency-dependent scale `0.24/(0.021*f_low + 19)`. The kernel is normalized by its mathematical maximum, then averaged with pair weights `(amplitude×confidence)_i × (amplitude×confidence)_j`.

This implementation is intentionally **global-gain invariant**. It is therefore a relative spectral-spacing descriptor, not an absolute loudness-dependent sensory-dissonance model. The distinction is recorded in every observation. Later psychoacoustic work may add calibrated level-dependent models under separate method IDs.

## Target-comb measurements — `zg.target_comb.v1`

A target comb is an explicit, sorted set of frequencies below Nyquist. Four quantities are kept separate:

- **source coverage:** amplitude/confidence-weighted source-component → nearest-target Gaussian fit. Adding more target teeth can only improve or preserve this raw term, so its density bias is stated in the label/details;
- **target precision:** equal-weight target-to-nearest-source support;
- **balanced fit:** harmonic mean of coverage and precision;
- **mean absolute mismatch:** weighted source-to-nearest-target cents distance;
- **target density:** number of teeth, stored as a measured control variable.

This split exists specifically to prevent the common error where a denser target comb appears “better” merely because it has more chances to be close to every observed component.

## Analysis window and computational bound

`analyse_descriptors()` accepts an explicit excerpt and refuses inputs longer than `DescriptorAnalysisSpec.max_samples` (262,144 samples by default). It does **not** silently crop a long track while claiming full-track support. Upstream callers must select/record a specific excerpt. All observations then use that excerpt’s exact `AudioAssetRef` and sample support.

ZG-013 component analysis must reference the exact same float32 PCM asset. A supplied partial bundle whose content/sample-rate/channel/frame identity differs is rejected.

## Calibration and sensitivity

`tools/descriptor_fixture_report.py` generates deterministic synthetic controls covering 55/220/880 Hz tones, noise, silence, constant DC, 4 Hz AM, global-level sweeps, harmonic versus inharmonic component sets, clustered-but-harmonic roughness, cents-tolerance sensitivity and sparse/dense target-comb bias. The CI artifact is numerical evidence only.

Private reference calibration is separate and local-only. `tools/descriptor_reference_report.py` requires the ZG-006 locator file, verifies every private file’s exact hash/byte identity, decodes only selected annotated excerpts with FFmpeg, and writes descriptor JSON with source hashes and annotation provenance. It never writes source audio or locator paths. The currently committed paired suggestions are automatic zero-confidence candidates; their presence is **not** treated as validated correspondence.

Example local command after creating a private locator file:

```sh
python tools/descriptor_reference_report.py --locators references/private/locator.json --out local-descriptors.json
```

Do not commit that output without checking whether its metadata is appropriate to publish; never commit the source recordings or locator file.

## Verification

From repository root:

```sh
python -m pip install numpy==2.3.5 scipy==1.17.0 -r requirements-contracts.txt
python -m unittest discover -s tests/descriptors -v
python tools/descriptor_fixture_report.py --out descriptor-fixtures.json
```

Linux/Windows CI runs the same synthetic calibration. The inherited contract workflow remains active. See `FAILURE_CATALOGUE.md` for known failure modes and interpretation boundaries.
