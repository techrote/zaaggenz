# ZG-042 bounded long-form workload policy

Status: **bounded corrective implementation in review; #43 remains non-dependency-satisfying until final-head gates pass and the reviewed head merges**  
Policy: `zaaggenz.workload-cost/1.1.0`

## Corrective repair — 2026-09-19

PR #210 established useful workload-cost metadata, BATCH-lane routing, benchmark tooling and explicit fail-closed boundaries for zero-phase/windowed processing. Independent post-merge review then reproduced four narrower defects: caller-owned execution inputs could change after admission, retained-output allocation happened before the first cancellation check, an unfinished glide could cross a section boundary without serializable continuation state, and the advertised 64-bar full-rate plan exceeded its memory reservation.

The 1.1.0 corrective keeps the useful #210 architecture but tightens the execution contract:

- `submit_persistent_sections()` deep-snapshots the bounded section sequence, nested recipe/progression inputs and runtime specification once **before admission**; the exact same snapshot is later executed. Caller mutation cannot enlarge or change admitted work, and one-shot iterators are consumed only once.
- Persistent sequences are capped at 4,096 explicit sections before execution. This is a request-domain bound, not silent coarsening.
- The authoritative sequence reservation is now the peak one-section DSP working set + retained mix/BODY/AUX/SUB/pre-master PCM + 32 MiB fixed orchestration/snapshot headroom + 1 MiB per retained section diagnostic/snapshot allowance.
- A completed section's full render result is released after its retained products, continuation state and copied diagnostics are extracted, before the next section renderer is entered. The estimator no longer assumes a lifetime pattern the implementation violates.
- Cancellation is checked after preflight and **before retained PCM allocation**, before each section, and after each section boundary.
- ZG-029 runtime state remains version 1.0.0. ZG-042 does not widen or reinterpret that accepted ownership contract merely to make chunking convenient. Instead, preflight rejects a repeated-target boundary that would split an unfinished glide whose remaining trajectory ZG-029 does not serialize. Explicit role reset remains a valid boundary.
- The existing exact phase/release/tail test remains, and a new adversarial fixture cuts a 1,500-sample glide after 1,000 samples and proves rejection occurs before any PCM render.
- Source SYNTHLINE/exciter arbitrary slicing, zero-phase crossover chunking and analysis-window chunking remain fail-closed exactly as before.

No recovered source/audio/provenance, source-preserving note semantics, tuning, crossover/DSP algorithm, final-master policy or artistic default is changed. No accelerator is required and no hidden quality tier is introduced.

## Purpose

ZG-042 makes the cost and execution boundary of expensive offline work visible without changing the sound to make benchmarks pass. It does **not** introduce a mandatory accelerator, an adaptive hidden quality setting, or a new audio default.

The production authorities remain:

- ZG-004 for scheduler lanes, cancellation, declared-memory admission and process numerical-thread ownership;
- ZG-008 for source-preserving note rendering and its explicit `standard` / `high` phase-vocoder FFT choice;
- ZG-012/ZG-013 for bounded STFT/component analysis;
- ZG-016/ZG-021 for zero-phase multiband/effect-delta processing;
- ZG-029 ownership 1.1.0 for persistent BODY/AUX/SUB ownership and section transitions.

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

`persistent_sequence_memory_bound()` is the authority for an accepted multi-section persistent sequence. It adds retained sequence products and explicit orchestration/snapshot/diagnostic headroom to the largest section's real persistent-layer estimate. `estimate_persistent_sequence()` and `recommended_section_bars()` both call that same bound, so planning and admission cannot silently use different arithmetic.

`admission_memory()` applies the estimate to the real ZG-004 `SchedulerLimits`. Caller overrides may reserve **more**, never less. Preview must fit the interactive reserve; background work must fit the background lane and per-job bound.

For 64 bars at 48 kHz / 200 BPM under default limits, the corrected conservative planner recommends at most **20 bars per section**, producing the explicit plan `20 + 20 + 20 + 4`. The benchmark executes this product-scale plan and requires its measured Python allocation peak to remain at or below the exact scheduler reservation. Failure of that inequality fails the benchmark and therefore CI; this is no longer a projection-only claim.

RSS is still reported as host context, not compared directly with the reservation because process RSS includes interpreter/libraries and pre-existing process state outside the job's declared incremental working set.

## Immutable admission snapshot

Admission and execution are bound to one immutable logical request:

1. the iterable is consumed once with the 4,096-section cap;
2. every `LayerSection` is rebuilt from a detached `Contract` document plus copied progression/frame/reset data;
3. the `LayerRuntimeSpec` is deep-copied, including nested transform claims;
4. estimation and representability checks run against that snapshot;
5. the scheduled closure captures and executes only that snapshot.

A mutable caller list may be appended to after submission and the original recipe dictionaries may be edited; neither mutation changes the queued workload. A one-shot iterator is valid because no later execution pass attempts to consume it again.

## Chunk/equivalence policy

Chunking is allowed only where state/support makes equivalence explicit.

