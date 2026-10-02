# Nyquismic Modulation — implementation RAG and issue map

**Repository:** `techrote/zaaggenz`  
**Master:** [NYQ-000 #249](https://github.com/techrote/zaaggenz/issues/249)  
**First task:** [NYQ-001 #250](https://github.com/techrote/zaaggenz/issues/250)  
**Feature specification:** [NYQUISMIC_MODULATION.md](../dsp/NYQUISMIC_MODULATION.md)  
**Validation:** [NYQUISMIC_VALIDATION.md](../dsp/NYQUISMIC_VALIDATION.md)  
**Status at creation, 2026-10-02:** all nine children open; planning/docs only, no implemented or accepted Nyquismic capability yet.

This is the focused retrieval map and executable-work handoff for the approved feature. It does not replace accepted implementation/contracts or the canonical ZG programme's readiness state. `NYQ-*` are local follow-up identifiers, like `MBR-*`, not additions to the stable `ZG-000` through `ZG-045` IDs. Do not renumber the programme or silently rewrite its DAG.

## NYQ-001 implementation handoff

The 1.0.0 foundation is now in `zaaggenz_contracts/nyquismic.py` and
`zaaggenz_contracts/nyquismic_clock.py`; read
[NYQ001_FOUNDATION.md](../dsp/NYQ001_FOUNDATION.md) before changing or consuming it.
It is the frozen parameter/bounds/phase/source-map/seed/checkpoint/identity and
fixture-hash reference. `tests/contracts/test_nyquismic.py` runs through the
existing mapped ZG-002 contract workflow; independent oracle and fixture paths
also have explicit reverse-dependency ownership. No audio renderer, rack insert,
Project migration or factory change is supplied. All audio execution fails
explicitly, and unsupported routed/jitter/quantized clock geometry fails too.

Reconciled main is `b76d22df189d176ea371e14e2fb0eff74cd2f7af`, containing accepted
#248 and documentation #259. Concurrent #240 owns execution/runtime/API/export;
NYQ-001 stays on contract/oracle surfaces. This source note does not satisfy a
merge gate: consult #250's exact-head CI and verified merge before starting #251.
#251 should reuse the integrated phase/event authority and frozen independent
fixtures, not introduce a competing rounded-hold or period-recurrence clock.
#256 alone owns the future typed rack adaptation after #255 and accepted #242.

## Owner decisions to preserve

The feature name is **Nyquismic Modulation**; technical descriptions are **modulated virtual sampling lattice** and **virtual sample clock**. Retrieval aliases: nyquizmic, Nyquist modulation, clockfold, ratewarp, modulated sample-rate reduction, clock jitter, resampling damage, alias lattice.

Intent: selectable and modulatable virtual sampling/reconstruction, arbitrary positive rates/ratios, rate quantization, jitter, playback warp and cascades as a first-class optional sound-design family. It extends rather than replaces amplitude bitcrushing.

ZaagGenZ is primarily offline, with no hard realtime, latency or performance-efficiency requirement. Prioritize accurate evaluation and reproducibility. Keep finite work/memory bounds, cancellation, progress and atomic results for safety, not as an arbitrary realtime acceptance gate.

Do not conflate numerical evaluation quality, virtual artistic rate and delivery sample rate. Preserve intentional sonic aliases while controlling accidental numerical artifacts. Do not imply awkward ratios inherently degrade high-quality conversion, or claim this product name invents sample-rate reduction/jitter. The spec records primary references and their limits.

Factory/source/default records remain immutable, including `locked_bloom`; edits create opt-in working-copy/user-preset revisions. Owner listening/favorites/default promotion remain separate from engineering correctness. No new rating campaign, ZG-024 prerequisite, private-audio upload or external plug-in prerequisite.

## Issue chain and readiness

| Local ID / issue | Owns | Direct hard prerequisites |
|---|---|---|
| [NYQ-001 #250](https://github.com/techrote/zaaggenz/issues/250) | Executable contracts, clock/time semantics, independent fixtures and bounds | No local child; validate live accepted foundation evidence |
| [NYQ-002 #251](https://github.com/techrote/zaaggenz/issues/251) | Fractional-event sampler, continuous phase and state | #250 |
| [NYQ-003 #252](https://github.com/techrote/zaaggenz/issues/252) | Capture/prefilter/reconstruction policies and model-aware evaluation quality | #251 |
| [NYQ-004 #253](https://github.com/techrote/zaaggenz/issues/253) | Musical/audio-derived modulation, rate quantization and deterministic jitter | #251 |
| [NYQ-005 #254](https://github.com/techrote/zaaggenz/issues/254) | Explicit read-clock/playback warp | #252 and #253 |
| [NYQ-006 #255](https://github.com/techrote/zaaggenz/issues/255) | Ordered three-stage damage cascades and local rate-domain composition | #254 |
| [NYQ-007 #256](https://github.com/techrote/zaaggenz/issues/256) | Real graph/rack execution, state/persistence, per-band preview/cache/export | #255 and accepted MBR Phase A / #242 |
| [NYQ-008 #257](https://github.com/techrote/zaaggenz/issues/257) | Normal Compose UI, automation, inspection and user presets | #256 |
| [NYQ-009 #258](https://github.com/techrote/zaaggenz/issues/258) | Independent numerical/compatibility/Windows workflow acceptance | #257 |

```text
#250 -> #251 -> #252 --+
             -> #253 --+-> #254 -> #255 --+
                           MBR #242 -----+-> #256 -> #257 -> #258
```

#252 and #253 may run in parallel only after #251 freezes their interfaces and ownership is disjoint. Kernel/contract work need not wait for MBR. Integration #256 must consume actually accepted built-in rack evidence through #242; no dependency on MBR VST3 Phase B #243–#247. This chain cannot mark master #238 complete after built-in integration.

A prerequisite is satisfied by accepted implementation/evidence, not merely a closed GitHub issue. For canonical ZG foundations consult live `programme/task_state.json` and the corresponding accepted contracts/tests; for local NYQ/MBR children inspect their verified merge/evidence records. Missing/revoked evidence blocks reliance. Update canonical state only if its own accepted evidence genuinely changes through review.

## Planning snapshot and live reconciliation

Planning inspected main `2dc6390b6f134c897170b8b0bf88fdffe328e373`. Existing `BitcrushSpec` uses an integer sample-0-anchored hold plus amplitude quantizer; it is not the proposed fractional-event sampler. The generic AA layer's existing production/reference policy is preserved, not widened by this plan.

The latest #238 handoff at planning has MBR-001 #239 implemented in PR #248 but not merged/accepted, with #240 execution, #241 UI and #242 built-in acceptance still distinct. PR #237 carries separate preset/audition work. Re-read live refs/issues/PRs before coding; this paragraph is dated evidence context, not a permanent blocker or instruction to branch from an old hash.

Do not copy pending implementation from #237/#248 or acquire their shared files implicitly. New Nyquismic integration must extend the actual landed rack schema; preserve all old four stage anchors/24 orders and use explicit versioning for arbitrary Nyquismic inserts.

## Common mandatory read set

Read the chosen child and master #249 in full, including current comments and accepted predecessor completion records. Then retrieve:

- applicable `AGENTS.md` files, if present in the live checkout;
- [AGENT_OPERATING_RULES.md](briefs/AGENT_OPERATING_RULES.md), [ARCHITECTURE.md](briefs/ARCHITECTURE.md), [VALIDATION_GATES.md](briefs/VALIDATION_GATES.md), and [CONTEXT_AND_DECISIONS.md](CONTEXT_AND_DECISIONS.md);
- the feature spec and validation plan linked above;
- [DSP graph/ownership](../dsp/README.md), [ZG-019 AA ADR](../dsp/ZG019_ANTIALIAS_ADR.md), [ZG-021 band DSP](../dsp/ZG021_BAND_SELECTIVE_DSP.md);
- live `programme/tasks.json`, `programme/dependency_graph.json`, `programme/task_state.json`, issue/PR evidence and [CI reverse dependencies](CI_REVERSE_DEPENDENCIES.md).

No AGENTS.md was returned by the planning code search; this is not proof that a future checkout has none. Inspect the actual checkout rather than inventing instructions or assuming this observation is permanent.

## Focused retrieval and ownership map

| Work | Retrieve in addition to common set | Shared locks to coordinate when touched |
|---|---|---|
| NYQ-001 contracts | `zaaggenz_contracts/{model,registry,recipe_schema,validation}.py`, Project/TimeMap/state formats, accepted MBR schema | `contracts-registry`, `graph-registry`, `session-format` |
| NYQ-002 sampler | `zaaggenz_dsp/{bitcrush,antialias,graph}.py`, new accepted clock/state contract and independent fixtures | `graph-registry`, `render-integration` |
| NYQ-003 filtering/quality | Accepted NYQ sampler, AA ADR, actual pinned SciPy API, source representation and numeric QC | `graph-registry`, `render-integration` |
| NYQ-004 modulation | TimeMap/automation, gesture/meter, immutable feature/detector contracts and upstream graph taps | `gesture-registry`, `graph-registry`, `feature-registry`, `render-integration` |
| NYQ-005 warp | Existing source-preserving melody/transposition, TimeMap, Nyquismic interpolation/state | `render-integration`, `graph-registry` |
| NYQ-006 cascade | Existing typed graph, stage order, shapers/bitcrusher, accepted local quality and state | `graph-registry`, `render-integration` |
| NYQ-007 integration | Actual accepted #238–#242 contracts; `band_selective.py`, `band_router.py`, session/jobs/timeline/long-form/export and layer ownership | `contracts-registry`, `session-format`, `band-dsp-integration`, `render-integration`, `api-integration`, `export-integration` |
| NYQ-008 UI | Existing Compose/rack editor, API, user-preset persistence, inspector and UI/backend manifests | `frontend-integration`, `api-integration`, `session-format` |
| NYQ-009 acceptance | All accepted children; packaging/environment, Windows/browser evidence, factory goldens and validation matrix | `test-baseline`, `release-integration` and actual repair owners |

Locks listed here refer to existing shared ownership concepts; they do not create a new global locking service. Record the exact files/reservation in the child before edits. New modules may be disjoint, but shared contract/registry/runtime files require serialization with MBR and other active work.

## Implementation rules that must survive handoff

Use integrated positive clock phase and fractional events. Preserve fixed output duration in sampler mode; playback warp has its own source read-time map and boundary policy. Ratio references, seeds and sonic filter support do not depend implicitly on numerical evaluation rate or chunk count.

Capture interpolation, prefilter, reconstruction and final numerical conversion are separate stages. Irregular-clock reconstruction has truthful limited capabilities, not a blindly reused uniform sinc. A local `f_v/2` display is a heuristic for nonuniform clocks. Retain intermediate frequencies that can mix back into the audible band through subsequent nonlinear processing.

All-bypass/zero-wet is exact identity after validation. Zero modulation means static effect, not necessarily dry. Preserve phase/reset/tails, instance/stereo state, immutable source and feature provenance, effect-delta alignment/confinement, all layer ownership and one final master. No hidden normalization, unsupported automation fallback or private source upload.

Use the existing RuntimeSession/JobScheduler/cache/export, not a parallel application. Region previews restore adequate prior/next context. Cache/render identity includes sonic and numerical settings; stale/cancelled/failed/inconclusive-quality artifacts cannot replace or masquerade as the current audible/exported revision.

A global 8x/16x quality-default change, universal 96/192 kHz export migration, physical ADC/DAC hardware-clock control, native VST host redesign and algebraic/self-modulating feedback solver are outside this feature chain. Do not add them as prerequisites or quietly implement them under Nyquismic.

## Autonomous kickoff prompt

```text
Work autonomously in techrote/zaaggenz on Nyquismic Modulation master #249.

Reconcile live main, applicable AGENTS.md, programme acceptance and in-flight
PRs, especially the separate MBR #238 chain and preset work. Read master #249
and the full first unfinished dependency-ready child, starting with #250 /
NYQ-001 unless live accepted evidence or recorded ownership says otherwise.

Read docs/zaaggenz/NYQUISMIC_IMPLEMENTATION_RAG.md,
docs/dsp/NYQUISMIC_MODULATION.md, docs/dsp/NYQUISMIC_VALIDATION.md and the
child's focused read set. Implement the actual child, not another issue
chain, speculative rewrite or disconnected demonstration.

ZaagGenZ is offline: prioritize faithful sound/reproducibility, not hard
realtime speed or latency. Keep finite safety budgets and cancellation.
Separate fixed project/delivery time, numerical evaluation quality and the
artistic virtual sampling clock. Preserve intentional alias character,
legacy factories/defaults, source/layer/phase/tail/master ownership and
exact bypass. Use fractional clock events and explicit playback-warp
semantics; no rounded-hold substitute or hidden global clock changes.

Reuse the existing contracts/graph, bitcrusher/shapers, band effect-delta
router, immutable Project/RenderRecipe, single RuntimeSession and jobs.
Record shared-file ownership. Add independent analytic and adversarial
oracles, state/chunk/region/serialization/finite-output tests appropriate
to the child, plus real instrument/browser evidence when integration/UI
is in scope. Freeze comparison rules before examining outcomes.

Open a focused PR; map changed paths to existing direct/reverse CI.
Repair actual failures without weakening the accepted behavior or tests.
Merge only after required exact-final-head checks/evidence pass; verify
main before closing the child or updating master #249. Continue only to
an actually dependency-ready unowned child. Record precise blockers and
stop rather than polling/revalidating or increasing quality indefinitely.

NYQ-003/#252 and NYQ-004/#253 may run concurrently after #251 only with
disjoint ownership. NYQ-007/#256 requires accepted built-in MBR #242;
core DSP does not wait for that rack, external VST3 Phase B, ZG-024, or a
new numerical owner-rating campaign. #258 owns final acceptance; do not
close master #249 on component-only tests or documentation completion.
```

## Reporting and drift control

Each child records exact PR/merge, implementation/contract version, commands/environment, oracle/render/artifact hashes, supported capabilities, direct/reverse CI, limitations and next actual prerequisite. Update this read set and the master checklist from evidence rather than issue state alone.

Run the existing programme state/docs validators when their surfaces are touched. Add direct CI ownership for new implementation paths as part of NYQ-001 and later children; do not add unmapped workflows, duplicate jobs, private runners or an unbounded evaluation matrix. This docs-only plan does not alter programme files or claim any new readiness.

A final completion must distinguish numerical correctness, normal instrument integration, platform acceptance and owner sound preference. A missing core mode or missing saved UI-to-export path remains a blocker; an optional unsupported policy combination must be visible and documented rather than falsely advertised.
