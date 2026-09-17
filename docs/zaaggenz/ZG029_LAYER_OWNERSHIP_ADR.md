# ZG-029 layer ownership ADR — authoritative pre-integration policy

Status: **accepted prerequisite policy**  
Policy identifier: `zaaggenz.layer-ownership`  
Policy version: `1.0.0`  
Parent: ZG-029 / issue #30  
Corrective reconciliation: issue #91  
Protected-base prerequisite: issue #138 / PR #151

## Decision

ZG-029 integration uses one canonical layer vocabulary:

| role | stem | musical responsibility | source identity | pitch/tuning owner | phase/state owner | gain owner |
| --- | --- | --- | --- | --- | --- | --- |
| `synthline` | `synthline` | lead / protected source line | protected source | authored PhrasePlan event | RenderRecipe note mode (`source-derived` or explicit `reset-event`) | event/gesture, then the one final master |
| `exciter` | `exciter` | transient reinforcement | derived from the SYNTHLINE event; never a substitute for SYNTHLINE | SYNTHLINE event | SYNTHLINE event; each exciter trigger is a reset boundary | exciter generator, then the one final master |
| `body` | `body` | persistent upper sonority/body | layer generator | harmony-layer owner | BODY persistent layer state | BODY automation, then the one final master |
| `aux` | `aux` | complementary group | layer generator | harmony-layer owner | AUX persistent layer state | AUX automation, then the one final master |
| `sub` | `sub` | pedal or moving-root foundation | layer generator | `PhrasePlan.bass_role` | SUB persistent layer state | SUB automation, then the one final master |

Every canonical role owns a distinct same-named pre-master stem. The policy declares independent stem audition, role-scoped mute ownership and a no-retune/no-reweight identity path for every role. In particular, muting or deriving the exciter never satisfies or removes the SYNTHLINE stem obligation.

`BODY low` and `BODY upper` are not new frozen RenderRecipe-v1 wire roles. When a legacy/current implementation exposes them separately they are subcomponents of canonical `body`; ZG-029 may add an explicitly versioned independently-addressable layer section later, but current code must not forge new `PhrasePlan.layer_role` values.

Persistent BODY/AUX/SUB phase is continuous-integrated across ordinary note/phrase boundaries. A section reset is an explicit state transition, not an alternate implicit default. A consumer that cannot preserve the declared persistent state must fail/abstain rather than infer reset from call boundaries.

## Why a policy adapter, not a frozen ZG-002 schema rewrite

ZG-002 already serialises the output-relevant pieces used by accepted source-preserving paths:

- `PhrasePlan.events[].layer_role`;
- `PhrasePlan.bass_role`;
- `RenderRecipe.phase_policy`;
- `RenderRecipe.tail`, DSP topology, and final `output` policy.

Changing the frozen `RenderRecipe`/`PhrasePlan` `1.0.0` shape merely to restate those fields would create a compatibility migration without changing present audio capability. Issue #91 therefore introduces a **versioned ownership adapter/manifest** in `zaaggenz_contracts.ownership`. `ownership_manifest()` binds the existing PhrasePlan by canonical digest and expands it into a strict-JSON, deterministic policy snapshot. ZG-029 can bind/store that manifest when persistent layer instances become real output state.

This is a compatibility interpretation layer, not a new audible default. Existing recipe hashes and frozen v1 wire schemas are unchanged.

## Transform conflict rule

Retune and reweight ownership is exclusive per `(layer, quantity)`.

A second claimant is invalid unless **every** claimant supplies a distinct non-negative integer `order`. A complete explicit order creates an ordered chain. There is no priority-by-call-order, metric-score, module name, or "last writer wins" rule.

`resolve_transform_claims()` returns the serialisable ordered plan or raises `OwnershipConflict` with a strict structured `LayerOwnershipDiagnostic`. Unknown layers/quantities, malformed owner ids, partial orders, duplicate orders, and unordered competing owners fail closed.

Consequences:

- adaptive tuning and spectral retune cannot both move the same component silently;
- a fixed SUB/pedal is independent of upper-sonority motion;
- moving SUB/root is permitted only by the declared bass role or a future explicit owner chain;
- no analysis metric is promoted into an artistic-priority oracle.

## Bass/root rule

`PhrasePlan.bass_role` has one authoritative projection:

- `none` -> SUB pitch mode `inactive`;
- `pedal` -> `fixed-pedal`;
- `moving` -> `follow-declared-root`.

Upper BODY/AUX transforms do not move SUB by implication. This distinction is deterministic and survives serialisation because `bass_role` is already frozen PhrasePlan data.

## Section-boundary state rule

`section_transition_manifest()` is the explicit persisted boundary record for ownership policy `1.0.0`. It is content-addressed to the exact `LayerOwnershipManifest` and a canonical boundary id.

For BODY/AUX/SUB, the only legal section actions are:

- `continue`: preserve tail state and continue integrated phase/state;
- `reset`: reset to the declared layer origin and reset the layer-owned tail state.

