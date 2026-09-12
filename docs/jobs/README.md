# ZG-004 bounded local jobs

This layer keeps expensive offline work from stealing the only execution lane needed by live preview. It is deliberately local: no distributed queue, daemon dependency or GPU requirement.

## Scheduling contract

`JobScheduler` has two independent worker lanes. `PREVIEW` and `RENDER` use the interactive lane; `ANALYSIS`, `RESEARCH` and `BATCH` use the background lane. Background workers are mechanically unable to occupy interactive workers. They are also capped below `max_memory_bytes - interactive_memory_reserve_bytes`; every preview must fit inside that reserve. Therefore a long analysis cannot starve a preview through worker or declared-memory exhaustion. A non-cooperative long *interactive render* is not claimed to be preemptible.

Defaults: 1 interactive worker, 2 background workers, 64 total queued jobs, 48 queued background jobs, 512 MiB declared running-memory budget, 64 MiB interactive reserve, 256 MiB per-job bound, 64 MiB preview bound, 96 MiB/32-entry preview result cache and one native numerical thread per BLAS/OpenMP pool. `threadpoolctl` applies the native limit after libraries are loaded; OMP/OpenBLAS/MKL/NumExpr/Accelerate environment limits are also set.

Memory accounting is admission/reservation metadata, not a claim that Python can prevent an executor from allocating more than declared. Future subprocess isolation may add hard RSS enforcement if profiling justifies it.

## State and cancellation

Jobs expose queued, running, cancel-requested, cancelled, completed and failed states with monotonic progress. Queued cancellation is immediate. Running cancellation is cooperative through `JobContext.check_cancelled()`. A worker exception fails that job and does not poison the lane. Shutdown invalidates/cancels outstanding work and reports whether cooperative workers actually joined.

## Preview replacement and browser safety

`RenderCoordinator` owns a monotonically increasing generation per transport channel. A replacement cancels the previous job; even if it completes late, the old generation cannot publish. `stop()` also advances the generation, preventing late HTTP/decode results from starting playback. Identical completed preview requests use a bounded cache but are rewrapped in the new generation.

`web/jobs_transport.mjs` independently applies the same rule in the browser and replaces audio/scopes/revision metadata as one snapshot. This prevents an audio result from revision N being displayed with scopes or recipe identity from N+1.

## Atomic output

`atomic_publish_bytes()` fsyncs a temporary sibling and uses `os.replace` only after the cancellation check. A cancelled publication cannot partially overwrite an existing artifact. Project render slots should be bound only after artifact validation/publication succeeds.

## Numeric oversubscription

The scheduler's default `numeric_threads=1` prevents each Python worker from independently spawning a full BLAS/OpenMP team. This is a process-wide policy. Change it only after profiling; worker-count × native-thread-count is the quantity that matters.

## Validation and benchmarks

Run each command separately from the repository root after materializing the authenticated baseline:

```sh
python -m pip install numpy==2.3.5 scipy==1.17.0 -r requirements-contracts.txt -r requirements-jobs.txt
python -m unittest discover -s tests/jobs -v
node tests/jobs/browser_transport.mjs
python tools/benchmark_jobs.py --baseline --out jobs-benchmark.json
```

The benchmark records cold preview, warm-cache, preview-under-background-load and cooperative cancellation latency with platform/Python metadata. Its numbers describe only the host that executed it; they are not universal real-time guarantees.
