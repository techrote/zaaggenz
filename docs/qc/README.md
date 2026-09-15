# Audio QC v1

ZG-005 establishes synthetic ground truth and regression checks **before** advanced spectral methods are allowed to influence the instrument. Reference recordings are not used as ground truth here.

## Fixture catalogue

Version `zg-qc-fixtures-v1` generates silence, impulse, sine, harmonic/stretched combs, AM, integrated-phase FM, chirp, crossing chirps, seeded band-limited noise, transient+tone, three stereo phase relationships, and an intentional >1.0 floating signal. Every fixture records sample rate, channel count, generation rule and automated/listening provenance.

## Diagnostics versus certification

`zg-qc-diagnostics-v1` reports finite fraction, peak, RMS, crest, DC, channel diagnostics and fraction of samples at/above unit magnitude. Analysis uses floating input directly; **it does not clamp at +/-1**. `diagnose()` is intentionally descriptive: non-finite samples are excluded from level arithmetic and exposed through `finite_fraction`, so a corrupted signal can still be described without pretending that description certifies it.

The public `check_*` acceptance functions are stricter. They fail closed before tolerance comparison when required audio, a control/tolerance, or a required derived metric is NaN or ±Inf. They do not coerce invalid values to zero or rely on Python/NumPy's `NaN` comparison behaviour. Finite but very large master-check signals use scale-safe RMS arithmetic so overflow in the QC calculation itself cannot turn valid finite input into an undefined ratio.

Identity tests are exact when the declared path should be transparent. Tolerant identity requires an explicit finite, nonnegative `atol`/`rtol` and latency. Source preservation additionally removes one best-fit scalar gain before measuring residual error, so a harmless gain change is not confused with waveform/timbre flattening.

For zero-variance source-preservation inputs, Pearson correlation is mathematically undefined; v1 retains an explicit deterministic diagnostic convention rather than fabricating a Pearson value: bit-identical degenerate arrays report correlation `1`, otherwise degenerate pairs report `0`. The gain-aligned residual remains the certification quantity. Digital silence compared with itself therefore has finite gain/error diagnostics and zero relative residual; a constant signal compared with a pure scalar multiple may have correlation `0` under this degenerate convention while still correctly passing the gain-aligned shape check. These values are engineering sentinel semantics, not statistical correlation claims.

## Regression sentinels

CI deliberately proves it can detect:
- a missing full `SYNTHLINE` stem in reversebass combined output;
- a strongly flattened/clipped SYNTHLINE;
- one-sample/data perturbation of an exact bypass;
- cache-independent master gain ratio errors;
- NaN/±Inf in every public QC acceptance path;
- non-finite master controls and arithmetic overflow before comparison;
- stem shape/nonfinite failures and impulse misalignment.

The tests also positively retain transparent SCULPT identity, valid zero/constant source-preservation semantics, scale-safe huge-finite master checks and the existing full combined stem inventory.

## Tolerance tiers

| Tier | Purpose | Typical rate | Evidence |
|---|---|---:|---|
| exact | bypass/data ownership | 12/48 kHz | bit/array equality where specified |
| numerical | algorithms with unavoidable floating variation | declared per test | explicit atol/rtol/latency |
| full-rate automated | release candidate diagnostics | 48 kHz | same metrics plus baseline contracts |
| listening | artistic/default validation | 48 kHz or export rate | separately level-matched owner/listener evaluation |

Passing small CI never substitutes for listening approval. Every generated report states sample rate and `evaluation_mode`. A diagnostic record containing `finite_fraction < 1` is evidence of invalid/corrupted audio for any acceptance check that requires the signal; downstream tools must not reinterpret its other finite descriptive fields as a pass.
