# Context, authority and decisions

## What this programme is

**zaaggenz** is to remain an offline / asynchronously rendered synthesiser and musical construction instrument while gaining reproducible investigation tools. Its artistic centre is **bouncy, melodic zaag-oriented uptempo**. Piep, clean tones, noisy textures and deliberately excessive edits are useful contrasts, not substitutes for that target. A successful release must let the owner make music without running a study, learning an analysis model or provisioning a GPU.

This programme contains a proposed implementation workflow, not a claim that the features already exist. `ZG-001` must establish the actual code baseline before implementation.

## Evidence and access status

| Input | What was actually available | Authority / limitation |
|---|---|---|
| This conversation from the v1.2.1 delivery onward | Visible messages, including the user's corrections, two research discussions and the current request | Authoritative for intent and reasoning trajectory; historical claims of validation are not fresh test results |
| Earlier implementation history | Visible code excerpts and release descriptions | Useful navigation clues, not proof of current files or behaviour |
| “Compare Zaag and Piep” | User-supplied quotations and partial named-chat retrieval | The full transcript was not recovered; do not label this bundle a complete rereading of it |
| Prior scientific research | Primary papers, author/institutional records and official specifications in [references/SOURCES.md](references/SOURCES.md) | Source-specific access depth and claim boundaries are recorded |
| Two uploaded MP3s | Both actual files, decoded and measured locally | Numerical reference audit completed; no claimed listening session, production-chain reconstruction, verified chord transcription or beat alignment |
| Originally named GitHub destination `techrote/zaaggenzrepo` | Repository lookup returned 404 | Superseded by explicit owner confirmation of `techrote/zaaggenz` |
| Confirmed `techrote/zaaggenz` | Owner explicitly confirmed this private repository as the intended destination | Authorised destination for programme docs/issues; empty state is not evidence that source recovery is complete |
| v1.2.1 source archive | Not present in this run's filesystem | Recovery/import is a hard baseline gate; do not reconstruct production source from snippets |

The old release message reports archive SHA-256 `90be319a4660a637077df935a8ebcbd1bb4c3a629e28e2f6d4bfe62d88dfe8a8`. Treat that as a candidate provenance check when recovering the archive, not as a newly verified checksum. The available `locked_bloom` screenshots and descriptions contain differing envelope values across iterations. Freeze the actual recovered preset; do not silently rebuild it from selected remembered numbers.

## Intent recovered from the discussion

After v1.2.1 the focus moved from repairing saturated buses and UI deployment to **musical organisation above the DSP**. The owner welcomed grounding and explicitly rejected a naive biochemical control story. The phrase “dopamine tickle” is a phenomenological motivation; the measurable endpoints are pleasure, excitement, tension, amusement, absorption, familiarity and urge to move. Audio descriptors do not measure neurotransmitters.

The user's proposed double event is richer than two successive surprises. A highly expected local event can be violated while its replacement preserves—or reveals—the expected phrase destination. Uncertainty about fill identity may coexist with certainty about return time. A wrong-looking event can morph into a recognisable arrival and be reinterpreted retrospectively. These are **research hypotheses**, not established two-hit reward mechanisms.

`1234 1234 1234 5555` describes a predictable permission window for variation, not a request for five-beat metre. A dancer may express the phrase function even without imitating the exact fill. Stable variation location, variable local content and conserved gesture directionality are separate compositional dimensions. The owner also observed accessible nested rates: fast articulations, half-rate bounce and quarter-rate sway. These are metrical levels; genuine cross-rhythms are another option.

Vocalising `bu budu budubu ...` suggests both an input language and an experimental manipulation. A vocal gesture can encode timing, accent, length, pitch contour and spectral opening without recreating the original waveform. The sensation might depend on familiarity, fluent self-chosen action, attention, expectation framing or their interaction. The plan therefore includes neutral framing, imagined/audible participation and effort measures rather than asserting a vocalisation benefit.

