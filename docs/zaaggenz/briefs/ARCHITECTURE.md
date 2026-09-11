# Architecture and shared contracts — programme brief

## Design rule

Zaaggenz remains an offline/asynchronously rendered **instrument first**. Research/analysis modules consume immutable project/audio artefacts and return observations or explicit proposed transforms; they never mutate the working sound implicitly.

## Layered system

```text
Project / RenderRecipe
  ├─ TimeMap + TuningSpec + PhrasePlan + GestureSpec
  ├─ SYNTHLINE source / note renderer
  ├─ optional partial-domain spectral transforms
  ├─ exciter + BODY + AUX + SUB persistent layers
  ├─ typed DSP graph / band processors / SCULPT
  ├─ final declared master/output policy
  └─ stems + mix + feature/analysis artefacts
```

The full SYNTHLINE is a first-class stem. A short exciter may reinforce/transient-trigger state but is not a substitute for the source line. Every layer owns explicit phase/reset/tail/state semantics.

## Core versioned contracts

ZG-002 should freeze minimal schemas for:

- **RenderRecipe** — all sonic intent, stage ordering, quality settings and deterministic random-stream identities.
- **AudioAssetRef** — immutable identity plus portable metadata; local location handled separately.
- **TimeMap** — samples/seconds/rational beats/tempo/meter plus conversion policy.
- **TuningSpec** — reference frequency, period, degrees/ratios/cents and keyboard mapping.
- **FeatureBundle** — method/version, time support, units, validity/confidence and measurements.
- **Partial/ComponentBundle** — frequency/amplitude/phase/confidence/track identity plus transient/remainder references.
- **GestureSpec / PhrasePlan** — musical direction, phrase roles, timing constraints and deterministic variation.
- **DSPNodeSpec / graph** — channels, units, parameters, state, reset, latency and automation.
- **TrialSpec / RunManifest** — immutable research stimuli, matching/randomisation and analysis identifiers.

## Timing / phase / state

Musical timing uses rational beat positions mapped through `TimeMap`; render scheduling ultimately resolves to integer samples under an explicit rounding policy. Tempo changes and tails must not silently alter event order. Analysis windows store centre plus support interval rather than pretending every estimate is instantaneous.

Oscillators/components declare whether phase is continuous, reset, inherited or source-derived. Stateful effects declare reset/chunk boundaries. Stereo processing declares linked identities vs channel-specific gains/phase.

## Gain policy

Keep source-level intentional nonlinear behaviour distinct from accidental bus overload. Stems specify whether they are pre- or post-master. The final master is one declared stage; subtractive SCULPT/pocket work is not normalised upward afterward unless the recipe explicitly requests another stage.

Numerical analysis preserves pre-output floating-point values so encoded clipping/limiting does not erase diagnostic information.

## DSP graph / band routing

Start with a constrained typed DAG rather than a free-form plugin host. Nodes expose units/bounds, latency/lookahead, channel shape, state and automation. Cycles are invalid unless a future explicitly bounded delayed-feedback contract is accepted.

Band-local processing should prefer effect-delta confinement so a zero-wet inserted band stage can retain identity. Crossover/filter transition and phase behaviour are part of the recipe. Nonlinear-stage ordering is musically significant and must be stored.

## Analysis / transform separation

Analysis produces immutable artefacts keyed by content + method configuration. A transform explicitly consumes those artefacts plus a target and emits a new recipe/render revision. Low-confidence analysis must permit abstention/identity fallback.

Requested target, estimated source and realised output are separate quantities throughout API/UI.

## Async jobs

Preview/render/analysis/search use bounded jobs with revision IDs, progress, cancellation and atomic result publication. A result computed from an old project revision cannot replace a newer transport/scopes silently. Cache entries are keyed by sonic/content/method identity rather than display labels.

## Extension policy

Prefer small registries with explicit schemas over inheritance-heavy frameworks. New tuning systems, phrase grammars, source families, feature methods and DSP nodes declare version, provenance/licence, bounds, compatibility and tests. Existing modules are wrapped through adapters before broad rewrites.

## Release invariant

A project saved in a release must either reopen with the same declared behaviour or fail with a specific migration/compatibility message. UI asset fingerprints/backend version must agree so the browser cannot silently combine releases.
