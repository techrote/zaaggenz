# ZG-024 — research handoff 1

**Status:** Startoff 1 foundation only; **ZG-024 / issue #25 remains open**.
Next pass is authorised to investigate search strategies, not to treat these
synthetic wins as evidence for a production optimiser or a recovered chain.

## Entry points and architecture

`zaaggenz_inverse/{contracts,render,objectives,validation,engine,jobs,fixtures}.py`
implements a typed, bounded offline laboratory. Start with [README](README.md)
for units, numerical policy, limits and accepted-prerequisite mapping; consult
[recovered-baseline characterisation](ZG024_BASELINE_CHARACTERISATION.md) before
using historical scores. Authoritative inspected prerequisite revision:
`6e0153d824608d6a9899c5ea8e8c0b9a29688c98`.

Contracts compose existing AudioAssetRef, DSPNodeSpec, output policy, canonical
hash/seed and sample-support conventions. Source revisions remain existing
project IDs. GraphRenderer restores editable real-node recipes from its hashed
method JSON. Actual component tracking, descriptors, Chordness and tuning
interaction models feed the objectives. No parallel scheduler/DSP/tuning model,
new product default, trained model or playback service was introduced.

`prepare_problem` returns a **fit-only capability** and a separate audit target.
`run_baseline` freezes retained candidates; `audit_result` checks render identity
before measuring holdouts/whole-signal diagnostics, without reranking. Full
candidate records contain ten objective axes, target/candidate measurements,
feature/render identities, validation codes, and before/after gain provenance.

## Exact baseline, retention and checkpoint

`zg.inverse.lexicographic-grid.v1` enumerates sorted explicit levels, ascending
parameter names, using a lazy mixed-radix ordinal. The declared prefix consumes
one attempt per point including failures/cache hits, with at most two renders
per attempt. No adaptive refinements, stochastic proposals, DE, BO, ML or hidden
convergence criterion were added. Root search seed is `24001`; render seed is the
inherited named derivation `inverse-render`. Current graph rendering is stateless.

Same-execution repeated identity is mandatory. Candidate divergence cannot win.
There are at most 512 attempts, 16 fully retained records, 16 parameters, four
windows per split, two channels and 65,536 samples. All attempt vectors survive
in the ledger. Pareto-first retention reserves the scalar winner (important when
zero-weight axes make a scalar tie winner dominated), then uses explicit scalar
rank/ordinal ties. Different recipes with equal observations remain distinct.

Checkpoints save a contiguous prefix/hash chain and exact request atomically.
Resume deliberately replays and verifies the prefix, accounting for that extra
verification separately. Candidate records/trace/frozen set match uninterrupted
execution; lineage metadata records the resume. Code, backend, budget, bounds or
seed changes require a new, explicitly parented request. This is intentionally
not an opaque SciPy population snapshot or distributed execution framework.

## Fixture catalogue and observed calibration

Source-generation seed: `20260914`. Cheap cases use 8,192 samples at 12 kHz; rich
case uses 32,768 samples at 48 kHz. Each has two disjoint fitting quarters and two
held-out quarters. Truth is recorded in a separate witness, never supplied to
search. Renderer objects expose public forward models, not target lookups.
Exact hashes, requests, seeds, bounds, measurements and all attempted vectors:
`examples/zg024a_inverse_baseline.json`. Reproduce with the report command below.

| Fixture | Budget / retained | Observed result and meaning |
|---|---:|---|
| identifiable-bands | 9 / 9 | Correct low/high-band gains (6/-6 dB); zero fit and holdout losses; one frontier recipe |
| weakly-identifiable-gains | 9 / 9 | True 0/0 dB gains give exact match, but three reciprocal recipes through near-linear tanh differ in waveform NRMSE by less than 0.001; weak practical identification |
| nonidentifiable-gains | 9 / 9 | Three materially different serial-gain recipes have exactly identical PCM and zero losses; three frontier identities, no unique recovery |
| polarity-feature-conflict | 2 / 2 | Feature-only scalar gives zero to both signs; ordinal-first negative sign has waveform NRMSE 2; the full vector exposes the disagreement |
| fit-only-tail | 3 / 3 | -12/0/+12 dB tail recipes fit equally perfectly; selected -12 dB tail has held-out NRMSE about 0.748811 and 12 dB level error |
| rich-nonlinear-48k | 25 / 9 | Accepted 2x-AA tanh recovers on-grid 6 dB drive / -6 dB post-gain exactly; nearby gain/drive combinations expose covariance |

This is **57 unique attempted points / at most 114 search renders**, plus fresh
repeat runs, post-freeze audits and one-prefix resume verification. On-grid truth
is deliberately present to calibrate correctness. Zero loss is not evidence of
optimizer efficiency, robustness to off-grid targets or arbitrary audio recovery.

The unchanged recovered quick-DE smoke uses 133 evaluations and improves its
own historical scalar from about **0.358593 to 0.350155**. The inherited staged
smoke uses 354 evaluations, score about 0.307814, f0 about 43.6777 Hz. These
normalised-feature scores are **not comparable numerically** to the new raw-level
scores. No before-normalisation provenance is fabricated for that old renderer.