A reset must name the persistent role explicitly. SYNTHLINE and exciter cannot be smuggled into this reset list because their reset lifetime is owned by the authored event/RenderRecipe note policy instead. Duplicate, unknown and non-persistent reset requests fail with structured diagnostics.

The section record is strict JSON with its own digest. `validate_section_transition()` verifies the digest and, when the bound ownership manifest is supplied, reconstructs the authoritative transition and rejects a re-hashed semantic mutation. JSON save/reload therefore preserves the declared continue/reset/tail decision exactly. The policy does not fabricate oscillator samples or phase accumulators before the persistent renderer exists; ZG-029 runtime must checkpoint any concrete state required to realise the already-declared transition.

## Source and transient protection

SYNTHLINE remains the full first-class protected source stem. Harmony/layer coordination may request pitch intent, but it does not grant permission to replace a source-derived hit with a re-synthesised one. Target-note synthesis remains an explicit named melody-render mode, not a harmony side effect.

The exciter is a derived transient/retrigger stem. It may reinforce a SYNTHLINE event but cannot satisfy, replace, mute, or stand in for the SYNTHLINE obligation. Residual/transient ownership established by analysis/component contracts is unchanged.

The #138 base-preservation barrier remains authoritative: source-preserving compilers transform the actual immutable project head, preserve compatible protected topology/output policy, and fail on ambiguous non-synth topology rather than rebinding it to SYNTHLINE.

## Gain, pockets, nonlinear stages, and final output

Each role may own its local gain automation and explicitly declared nonlinear stage. Those stages are pre-master. The only final output owner is `RenderRecipe.output`.

Subtractive SCULPT, multiband pockets, or future sidechains do **not** acquire makeup/normalisation authority merely because they reduce energy. Any gain restoration would require another explicitly versioned stage; it cannot be synthesized by the ownership adapter.

The ownership manifest therefore declares:

- final master owner: `render-recipe.output`;
- position: `single-final-stage`;
- normalisation: `none`;
- implicit subtractive makeup: prohibited.

ZG-030 may add pocket/sidechain behaviour, but it must consume this ownership rule.

## Legacy projection

Where recovered v1.2.1 concepts need names in the new model, the projection is explicit:

- legacy `click` -> `exciter`;
- legacy `body` -> `body`;
- legacy `sub` -> `sub`;
- recovered `synthline` -> `synthline`;
- recovered `aux` -> `aux`.

This is semantic mapping only. It does not rewrite recovered parameter records, move legacy processing onto another stem, or claim that legacy rendering had independently-addressable stems where it did not.

## Consumer rule, inspection and structured diagnostics

A renderer/compiler declares the canonical roles it owns. `require_renderer_roles()` compares authored PhrasePlan roles against that declaration and returns the same versioned manifest on success. Any non-owned authored role raises structured diagnostic code `role-not-owned-by-renderer`; consumers must not silently render it into a convenient stem.

`transform_inspection()` provides the stable inspection envelope required by later ZG-041 UI and provenance. It records layer, retune/reweight quantity, exclusive owner, stage, requested target, realised target when applied, and one of `requested`, `applied` or `abstained`. Applied records require a realised target. Abstentions require a reason. Targets are bounded strict JSON and malformed/non-finite evidence fails closed. The record is content-addressed; it does not choose a target or turn a metric into artistic priority.

Current ZG-008 remains SYNTHLINE-only. Its accepted exciter output is generated from SYNTHLINE roll/retrigger intent, not authored `layer_role=exciter` input. Persistent BODY/AUX/SUB audio execution remains ZG-029 work; this ADR prevents that work from inventing ownership locally.

## Compatibility and protected semantics

This decision intentionally does **not**:

- change `RenderRecipe` or `PhrasePlan` v1 JSON shape/version;
- change current accepted audio samples, note timing, source identity, tuning math, tail policy, DSP ordering, clipping policy, or final-master gain;
- introduce implicit resynthesis, normalization, makeup gain, retuning, or stem promotion;
- make BODY/AUX/SUB audible before ZG-029 implements them;
- alter #138 protected-topology preservation;
- alter partial/transient/residual provenance or ownership.

The policy manifest, section-transition record and transform-inspection record have their own digests and can be bound as evidence without changing frozen recipe identity.

## Required integration behaviour downstream

ZG-029/ZG-030 implementations must:

1. bind a policy manifest (or a future versioned successor) to each integrated persistent-layer render;
2. realise the saved `LayerSectionTransition` exactly and checkpoint any concrete persistent state needed to continue it across process save/reload;
3. keep every canonical same-named pre-master stem independently auditionable with role-scoped mute/null checks;
4. preserve `bass_role` fixed/moving independence;
5. route retune/reweight claims through the explicit conflict rule;
6. emit `LayerTransformInspection` evidence for requested/realised target, owner/stage, and conflict/abstention;
7. preserve one final `RenderRecipe.output` stage and no hidden post-pocket normalisation.

A future requirement that cannot be represented by policy `1.0.0` requires an explicit policy-version change; it must not be smuggled into the meaning of an existing field.
