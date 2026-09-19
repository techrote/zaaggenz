# ZG-042 bounded long-form workload policy

Status: **post-merge corrective-active; implementation/evidence partial; not dependency-satisfying** (issue #43 reopened 2026-09-19)  
Policy: `zaaggenz.workload-cost/1.0.0`

## Current corrective hold — 2026-09-19

PR #210 established useful workload-cost metadata, BATCH-lane routing, benchmark tooling and explicit fail-closed boundaries for zero-phase/windowed processing. Independent post-merge review found that two stronger claims are not yet established: the long-form memory estimate is not conservative for the documented full-rate section plan, and explicit section continuation is not exact when a boundary cuts through state the ZG-029 runtime does not serialize (notably an unfinished glide).

Until issue #43 is repaired and reclosed:

- admission and execution must use the same immutable bounded snapshot of section/nested inputs; caller mutation or one-shot iterator exhaustion cannot change the admitted workload;
- the estimator must cover actual object lifetimes, retained diagnostics and overlapping section temporaries, or implementation lifetimes must be shortened to fit the reservation;
- the documented 64-bar / 48 kHz / 200 BPM section plan must be measured against its reservation, not only projected from reduced-rate CI;
- cancellation must be checked before large retained-output allocations as well as between sections;
- section boundaries must be rejected unless every in-progress state is representable by the continuation contract, or that state must be explicitly versioned and serialized;
- whole-vs-section evidence must include a cut through an unfinished glide, in addition to phase/tail/release cases.

`programme/task_state.json` is authoritative and currently marks ZG-042 partial/not dependency-satisfying. ZG-044/ZG-045 must not consume the current memory/exact-chunking claims as accepted release evidence.

## Purpose

ZG-042 makes the cost and execution boundary of expensive offline work visible without changing the sound to make benchmarks pass. It does **not** introduce a mandatory accelerator, an adaptive hidden quality setting, or a new audio default.

The production authorities remain:

- ZG-004 for scheduler lanes, cancellation, declared-memory admission and process numerical-thread ownership;
- ZG-008 for source-preserving note rendering and its explicit `standard` / `high` phase-vocoder FFT choice;
- ZG-012/ZG-013 for bounded STFT/component analysis;
- ZG-016/ZG-021 for zero-phase multiband/effect-delta processing;
- ZG-029 ownership 1.1.0 for persistent BODY/AUX/SUB state and section transitions.

ZG-042 adds conservative **preflight estimates and execution policy** around those accepted implementations.

## Cost estimates

`zaaggenz_performance.estimate_workload()` covers:

| workload | estimate includes | quality policy |
| --- | --- | --- |
| preview | note-render working set plus output/artifact bytes | explicit `standard` / `high`; never selected automatically |
| note render | source/stems, pitch-warp/phase-vocoder and FFT work | existing ZG-008 `standard` / `high` only |
| multiresolution analysis | source plus peak sequential short/medium/long STFT and feature rows | exact |
| component tracking | tracker STFT, multiresolution transient analysis, bounded candidate rows and concrete component arrays | exact |
| band processing | whole-signal zero-phase crossover/effect-delta working arrays | exact |
| persistent layer render | source bus, BODY/AUX/SUB working/retained PCM and state | exact |

These estimates are intended as conservative admission metadata, not claims of exact RSS. **The current persistent-sequence estimate undercounts a reproduced full-rate accepted path; treat it as provisional until #43 is reclosed.** The benchmark records the estimate alongside elapsed time, Python traced peak and sampled RSS where the host exposes it.

`admission_memory()` applies the estimate to the real ZG-004 `SchedulerLimits`. Caller overrides may reserve **more**, never less. Preview must fit the interactive reserve; background work must fit the background lane and per-job bound.

For long persistent arrangements, `recommended_section_bars()` accounts for both one-section working memory and retained output. A 64-bar 48 kHz plan that is too large as one job is sectioned rather than silently reducing sample rate, quality or layer count.

## Chunk/equivalence policy

Chunking is allowed only where state/support makes equivalence explicit.

### Provisional exactness claim: persistent BODY/AUX/SUB section state

`render_persistent_sections()` is an exact persistent-layer **submix** path:

- SYNTHLINE and exciter must be muted; arbitrary source-phrase chunking is not claimed;
- each section carries its real ZG-029 `LayerRuntimeState`;
- every continuation after the first is authorised by a content-bound `LayerSectionTransition`;
- oscillator phase, previous frequency and release/tail state cross the boundary explicitly; **unfinished glide trajectory is not currently serialized, so boundaries through an active glide are unsafe and must be rejected or given a versioned continuation state under #43;**
- BODY/AUX/SUB/pre-master and final output are concatenated only after each section executes its declared master.

The regression suite compares a whole two-frame render with two explicit sections containing a release gap and a glide into the second target. PCM and final state must agree within the documented float32 assembly tolerance.

`submit_persistent_sections()` always submits as ZG-004 `BATCH`, not `RENDER`. Long offline construction therefore cannot occupy the interactive worker lane reserved for preview. It uses the authoritative sequence estimate for scheduler admission and checks cancellation/progress between sections.

### Not exact: zero-phase crossovers

ZG-016/ZG-021 use offline `scipy.signal.sosfiltfilt`. Splitting a signal at an arbitrary sample creates new filter edges; processing two halves is demonstrably not equal to processing the whole signal.

ZG-042 therefore keeps band processing `whole-signal-zero-phase`. No overlap size is invented and no causal replacement filter is substituted. Tests deliberately show the naive half/half result differs and require an attempted multi-chunk policy to fail closed.

### Not exact: multiresolution/component windows

STFT padding/support and spectral-flux history cross arbitrary chunk boundaries, while component association adds phase/track continuity. Splitting a long analysis changes frame/support cardinality even before higher-level tracking.

These workloads remain `whole-signal-window-support` under v1. Existing ZG-012 memory bounds reject unsafe requests before allocation. A future streaming implementation needs an explicit overlap/history state contract plus whole-vs-streaming evidence before this policy may change.

### Not exact: source-derived note phrases

ZG-008 source-derived pitch warping, phase-vocoder state, glides and tails are phrase-owned. ZG-042 does not slice those paths at arbitrary samples. Long-form sequencing should compose accepted phrases/sections rather than treating the renderer as a stateless block processor.

## Threads and responsiveness

The default scheduler continues to own one numerical thread per native pool. ZG-042 does not create a second BLAS/OpenMP policy.

Long-form section rendering uses the background `BATCH` lane. The ZG-042 test and benchmark both exercise preview while background work exists; interactive preview admission remains mechanically isolated by the accepted ZG-004 lane and memory-reserve contract.

Cancellation is cooperative at every explicit section boundary. This is not a claim that an already-running individual section is preemptible inside arbitrary native DSP.

## Reproducible benchmark

After authenticated baseline materialisation:

```sh
python -m pip install numpy==2.3.5 scipy==1.17.0 -r requirements-contracts.txt -r requirements-jobs.txt
python -m unittest discover -s tests/performance -v
python tools/benchmark_zg042.py --out zg042-performance.json --sample-rate 8000 --analysis-seconds 0.5 --quality standard
```

The benchmark actually executes:

- one source-derived note render;
- short/medium/long multiresolution analysis;
- component tracking;
- multiband processing;
- persistent 4-, 16- and 64-bar section renders;
- a preview while a real long-form BATCH render occupies/queues background work.

It records platform/Python/CPU, process numerical-runtime/thread environment, elapsed time, conservative memory/work estimate, Python allocation peak, sampled RSS where available, and the measured top three costs.

The CI command uses an explicitly reduced **measurement fixture** so cross-platform validation stays bounded. That fixture is not a product quality tier and changes no default. The report also includes a 64-bar / 48 kHz / 200 BPM planning projection and the default-scheduler recommended section size without executing that expensive projection in CI.

Benchmark timings are host observations, not universal realtime guarantees and not acceptance thresholds. A slower runner is not a reason to reduce audio quality.

## Acceptance interpretation

ZG-042 is satisfied when:

1. the measured report identifies dominant costs with reproducible host/environment metadata;
2. every expensive workload exposes a bounded preflight estimate before scheduler admission;
3. long-form persistent work uses the background lane with section cancellation/progress boundaries, leaving preview mechanically available;
4. exact stateful section equivalence is tested;
5. unsafe zero-phase/window/source chunking is shown non-equivalent or unsupported and fails closed;
6. no default quality, protected source semantics, tuning, phase/tail ownership, master policy or provenance changes merely for performance.
