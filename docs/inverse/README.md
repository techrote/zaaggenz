# ZG-024a — deterministic inverse-search laboratory

**Startoff 1 of ZG-024 / #25, not issue completion.** This is an offline research
substrate and calibration baseline. It does not choose a production optimiser,
identify an original production chain, modify `locked_bloom`, or enter playback.
The recovered inverse UI and implementation remain unchanged.

## Run and retrieve

Install the existing pinned contracts/jobs requirements and NumPy 2.3.5 / SciPy
1.17.0. Materialise the authenticated application with
`python baseline/recovered_source/materialize_v2.py --out .`. Run:

```text
python -m unittest discover -s tests/inverse -v
python tools/check_inverse_regressions.py
python tools/inverse_foundation_report.py --out inverse-evidence.json --full-dir inverse-records --compare examples/zg024a_inverse_baseline.json
```

Set `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`, and `PYTHONUTF8=1` before starting
Python, as CI does. Timings are host observations, not acceptance thresholds.
The evidence command also runs the **unmodified** recovered quick-DE benchmark.
The compact checked-in JSON includes exact requests, truth witnesses' identities,
all attempted objective vectors, retained fit/holdout results and provenance.
Sidecars preserve complete candidate, window, validation and witness records.

```python
from zaaggenz_inverse import run_baseline, audit_result, Checkpoint
from zaaggenz_inverse.fixtures import make_fixture

case = make_fixture('fit-only-tail')
problem, audit_target = case.problem()
paused = run_baseline(problem, pause_after=1, checkpoint_path='inverse-checkpoint.json')
result = run_baseline(problem, resume=Checkpoint.load('inverse-checkpoint.json'))
audit = audit_result(result, audit_target, case.renderer)
# result is immutable. audit neither selects nor changes its candidates.
```

Read [baseline characterisation](ZG024_BASELINE_CHARACTERISATION.md) before
comparing historical scores. Read [research handoff 1](ZG024_RESEARCH_HANDOFF_1.md)
before changing the search method or declaring new research outcomes.

## Accepted prerequisites and reuse

Inspected on accepted `main` **6e0153d824608d6a9899c5ea8e8c0b9a29688c98**. These
are actual merged source/tests/evidence, not reliance on issue closed states:

| Prerequisite | Authoritative implementation and read-set | Reused here |
|---|---|---|
| ZG-003 | `zaaggenz_project/`, `docs/project/README.md`, `tests/project/` | Existing source revision IDs, immutable recipe conventions, integrity-checked `ArtifactCache` |
| ZG-004 | `zaaggenz_jobs/`, `docs/jobs/README.md`, `tests/jobs/` | RESEARCH lane, memory admission, cancellation, progress, atomic checkpoint publication |
| ZG-005 | `zaaggenz_qc/`, `docs/qc/README.md`, `tests/qc/` | Raw QC, source-preservation diagnostics, seeded noise fixture |
| ZG-014 | `zaaggenz_descriptors/`, `docs/descriptors/README.md`, fixture evidence/tools | Actual periodicity, occupancy, roughness and descriptor validity/confidence |
| ZG-018 | `zaaggenz_spectral/chordness_*`, `docs/spectral/ZG018_MULTI_COMB_CHORDNESS.md` | Existing `CombTemplate` and union-fit/precision observations |
| ZG-019 | `zaaggenz_spectral/placement.py`, `zaaggenz_dsp/graph.py`, `docs/dsp/ZG019_SPECTRAL_PLACEMENT.md` | Real graph nodes, exact order/automation, nonlinear legacy/AA stage specifications, final output policy |
| ZG-020 | `zaaggenz_tuning/dissonance_*`, `docs/analysis/ZG020_ADAPTIVE_TUNING.md` | Partial-derived timbre and existing dissonance interaction/model conventions |

