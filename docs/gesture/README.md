# ZG-027 — directionality-preserving timbral and rhythmic gestures

ZG-027 stores the **direction and phrase function of a gesture separately from its exact surface**. The authoring format covers onset density, accent, duration, pitch, brightness, roughness, spectral occupancy and spectral width plus explicit landmarks and a terminal landing.

It is an opt-in layer above the accepted ZG-008 source-preserving renderer. It does not change `locked_bloom`, the recovered nonlinear topology, frozen GestureSpec axes, final gain policy or any existing preset.

## Directional constraints

Every trajectory is a bounded sequence of beat/value points divided into contiguous directional segments. Segments are explicitly `rising`, `falling`, `flat` or `free`; every internal segment boundary must have a `turn` landmark. Entry, terminal landing and endpoint landmarks are also mandatory. Construction fails when values contradict a declared sign, a turn has no landmark, units are wrong or the landing does not end exactly at the gesture duration.

The starter `rise_turn_return()` is four beats long. Its density, accent, pitch, brightness, roughness, occupancy and width increase into a protected turn at beat 2 and then return; event duration narrows into the turn and broadens afterwards. A fixed terminal landing starts at beat 3.5 and ends exactly at beat 4.

## Surface variation and reversal

`vary_surface()` moves only non-protected interior control-point times on a deterministic 1/960-beat grid. Values, directional signs, turn time, landing time and endpoint are preserved. Axes can be selected independently and `source_family` can be changed without changing the directional contract.

`reverse_direction()` reflects selected trajectory values within their existing min/max range and flips rising↔falling signs while keeping point times, density/duration/gain inventory and terminal landing intact unless those axes are explicitly selected. This gives a controlled “similar surface, opposite direction” manipulation.

`replace_trajectory_points()` provides manual correction under the same validator. `edit_landing()` changes terminal degree/detune/gain independently of trajectory direction or source-family identity. No learned model is needed for authored or corrected gestures.

## Source-preserving compilation

`compile_gesture()` samples the authored density, duration, pitch and accent trajectories into explicit ZG-008 note events. This avoids silently collapsing time-varying density into one roll setting. The terminal landing is emitted as its own exact event. The resulting PhrasePlan uses one declared source ID and contains no unsupported GestureSpec curves.

`compile_gesture_recipe()` obtains source parameters, tuning and TimeMap from an accepted ZG-009 Project and constructs a normal **source-derived** melodic RenderRecipe. It asserts that the source object is unchanged and that no nodes or SCULPT graph have been injected.

The authoring `source_family` is retained in the compile trace, not masqueraded as multiple audio sources. RenderRecipe v1 still has exactly one protected source.

## Deferred timbral/stem automation

Brightness, roughness, spectral occupancy and spectral width are exported in `zaaggenz-gesture-automation` as typed rows with units, layer, stage and exact points. They are marked `deferred-explicit` and `protected_topology_rewrite=false`:

- brightness / roughness → post-shaper SYNTHLINE automation;
- spectral occupancy / width → SYNTHLINE stem-space automation.

The current ZG-008 renderer rejects these axes, so ZG-027 records them instead of applying an undocumented approximation. A later graph/layer issue may consume them under an explicit compatible contract. This is the required preservation boundary, not missing hidden processing.

## Matched evidence

The full-rate fixture tool creates three source-derived examples:

1. baseline authored direction;
2. same direction / different surface — internal pitch/brightness point timing and source-family label differ, but density, duration, gain, turn and landing remain fixed;
3. similar surface / opposite direction — pitch/brightness signs reverse while event timing, duration, gain and landing remain fixed.

All renders use the protected source. Deferred timbral rows are exported beside each recipe but are not silently applied. WAV comparison uses one playback-only whole-file RMS gain per immutable render and a common sample-peak ceiling; this is not a perceptual-loudness or true-peak claim.

```console
python -m unittest discover -s tests/gesture -v
python -m unittest discover -s tests/melody -v
python tools/gesture_fixture_report.py --out gesture-fixtures-48k.json --audio-dir gesture-listening-48k --sample-rate 48000
```

Automated direction/identity checks and matched WAVs are engineering evidence. They do not imply that one direction is preferred or constitute owner listening approval.
