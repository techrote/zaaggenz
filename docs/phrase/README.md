# ZG-025 — phrase-role windows and predictable variation

This module encodes phrase function separately from exact fill content. A role plan is a versioned JSON authoring document whose windows say **where** establishment, repetition, reinforcement, variation, teasing, turning or return can occur. Each window owns weighted content variants, weighted placement offsets and an optional destination anchor. Placement and content use independent named SHA-256 choice streams, so changing a fill need not move the permission window and changing placement need not change the event inventory.

The generator probabilities recorded in traces are engine-choice probabilities only. They are not listener certainty, liking, reward or biochemical estimates.

## `1234 1234 1234 5555`

`template_1234_5555()` implements the owner’s phrase-role idea as four ordinary 4/4 bars:

- bars 1–3: stable `1234` material under establish / repeat / reinforce roles;
- bar 4: one predictable variation permission window with independent fill-content and placement choices;
- beat 15: an explicit tonic return anchor that survives even when the selected variant is `no-fill`.

`5555` is therefore a phrase-function label for the fourth-bar variation/return region, **not quintuple metre**.

## CLI

After materialising the authenticated source and installing the existing numerical/contract/job dependencies:

```console
python -m zaaggenz_phrase template phrase-role.json --placement-seed 11 --content-seed 7
python -m zaaggenz_phrase timeline phrase-role.json phrase.zgtimeline.json --sample-rate 48000
python -m zaaggenz_timeline --open
python -m zaaggenz_phrase render phrase-role.json phrase.wav --sample-rate 48000
```

The exported timeline is a normal accepted ZG-009 document: notes, rests, roll densities and role-region clips are editable in the browser. The retained legacy Project, layer ownership and protected source are not rewritten. The role-plan JSON remains the authoritative generator state; editing the exported timeline does not silently mutate the generator.

## Plan semantics

A role window has an absolute start/end, a role, weighted placement offsets, weighted content variants and optional absolute destination anchor. Content variants carry a `source_family` identity plus relative source-preserving note/rest events. `source_family` is preserved in the compiled PhrasePlan/trace as an authoring identity and future routing hook; ZG-025 deliberately does **not** invent multiple new synthesis engines. The current ZG-008 renderer still uses the one protected source waveform while preserving those event labels.

Every declared placement must fit every event in every variant. This makes invalid authoring fail at plan construction rather than allowing a choice to become infeasible only after a seed is drawn. No-fill variants are allowed only in vary/tease/turn roles. Return roles require a destination. The accepted ZG-009 bound of 256 note/rest objects is enforced against worst-case expansion.

Role names map onto the frozen PhrasePlan vocabulary without changing that shared schema: `reinforce → repeat`, `vary → variation`, `tease → fakeout`, and `turn → transition`. Destination anchors add an explicit `return` role. The richer authoring vocabulary lives only in the versioned ZG-025 wrapper.

## Independence guarantees

`placement_seed` chooses only window placement offsets. `content_seed` chooses only content variants. Each trace row records the selected indices, raw deterministic draw, declared choice probabilities, joint generator probability, source family, window bounds, emitted event IDs and return destination. Stable windows can use one choice with probability 1.0.

For matched controls, changing only `placement_seed` preserves the selected variant, pitch/duration/gain/source-family inventory and roll presence; only onset locations move. Changing only `content_seed` preserves the window and placement. These guarantees are covered by tests and 48 kHz generated-source fixtures.

## Source-preserving integration

`compile_role_recipe()` extracts the protected source parameters, TimeMap and TuningSpec from an accepted timeline Project, expands the role plan, and creates an ordinary ZG-008 source-derived melodic recipe. The source payload is asserted unchanged. No frozen contract, preset or nonlinear topology changes occur.

`plan_to_timeline()` exports selected role events to the ZG-009 browser editor and creates one named clip per role window. The full legacy Project remains byte-for-byte equivalent at the JSON-object level. BODY/AUX/SUB/SCULPT coordination is still ZG-029; this issue does not claim it.

## Verification and evidence

```console
python -m unittest discover -s tests/phrase -v
python -m unittest discover -s tests/melody -v
python -m unittest discover -s tests/timeline -v
python tools/phrase_fixture_report.py --out phrase-fixtures-48k.json --audio-dir phrase-listening-48k --sample-rate 48000
```

The fixture report creates four original generated-source comparisons: baseline, changed content with the same placement, changed placement with the same content, and a no-fill condition with the same explicit return. It exports exact role plans, expansion traces, accepted timeline documents and 48 kHz WAVs. One playback-only RMS gain per immutable render is used for comparison, with a common sample-peak ceiling; it is not a perceptual-loudness or true-peak claim.

CI runs the issue suite and inherited melody/timeline regressions on Windows and Linux. Numerical/test evidence does not imply owner listening approval or that a predictable variation window is universally preferred.
