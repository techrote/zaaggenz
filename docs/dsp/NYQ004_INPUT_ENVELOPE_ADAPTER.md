# NYQ-004 bounded upstream input-envelope adapter

Status: **experimental opt-in component on PR #267**, not accepted
NYQ-004, saved Compose execution, audio-rate phase integration or a real
graph-feature/cross-band capability. The accepted NYQ-002 SamplerPlan and
ClockSpec.require_geometry rejection remain unchanged.

`UpstreamRmsPolicy` in `zaaggenz_contracts.nyquismic_input_envelope`
declares the frozen PCM hash (SHA-256 of interleaved little-endian float32
bytes), sample rate, frame count, exact upstream stable source ID, selected
channel, physical-time origin, integer window support and rational full-scale
reference amplitude. Consumers additionally declare their stable instance ID
and a **graph-owner-verified** acyclic upstream ID set. The adapter rejects
a self tap, missing upstream source, duplicate/invalid IDs, mismatched
audio identity, nonfinite PCM, invalid channel, oversized lane and over-range
levels rather than inventing a source or normalizing it.

For each half-open `window_frames` source interval, compute RMS in float64
and divide by the **explicit saved reference amplitude**. Quantize to a
bounded 1,000,000-denominator rational (not to the evaluation sample clock).
This is a deterministic physical-time, right-continuous *step* control; its
value owns the interval beginning at that window start. With a nonzero saved
`origin_s`, the route holds a **neutral zero value until the exact source
origin**, then inserts the first measured value as an additional step point;
it cannot disclose future PCM before that origin. The extra point consumes
one of the same 256-point budget slots, failing closed if over capacity.
Because it measures
the entire window before applying the value, it requires **up to one window
of offline lookahead**, recorded in diagnostics; no causal/realtime claim.
Incomplete final windows use actual samples, not implicit zeros. The
returned ordinary `ModulationRoute` has <=256 points plus an initial
value; it can be inspected by `evaluate_instantaneous_rate` but cannot
yet be executed by the frozen NYQ-002 sampler.

Record the complete `UpstreamRmsPolicy` JSON alongside the compiled route,
its independent policy SHA, PCM SHA and route SHA. This adapter does not
register a graph node, discover ancestors, perform source-to-project binding,
support spectral-centroid confidence or high-rate input-derived jitter, or
create a WAV/demo render. A future integration must establish real graph
topology, cache invalidation, consistent source support and sampler phase
execution before claiming input-driven cross-band instrument support.

Test: `python -m unittest discover -s tests/contracts -p 'test_nyquismic_input_envelope.py' -v`.
Tests cover exact step/window boundaries, actual clock inspector consumption,
source tampering, upstream identity/cycle admission, pre-origin leakage and
strict delayed-source point budgets, mono/stereo/partial/empty
input, full-snapshot persistence, deterministic repeat, bounds and cancellation.

## Exact DAG-snapshot input binding (experimental)

`UpstreamGraphSnapshot` / `UpstreamGraphEdge` provide the optional
`nyq.upstream-graph-snapshot.v1` proof mode for RMS and transient controls.
A complete bounded 128-node / 1024-edge stable-ID DAG rejects cycles,
foreign endpoints, duplicates and unordered identities. The exact
transitive ancestors of the consumer must match the declared source set.
The supplied current graph SHA must match the snapshot digest; stale,
missing, forward, self and downstream input references refuse execution.
The source PCM remains privately snapshotted and content-hashed. Diagnostics
record the verified **snapshot** digest, separately from the PCM/policy hashes.

**Authority limitation:** this validates a *provided* graph and hash, not
that either originates from the live Compose/RenderRecipe graph. Integration
must independently bind the snapshot and expected digest to the current
project revision. Legacy ID-only calls explicitly report
`caller-declared-only`; they are not reclassified as verified ancestry.
No product graph, NYQ-002 sampler, schema migration or default sound changes.
A controlled-clock cross-band numerical PCM test is an experimental model
fixture, not evidence of live Compose feature plumbing or general audio-rate
modulation.
