# ZG-004 bounded local jobs

This layer keeps expensive offline work from stealing the only execution lane needed by live preview. It is deliberately local: no distributed queue, daemon dependency or GPU requirement.

## Scheduling contract

`JobScheduler` has two independent worker lanes. `PREVIEW` and `RENDER` use the interactive lane; `ANALYSIS`, `RESEARCH` and `BATCH` use the background lane. Background workers are mechanically unable to occupy interactive workers. They are also capped below `max_memory_bytes - interactive_memory_reserve_bytes`; every preview must fit inside that reserve. Therefore a long analysis cannot starve a preview through worker or declared-memory exhaustion. A non-cooperative long *interactive render* is not claimed to be preemptible.

Defaults: 1 interactive worker, 2 background workers, 64 total queued jobs, 48 queued background jobs, 512 MiB declared running-memory budget, 64 MiB interactive reserve, 256 MiB per-job bound, 64 MiB preview bound, 96 MiB/32-entry preview result cache and one native numerical thread per BLAS/OpenMP pool. `max_history_jobs` must be large enough to hold the maximum queued work plus every worker. History pruning scans for the oldest terminal records rather than stopping behind an old running job, and pruning occurs on later admission so a just-completed result remains observable to its waiter.

Admission distinguishes permanent impossibility from temporary backpressure. Every accepted job must fit the immutable memory capacity of its assigned lane when that lane is otherwise idle: interactive work may use up to the process reservation subject to its existing per-job/preview bounds, while background work must fit `max_memory_bytes - interactive_memory_reserve_bytes`. A request that can never fit is rejected synchronously before queue mutation; a feasible job that is only blocked by currently running work remains queueable and starts once memory is released. This lane-feasibility check does not clamp or rewrite caller estimates, and it intentionally permits `max_job_memory_bytes` to exceed the background lane capacity so larger interactive renders remain expressible.

Memory accounting is admission/reservation metadata, not a claim that Python can prevent an executor from allocating more than declared. Future subprocess isolation may add hard RSS enforcement if profiling justifies it.

## State and cancellation

Jobs expose queued, running, cancel-requested, cancelled, completed and failed states with monotonic progress. Queued cancellation is immediate. Running cancellation is cooperative through `JobContext.check_cancelled()`. A cancelled/cancel-requested preview is not eligible for deduplication into a new request. A worker exception fails that job and does not poison the lane. Shutdown invalidates/cancels outstanding work and reports whether cooperative workers actually joined.

Executor return is **not** the publication boundary. A returned value remains provisional until the worker reacquires the scheduler condition lock and commits its terminal state. Under that lock the scheduler atomically chooses cancellation or completion: if `cancel()`/shutdown was accepted before the commit, cancellation wins, the record becomes `cancelled`, the provisional result is discarded, progress is not forced to `1.0`, and no preview-cache insertion occurs. If completion acquires the lock first, `completed` plus result/cache publication is committed atomically and a later `cancel()` returns `False` rather than revoking already-published work. This publication guard applies even when an executor performs no internal cancellation checks; cooperative checks remain necessary only for stopping expensive work *before* it naturally returns.

## Preview replacement and browser safety

`RenderCoordinator` owns a monotonically increasing generation per transport channel. A different replacement cancels the previous job; even if it completes late, the old generation cannot publish. An **identical** replacement instead adopts the still-queued/running computation under a new client generation, so rapid duplicate key/UI events neither restart expensive work nor allow the old generation to publish. `stop()` advances the generation and cancels the active job, preventing late HTTP/decode results from starting playback. Identical completed preview requests use a bounded cache but are likewise rewrapped in the new generation.

Every preview request is bound to one immutable publication identity: `(revision_id, recipe_sha256, cache_key, product="preview")`. `RequestTicket` carries that complete identity across asynchronous completion. The same fail-closed validator is applied to cache hits, fresh worker results, and the final accepted-message path. A mismatched executor result fails as `JobError` before it can enter the preview cache; a mismatched pre-existing cache entry is rejected before it can become channel state. Identity fields are never relabelled or rewritten to make a result fit the request. `product` is explicitly fixed to `preview` so an artifact from another render product cannot cross-publish through this surface.

`web/jobs_transport.mjs` independently binds a complete request identity at `begin()` and replaces audio/scopes/identity metadata as one snapshot only after every bound field agrees. The preview coordinator binds `product="preview"`; browser consumers of other artifact products must pass the artifact's exact product explicitly rather than relying on that preview default. Timeline playback therefore binds the completed render artifact's revision, recipe SHA, cache key and product before making its object URL playable. A stale generation or any revision, recipe, cache-key, or product mismatch is non-playable and cannot replace already accepted audio/scopes. This is a publication guard only; it does not change audio bytes, DSP, recipe hashing, cache-key derivation, or product defaults.

