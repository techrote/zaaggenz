# ZG-008 roll retrigger admission policy

Issue #129 corrects the renderer-cap boundary for source-derived roll slices. The supported policy is **rejection, never truncation**.

For a pitched event with a constant integer `density_per_beat = d > 1` and exact rational duration `D` beats, retriggers are the strictly interior roll-grid points `j/d` satisfying `j >= 1` and `j/d < D`. The requested count is therefore `ceil(D * d) - 1`. Density values `0`/`1` have no retriggers. The count is beat-domain and does not depend on BPM or sample rate.

`MelodicRenderSpec.max_roll_retriggers` is an admission bound. Before legacy source synthesis, target-note synthesis, pitch shifting, roll slicing, stem allocation beyond the nominal recipe validation path, or preserved DSP execution, `render_phrase()` computes the exact requested retrigger count for every pitched event. If any request exceeds the active render spec, the entire render fails with a `MelodyError` containing the requested count and active cap. The caller must split the event, lower density, or intentionally select a larger valid render bound.

Successful rendering has no truncation mode: every accepted roll emits exactly its requested number of source-derived retrigger slices. The existing `roll_retriggers` event/phrase diagnostics therefore remain the realised count and, by admission invariant, equal the authored request. There is no successful state in which requested and realised counts differ.

The existing slice architecture is unchanged: the full main event remains in `synthline`; retriggers remain tapered source-derived slices in `exciter`; interval/slice-length bounds, energy compensation, pitch articulation, tail ownership, output policy, recipe identity and source-once semantics are unchanged.

## Adapter boundary

Timeline roll objects already reject more than 64 strictly interior retriggers using the same rational-grid rule. A compiled timeline roll is still checked again against the active `MelodicRenderSpec`, so a caller using a stricter runtime cap cannot bypass renderer admission. Any other PhrasePlan/GestureSpec producer (gesture, linked-event, text-gesture, vocal-gesture, or direct contract construction) reaches the same renderer preflight; adapters cannot opt into silent truncation.

## Contract/version consequence

No frozen `PhrasePlan`, `GestureSpec`, `RenderRecipe`, timeline document, or audio identity schema changes. `MelodicRenderSpec` remains version `1.0.0`: `max_roll_retriggers` already existed as the declared safety bound, and this corrective change makes acceptance honor that bound instead of treating it as an undocumented lossy rendering cap. Recipe/cache identity derivation and protected source/audio defaults are unchanged.

Boundary evidence covers below-cap, exact-cap, cap+1, a zero cap, slow and extreme-fast tempi, timeline-generated GestureSpec rolls, and source-once behavior at the default 64-retrigger boundary.