Also reuses ZG-002 canonical hashing, seeds, `AudioAssetRef`, `DSPNodeSpec`, method
and sample-support schemas; ZG-012 STFT/`AnalysisCache`; ZG-013 component tracking.
No shared contract enum, DSP implementation or predecessor evidence is rewritten.
A graph is stored as its existing node documents, not inverse-only DSP classes.
The shared METHOD configuration permits scalar values: the complete canonical
recipe JSON string and its shared digest are stored there explicitly.
`GraphRenderer.from_method(source, method)` verifies and restores that recipe.

## Small versioned contracts

All inverse documents are v1.0.0. `contracts.py` composes rather than widens the
ZG-002 contract enum. `Snapshot` defensively owns bounded JSON and inherits its
strict loader and exact numeric canonical digest. Supported entry points validate
unknown fields, version, finite numbers, safe dimensions and domain agreement.

| Contract / record | Meaning |
|---|---|
| `ParameterBound`, `ParameterDomain`, `ParameterState`, `Grid` | Named units, inclusive bounds, integer restrictions, canonical values, explicit levels |
| `Window`, `WindowPlan` | Half-open sample support, no padding, separate disjoint fitting and held-out sets |
| `Budget`, `Stage` | Unique-point attempt limit, retained-record cap, explicit stage and parent lineage |
| `SearchRequest` | Source/target assets, existing source revision if supplied, renderer, objectives, gates, seed, budget and execution identity |
| `Rendered` | Immutable pre-master and output PCM plus actual graph/seed/output policy |
| `InverseWindowFeatures`, component/aggregate records | Method/asset-bound measurements, units/scales, applicability, decomposed losses |
| `InverseCandidate` | Bounded editable state, rendering/feature identities, full fitting result, validation and reproducibility state |
| `InverseSearchResult` | All attempted vectors, retained alternatives, fixed objective axes, frontier, frozen candidate-set identity |
| `Checkpoint`, `InverseAudit` | Verified prefix and resume lineage; separate post-freeze held-out/whole-signal measurements |

This pass intentionally supports **audio-backed** waveform/feature/sonority
objectives. A standalone descriptor-only target, time-warp/alignment search,
production UI application, multi-stage controller and custom optimiser plug-in
are future passes, not falsely exposed options.

## Determinism, budget and identity

The boring method is `zg.inverse.lexicographic-grid.v1`: sorted parameter names,
ascending explicit levels, lazy mixed-radix enumeration of a declared prefix.
There is no random ordering, adaptive refinement or hidden stopping criterion.
The declared root seed is an inherited unsigned-64 **decimal string**; the renderer
gets `derive_seed(root, 'inverse-render')`. Current graphs are stateless; their
common render seed remains explicit even when unused. Fixture-noise seeds are
separate and never used to leak a truth state into the optimiser.

One budget unit is an attempted grid point, including invalid candidates and
cache hits. Each valid attempt performs **two renders** to verify exact identity;
rejected early attempts may perform one. At most 512 attempts, 16 fully retained
records, 16 parameters, 128 levels per axis, one million declared grid points,
65,536 source/target frames, two channels, and four windows per split are admitted.
These are foundation resource limits, not a claim of production scalability.

Search identity hashes the full request: source/target identities, bounds/grid,
parameters via candidate identity, method/version, seed, stage/parents, fit and
holdout declarations, budget/retention, objective/gate configuration and relevant
code/numerical versions. Holdout **hashes and support declarations** are allowed
metadata; their sample values/features are not available in `FitProblem`.
Candidates with equal audio but different recipes keep different identities.
Render identity retains both taps, policy, graph order and seed; measurement
identity retains its PCM and actual analysis records/methods.

PCM is explicitly canonicalised to little-endian float32 **before** hashing and
measurement; measurements compute in float64 from precisely those samples.
Otherwise two sub-float32-different arrays could share an asset hash but be
measured differently. No implicit peak/RMS normalisation, DC removal, onset
alignment, channel downmix or clipping is permitted. Stereo spectral power is
averaged per channel, so opposite channel polarity does not cancel its energy.

