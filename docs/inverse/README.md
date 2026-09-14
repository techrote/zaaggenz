# ZG-024a inverse-search laboratory

**Status:** first serial implementation of **ZG-024 / issue #25**, not completion of that issue. The recovered inverse remains available and unchanged. This package provides an offline, bounded experimental substrate; it does not select the production optimizer, change product defaults, or identify an original production chain.

Read [the recovered benchmark](RECOVERED_BASELINE.md) and [research handoff 1](ZG024_RESEARCH_HANDOFF_1.md) before proposing a new strategy. The tested starting tree is `6e0153d824608d6a9899c5ea8e8c0b9a29688c98`.

## Accepted ownership and reuse

| Accepted prerequisite | Reused implementation / contract | Boundary retained |
|---|---|---|
| ZG-003 | `zaaggenz_project.Project`, revision digest and `cache_key` | Committed source identity is not UI audition state. Candidate exports are ordinary editable `RenderRecipe` values. |
| ZG-004 | `JobScheduler`, `JobClass.RESEARCH`, cancellation/progress, memory admission, numeric thread limit and atomic publishing | No parallel scheduler, background service or distributed executor. |
| ZG-005 | `diagnose`, `source_preservation`, synthetic-first engineering evidence | Gain-aligned similarity is diagnostic only, never a replacement for raw level/waveform loss. |
| ZG-014 | accepted periodicity, occupancy, descriptor analysis and observation validity | Abstention stays null; no fabricated zero loss or listener-preference score. |
| ZG-018 | accepted `CombTemplate` and `evaluate_union` Chordness descriptors | Source/target comb coverage and balanced fit remain interpretable observations. |
| ZG-019 | accepted explicit nonlinear graph / antialiased stages and `transient_metrics` | Stage order, source normalization and final gain are declared; transient measurements retain physical channels. |
| ZG-020 | `DissonanceModelSpec`, `TimbreSpectrum`, `spectrum_from_partial_bundle`, `interaction_roughness` | L1 amplitude normalization is explicit; the tuning model does not redefine level fidelity. |
| Shared ZG-002/012/013 | `Contract`, `zg-c14n-v1`, `derive_seed`, numeric registry, `AudioAssetRef`, STFT, `AnalysisCache`, `PartialTrackBundle` | No widened frozen schemas, duplicate source representation, alternative hash format, or invented spectral tracker. |

These are implementations and tests present on the accepted main tree, not inferred acceptance from issue closure. Their authoritative documentation lives in `docs/project`, `docs/jobs`, `docs/qc`, `docs/descriptors`, `docs/spectral/ZG018_MULTI_COMB_CHORDNESS.md`, `docs/dsp/ZG019_SPECTRAL_PLACEMENT.md`, and `docs/analysis/ZG020_ADAPTIVE_TUNING.md`.

## API and experimental boundary

```python
from zaaggenz_inverse.fixtures import synthetic_fixture
from zaaggenz_inverse import run_grid

fixture = synthetic_fixture('holdout-step')  # experiment owner only
fit, audit = fixture.experiment()
result = run_grid(fit)                     # cannot receive fixture/truth/holdouts
selection = result.audit_selection(all_candidates=True)  # freeze before audit
reports = [audit.evaluate(c, selection) for c in result.candidates]
editable_recipe = result.candidates[0].recipe  # does not apply to project/defaults
```

For real inputs, use `request_from_project(existing_project, target_pcm, window_plan, domain, ...)`, then `prepare_experiment(request, target_pcm, window_plan)`. The existing project supplies the source revision; the target is an existing content-addressed `AudioAssetRef` of canonical **f32 little-endian PCM**, with no import normalization. `(n,)` and `(n,1)` mono inputs canonicalize to the same shape and identity. Standalone measurements retain stereo as two physical channels, so downmix cancellation cannot hide lost content; the initial legacy-exact recipe adapter is mono.

