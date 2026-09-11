# Spectral harmony and timbral tuning — implementation brief

## Goal

Treat distorted zaag timbre as a moving collection of partials, sidebands, nonlinear products and residual energy rather than assuming one fundamental is the whole musical object. The instrument should be able to **retune, reweight, or redistribute partial groups** toward explicit tuning/sonority targets while preserving attacks, low-frequency anchoring, source identity and a configurable amount of roughness/residual.

## Prior art and framing

Build openly on Sethares-style local consonance, adaptive tuning and spectral mappings, plus sinusoidal/residual modelling and phase-coherent transformation methods. “Spectral Auto-Tune” describes the use case; it is not a novelty claim.

A harmonic or inharmonic target can be represented as one or more weighted spectral combs. `Chordness` must therefore expose a documented operation—frequency attraction, gain reweighting, multi-comb occupancy, harmonic convergence, or a bounded hybrid—not a vague “pleasure” score.

## Representation

Use a canonical audio timeline with short/medium/long analysis support. Track partial frequency, amplitude, phase convention, confidence, local noise estimate, births/deaths and candidate group identity. Low-confidence regions should fall back toward identity/residual preservation rather than invented harmonic tracks.

Initial transformation modes:

- **Retune** — move confident partial frequencies with phase/trajectory continuity.
- **Reweight** — alter amplitudes near target teeth without moving frequencies.
- **Hybrid** — bounded retune + bounded reweight with residual retention.
- **Spectral morph** — interpolate source/target structure with explicit movement and texture budgets.

The optimisation must preserve selectable roughness/source character and reject degenerate solutions such as muting upper partials or collapsing everything to unison.

## Stage placement

Spectral transformation before nonlinear DSP is not equivalent to transformation after it. Provide explicit stage choices first: pre-shaper, post-shaper, selected inter-stage points, and band-local post-shaper. Store exact ordering in recipes.

Band-local effects should process and re-confine the **effect delta** so bypass can remain identity-safe and transition-band leakage is measurable.

## Timbre-dependent tuning

Compute versioned dissonance/roughness curves for analysed spectra and expose stable local minima as **candidate compatible intervals**, never as proof of a key, cultural rule or listener preference. Adaptive tuning requires home anchors, cumulative-drift limits, voice-leading costs and the ability to increase deliberate tension.

## Musical acceptance

The first useful result is an editable melodic zaag phrase that preserves `locked_bloom` at identity while changing upper-partial relations across explicit sonorities/tunings. SUB/low BODY can remain fixed anchors. Numerical reconstruction/QC is necessary but musical acceptance requires reproducible level-matched audition and owner judgement.

Detailed section-level research notes and source IDs are indexed by `docs/zaaggenz/RAG_INDEX.md` and the programme RAG bundle.
