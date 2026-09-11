# Validation gates and release evidence

## Gates

| Gate | Evidence | Consequence |
|---|---|---|
| **G0 — recoverable baseline** | Source provenance, real file map, current tests with failures retained, reproducible baseline renders | No DSP replacement or migration before this gate |
| **G1 — contract stability** | Versioned schemas/adapters, units, timing/channel/phase conventions, migration policy | Parallel consumers may implement against frozen contracts |
| **G2 — useful construction instrument** | Tuned source-preserving notes/phrases, save/reload, async preview/render, aligned stems, protected UI behaviours | First usable musical milestone independent of studies |
| **G3 — trustworthy analysis/transformation** | Calibrated synthetic fixtures, null/identity paths, confidence handling, adversarial edge cases | Spectral transformations may be exposed behind explicit method/quality settings |
| **G4 — musical spectral instrument** | Chordness/retuning/timbre controls survive matched audition and preserve selectable source character | Curated melodic-zaag spectral workflows may ship |
| **G5 — interpretable research** | Frozen protocols/stimuli, matching, consent/privacy where relevant, preregistration or explicit exploratory status | Research claims limited to their design |
| **G6 — release** | End-to-end compose/research demos, performance budgets, packaging/build coherence, rights scan, protected-sound regressions | Publish versioned deliverable with evidence and limitations |

Gates are evidence predicates, not global milestone barriers. Closing or abandoning an issue does not satisfy a dependency unless the required artefact/evidence exists or an approved equivalent is recorded.

## Test pyramid

- **Contracts/properties:** recipe hashing, serialisation, units, tempo/meter maps, non-octave tuning, graph validity and bounds.
- **Signal fixtures:** silence, impulse, sine, harmonic/inharmonic combs, AM/FM, chirps, partial crossings, amplitude nulls, band-limited noise and mixed transient/tonal cases.
- **DSP identity/quality:** true bypass, reconstruction residual, alignment, phase/stereo stability, output gain and clipping policy.
- **Perceptual proxies:** frequency error, track confidence, onset displacement, modulation trajectories, band-energy changes, roughness/fit descriptors with method/version metadata.
- **Listening:** reproducible level-matched owner evaluation and later blinded comparisons where appropriate. Objective descriptors never certify artistic quality by themselves.
- **System/UI:** API round trips, queued/cancelled jobs, stale-result rejection, save/reopen equality, long-file memory and real browser interactions.

## Musical regression grid

Cover slow through extreme tempos (including 20, 80, 160, 200, 240 and 360 BPM), short and long arrangements, tempo changes, rests/pickups, overlapping tails, dense subdivisions, sparse/dense sonorities, moving/pedal bass, non-octave tunings, source-preserving and transformed paths, plus deliberately noisy/inharmonic cases.

Protect full SYNTHLINE contribution in combined renders and keep stem/master/tail semantics explicit. Do not infer full-band quality from reduced-sample-rate smoke tests.

## Completion evidence

Implementation PRs should state contract versions, exact commands, fixtures/hashes, deterministic seeds, positive/negative tests, named environment/runtime data, listening recipes for audible changes, limitations and migration effects. Research tasks should additionally preserve protocol/stimulus versions and report outcomes honestly, including null/inconclusive findings.