`FitEvaluator` copies only fit excerpts into independent immutable arrays. It receives target metadata/hash, **not** full target audio, holdout samples, ground truth, or fixture names. Each excerpt is analyzed locally, including its padding; analysis is never performed over a whole target and then sliced. Tests modify both holdouts and samples immediately outside fit boundaries without changing fit results or grid order. Whole-render shape/non-finite checks are structural checks, not comparisons against unobserved target content.

`AuditEvaluator` owns the independent target and `WindowPlan`. It evaluates frozen candidate IDs only, re-renders each recipe, and records holdout, whole-signal and frozen-fit values separately. It cannot revise fit rank or the fit Pareto frontier. Its exploratory overfit warning is **fit score < 0.05 and holdout minus fit > 0.25**; this is not a statistical significance test. Repeated researcher inspection can still contaminate a holdout: later passes should reserve a genuinely untouched final test set. Python capability separation prevents accidental leakage, not malicious introspection of the orchestration process.

## Small versioned contracts

All new envelopes are `1.0.0`, finite, serializable and canonically hashed through the accepted tagged exact-binary-rational `zg-c14n-v1` implementation. Unknown/missing fields and unsupported versions fail rather than migrate silently.

| Type | Responsibility |
|---|---|
| `ParameterAxis`, `ParameterDomain`, `ParameterState` | Canonical recipe pointers, explicit inclusive units/bounds, continuous or integer type, exact parameter set and immutable candidate values. |
| `Window`, `WindowPlan` | Named half-open sample intervals; non-overlap across fit and holdout, exact target frame count and explicit support. |
| `SearchStage`, `SearchBudget` | Method/version, stage ID, parent search/candidate identities; grid resolution and deterministic evaluation count. |
| `ObjectiveTerm`, `ObjectivePolicy` | Retained component name, units, positive scale, weight, rich-descriptor request and explicit Pareto axes. |
| `ValidationPolicy` | Independent engineering thresholds and explicitly labeled permitted exceptions. |
| `SearchRequest` | Composition of existing recipe/asset/revision with the small contracts, fit windows and string-u64 root seed. No holdout data. |
| `RenderTrace`, `Candidate` | Source/pre-master/post-gain/output provenance, reproducibility state, fit measurements, validation state, editable recipe, vector and lineage. |
| `Checkpoint`, `SearchResult`, `AuditSelection` | Completed-prefix replay lineage, retained archive/ranks/frontier, and frozen post-search audit selection. |

Candidate parsing checks parameter state against its editable recipe, candidate/render/feature identities, aggregate against individual window measurements, and scalar/Pareto scaling against the retained components. Persisted candidate records are consistency-checked, not externally authenticated proofs; replay remains the authority on actual rendering.

The initial binding supports numeric source parameters, existing graph-node parameters, registered automation-point values, and explicit final master gain. Registry bounds and units remain authoritative; inverse bounds may narrow but never extend them. Linked source f0/tuning and seed fields are rebuilt through `freeze_legacy`. Unsupported enum axes, source families, changing timeline length, and implicit SCULPT integration fail explicitly. The pass is deliberately limited to single-beat mono legacy-exact synth recipes, at most 262,144 samples, 16 axes, 16 total declared windows and 256 logical evaluations. Windows need at least 32 samples. Rich sonority experiments require targets no longer than 16,384 samples; no hidden truncation occurs.

## Objectives, units and scaling

For reference `r` and candidate `c`, RMS uses physical samples/channels. `epsilon = 1e-8` linear amplitude is an explicit floor. No waveform alignment, fitted gain, peak normalization or normalizing output stage is added by the objective.

| Component | Measurement / unit | Interpretation |
|---|---|---|
| waveform | `RMS(c-r) / max(RMS(r), epsilon)`; relative RMS | Zero is sample agreement. Inverted polarity can be 2 despite identical spectra. |
| spectrum | `norm(abs(STFT(c))-abs(STFT(r))) / max(norm(abs(STFT(r))), epsilon)`; relative magnitude L2 | Absolute-level-sensitive magnitude error; phase is deliberately absent. STFT: 256-sample window, 64 hop, 512 FFT. |
| level | Absolute `20*log10(max(RMS(c),epsilon)/max(RMS(r),epsilon))`; dB | Independent level loss; signed delta, both RMS values and raw RMSE are also retained. |
| periodicity / occupancy | Absolute difference of existing descriptor observations; descriptor units | Feature agreement, with descriptor validity/abstention retained. |
| comb_fit | Absolute difference of accepted balanced target-comb fit; unit interval | Not an inferred chord label or listener judgment. |
| roughness | Absolute difference of accepted within-spectrum relative roughness; model units | Matching an observation, not universally minimizing roughness. |
| interaction | Absolute difference of accepted timbre interaction against a fixed declared anchor; model units | L1-normalized compatibility measurement, never a substitute for raw energy checks. |

