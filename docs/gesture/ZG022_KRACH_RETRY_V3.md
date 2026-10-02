# ZG-022 / #232: Krach v3 audition

## Owner feedback and disposition

The owner found v2 too nasal, with a blocked-ears feeling, and requested a less cheesy melody. V2 is not approved. Its module and existing evidence are retained unchanged. PR #236's rejected v1 is also preserved. This is an additive v3 experiment, not a modification of the six accepted production presets or locked_bloom.

## New attempt

`zaaggenz_zaag/krach_retry_v3.py` generates four new audition-only identities: Open, Pulse, Weight and Edge. They use accepted-family recovered synthesis parameter sets as substrates; no source-recording samples are embedded.

Changes from v2:
- no fixed or swept formant resonators;
- no bandpass-led tone construction or 2.6–4.6 kHz surface low-pass ceiling;
- much less odd/even harmonic bias, with a broad phase-locked partial bank adding upper structure rather than boosting the previous WAVs;
- mild broad mid relief, matched zero-phase body/surface splits, smooth modulation and four-times oversampled synthesis/processing;
- no additional noise samples, bitcrushing, whole-mix grit or presentation EQ.

These are design choices, not proof that the owner will prefer v3. No acoustic diagnostic is a quality score.

## Riff and presentation

The old repeating 0,3,5,7,5,3,-2,0 half-beat melody is not reused. The shared four-bar riff uses a root pedal, rests, syncopated pickups, occasional semitone falls and one five-semitone descent. All sounds receive the exact same score and tempo. Polyphase sampler transposition replaces phase-vocoder time-preserving pitch shifting in these demos; changed source duration and short sampler release gates are explicit in the manifest.

The pack contains 14 mono 48 kHz / 24-bit WAVs: four source hits, four eight-bar root loops, four eight-bar riffs, a tone comparison and a separate riff comparison. No effects-only demonstration is substituted for a raw source comparison. The local HTML player is included. Constant RMS matching is scalar-only and is not claimed to be perceptually equal loudness.

## Reproduction and tests

After materializing the authenticated recovered source and installing declared dependencies:

`PYTHONPATH=app:. python -m zaaggenz_zaag.krach_retry_v3 --out NEW_EMPTY_DIRECTORY`

On Windows set PYTHONPATH to `app;.`. The v3 source is independent of the v2 module. Eight focused local tests passed with NumPy 2.3.5 / SciPy 1.17.0. They cover deterministic finite 12/48 kHz renders, BPM and input bounds, unchanged accepted recipe/catalogue state, score timing and non-overlap, sampler pitch accuracy, constant-gain matching, WAV/hash integrity and no overwriting of previous packs. CI reuses the existing ZG-022 workflow ownership and exports the full-rate v3 pack.

## Gate

Owner status remains pending. No production promotion, new default, issue closure or merge is authorized by these checks. The owner must judge both the revised tone and the revised riff.
