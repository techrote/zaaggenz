# ZG-029 persistent layer runtime

Status: implementation contract for ZG-029 / issue #30  
Ownership authority: `docs/zaaggenz/ZG029_LAYER_OWNERSHIP_ADR.md`  
Runtime identifier: `zaaggenz.layer-runtime`  
Runtime version: `1.0.0`

## Purpose and compatibility boundary

`zaaggenz_layers` is the executable adapter that turns the accepted ZG-029 ownership policy into real BODY/AUX/SUB state and stems while leaving the frozen ZG-002 `RenderRecipe` and `PhrasePlan` 1.0.0 wire contracts unchanged.

The adapter deliberately does not reinterpret existing recipes. A base recipe remains the protected source/SYNTHLINE owner and is rendered by the accepted ZG-008 renderer. A separate accepted `ProgressionResult` supplies stable harmony voice identities and BODY/AUX/SUB target frequencies. The runtime combines those two authorities without re-synthesising the protected source line.

No existing recipe hash, source/content identity, recovered-source byte, DSP topology, tuning equation, clipping policy or artistic default is changed by introducing this adapter.

## Inputs and ownership

A coordinated render requires:

1. an accepted synth-mode `RenderRecipe` whose authored phrase events are SYNTHLINE events;
2. a `ProgressionResult` using the same `TuningSpec.id`;
3. exact frame start/duration rationals;
4. a `LayerRuntimeSpec` containing an **explicit** generator specification for every persistent role present in the progression;
5. optional transform ownership claims/targets; and
6. when concrete state is continued from an earlier section, an explicit `LayerSectionTransition` bound to the exact ownership manifest.

Authored BODY/AUX/SUB/exciter events in the base PhrasePlan currently fail with `ambiguous-authored-layer`; they are not silently ignored, rebound or collapsed into a convenient renderer. ZG-029 v1 uses stable harmony voice IDs from `ProgressionResult` for persistent state because the frozen PhrasePlan event shape does not carry a separate persistent voice identity. A future PhrasePlan-to-persistent-layer adapter must be explicitly versioned rather than inferred from event IDs.

The current persistent generator is intentionally narrow: the caller must explicitly select a `sine` generator and its role gain, glide length, release length and initial phase. There is no hidden BODY/AUX/SUB timbre or gain default.

## Protected SYNTHLINE and exciter path

The base recipe is rendered through `zaaggenz_melody.render_phrase()`. Its exact raw `synthline` and `exciter` stems are retained in the coordinated result.

Harmony voices carrying role `synthline` are recorded in the runtime trace as `source-owned-not-resynthesized`; the coordinator does not create replacement PCM for them. This is the executable source-preservation rule required by ZG-029 and corrective issue #202.

Role-scoped muting happens before the protected SYNTHLINE graph is applied. Therefore a mute cannot be simulated by deleting an already-processed full mix. Existing compatible SYNTHLINE topology is then executed by the same preserved-topology path used by ZG-008.

## Persistent BODY/AUX/SUB state

Concrete state is stored in a versioned, content-addressed `LayerRuntimeState`. Each `(role, harmony voice id)` checkpoints:

- oscillator phase in cycles;
- last realised frequency;
- release-tail level; and
- remaining release samples.

The state is strict deterministic JSON and carries its own SHA-256 identity. Tampering or non-finite/out-of-bound values fail closed.

BODY/AUX/SUB phase is integrated sample-by-sample. Target changes use the caller-declared bounded glide length. Gaps use the caller-declared bounded linear release while phase continues to advance at the last realised frequency. This makes save/reload continuation deterministic rather than dependent on process-local oscillator objects.

A non-empty prior state cannot be consumed without a `LayerSectionTransition`. `continue` preserves the checkpoint. An explicit role reset removes that role's checkpoint so its next voice starts at the declared generator phase and with cleared tail state. Reset decisions therefore cannot be inferred from function/process boundaries.

## SUB pedal and moving-root semantics

`PhrasePlan.bass_role` remains authoritative:

