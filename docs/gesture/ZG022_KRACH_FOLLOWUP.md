# ZG-022 / #232 — Deutscher Krach follow-up

This follow-up adds four **audition-only** mechanisms informed by six owner-supplied private references. It does not alter the six owner-approved production presets and does not replace the protected `locked_bloom` default.

## Reference-derived design axis

The private files remain outside git and are bound by exact SHA-256 in `references/krach_private_registry_v1.json`. The derived, non-audio analysis in `references/krach_texture_analysis_v1.json` measures band allocation and temporal body/surface separation.

The useful signal is not simply brightness or distortion amount. Across the supplied references, low-frequency mass can remain comparatively stable while mid/high texture changes much more strongly. `BOUNCIN 2 THA BEAT` is the clearest bridge example in this set: dark/sub-heavy allocation with unusually large high-band change while low-band change is locally small. `FA-TI-CO` is the exposed-teeth endpoint; `BLOW` is more body-heavy; `This Is Krach` exhibits stronger surface/body flux separation.

These are descriptive observations only. They are not a genre classifier, authenticity metric, preference score, or reconstruction of any producer's processing chain.

## Four mechanisms

| ID | Design target | Main mechanism |
|---|---|---|
| `zaag.krach-black-mass` | darkest / most body-stable | retained low body + independently saturated shifting surface |
| `zaag.krach-dark-bounce` | Bouncin-style dark animation | retained body + two-rate ratcheted mid/upper surfaces + short comb motion |
| `zaag.krach-mid-shred` | destructive moving midrange | opposed low-mid/high-mid motion + moving ring interaction over retained body |
| `zaag.krach-air-teeth` | exposed teeth/air endpoint | retained body + heavily excited high-mid/air fragments + rapid gating / bounded crush |

The four profiles are deterministic engineering identities. Parameter-neighbour variations do not count as separate mechanisms.

## Audition contract

`build_krach_audition_pack()` contains exactly the four #232 candidates and is revision `zg022-krach-followup-232-v1`. Every candidate receives:

- a level-matched one-beat source render;
- an identical-pattern one-bar melodic demo;
- an identical repeated-root two-bar loop;
- an audition-only EQ-motion version of that same loop, explicitly labelled as presentation processing rather than preset DSP.

The owner endpoints remain bounce, melodic identity, source character and practical usefulness. Repetition interest should also be judged separately from simple brightness/loudness.

## Promotion boundary

The Krach candidates use classification `krach-candidate` and are excluded from `PRODUCTION_PRESET_IDS`. They cannot enter the ordinary product preset catalogue merely by existing, passing CI, or matching a descriptor. Explicit owner listening/disposition is required.

The six accepted brutal families remain first-class production presets throughout this experiment. `locked_bloom` remains the protected default.