## Artifact and atomic-output integrity

`RenderArtifact` stores `audio_bytes` as the caller-provided immutable `bytes` object and does not duplicate the audio payload. Asset and scope metadata are serialized once, before validation, into bounded deterministic key-sorted JSON byte snapshots. The `AudioAssetRef` contract plus PCM frame/channel shape and content SHA-256 checks are run against a fresh decode of the exact retained asset snapshot, so caller-owned dictionaries can never become a second authority after validation.

Public `.asset`, `.scopes`, and `.metadata()` access remains source-compatible with callers that expect ordinary mutable JSON-compatible dict/list values: each access returns a fresh container. Mutating those returned values, or mutating the original construction inputs after the artifact is created, cannot change the artifact's accepted identity, provenance, scopes, cache accounting or later listening/preview serialization. Logical metadata equality is independent of dictionary insertion order because snapshots and accounting use the same deterministic key ordering. The existing JSON guard remains fail-closed for NaN/Inf, non-JSON values and metadata larger than 2,000,000 encoded bytes. Preview cache accounting uses the actual immutable audio plus serialized artifact metadata; it does not rely on a fixed guessed overhead.

`atomic_publish_bytes()` fsyncs a temporary sibling and uses `os.replace` only after the cancellation check. A cancelled publication cannot partially overwrite an existing artifact. Project render slots should be bound only after artifact validation/publication succeeds.

## Numeric oversubscription and process ownership

The scheduler's default `numeric_threads=1` prevents each Python worker from independently spawning a full BLAS/OpenMP team. The limit is process-wide, so it is owned by one reference-counted numerical runtime rather than independently by each `JobScheduler`.

The first production scheduler that enables numerical limiting captures the exact external values (including absence) of `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `NUMEXPR_NUM_THREADS`, and `VECLIB_MAXIMUM_THREADS`, installs the requested environment limit, and enters one `threadpoolctl.threadpool_limits()` guard when `threadpoolctl` is available. Additional schedulers requesting the **same** limit acquire leases on that same policy; they do not re-enter or independently restore the process guard. A scheduler requesting a **different** limit while an owner is active fails synchronously with `JobError` rather than changing native pools underneath already-running work. Shutdown order is therefore irrelevant: only release of the final lease restores the original native threadpool state and exact external environment.

When `threadpoolctl` is unavailable, acquisition remains explicit but is marked `degraded` through `zaaggenz_jobs.runtime_state()`: environment limits are owned/restored, but no claim is made that already-loaded native libraries were reconfigured. This is a diagnostic/deployment state, not silent assurance. `apply_numeric_limit=False` remains the explicit path for a scheduler running beneath an already-owned process runtime (and for narrowly scoped tests); such a scheduler does not acquire or release numerical-runtime ownership itself. Callers using that mode are responsible for ensuring a surrounding owner exists where hard native-pool governance is required.

Construction and teardown are exception-safe at the ownership boundary. If scheduler construction fails after acquiring a lease, partially started idle workers are shut down before that lease is released. Normal scheduler shutdown releases its lease only after its workers have joined; a worker/job failure does not release another scheduler's ownership. The policy changes resource governance only: it does not alter DSP, audio bytes, render identity, scheduling lanes, memory admission, cancellation semantics, or musical defaults.

## Validation and benchmarks

Run each command separately from the repository root after materializing the authenticated baseline:

```sh
python -m pip install numpy==2.3.5 scipy==1.17.0 -r requirements-contracts.txt -r requirements-jobs.txt
python -m unittest discover -s tests/jobs -v
node tests/jobs/browser_transport.mjs
python tools/benchmark_jobs.py --baseline --out jobs-benchmark.json
```

The jobs suite includes production-path multi-scheduler ownership in both shutdown orders, conflicting-limit rejection, exact external-environment restoration, the explicit no-`threadpoolctl` degraded path, construction/worker failure cases, and real native-pool inspection when NumPy exposes a backend through `threadpoolctl`. ZG-004 CI runs that evidence on both Ubuntu and Windows. The benchmark records cold preview, warm-cache, preview-under-background-load and cooperative cancellation latency with platform/Python metadata. Its numbers describe only the host that executed it; they are not universal real-time guarantees.