- `none`: a progression containing SUB is rejected;
- `pedal`: every persistent SUB voice must retain one frequency across the supplied progression; movement fails with `pedal-sub-moved`;
- `moving`: SUB may follow the explicit harmony progression.

BODY/AUX retune/reweight targets are layer-scoped and cannot move SUB by implication. An explicit SUB transform claim is a separate owner decision.

## Transform coordination

The runtime feeds `LayerRuntimeSpec.transform_claims` through the accepted `resolve_transform_claims()` ownership rule. Competing owners fail unless every owner has a complete, unique non-negative order.

`LayerTransformTarget` is the executable value supplied by an already-authorised owner. In runtime v1:

- `retune` values are bounded cents offsets;
- `reweight` values are bounded dB offsets;
- targets may apply to one stable voice id or `*` for the role;
- a target without a matching ownership claim fails;
- an owner with no supplied target follows the declared identity/bypass path; and
- the diagnostic voice trace records the exact ordered owner chain and applied/bypassed value.

This is coordination, not a replacement for ZG-017 spectral tracking or ZG-020 adaptive-tuning estimation. Those systems may produce explicit targets; they do not gain implicit priority by calling last.

## Stems, routing and final master

A coordinated result exposes same-named role stems:

- `synthline`;
- `exciter`;
- `body`;
- `aux`;
- `sub`; and
- assembled `pre_master`.

BODY/AUX/SUB generator PCM is pre-master and is not passed through the protected SYNTHLINE graph. Future role-local nonlinear stages require an explicit owner/stage contract; they are not inferred here.

The only final output operation is the base `RenderRecipe.output` policy, applied once after role assembly. No normalization, makeup gain or automatic energy restoration is introduced. Stem and final-mix PCM hashes are recorded in diagnostics for null/regression evidence.

ZG-030 remains the owner of layer-aware subtractive pockets and measured sidechain separation. It must consume these role stems and preserve the single-final-master/no-hidden-makeup rule.

## Fail-closed boundaries

The runtime returns structured diagnostics instead of silently dropping/rebinding material for at least:

- invalid or non-synth base recipes;
- authored non-SYNTHLINE base roles without a declared adapter;
- tuning disagreement;
- overlapping/out-of-span harmony frames;
- harmony voice role changes;
- undeclared or moving pedal SUB;
- missing explicit persistent generator;
- ambiguous transform ownership;
- unowned transform targets;
- out-of-band persistent targets;
- tampered runtime state;
- continued state without a section transition; and
- final-output execution failure.

## Validation

`tests/layers/test_runtime.py` exercises the real ZG-008 renderer plus real harmony progression output. It covers:

- exact SYNTHLINE/exciter PCM preservation;
- independently addressable BODY/AUX/SUB stems and role mute boundaries;
- fixed-pedal versus moving-root SUB;
- layer-scoped upper retune that leaves SUB unchanged;
- unordered transform conflict and explicitly ordered execution trace;
- save/JSON-reload/continue identity and explicit reset divergence;
- missing-transition and missing-generator fail-closed behaviour;
- one final master with no hidden normalization;
- non-octave 13-ED3 execution; and
- state tamper rejection.

The ZG-029 workflow runs this suite on Ubuntu and Windows together with inherited ownership, harmony and melody regressions. Reverse-dependency CI owns `zaaggenz_layers/**` as ZG-029 so downstream ZG-030/ZG-038/ZG-042/ZG-043 and their transitive dependents can be selected by the programme impact checker when those workflows exist.

## Scope deliberately not claimed

This runtime does not claim to implement ZG-030 pocket/sidechain DSP, a new persistent-layer timbre library, automatic adaptive/spectral target selection, or a new frozen contract version. It supplies the executable state/stem/ownership layer those later systems require.

The earlier ownership ADR contains historical wording that persistent BODY/AUX/SUB execution was still future ZG-029 work. That statement describes the pre-runtime state in which the ADR was accepted; this document is the implementation record that supersedes that status while retaining the ADR's policy decisions unchanged.
