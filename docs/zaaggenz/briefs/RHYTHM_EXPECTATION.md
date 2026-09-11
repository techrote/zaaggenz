# Rhythm, phrase roles and embodied prediction — implementation brief

## Core hypothesis

Zaaggenz should model musical expectation at multiple timescales rather than reducing rhythmic complexity to one density control. A listener can be wrong about the immediate event while remaining right about the phrase destination. That distinction motivates separate state for local event prediction, variation-window expectation, metrical anchors and long-form return.

The user’s `1234 1234 1234 5555` description is interpreted as a **phrase-role grammar**, not five-beat metre: stable establishment/repetition followed by a predictable permission window for variation and a recognisable return. Variation location, fill identity, gesture direction and return time must be independently controllable.

## Nested pulse / movement levels

At 160–240 BPM, the same material can support fast articulation, half-rate bounce and quarter-rate sway. These are nested metrical levels, not automatically polyrhythms. The engine should permit one level to remain orienting while another becomes syncopated or surprising.

Represent rhythmic state explicitly: pulse hierarchy, anchor confidence, syncopation target, event density, phase relation and phrase role. Preserve the possibility of longer quasi-periodic/cross-rhythmic modulation without forcing every pattern into 4/8/16-beat repetition.

## Linked violation / recovery

Implement fake-out and recovery as one compositional object. A strong local expectation can be violated while the substitute event preserves or gradually reveals the expected phrase destination. The interesting test is not merely “wrong event then right event,” but whether an apparently wrong event can **morph into the right beginning** through timing, spectral emergence, layer entry or gesture continuation.

The software feature is valid even if later experiments find no general preference benefit. Pleasure, excitement, amusement, urge to move and tension remain separate outcomes.

## Gesture directionality

Two fills may be perceptually equivalent in phrase function despite different notes or DSP if they share directional features such as acceleration, increasing brightness, narrowing duration, rising/falling pitch tendency, or a common terminal landing. Store gesture trajectories separately from the exact event sequence.

A gesture representation should support both authored/text input and later vocal capture: onset times, accent, duration, pitch contour, brightness/spectral-opening contour and confidence.

## Modal / non-Western extensibility

Support directional and motif-based modal grammars rather than treating every system as an unordered pitch-class set. A grammar may distinguish ascent/descent, resting tones, characteristic motifs, departures, distant regions and return gestures. Culture-specific naming requires appropriate sources and review; generic synthetic grammars can borrow structural ideas without claiming authenticity.

## Acceptance direction

Early creative validation should demonstrate a four-/sixteen-bar phrase in which variation content changes while variation location/return remains stable, plus examples where fast articulation changes without destroying half-/quarter-rate orientation. Later research issues can test whether these manipulations alter enjoyment, prediction or movement.

Detailed research evidence and experiment boundaries are indexed through `docs/zaaggenz/RAG_INDEX.md` and the source register.
