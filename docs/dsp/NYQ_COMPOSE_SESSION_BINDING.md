# NYQ controlled sampler — source-bound Compose integration slice

Integration-owned, opt-in source/PCM acceptance boundary for #252/#253.
Candidate stacked on #273 at exact reviewed head `ec95dc7ac559c09c1afb469025727900c4a623d9`.
This is not an approved product graph node, per-band insert, 48-kHz delivery
converter or upstream-feature route. Do **not** merge #273 or this candidate
without final-head original-host qualification and independent review.

## What the new adapter does

`bind_completed_compose(timeline, job_id)` accepts **only** a completed,
current, TimelineService-owned, full-context ordinary Compose render. It reads
the authoritative RuntimeSession generation and TimelineDocument, independently
compiles that document's RenderRecipe and verifies the owned artifact's revision,
recipe SHA, full region, PCM byte count and content SHA-256. It creates a
`FrozenInput` directly from the actual returned float32 PCM; there is no
caller-supplied mutable audio or claimed graph hash on the binding path.

The resulting `packet_claims` describes this **current complete-mix source
only**: source revision = TimelineDocument revision, graph identity = compiled
RenderRecipe SHA, rack identity = source-derived rack digest, and actual
FrozenInput asset digest. These become parameters for the existing #267 packet
producer. `prepare(...)` revalidates the current source, graph, actual packet
and existing #266 SamplerPlan; it refuses upstream-feature routes because
their graph taps and input PCM are not yet authenticated. Render and checkpoint publication validate the source/recipe/PCM before entering
a short final handoff synchronized with TimelineService's owned-job lock and
RuntimeSession's document lock (in that order). This final check rejects edits,
including A→B→A, job revocation, and caller cancellation observed at handoff;
it also rechecks authority after the cancellation callback in case the callback
caused a reentrant mutation. Expensive controlled audio rendering stays outside
the locks. Publication has a defined final-check linearization point, not a
promise that independent caller cancellation flags cannot change *after* return.
The delegated renderer checks cancellation between bounded blocks.
No legacy audio or default route is changed.

This demonstrates the source/session authority needed by a later registered
Compose consumer. It deliberately **does not** change the underlying #266
diagnostic `live_graph_authenticated=false`: authoritative *component graph
execution and upstream routing* are still unimplemented. Nor does it claim
the post-master full mix is an approved per-band placement.

## Qualification

```sh
python -m unittest discover -s tests/runtime -p 'test_nyquismic_compose.py' -v
```

The tests render real Compose source PCM through the ordinary TimelineService,
compile the #267 physical-event clock, and execute the #266 controlled sampler.
They verify region/checkpoint PCM identity, real current-session graph/source
receipts, refusal of a forged graph SHA and truncated source region, generation
revocation across a repeated document (ABA), cancellation during rendering,
and saved-document cold-reopen numerical identity. Adversarial regressions
also inject ordinary Compose edits, direct RuntimeSession edits, job revocation,
and caller cancellation on the *last* artifact read of the final guard: a
successful ordinary PCM render must not publish past these late boundaries.

Record exact Ubuntu/Windows CI checks, direct/reverse programme impact and
independent review **before** considering this code qualified. Any ZG-024a
implementation-provenance transition needs exact-source, reviewer-approved
registration; never add a wildcard exemption. Standalone #266/#267 source
ownership remains unchanged.

## Required subsequent product work

The actual editable/saved Nyquismic route still needs an Integration-owned,
versioned live graph placement and a final delivery/export authority, explicit
upstream tap/feature input verification, and independent owner audition.
`#252` and `#253` remain unsatisfied, `#254` remains blocked. This
candidate must not bypass #242's independent Gate A/B Phase-A HOLD.
