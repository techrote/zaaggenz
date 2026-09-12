# v1.2.1 compatibility and branding boundary

ZG-001 freezes the recovered implementation before zaaggenz expands it. These are compatibility invariants, not permanent prohibitions against opt-in alternatives.

## Protected musical behaviour

### `locked_bloom`

The current canonical production/default source remains the recovered `locked_bloom` state. Canonical JSON SHA-256:

`6a6e5a55f04f978e57e90b9e582d2b830b3d82192aec7d0f727112ef75b5afe2`

Key invariants include terminal f0 48 Hz, 49 harmonics, zero explicit noise and roughness, sweep -1.604 semitones, wavefold 0.875, hard-clip mix 0.803 and seed 1305. Its aggressive internal nonlinear topology is intentional. New “cleaner” research processing must not replace it by default without owner audition/approval.

### Source-preserving ARRANGE

`preserve_source_timbre=true` is the normal protected architecture. The finished SYNTH source is rendered and reused/source-derived for events and rolls. The legacy per-event re-synthesis mode remains available for comparisons but is not the compatibility target.

### ARRANGE+BASS

Combined rendering must preserve the full SYNTHLINE independently from the short impact/exciter. BODY/AUX/SUB remain stateful layers, not replacements for the finished synth source. Canonical `layered_reverse` JSON SHA-256:

`77c309b17894b89a965f145cbb13c6bee1cf29d9be9c38054afe0ce5a3be4aa6`

The full-rate frozen SYNTHLINE stem SHA-256 is recorded in `baseline/V1_2_1_CONTRACT.json`.

### SCULPT

`transparent` is a true disabled baseline and must preserve the source unchanged. Canonical JSON SHA-256:

`30821d1e9e5e9087258d2938164365e5cc6f0c1d344e627d1302a1391a4502a0`

Future spectral processing may add explicit opt-in paths but should not hide reconstruction error inside bypass.

### Final MASTER

MASTER is a final linear gain after generation/mix and optional SCULPT, before WAV/output encoding. It is not a SYNTH preset parameter and does not renormalise negative gain back upward. The frozen -6 dB factor is `0.5011872336272722`; the recovered API test reports zero clipping for the baseline example.

### Live preview

Live stab/keyboard preview uses the same synthesis topology with a bounded preview duration/release and without descriptor/file-generation overhead. BPM bounds are 20–360. Preview must not silently mutate the current synth state.

## Protected UI behaviour

- default skin: Earth / Neutral;
- six built-in themes plus custom palette controls;
- persistent header render products: `SYN`, `ARR`, `A+B`, `BASS`;
- named render transport slots with play/pause/stop ownership;
- scrubbable whole-render waveform/timecode presentation;
- Morph Lab advanced controls remain available;
- static assets use versioned URLs and `Cache-Control: no-store, max-age=0` to prevent old/new frontend/backend mixing.

Later UI work may reorganise these features, but removing access or changing defaults requires explicit issue scope and compatibility evidence.

## Branding/migration policy

The repository/product name is **zaaggenz**, while the recovered Python package remains `uptempo_harmony` for compatibility. Do not perform a wholesale package/module rename in ZG-001. Future branding can change display text and introduce adapters/aliases first, preserving preset/session imports and command entrypoints until a separately tested migration is justified.

## Golden evidence

`baseline/V1_2_1_CONTRACT.json` freezes 12 kHz CI and 48 kHz full-rate raw-array hashes for locked bloom, noisy contrast, source-preserving arrangement, ARRANGE+BASS, preview, transparent SCULPT and -6 dB master output. It also freezes preset identities, API WAV hashes and cache semantics.

Strict raw-array identity is expected only in the recorded environment. Across supported environments, compare sample count, structural invariants and numerical statistics with declared tolerance. Owner listening remains mandatory before a later issue replaces a musical default even when numerical tests pass.
