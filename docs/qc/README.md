# Audio QC v1

ZG-005 establishes synthetic ground truth and regression checks **before** advanced spectral methods are allowed to influence the instrument. Reference recordings are not used as ground truth here.

## Fixture catalogue

Version `zg-qc-fixtures-v1` generates silence, impulse, sine, harmonic/stretched combs, AM, integrated-phase FM, chirp, crossing chirps, seeded band-limited noise, transient+tone, three stereo phase relationships, and an intentional >1.0 floating signal. Every fixture records sample rate, channel count, generation rule and automated/listening provenance.

## Diagnostics

`zg-qc-diagnostics-v1` reports finite fraction, peak, RMS, crest, DC, channel diagnostics and fraction of samples at/above unit magnitude. Analysis uses floating input directly; **it does not clamp at +/-1**. This matters for diagnosing mastered/decoded audio and internal buses.

Identity tests are exact when the declared path should be transparent. Tolerant identity requires an explicit `atol`/`rtol` and latency. Source preservation additionally removes one best-fit scalar gain before measuring residual error, so a harmless gain change is not confused with waveform/timbre flattening.

## Regression sentinels

CI deliberately proves it can detect:
- a missing full `SYNTHLINE` stem in reversebass combined output;
- a strongly flattened/clipped SYNTHLINE;
- one-sample/data perturbation of an exact bypass;
- cache-independent master gain ratio errors;
- stem shape/nonfinite failures and impulse misalignment.

The tests also positively retain transparent SCULPT identity and the existing full combined stem inventory.

## Tolerance tiers

| Tier | Purpose | Typical rate | Evidence |
|---|---|---:|---|
| exact | bypass/data ownership | 12/48 kHz | bit/array equality where specified |
| numerical | algorithms with unavoidable floating variation | declared per test | explicit atol/rtol/latency |
| full-rate automated | release candidate diagnostics | 48 kHz | same metrics plus baseline contracts |
| listening | artistic/default validation | 48 kHz or export rate | separately level-matched owner/listener evaluation |

Passing small CI never substitutes for listening approval. Every generated report states sample rate and `evaluation_mode`.
