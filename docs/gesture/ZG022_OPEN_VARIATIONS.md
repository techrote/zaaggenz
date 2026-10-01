# ZG-022 / #232 — Approved Open and four additional variations

## Owner disposition

The owner approved **Open** (`zaag.krach-v3-open`) as a first-class preset and retained **Pulse, Weight and Edge** as second-class presets that may suit further user-applied distortion. Their audio is unchanged. The owner now prefers favourites and concrete issues rather than numeric rating sheets; no new numerical scores are inferred.

`krach_presets.py` records primary/secondary tiers separately from the immutable v3 audition recipe payloads. The original `krach_retry_v3.py` is unchanged, including its historical candidate status. This protects the exact heard source instead of changing its identity when approval metadata changes. Its Git blob is `26c627d018933139b4d5272f3e3cb3d7f03b5cf0`.

The original six approved brutal-family recipes and `locked_bloom` remain unchanged. No default replacement was requested. The legacy `FAMILIES` / `PRODUCTION_PRESET_IDS` collection remains the frozen six-family renderer registry; the ordinary `product_preset_catalogue()` composes it with the four approved v3 presets. All eleven selectable entries (default plus ten additional presets) retain stable source identities. Secondary does not mean rejected, disabled or automatically distorted.

## Product integration

Open and the three secondary presets are available through the existing Compose Source preset selector, with secondary labels explicit. Source IDs and exact parameter snapshots persist through ordinary project save/reopen and route to the frozen v3 renderer. Unknown or altered named v3 source bindings fail before job admission, including silent projects. Source generation remains in the numerical job, not the UI validation path.

The v3 source supports 12 kHz and 48 kHz output and 60–260 BPM. Its 4x synthesis working set receives a larger admission estimate. Existing Compose source-derived pitch and event-tail policies remain unchanged: the source is exact, but a composed phrase need not match an audition demo that uses sampler transposition and its own explicitly gated score. No user distortion is pre-applied.

## Four new audition candidates

The working hypothesis is that Open benefits from a continuous low body, a broad root-locked harmonic surface and slow nonlinear movement without narrow resonances. This is a design hypothesis, not proof of why the owner likes it.

| Candidate | Stable identity | Distinct mechanism |
|---|---|---|
| Drift | `zaag.open-drift-v1` | Broad complementary spectral movement and travelling harmonic weights |
| Roll | `zaag.open-roll-v1` | Two rounded pressure swells per beat with answering upper detail |
| Fold | `zaag.open-fold-v1` | Smooth fold-depth bloom restricted to the surface branch |
| Spread | `zaag.open-spread-v1` | Interleaved integer harmonic groups exchanging emphasis with root-synchronous phase motion |

Each uses Open's exact substrate settings, low-body branch and fixed phase seed. Setting its bounded depth to zero reconstructs Open exactly at 12/48 kHz in local tests. This is not a new random seed or a louder copy masquerading as a different mechanism. The new IDs remain pending owner audition and are excluded from the ordinary preset catalogue.

## Audition deliverable

`python -m zaaggenz_zaag.open_variations --out NEW_EMPTY_DIRECTORY`

Produces seventeen mono PCM24 WAVs: three examples each for Open reference and four new candidates (source, eight-bar root loop, eight-bar restrained riff), plus tone and riff comparisons. All use 190 BPM by default. The riff is the same sparse v3 score; no new scale-like melody or presentation EQ is added. Comparisons run Open → Drift → Roll → Fold → Spread. Matching is one scalar per complete file, without compression or limiting.

The pack includes `listen.html`, exact settings/gains/scores/hashes, and separate primary/secondary saved preset records. The preset JSONs document the renderer binding; ordinary product selection uses the integrated catalogue, not an unsupported arbitrary JSON import. The local reference source/root/riff WAVs were checked byte-for-byte against the owner's v3 pack. New comparison WAVs are new presentations, not rewritten historical evidence.

## Verification and boundaries

Run `python -m unittest discover -s tests/zaag -v` after the authenticated baseline is materialized. The focused v3 plus Open-variation local suite passed twenty tests, covering exact reconstruction, deterministic finite sources, bounds, unchanged approved state, preset tiers, save/reopen/render, malformed bindings, memory admission, cancellation, sparse-score reuse and pack hashes. The renderer-byte guard normalizes Git checkout line endings for Windows; source semantics are unchanged.

Native local HTTP checks exercised selection, save/reopen validation, numerical rendering and WAV export for all four approved v3 IDs. Seventeen full-rate WAVs passed format/hash/finite-PCM and reconstructed-peak checks. Local Chromium runtime navigation was blocked by environment policy; no local browser pass is claimed. The normal CI browser and reverse-dependency workflows remain required; local evidence does not establish a fresh-head CI pass.

Qualitative feedback is sufficient: favourites and specific objections. No automatic promotion of the new four follows from a numerical descriptor, a passing test, or similarity to Open. Issue #232 remains open for their listening disposition. This additive expansion does not revoke the already accepted ZG-022 programme dependency or modify the separate ZG-024 research gate.
