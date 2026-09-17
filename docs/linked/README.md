# ZG-028 — linked fake-out, reinterpretation and return

ZG-028 turns the proposed “double event” into an editable compositional object, not a listener/reward claim. A `LinkedEventPlan` has four contiguous phases — preparation, violation, bridge and return — with explicit phrase role, active layer set, harmonic destination, slow metrical anchor and transformation policy.

The starter `linked_fakeout_return()` is a sixteen-quarter-note-beat source-derived phrase. Preparation establishes a local expected degree. At beat 8 the controlled condition supplies either that expected event or a same-time/same-gain substitute. Beats 10–14 form a bridge. Beat 15–16 is the same declared return in every condition.

## Controlled variants

Five names are closed and reproducible: `baseline` (expected local event + neutral bridge), `violation-only` (substitute + neutral bridge), `recovery-only` (expected event + linked bridge), `both-linked` (substitute + linked bridge), and `both-unrelated` (substitute + equally timed recovery surface that is not linked to the destination).

All five use the same protected source, phrase duration, event onset/duration/gain signature, return event and embedded slow-anchor clock. Violation and recognisable recovery can therefore be manipulated independently without smuggling in duration, gain, endpoint or source changes.

## Linked versus unrelated recovery

A linked bridge is more than an unrelated sound before the final note. Its pitch path is interpolated in log-frequency space from the event currently in force toward the declared return. Every bridge event records `link_progress` and cents-distance to the return, and compilation requires that distance to decrease strictly until the landing. `both-unrelated` deliberately uses a non-monotonic distance sequence while preserving the comparison invariants.

`distance_to_return_cents` is a physical, directionless cents distance derived from the active `TuningSpec`: the compiler resolves the emitted bridge degree plus detune and the declared return degree plus detune to frequencies, then measures the frequency ratio in cents. Degree coordinates and cents distances are therefore distinct. No path assumes one degree equals 100 cents unless the active tuning actually has that spacing; unequal-step octave scales and non-octave periods use the same definition. Neutral bridge rows continue to report no distance because they do not claim a recovery-distance diagnostic, while the return reports exactly zero.

This is a corrective clarification within linked-return format `1.0.0`, not a trace-version change: the field was already documented as cents distance to the return, and the previous `100 × degree difference` calculation for unrelated bridges was an incorrect implementation of that declared meaning. Event degree selection, detune, source, timing, gain, return destination and rendered audio are unchanged. Downstream ZG-035/ZG-044 evidence must consume the corrected tuning-derived value and must not reconstruct cents distance from degree numbers.

The return is constrained by an explicit ZG-010 `SonoritySpec`; the starter return is the root of a declared root/third/fifth sonority. This is an authored harmony target, not chord inference from audio.

## Slower anchor

The plan embeds an accepted ZG-026 `MeterPlan`: exact 1:2:4 articulation/bounce/sway with `sway` as the stable anchor. Its tick sequence continues unchanged through violation, bridge and return, so a local event can violate expectation while slower orientation remains available.

## Transformation boundary

The plan carries all requested families: withheld low-band arrival, motif completion, spectral emergence, envelope morph and restored phase/alignment. Motif completion is applied now through source-derived notes. The other families remain typed `deferred-explicit` controls with `protected_topology_rewrite=false`; ZG-028 does not pretend the current renderer can safely perform persistent layer/spectral/phase routing. Later graph/layer issues may consume those rows explicitly.

## Compose integration

`compile_linked_recipe()` creates an ordinary ZG-008 source-derived recipe. `plan_to_timeline()` exports notes into the accepted ZG-009 timeline with four named phase clips. The full retained Project, including existing arrangement/reversebass/SCULPT state, is preserved; the compiled melody branch does not silently claim ZG-029 persistent-layer coordination.

The plan stores local-prediction probability, destination probability and uncertainty under `engine_model` with mandatory semantics `generator-state-not-listener-outcome`. These are engine authoring variables only, not measured listener expectancy, liking, pleasure or biochemistry.

## Verification

```console
python -m unittest discover -s tests/linked -v
python -m unittest discover -s tests/harmony -v
python -m unittest discover -s tests/phrase -v
python -m unittest discover -s tests/meter -v
python -m unittest discover -s tests/gesture -v
python -m unittest discover -s tests/timeline -v
python tools/linked_fixture_report.py --out linked-fixtures-48k.json --audio-dir linked-listening-48k --sample-rate 48000
```

The fixture report produces all five immutable source-derived controls at 48 kHz with exact traces, deferred automation, timeline documents and PCM/WAV hashes. Playback matching uses one whole-file RMS gain per immutable render under a common sample-peak ceiling; it is not perceptual-loudness or true-peak certification. Automated success is not owner listening approval and does not validate the later ZG-035 listener hypothesis.