### Persistent BODY/AUX/SUB section state

`render_persistent_sections()` is an exact persistent-layer **submix** path only at representable boundaries:

- SYNTHLINE and exciter must be muted; arbitrary source-phrase chunking is not claimed;
- each section carries its real ZG-029 `LayerRuntimeState`;
- every continuation after the first is authorised by a content-bound `LayerSectionTransition`;
- oscillator phase, last target frequency and release/tail state cross the boundary explicitly;
- an in-progress glide trajectory is **not** serialized by ZG-029 v1 state, so a repeated-target split that would require that hidden continuation fails preflight before retained PCM allocation or section rendering;
- an explicit reset can intentionally terminate the prior role state at the boundary;
- BODY/AUX/SUB/pre-master and final output are concatenated only after each section executes its declared master.

The positive equivalence fixture compares a whole two-frame render with two explicit sections through oscillator phase, release gap and a completed glide. PCM and final state must agree within the documented float32 assembly tolerance. The adversarial unfinished-glide fixture proves that a boundary whose missing state would change PCM cannot be represented and is rejected rather than mislabeled exact.

### Not exact: zero-phase crossovers

ZG-016/ZG-021 use offline `scipy.signal.sosfiltfilt`. Splitting a signal at an arbitrary sample creates new filter edges; processing two halves is demonstrably not equal to processing the whole signal.

ZG-042 therefore keeps band processing `whole-signal-zero-phase`. No overlap size is invented and no causal replacement filter is substituted. Tests deliberately show the naive half/half result differs and require an attempted multi-chunk policy to fail closed.

### Not exact: multiresolution/component windows

STFT padding/support and spectral-flux history cross arbitrary chunk boundaries, while component association adds phase/track continuity. Splitting a long analysis changes frame/support cardinality even before higher-level tracking.

These workloads remain `whole-signal-window-support` under v1. Existing ZG-012 memory bounds reject unsafe requests before allocation. A future streaming implementation needs an explicit overlap/history state contract plus whole-vs-streaming evidence before this policy may change.

### Not exact: source-derived note phrases

ZG-008 source-derived pitch warping, phase-vocoder state, glides and tails are phrase-owned. ZG-042 does not slice those paths at arbitrary samples. Long-form sequencing should compose accepted phrases/sections rather than treating the renderer as a stateless block processor.

## Threads, cancellation and responsiveness

The default scheduler continues to own one numerical thread per native pool. ZG-042 does not create a second BLAS/OpenMP policy.

Long-form section rendering uses the background `BATCH` lane. The ZG-042 test and benchmark both exercise preview while background work exists; interactive preview admission remains mechanically isolated by the accepted ZG-004 lane and memory-reserve contract.

Cancellation is cooperative. It is checked before retained sequence arrays are allocated and at every explicit section boundary. This is not a claim that an already-running individual native DSP call is asynchronously preemptible.

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
- reduced-rate persistent 4-, 16- and 64-bar section renders for routine host comparison;
- a preview while a real long-form BATCH render occupies/queues background work;
- the accepted **64-bar / 48 kHz / 200 BPM** persistent plan under default scheduler limits.

It records platform/Python/CPU, process numerical-runtime/thread environment, elapsed time, authoritative memory/work estimate, Python allocation peak, sampled RSS where available, and the measured top three reduced-fixture costs. The full-rate evidence additionally records the explicit section plan, exact admission reservation and `tracemalloc_within_reservation`; the tool exits unsuccessfully if the measured traced peak exceeds the reservation.

The routine CI analysis/note fixtures remain intentionally reduced so cross-platform validation stays bounded. That does not alter product quality. The full-rate persistent memory case is separately executed because it is the acceptance boundary that exposed the #210 defect.

Benchmark timings are host observations, not universal realtime guarantees and not acceptance thresholds. A slower runner is not a reason to reduce audio quality.

## Acceptance interpretation

ZG-042 can return to accepted/dependency-satisfied only when the exact reviewed head proves all of the following on required CI:

1. admission and execution use the same bounded detached request snapshot;
2. caller mutation and one-shot iterators cannot invalidate memory admission;
3. the corrected multi-section memory bound is authoritative for both recommendation and execution;
4. the product-scale 64-bar / 48 kHz / 200 BPM accepted plan executes with measured Python allocation at or below its reservation;
5. cancellation precedes retained allocation and is checked at each section boundary;
6. representable stateful boundaries retain exact PCM/state evidence while an unfinished-glide cut fails before rendering;
7. unsafe source, zero-phase and window/history chunking remains fail-closed;
8. ZG-004 lane isolation, explicit quality policy, no-accelerator rule and all protected source/audio/provenance/default semantics remain intact;
9. final-head ZG-042 Ubuntu/Windows plus ZG-004, ZG-029, programme-state and reverse-dependency gates pass.

Until those final-head gates pass and the corrective head is merged, `programme/task_state.json` correctly keeps ZG-042 partial and non-dependency-satisfying.
