# Requirements-to-work traceability

This document explains **why** each major programme thread exists. It is a requirements map, not a live implementation-status report. Current accepted implementation/evidence, research state, owner gates and dependency readiness are recorded in [`programme/task_state.json`](../../programme/task_state.json); issue bodies contain work-specific details and `programme/tasks.json` contains the planned machine-readable dependency/lock graph.

| Requirement / recovered intent | Primary tasks | Validation / evidence |
|---|---|---|
| Preserve `locked_bloom`, source-preserving arrangement and full SYNTHLINE | ZG-001,005,008,029,044 | protected render hashes, source-preservation and stem/null tests, owner review |
| Keep the tool a usable offline/async instrument | ZG-003,004,009,041,042,043,045 | save/reload, preview/cancel, long-render budgets, clean offline package |
| Explicit tuning, scales, accidentals and alternatives to 12-TET | ZG-007,010,011,020,043 | tuning fixtures, non-octave progressions, export warnings |
| “Spectral Auto-Tune” / multiresolution partial-domain control | ZG-012,013,017,019,021,023 | synthetic component ground truth, identity reconstruction, before/after inspector |
| Mathematically meaningful Chordness control | ZG-014,018,023,034 | multi-comb fit/reweight/retune ablations, separate sonority/source ratings |
| Timbre can imply compatible interval/tuning candidates | ZG-014,020,034 | method-versioned dissonance maps, sensitivity tests, listening evaluation |
| Keep rough/noisy character as a controllable resource, not an error | ZG-014,018–022,030 | roughness separated from harmonic/chord fit; owner auditions and controlled contrasts |
| Process selected bands; bitcrush/compress/retune without destroying whole mix | ZG-016,019,021,030 | dry identity, spill/leakage, pocket/sidechain and ordering tests |
| `1234 1234 1234 5555`: stable variation location / variable content | ZG-025,026,036 | phrase-role templates, matched-placement experiment |
| Fast detail + half-rate bounce + quarter-rate sway | ZG-026,036 | nested-clock tests and multiple supported metrical interpretations |
| Fake drops / local violation + larger-scale recovery | ZG-028,035 | linked/unrelated factorial stimuli; separate affect/recognition outcomes |
| Preserve gesture direction while varying surface detail | ZG-027,031,036 | directional trajectory fixtures and matched listening conditions |
| “bu budu…” as communicable musical/timbral gesture language | ZG-031,032,037 | text round-trip, contour extraction/manual correction, participation study |
| Modal grammar beyond unordered scale membership | ZG-011,029,038 | synthetic directional grammars, exposure/return-recognition study |
| Learn from rare/non-Western structures without stereotype/authenticity overclaim | ZG-011,020,038 + source review | synthetic labels by default; source-reviewed named packs only |
| Use paired piep/zaag tracks as a contrast without overfitting | ZG-006,033 | private ingest/alignment, loudness-matched motif and synthetic ablation |
| Inverse-fitting remains bounded/interpretable | ZG-024,039 | synthetic recovery, holdouts, Pareto results, optional preference model |
| Scientific work must be reproducible and able to return null results | ZG-015,033–040 | immutable stimuli, study manifests, preregistration, effect/uncertainty reports |
| Research UI must not engulf Compose | ZG-009,023,041 | Compose-first browser tests, explicit apply/undo, no silent research mutation |
| Long-form construction/export and release quality | ZG-042–045 | long-form examples, aligned stems, performance, packaging and owner validation |

## Programme-wide acceptance rule

A numerical proxy cannot satisfy an artistic requirement by itself. A listening preference cannot validate a scientific claim by itself. Each issue should point to the evidence type appropriate to its requirement and keep these gates distinct. Whether that evidence currently satisfies programme dependencies is read from `programme/task_state.json`, never inferred from GitHub issue closure or from this traceability table.