The policy is **same-execution exact repeat**, not cross-machine bit identity.
Execution identity includes package-source digests, Python/NumPy/SciPy versions,
OS/machine and a fingerprint of loaded numerical backends/architecture/thread
counts. A mismatched execution rejects resume/audit. Cross-platform report checks
use the declared `rtol=1e-5, atol=1e-6` on component vectors and exact expected
validation/applicability, never fake matching asset hashes. Repeated results
within each CI environment must match exactly. A custom renderer that changes
between its two calls is explicitly divergent and cannot become best.

## Fit, holdout and whole-signal boundary

`prepare_problem` verifies the target asset and copies only fitting excerpts into
`FitProblem`. There is no target-wide analysis before slicing. Analysis padding
uses zeros belonging to that excerpt only. The controller separately retains an
`AuditTarget`; neither this object nor the fixture witness is passed to baseline
search. Candidate rendering may cover the entire source, but fitting metrics and
gates inspect **only fitting supports**. This prevents whole-output safety/QC
from becoming a covert holdout-selection channel.

After the candidate set freezes, `audit_result` rerenders and verifies the exact
recorded render identity, then measures held-out windows and whole-signal
**diagnostics**, in unchanged retained order. It cannot rerank or mutate the
search result. Repeatedly using these audit scores to design a strategy turns
this catalogue into development data; reserve new fixtures/windows for later
confirmatory comparisons. Disjoint windows are temporal holdouts, not a claim
of independent samples from different productions. This is an accidental-leakage
API boundary, **not** a security sandbox against malicious Python/reflection.

A regression changes only held-out target samples: search/candidate identities
correctly change, but fitting vectors and selected parameter states do not.
Ties are broken by grid ordinal, not a target-dependent candidate hash.
The tail fixture fits perfectly at -12/0/+12 dB; the first -12 dB recipe fails
holdouts. It remains the fit-selected result instead of being silently replaced.

## Objective interpretation

All axes minimise **distance to the target**, not an unsupported universal quality
or consonance optimum. Every window retains raw/scaled component values and
actual target/candidate descriptor measurements. Aggregate uses equal window
means, so a longer support does not silently have a larger weight.

| Axis | Raw units and measurement | Default divisor / scalar weight |
|---|---|---|
| waveform | Raw sample RMS error / target RMS | 1 / 1 |
| envelope | 2 ms block RMS-envelope error / target RMS | 1 / 0.5 |
| spectrum | RMS difference of time/channel-averaged STFT amplitude spectra in dB | 20 dB / 0.5 |
| level | Absolute raw RMS level difference in dB | 6 dB / 0.5 |
| periodicity | Absolute inherited periodicity-peak difference | 1 / 0.1 |
| occupancy | Absolute inherited spectral-occupancy difference | 1 / 0.1 |
| roughness | Absolute inherited pairwise-roughness difference | 1 / 0.1 |
| comb_fit | Absolute existing union-comb-fit difference | 1 / 0.1 |
| comb_precision | Absolute existing union-comb-precision difference | 1 / 0.1 |
| dissonance_profile | RMS difference of inherited self-interaction values at declared cents probes (default 0, 702) | 1 / 0.1 |

These divisors/weights are engineering calibration choices, **not** listening-
validated thresholds. STFT defaults: 256-sample periodic Hann, 64-sample hop,
256-point FFT; amplitude floor 1e-6 (-120 dBFS), RMS denominator floor 1e-8.
Raw STFT amplitude uses coherent-window-gain scaling. Read the inherited
roughness/dissonance definitions; their model units are dimensionless, not SPL,
pleasure or cultural consonance labels. A target-unavailable descriptor is marked
not applicable. Candidate abstention where the target was valid is **unavailable**,
not zero or silently removed; it makes the score incomplete and the candidate
ineligible. A zero scalar weight does not delete an objective from the fixed
Pareto vector. Equal vectors do not dominate each other. Frontier-first retention
has an explicit cap and reserves the scalar winner even when zero-weight axes
make it Pareto-dominated; all attempted vectors remain in the ledger for later analysis.

