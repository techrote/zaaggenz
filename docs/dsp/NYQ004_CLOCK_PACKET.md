# NYQ-004 — Immutable controlled sampler-clock packet v1

**Status:** component producer on Draft #267, not #253 acceptance. Owns no
accepted SamplerPlan, Compose graph/session, UI, final PCM converter or export.

## Interface

`compile_controlled_sampler_clock_v1(sonic, *, full_end_s,
input_asset_sha256, source_revision_sha256, graph_revision_sha256,
expected_live_graph_sha256, upstream_route_receipts, budget, cancelled=None)`
returns `ControlledSamplerClockV1`.

The immutable, strict-snapshot packet contains saved SonicSpec/clock hashes,
instance/band/clock-group/stereo/seed identities, route receipts, claimed graph
and input revision, and separate channel ledgers with exact rational
(index, epoch, crossing, coordinate_s, error_bound_s) records. Each ledger
is compiled once in **physical seconds**, not in evaluation-frame indices.
Strict half-open event geometry, certified enclosure, minimum spacing,
per-channel and combined event budgets, cancellation and packet digest
validation are mandatory. The ledger SHA is independent of any numerical
evaluation rate. The per-channel `seed_identity_sha256` is a *packet context
receipt* derived from the saved root seed, stream, full clock SHA, instance or
clock-group scope, ungrouped band and linked/independent channel. The producer
and `require_claims` derive it using the same deterministic function, so an
otherwise valid/rehashed packet with forged mono or stereo seed receipts
refuses. It is **not** the actual counter-addressed jitter draw namespace:
accepted `clock_cell_value` uses root seed/stream, instance-or-group, physical
cell index and effective channel, without whole-clock SHA or band. Changing
this receipt validation does not change any jitter draws, event positions or
the packet v1 encoding. `require_claims` compares consumer-side
source/spec/revision *claims*, not the live session.

Each compiled route needs an `AuthenticatedRouteReceiptV1` with exact
compiled route SHA and saved source SHA/method. For source-derived features,
it additionally requires a typed feature/method/immutable-PCM SHA, a frozen
acyclic `UpstreamGraphSnapshot`, an actual declared ancestor of the consumer
and full extent/support/lookahead. Missing, foreign, stale or inconsistent
receipts fail closed. The producer does **not** receive the underlying immutable
feature PCM or authoritative project graph object, so it cannot prove that a
caller-provided matching SHA reflects either actual PCM or live Compose state.
The `live_graph_authorized`, `upstream_pcm_authorized`, and
`sampler_checkpoint_qualified` packet flags are intentionally always false.
Cross-band group equality similarly needs Integration-owned graph authority.

## Frozen numerical oracle

The one-second, 48-kHz immutable ramp with base 4 Hz and +4 Hz additive
control until 1/2 s yields exactly six events at 0, 1/8, 1/4, 3/8, 1/2,
3/4 seconds. `tests/contracts/test_nyquismic_clock_packet.py` checks
canonical round-trip, the six exact crossings, unchanged physical ledger
across 192/384/768-kHz numerical-ownership probes, source-native controlled
PCM via the existing proof, linked versus independent stereo seed namespaces,
stale route/input/graph and feature-DAG rejection, corruption, admission and
cancellation. The 192/384/768 checks are **packet/event-only** and do not
claim an executed NYQ-003 cross-rate PCM converter.

## Pending separate ownership and acceptance

#266 exclusively owns the opt-in `SamplerPlan.prepare(... controlled_clock=
None|packet ...)` consumer, exact source PCM identity preflight, per-channel
capture-grid membership, full versus region/checkpoint restore, delivered
PCM at several numerical rates, and preserved legacy absent-packet bytes.
Integration exclusively binds the currently authorised immutable live
graph/session revision, source/feature data, cross-band group authorities and
shared provenance examples. A caller's `expected_live_graph_sha256` is **not
proof of live binding**. The packet is not a persistent audio-state checkpoint.
No shared `examples/zg024a_*`, programme, graph, rack or CI files are changed.

Original exact-head Ubuntu/Windows ZG-002 contracts, ZG-016 DSP, ZG-000
reverse dependencies and independent source-critical review are required
before admission. The existing ZG-024a source/validation transition remains
Integration-owned and must not be rubber-stamped.