The analysis anchor comes from the **base recipe's declared tuning**, not fixture truth or hidden target estimation. Exact descriptor/component specs and method hashes are recorded. Rich records retain descriptor bundles, partial-bundle identity, component validity and Chordness/timbre observations. Inactive rich components are null, not zero.

Across windows, each component is equal-window RMS (not duration weighting). A null observation on any window remains null. The optional search scalar is `sqrt(sum(weight*(component/scale)^2)/sum(weight))` over positive weights. Default active axes are waveform, spectrum and level; level's scale is 6 dB, other scales are 1. All eight component losses remain in records. Explicit zero-weight terms remain Pareto axes but do not influence the scalar. An unknown active component makes the scalar non-comparable. Unknown Pareto axes cannot dominate known ones. Equivalent nondominated candidates are retained separately rather than collapsed to a purported unique recipe.

## Independent anti-degeneracy diagnostics

Gates run per evaluation window, before eligibility. They remain separate from acoustic objective values, with measured quantities, units, thresholds, exceptions and source/target levels retained.

| Gate | Default trigger / protection |
|---|---|
| Invalid output / bounds | Parameter state is checked before rendering. Wrong shapes, non-finite output, extreme numerical overflow risk and invalid gain provenance cannot be explicitly permitted. |
| Silence and level | Active reference with candidate/reference RMS < 0.05; absolute level delta > 6 dB. |
| Transient loss | Target-anchored derivative-RMS ratio < 0.4, using accepted ZG-019 measurements per channel. Up to eight separated strong anchors prevent a surviving attack from hiding another lost attack. |
| Saturation / clipping | Near-rail adjacent-plateau fraction exceeds the target by > 0.03, including saturation below full scale. Actual final-output clipping rejects any clipped pre-output samples by default. |
| Bandwidth / energy | RMS-frequency ratio < 0.25 or active target-band energy ratio < 0.1. Absolute energy measurements supplement normalized descriptors. |
| Normalization exploit | Near-perfect gain-aligned reconstruction (< 0.03) with a forbidden level change is flagged; gain fitting is never applied. |
| Hidden output handling | Actual output differs from declared pre-master × gain + explicit final clipping by > 1e-7 peak amplitude. |

The accepted legacy engine performs internal harmonic RMS, noise-standard-deviation and final-peak normalization. This is **disclosed**, not removed or falsely claimed to be fully instrumented: separate internal gain factors are null because those taps are unavailable. Observable source/pre-master/post-gain/pre-clip/output levels and the exact graph/output policy are retained. The laboratory cannot reconstruct arbitrary latent processing or prove the absence of all possible adversarial transformations.

Acoustic exceptions require a named `ValidationPolicy.allowed` entry and result in `accepted-with-exceptions`, never an unqualified pass. Non-finite data, bounds violations and hidden/invalid gain handling cannot be legalized this way. Strong existing distortion in a target is not automatically an error; plateau detection measures excess over that target. These thresholds are engineering safeguards, not universal perceptual rules. Derivative anchors can include sharp periodic structure: six wrong-root trials in the identifiable fixture trigger the transient gate. This documented phase-sensitivity/false-positive risk must be investigated before using eligibility as a musical judgment; rejected candidates and their losses remain available for that analysis.

## Determinism, identity, caches and cancellation

