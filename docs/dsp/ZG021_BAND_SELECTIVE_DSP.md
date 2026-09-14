# ZG-021 band-selective tuning, compression and bitcrush

ZG-021 composes the accepted ZG-016 effect-delta multiband router with ZG-017/ZG-018 spectral transforms and new bounded compression/bitcrush primitives. It does not replace the dry crossover layer: the dry path stays intact and selected-band processing is added as an effect delta.

## Four-band routing

The fixed band names are `sub`, `lowmid`, `highmid`, and `air`. Crossovers are explicit in every `BandSelectiveRequest`. The filter policy is versioned as `zg.butter4_sosfiltfilt_effect_delta.v1`: fourth-order Butterworth SOS filters with offline zero-phase `sosfiltfilt` execution and zero declared sample latency.

Reconstruction remains:

`output = dry + sum(routed effect delta)`

The dry source is never split and recombined. This makes an all-identity request an exact PCM identity path rather than an approximate crossover reconstruction.

## Per-band slots

Each selected band may contain, in an explicitly persisted order:

- `spectral`: either a ZG-017 `SpectralRetuneRequest` or ZG-018 `ChordnessRequest` (including reweight/hybrid modes);
- `gain`: fixed linear gain from an explicit dB value;
- `compression`: a `CompressionSpec`;
- `bitcrush`: a `BitcrushSpec`.

The stage order is serialized in the request. No final normalization is applied; master gain is fixed at 0 dB in the experiment recipe.

## Compression semantics

`CompressionSpec` is a feed-forward linked-peak compressor. The detector is the maximum absolute channel amplitude at each sample. Static gain reduction follows threshold/ratio with optional soft knee. Attack and release smooth the **gain-reduction control signal**, not the audio waveform itself. The result exposes detector dB, static gain reduction, smoothed gain reduction and audio separately.

`ratio == 1` with zero makeup gain is an exact identity path. `wet == 0` is also exact identity. Makeup gain is explicit and therefore ratio-one plus nonzero makeup is intentionally not identity.

## Bitcrush and sample hold

`BitcrushSpec` uses a deterministic signed uniform round-to-nearest quantizer, no dither, and a sample-0-anchored hold period. It performs no hidden normalization. `wet == 0` is exact identity.

Quantization and sample hold intentionally create spectral images/alias components. The recipe records this alias policy. ZG-021 does not pretend the texture is alias-free; instead the band router controls whether the generated effect delta is reconfined.

## Confinement and deliberate spill

Each band has an independent `confine_delta` flag.

- `true`: the effect delta is projected back through the selected crossover band before addition to the dry signal;
- `false`: the raw effect delta is added, deliberately permitting generated content outside the selected pocket.

`BandDeltaReport` records raw/routed delta RMS and the routed delta projected into every band. This makes leakage and intentional spill directly measurable.

Confinement is the default. Spill is an explicit experiment axis, not an accidental side effect hidden in a processor.

## Uncertainty ownership

Spectral slots retain ZG-017/ZG-018 confidence and continuity policies. An isolated selected band is analysed using the accepted component model, and low-confidence/ambiguous partials remain preserved rather than being forced onto targets. Compression and bitcrush do not alter those source confidence semantics.

## Identity and protected pockets

The acceptance suite includes exact identity gates for:

- no selected processors;
- zero-wet compression;
- ratio-one compression with zero makeup;
- zero-wet bitcrush;
- zero-gain/identity composite slots.

The frozen evidence fixture includes a 60 Hz sub pocket, a 330 Hz low-mid `SYNTHLINE` pocket, an 890 Hz selected high-mid carrier and an air reference. The high-mid pocket receives compression, spectral retune and bitcrush. With effect-delta confinement enabled, sub and SYNTHLINE delta energy must remain below the declared leakage allowance relative to the selected high-mid delta.

A second render disables high-mid confinement. It must measurably increase total outside-selected effect-delta energy, demonstrating that deliberate spill is a real, inspectable option rather than a documentation-only toggle.

## Reproducibility

`examples/zg021_band_selective.json` freezes sample rate, source partials, crossovers, processing settings, stage order, leakage allowance and output policy. `tools/band_selective_report.py` records:

- exact identity hashes;
- confined and spill hashes;
- delta RMS by band;
- protected-pocket leakage;
- selected spectral changed-frame count;
- compressor gain-reduction/control metadata;
- bitcrush alias policy;
- complete request/filter/stage inspection.

These are engineering isolation/texture measurements, not listening-preference claims.