The anthropological reference was a deliberate invitation to explore beyond Western harmony and stereotypes. The owner explicitly said not to over-investigate the provenance of “Samal Moro” or turn the maritime phrase into an authenticity claim. Accordingly: include contextual, directional and motif-based theories; label synthetic swaying processes as design inspirations; require proper sources and musical validation before naming a culture-specific pack.

## Named-chat research thread, reconstructed with limits

The supplied highlights and partial retrieval point to **partial-domain rather than single-fundamental correction**. Detect the moving spectral lattice, preserve attacks and residual structure, then retune or reweight partial groups at chosen points in a nonlinear chain. Multiband routing makes it possible to retain sub pressure while changing upper-group interval relationships. A multiresolution view is motivated by fast attacks and low-frequency partial discrimination needing different windows.

“Chordness” is a plausible UI control only if it exposes a constrained representation underneath: multiple target combs, partial assignment, ratio/cents distances, group occupancy, amount, confidence and temporal continuity. It must not be a disguised major-chord preset, a scalar harmonicity score or a global pitch shifter. The comb analogy explains the representation; it is not evidence that every peak is an independent musical note.

Sethares' 1993 local-consonance work [S01], adaptive tuning [S02] and 1998 spectral mappings [S03] are particularly direct prior art. The programme should build on them openly. Its proposed contribution is their practical integration with persistent nonlinear zaag synthesis, multi-level phrase grammar, source-preserving arrangement, and user-specific empirical evaluation—not a novelty claim for spectral retuning.

## Product invariants to verify and protect

1. **Keep the known good sound.** `locked_bloom` and the source-preserving rendering mode are protected baselines. New engines are opt-in until null tests and audition evidence pass. Aggressive source clipping can be intentional; bus overload and accidental re-synthesis are distinct faults.
2. **Never lose the synthline again.** Full SYNTHLINE, short exciter and persistent BODY/AUX/SUB must remain explicit stems with controllable contributions. Reusing an exciter is not equivalent to preserving the source line.
3. **Keep construction immediate.** Preview, render, cancel, play/pause, stop, scrubbing, timecodes, named outputs, Earth/Neutral theme, palette choice, global render controls and final master gain remain accessible. Research controls can be disclosed in panels; mature controls are not deleted.
4. **Keep offline rendering honest.** Async does not mean hard real-time. Expensive analysis and rendering can take time, but requests must show progress, bounds and cancellation, and an old result must never replace a newer state invisibly.
5. **Reproducibility is end-to-end.** Parameter seed alone is insufficient: persist source files' hashes, versions, sample rate, tuning, timeline, automation, phase/reset policy, stage ordering, analysis settings and output gain.
6. **Do not optimise away the genre.** Reduced flatness, lower roughness or fewer clipped samples cannot certify a better sound. Gate artistic changes by level-matched listening to target-preserving and deliberately contrasting material.
7. **Do not publish reference recordings by accident.** “FREE DL” / “FREE PROMO” are labels, not demonstrated redistribution licences. Store local paths outside tracked data and commit only hashes, descriptors, annotations and synthetic fixtures.

## Decisions already made by this planning audit

- Preserve product utility and research validity as separate acceptance gates. Human-study outcomes do not block the basic musical release.
- Prefer a deterministic signal-model baseline before learned DDSP; keep learned methods optional.
- Use an invertible STFT path first, adding CQT/ERB views when they answer a defined question. Do not force three heavy transforms into every preview.
- Keep target-comb geometry, roughness, perceptual chordness, recognisable source character and preference separate in both data and UI.
- Introduce immutable contracts before parallel implementation, with narrow adapters rather than a speculative whole-application rewrite.
- Treat source-preserving notes and phrases as an early usable milestone, not a reward after all research completes.
- Do not let the paired reference become a two-file supervised genre dataset. It is a contrast/probe set that needs aligned segments and later out-of-family validation.
- Repository destination is resolved as `techrote/zaaggenz`. Programme publication there is authorised; production-source import still requires provenance/recovery under ZG-001 and unrelated branch contents must remain protected.