`zg.inverse.cyclic-grid.v1` is a transparent Cartesian enumeration, not adaptive search. Axes are sorted by canonical pointer, each gets evenly spaced inclusive levels (integer ties-to-even, deduplicated), and mixed-radix traversal starts at `derive_seed(seed, 'inverse-grid-v1') mod grid_size`. It visits a contiguous cyclic prefix and stops at `min(grid_size, budget)`. The target hash never determines traversal or tie-breaking. Rank uses fit score then ordinal; every visited candidate, including rejected candidates, remains in the archive.

A logical evaluation costs one budget unit even on a cache hit. Every cold candidate renders twice; exact trace equality is required for `repeat-verified`. Divergent candidates cannot appear successful. Physical render counts, cache use and elapsed time are telemetry, not budget or identity. A full grid may leave unspent declared budget, reported explicitly.

Search identity binds target/source/recipe identities, state domain/bounds, stage/method, seed, fit windows, budget, objective/validation policies, exact relevant source-file hashes and feature configuration. Candidate identity additionally binds its parameter state and recipe. Evaluation identity includes its measured results, validation and numerical environment. The environment records Python, NumPy, SciPy, platform, byte order and BLAS backend; numeric work is limited to one thread. Source text hashes normalize checkout line endings. Restart the process after implementation changes; hot code replacement is not supported.

Same-environment cold reruns and verified resume are exact. **Cross-platform equivalence is a tolerance-based engineering comparison, not interchangeable identities or resumability.** CI records each platform's exact identities and compares portable recipe definitions/metrics with predeclared absolute `1e-7` and relative `1e-5` tolerances. It does not overwrite hashes to force equality.

Both caches use the accepted bounded `AnalysisCache` (default eight entries). Render keys compose the existing project `cache_key` with recipe, render-engine and environment identity; search budget/target do not unnecessarily invalidate reusable renders. Feature keys include canonical excerpt PCM, STFT/configuration and accepted feature-engine identity. Immutable audio and defensive metadata avoid accidental cache mutation. Equal-audio but different recipes can reuse features while retaining separate lineage. No persistent duplicate artifact store is introduced; an existing `ArtifactCache` adapter is a later opportunity.

Checkpoints contain completed ordinal, exact completed evaluation hashes, parent checkpoint, search/environment identity and `verified-prefix-replay-v1`. Resume cold-replays the completed prefix, bypassing render and feature caches, then continues the original logical budget. A changed request/environment/result explicitly raises `ResumeDivergence`, rather than resuming a different experiment. Replay's physical cost is intentional and not charged as new logical candidates. Atomic journals publish only completed prefixes. `submit_search_job` uses the existing research lane and admission estimate; cancelled jobs do not publish a partial current result. Cancellation is cooperative between evaluations/renders/windows, **not a promise to interrupt inside a legacy render or FFT**.

## Reproduce and verify

```text
python baseline/recovered_source/materialize_v2.py --out .
python -m pip install numpy==2.3.5 scipy==1.17.0 -r requirements-contracts.txt -r requirements-jobs.txt
python -m unittest discover -s tests/inverse -v
python tools/inverse_foundation_report.py --out inverse-evidence.json --full-out inverse-full.json --telemetry-out inverse-timing.json --check examples/zg024a_inverse_calibration.json.gz
python tools/check_contracts.py --baseline --report contracts-check.json
```

The checked-in deterministic gzip JSON is compact calibration evidence, not opaque model weights. Read it using `tools.inverse_foundation_report.read_json`, Python `gzip`, or any gzip utility. It contains exact fixture/source/target/search/candidate identities, seeds, bounds, all 36 baseline states, component vectors, independent holdout/whole diagnostics and the retained legacy benchmark. Full CI artifacts add every editable recipe, complete candidate provenance, per-window intermediate observations, validation measurements, audit selection and checkpoint chain. Timing is a separate artifact excluded from evidence identity.

`.github/workflows/zg024a-lab.yml` runs Windows/Ubuntu acceptance, prerequisite regressions, evidence generation and frozen calibration comparison. Existing ZG-002 CI independently checks recovered equivalence. Calibration is never regenerated automatically to obtain green CI; `--reference-out` is an explicit authoring operation requiring evidence review.