## Gates, leakage and numerical observations

Raw amplitude is never silently aligned or normalised. Independent diagnostics
cover silence, level change, target transient loss, saturation/full-scale excess,
band/centroid energy loss, nonfinite/invalid output, final clipping, hidden-gain
inconsistency and declared/native parameter bounds. Candidate descriptor failure
where the target was measurable produces **unavailable**, never an advantageous
zero. Saturation/full-scale tests are relative to the target, preserving the
ability to describe intentionally distorted source character.

Tests include a waveform-perfect but secretly renormalised candidate, a waveform-
perfect destructively clipped output, and level-matched candidates missing either
an attack or upper-band energy. They fail independent gates. Gates are measured
engineering heuristics, not a universal proof against manipulation or a musical
quality score. Next-pass unfamiliar signals need new adversarial fixtures.

Changing only holdout samples changes identity, but not fitting vectors or chosen
parameter states. Whole-signal metrics never enter fit ranking or eligibility.
Holdouts are temporal generalisation checks, not independent production chains;
repeated tuning against this catalogue makes it development data. Reserve new
sealed examples before any confirmatory comparison. Python capabilities prevent
accidental leakage, not malicious introspection or dishonest renderer plugins.

PCM canonicalises to float32 before identity/measurement; measurement arithmetic
is float64. Exact repeat is scoped to recorded code/numerical/backend environment.
Cross-platform vectors use rtol 1e-5 / atol 1e-6, with exact gate/applicability
checks; cross-platform hashes are not claimed identical. Resume/audit fail on
execution changes rather than claiming continued identity.

## Cost, cache opportunities and baseline weaknesses

Measured local timings are stored under `observations_not_hashed`; they include
host load and are not performance acceptance thresholds. Local regression runs
used Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0 and single-threaded numerical backends.
The rich 25-point search took roughly 16 seconds in an isolated early local run;
search plus its retained audits took roughly 27 seconds. Full reproduction also
repeats the search and runs the historical benchmark. Use the evidence file's
actual observations, not those indicative early timings, for the final run.

Existing AnalysisCache and optional integrity-checked ArtifactCache reuse exact
window features across candidates/searches. Weight/scale-only changes reuse raw
measurements; changed PCM, analysis/sonority config or execution do not. Different
recipes with identical PCM therefore benefit. Corrupt disk artifacts abort the
run instead of becoming fake bad candidates. Repeated graph renders are not
cached away; later shared render caching must preserve independent verification.
Analysis/component extraction dominates these small graphs more than rendering.

Grid prefixes are axis-order biased, scale exponentially with dimension, and miss
off-grid optima. Tiny sweeps cannot rank optimisers. Default scales/weights are
engineering choices, not listener calibration. Fixed STFT resolution, eight QC
bands, a small set of dissonance probes, strict mono/stereo duration limits and
cooperative cancellation between analysis calls are explicit limitations.
Resume replay is trustworthy but intentionally spends extra work. High-dimensional
full retained records and long recordings are not supported at production scale.

## Questions and directions for the next pass

Compare simple low-discrepancy or seeded space-filling sampling, small coarse-to-
fine grids and transparent local coordinate/pattern searches at equal **unique
attempt budgets**. Investigate staged timing/envelope/root then spectral/texture
proposals using the same frozen evaluator and prefix lineage. Only then consider
the recovered DE as a separately bounded proposal strategy/ablation. Preserve
multiple recipes in flat valleys rather than interpreting one winner as truth.

Questions remain: which scales/weights remain useful away from synthetic cases;
how to separate practical from exact identifiability under observation noise;
which transient and bandwidth gates need signal-class calibration; how to expose
pure feature/sonority targets without inventing audio; how to compare objective
availability/confidence fairly; and which public proposal-method registry should
replace the current single-method request admission. A new method needs a
versioned request identity, not a hidden switch under the grid method name.

**Avoid:** normalising every candidate independently, dropping unavailable
objectives, muting difficult bands, treating clipped approximations as successes,
choosing from holdouts while calling them independent, deleting acoustically
identical alternatives by waveform hash, using unbounded optimiser evaluations,
calling same-seed cross-platform runs bit-identical, or equating debug-pitch fit
with fully observed reference agreement. Differentiable/ML/large-evolutionary
systems are not prerequisites and have no supporting advantage evidence here.

## Verification and continuation contract

Run foundation tests, inherited regressions, then:

```text
python tools/inverse_foundation_report.py --out inverse-evidence.json --full-dir inverse-records --compare examples/zg024a_inverse_baseline.json
```

Local inherited acceptance passed: **373 tests across 11 suites**, **13 recovered
smoke scripts**, and the existing browser transport regression. The dedicated
Ubuntu/Windows Python 3.13 workflow repeats foundation tests, those inherited
checks, exact-repeat evidence and portable metric comparison. Its full sidecars
are CI artifacts, while the compact baseline remains committed.

Continue under **ZG-024 / #25**. This pass does not complete the multi-stage
production integration, editable UI application, advanced proposal strategies,
real-reference evaluation or optional differentiable ablation. Keep the issue
open and carry forward null, ambiguous and failed-gate results, not only wins.
