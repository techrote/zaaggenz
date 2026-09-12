# v1.2.1 recovery test / limitation register

## Executed recovery checks

Fifteen checks were executed in the recorded recovery environment: Python compilation, JavaScript syntax validation, and all 13 recovered `*_smoke.py` scripts. **All passed.** No failing recovered test has been hidden or rewritten.

Representative observed outputs:

- arrangement smoke: 11.0 s, 47 events, 15 rolls
- audio headroom: arrangement crest 10.655 dB; guard engagement 0.000463; reversebass crest 9.931 dB
- intuitive UI: 27 presets, 20 macros, 136 default events, 72 default rolls
- inverse smoke: baseline score 0.358593 → best 0.350155, 133 evaluations
- multistage inverse: score 0.307814, 354 evaluations
- live preview: BPM bounds 20–360; 48 kHz preview rows valid
- reversebass: root continuity 0.7971; complement envelope correlation -0.9000
- source preservation: flatness 0.04547 versus legacy 0.16417
- spectral sculpt reconstruction RMS: `1e-10`
- UI cache regression: versioned assets and `no-store` pass
- UI theme/master regression: 6 themes; -6 dB master ratio 0.5011873; 4 title-bar render modes

The exact frozen source/preset/render/API identities are in `baseline/V1_2_1_CONTRACT.json`.

## Known boundaries that are not test failures

- The internal package name remains `uptempo_harmony`; ZG-001 deliberately does not rename it.
- Existing inverse synthesis is principally one-event morphology. It does not infer an entire stateful reversebass/arrangement graph from a mastered recording.
- Existing arrangement analysis is not the future phrase-role/expectation engine.
- Current multiband processing is the recovered production baseline. Preliminary research found an effect-delta confinement topology worth investigating later; ZG-001 must not silently substitute it.
- Source-preserving arrangement behaviour is intentional and protected. Legacy per-event re-synthesis remains an opt-in comparison path.
- `locked_bloom` intentionally contains strong nonlinear processing. Compatibility work must not optimise it toward lower roughness, lower flatness or less clipping simply because those metrics look cleaner.
- Output filenames may contain random/time tokens. Compatibility goldens therefore freeze recipes, arrays/PCM, statistics and API semantics rather than path names.
- Browser theme/master persistence uses local storage and does not redefine built-in defaults.
- Strict raw float hashes are environment-specific. Cross-environment compatibility must use the structural/numerical contract rather than pretending every platform produces bit-identical floating point.

## What source recovery resolves

Recovery now gives downstream tasks concrete modules, schemas, renderer order, UI control identities, preview/master semantics and the real smoke suite. Earlier research can therefore be adapted against actual code instead of guessed paths.

## What remains external

- owner listening approval before any default artistic sound changes;
- explicit licence decisions for new third-party dependencies;
- protocol/consent/statistical gates before human confirmatory studies;
- issue-specific acceptance evidence for each subsequent implementation.

Passing ZG-001 is a baseline gate, not evidence that later spectral/harmonic/rhythmic features are already correct.
