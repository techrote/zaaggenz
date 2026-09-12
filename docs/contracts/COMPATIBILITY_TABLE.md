# Contract compatibility table

| Surface | v1 contract | Legacy v1.2.1 adapter | New consumer required when |
|---|---|---|---|
| Source parameters | `RenderRecipe.source` | exact `KickParams` round-trip | source family/method differs |
| Time | `TimeMap` rational beat/tempo map | one constant tempo matching legacy BPM | tempo/meter changes are present |
| Tuning | `TuningSpec` | exact 12-TET metadata anchored at legacy `f0_hz` | non-default tuning/degrees are requested |
| Phrase/notes | `PhrasePlan`/`GestureSpec` | absent only | any explicit note/gesture/phrase intent exists |
| Arrangement | legacy section payload inside `RenderRecipe` | exact `ArrangementSpec` round-trip | new timeline semantics are requested |
| Reversebass | legacy payload inside `RenderRecipe` | exact `ReverseBassParams` round-trip | new harmonic/layer-role semantics are requested |
| SCULPT | legacy payload inside `RenderRecipe` | exact `SpectralSculptParams` round-trip | typed graph/band-node processing is requested |
| DSP graph | `DSPNodeSpec` DAG | empty only | any typed node exists |
| Phase/state/tail | explicit recipe/node metadata | exact legacy policies only | another reset/phase/tail policy is requested |
| Output | one declared master/clipping/stem policy | existing final master semantics | another output policy is requested |
| Analysis | `FeatureBundle` / `PartialTrackBundle` | no mutation of renderer | any transform consumes analysis artefacts |
| Research | `TrialSpec` / `RunManifest` | no renderer effect | study/provenance tooling consumes them |

The adapter deliberately fails on unsupported new intent. Compatibility is never implemented by silently deleting fields until a legacy call succeeds.
