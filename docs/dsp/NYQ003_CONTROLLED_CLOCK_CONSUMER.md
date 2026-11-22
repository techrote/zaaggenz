# NYQ-003 — Opt-in controlled-clock SamplerPlan consumer v1

**Draft #266 / issue #252. Component implementation; NOT cumulative acceptance.**
The authoritative packet producer is still separately owned by Draft #267. No
packet module, graph/session source, shared `examples/zg024a_*`, programme
state or CI was copied or edited on this branch.

## Executable API and identity

`SamplerPlan.prepare(source, sonic, sampler_evaluation(rate), *, controlled_clock=packet,
source_revision_sha256=..., graph_revision_sha256=..., rack_revision_sha256=...)`
uses the versioned #267 `ControlledSamplerClockV1` only when an actual packet is
present. It delegates to the immutable `ControlledSamplerPlan` execution type
rather than fabricating a legacy `ClockPlan` or `ClockCheckpoint`. The packet's
`require_claims` checks actual `FrozenInput.asset.sha256`, full physical extent,
sonic/source/route/clock/stereo/seed/band/group receipts and the asserted graph
revision. The consumer recomputes ordered per-channel frame ownership and
captures actual source PCM at each versioned rational physical event coordinate.
Certified error enclosures must give an unambiguous numerical frame; uncertain
nearest-source ties refuse. Complete source/channel, event, frame and output
extent budgets apply before publication; cancellation is atomic.

Supported reconstruction in this first controlled path is **hold, time-aware
nearest, linear and nonuniform cubic Hermite**, with explicit no-prefilter.
All static FIR prefilters and sinc/Shepard policies are **rejected** for this
controlled path, rather than treating irregular events as a uniform lattice.
Original static NYQ-003 execution continues to expose its own independently
qualified policies. Real modulated sampling does not synthesize an anti-alias
switch or suppress deliberate aliases.

For a selected packet, output identity binds the canonical frozen PCM asset,
exact packet and ledger hashes, source/rack/claimed graph revisions, numerical
evaluation and the full physical extent. Per-channel capture arrays are private
bytes-backed float64. Full, global-frame region and resumed checkpoint rendering
use identical event memberships and arithmetic anchors. A distinct strict
`nyq.controlled-sampler-checkpoint.v1` stores per-channel events-before,
neighbor indices/captures and render/packet/ledger hashes. Checkpoint restore
recomputes expected state from the immutable plan before accepting it; foreign,
stale and tampered checkpoints refuse.

A **missing packet takes the preexisting NYQ-002 path** with the same
`SamplerCheckpoint`, `ClockPlan`, identity and PCM bytes. There is no
automatic migration and no audible default change. A packet plus an explicit
bypass uses same-grid float32 dry copies only; no hidden resampler.

## Frozen cross-PR executable fixture

`tests/dsp/test_nyquismic_controlled_consumer.py` freezes one second of
canonical 48-kHz ramp, 4 Hz base with +4 Hz until t=1/2 and precisely six
half-open crossings at 0, 1/8, 1/4, 3/8, 1/2, 3/4 seconds. It compares
**actual SamplerPlan PCM** against independently specified per-frame hold
values on 192/384/768-kHz numerical grids, global-frame region and serialized
checkpoint replay, linked/independent stereo and per-channel capture values,
stale source/graph/sonic/checkpoint, cancellation and uncertainty-bound refusal.
The separate legacy absence test executes on ordinary #266.

The cross-PR tests use `skipUnless(HAS_PACKET)` intentionally. On #266
alone the #267 producer module does not exist: a green CI result with those
tests **skipped** is not consumer acceptance. Integration must construct a
reviewable **exact pinned #266 + #267** combined source, execute the test
methods on original Ubuntu and Windows jobs, and retain source-head/stack
receipts; no concealed author-side cherry-pick or shared-fixture admission.
Recommended focused command:

```sh
python -m unittest discover -s tests/dsp -p 'test_nyquismic_controlled_consumer.py' -v
```

Numerical output is component PCM, not final 48-kHz delivery, Compose
render/export, owner listening or native VST. Cross-rate *event ledger*
identity is required; PCM sample vectors at different numerical rates are
not required to have identical byte strings.

## Remaining authority and gates

The packet's graph revision and feature hashes are caller-supplied claims.
`live_graph_authenticated=false` and `upstream_pcm_authenticated=false`
are diagnostic truths, **not** a pass through Integration's serialized
live graph/session binder, acyclic source authority or upstream feature PCM.
No code on #266 certifies those independent gates. Separately review #267's
new packet head; resolve original reverse-dependency and ZG-024a provenance
failures under Integration ownership. Do not mark #252/#253 accepted, Ready,
merged or unblock #254 from this component result.