## Anti-cheating diagnostics

These gates remain separate from subjective/acoustic-fit components. Defaults:
RMS collapse <3% of target; unintended level change >6 dB; target-onset positive
2 ms RMS flux retention <35%; additional full-scale samples >1%; additional
near-peak plateaus >10%; energy retention <10% in a band carrying >3% of target
energy; centroid ratio <35%; suspicious gain-alignment gap >3 dB. Full-scale and
plateau tests are **relative to the target**, not an attempt to remove zaag's
intentional internal nonlinear character. Eight equal-Hz bands are explicit QC
bands, not a replacement for existing sonority descriptors.

Every declared final output policy is re-applied to the stored before-gain tap.
Inconsistent gain provenance and **any actual destructive final clipping** reject
the candidate, even if its waveform matches a clipped target. Raw, declared-gain,
and actual-output QC and clipping fractions are retained. Best-fit gain from the
existing source-preservation tool is diagnostic only: it never alters samples or
lowers waveform loss. Non-finite/complex/malformed/excessive signals and parameters
outside declared or inherited node bounds cannot become eligible.

These measurements are strong regression guardrails, not proofs against every
possible degeneration. Novel transient types, DC-heavy audio, stereo changes and
narrowband/pathological textures need new fixtures before loosening gates.
Silence as the complete fitting target is rejected rather than called recovery.

## Cache, cancellation and resumption

`FeatureStore` reuses bounded `AnalysisCache` and optional `ArtifactCache`, with a
single local lock. Keys bind exact excerpt assets, measurement configuration and
execution identity. Weight/scale-only changes reuse raw features; altered signal,
STFT/descriptors/comb/dissonance configuration or execution cannot. Disk corruption
aborts the run; it is not disguised as an unfavourable candidate. Full graph
renders are deliberately repeated rather than cached away: deterministic repeat
verification takes priority in this calibration pass. Later render-cache work can
reuse the immutable `Rendered` identity without hiding divergence verification.

`submit_inverse_job` uses the existing ZG-004 RESEARCH lane and source revision.
Construct the scheduler/numerical thread policy **before** constructing a request;
a later change of backend thread count is an execution change, not silently
accepted. Cancellation is checked between renders and measurement windows. A
single DSP/analysis call is cooperative only at its existing boundaries.

The checkpoint is a bounded contiguous prefix ledger with a hash chain, next
ordinal, exact request and explicit status. Writes use the existing atomic file
publisher. Resume replays and verifies every prior evaluation, reconstructing
retention rather than trusting saved scores or attempting to serialise SciPy/RNG
internals. Replayed verification work is recorded **in addition to**, not charged
again against, the unique-point budget. Resume metadata changes the final result
identity, while its candidate records, trace and frozen set match uninterrupted
execution. Divergent replay fails without overwriting the previous checkpoint.
Changed code/bounds/seed/budget require a new request with explicit parent lineage.
No distributed worker, model training or online optimisation service is required.

## Explicit component-association numerical policy

`ObjectivePlan.components` embeds the existing `ComponentTrackerSpec`, including
its opt-in `integer-microcent-v1` assignment cost policy. This avoids
last-bit floating-sum tie decisions fragmenting tracks and changing sonority
measurements across platforms. Only assignment costs are rounded (ties-to-even,
1e-6 cent); reported physical frequency/amplitude/phase observations are not.
The inherited default remains `legacy-float-v1`, with identical legacy metadata
and processing. Integer cost bounds fail closed rather than overflow.

The feature method is `zg.inverse.measured-window.v1.1`; component configuration
is identity- and cache-relevant, separately from objective weights. Read the
handoff's cross-platform finding for the observed failed experiment and repair.
Portable comparisons retain the original tolerances and now also enforce
identical budgets, domains, grids, windows, seeds, stages, objective/gate policies
and fixture generation metadata. Exact bit identity remains a same-execution
assertion, not a universal numeric guarantee.
