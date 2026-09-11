# zaaggenz — master programme overview and task atlas

**Repository:** `techrote/zaaggenz` · **Status:** programme published; implementation baseline still gated by ZG-001.

## Mission

Build an offline/async rendered instrument for **bouncy melodic zaag-oriented uptempo** while adding reproducible audio-science capabilities. Compose mode must remain useful without participant studies, machine learning, GPUs, or research logging. Research features observe and transform explicitly; they do not silently rewrite the working sound.

Protected behaviours: preserve `locked_bloom`, source-preserving notes/arrangement, full SYNTHLINE in combined renders, explicit exciter/BODY/AUX/SUB stems, final master semantics, responsive preview/cancel, and existing mature UI access.

## Architecture

```text
musical intent
  -> tuning / notes / sonorities / phrase roles / gestures
  -> source-preserving construction
  -> optional partial-domain spectral retune/reweight/Chordness
  -> explicit nonlinear / band-local DSP graph
  -> SYNTHLINE + exciter + BODY + AUX + SUB coordination
  -> subtractive spectral space
  -> declared final output policy
```

Research chain: immutable recipes and hashes -> calibrated measurements with uncertainty -> frozen matched stimuli -> blinded/counterbalanced observations where appropriate -> preregistered or explicitly exploratory analysis -> bounded conclusions. Audio descriptors never stand in for neurotransmitter measurements or artistic quality.

## Milestones

- **M0 — Recover and stabilise** — baseline, contracts, provenance, jobs, QC and private ingest. Evidence gates G0/G1.
- **M1 — Make and inspect music** — tuned notes, construction timeline, harmonic/modal grammar, shared analysis and listening infrastructure. Evidence gate G2 and G3 preparation.
- **M2 — Spectral harmony instrument** — phase-coherent retuning, Chordness, timbre-derived tuning and controlled nonlinear/band processing. Evidence gates G3/G4.
- **M3 — Phrase and layer intelligence** — variation windows, metrical anchors, directionality, linked returns, coordinated layers and vocal/text gestures. Evidence gate G4 and G5 preparation.
- **M4 — Research with honest inference** — protocols, controlled studies, optional preference learning and integrated Compose/Research UX. Evidence gate G5.
- **M5 — Long-form useful release** — measured performance, complete compositions, owner evaluation, packaging and evidence. Evidence gate G6.

Milestones are reporting groups, not blanket barriers. Readiness is determined by hard dependencies, external/evidence gates, and shared integration locks.

## Earliest useful vertical slices

1. Recover baseline -> contracts/provenance/QC -> tuning -> source-preserving melodic notes -> timeline.
2. Shared multiresolution analysis -> partial tracking -> spectral retune -> multi-comb Chordness -> inspector/presets.
3. Timeline -> phrase roles -> metrical anchors/gesture direction -> linked fake-out/recovery -> layer coordinator.
4. Trial infrastructure -> one bounded study, without blocking creative release.

## Complete task atlas

| ID | Task | Group | Hard prerequisites |
|---|---|---|---|
| **ZG-001** | Recover the verified baseline and freeze musical compatibility | M0 | — |
| **ZG-002** | Freeze versioned musical, analysis and DSP contracts | M0 | ZG-001 |
| **ZG-003** | Implement immutable sessions, recipe hashes and artefact provenance | M0 | ZG-001, ZG-002 |
| **ZG-004** | Build bounded async jobs with responsive preview and cancellation | M0 | ZG-002, ZG-003 |
| **ZG-005** | Establish independent audio QC fixtures and numerical CI | M0 | ZG-001, ZG-002 |
| **ZG-006** | Add private reference ingest, rights manifests and paired annotation | M0 | ZG-001, ZG-002 |
| **ZG-007** | Implement tuning, scale-degree and keyboard mapping primitives | M1 | ZG-002, ZG-003 |
| **ZG-008** | Render source-preserving melodic notes, glides and roll gestures | M1 | ZG-005, ZG-007 |
| **ZG-009** | Add a practical clip and note timeline for offline composition | M1 | ZG-003, ZG-004, ZG-008 |
| **ZG-010** | Add sonority progression and constrained voice-leading | M1 | ZG-007, ZG-008 |
| **ZG-011** | Implement extensible directional and motif-based modal grammars | M1 | ZG-007, ZG-010 |
| **ZG-012** | Build a shared multiresolution analysis and feature timeline | M1 | ZG-003, ZG-005, ZG-006 |
| **ZG-013** | Track partials and preserve transients plus residual in resynthesis | M1 | ZG-012 |
| **ZG-014** | Calibrate separate acoustic, harmonic and chord-fit descriptors | M1 | ZG-012, ZG-013 |
| **ZG-015** | Build blinded, level-matched listening and annotation tools | M1 | ZG-003, ZG-004, ZG-005 |
| **ZG-016** | Introduce validated DSP graphs and identity-safe multiband routing | M2 | ZG-002, ZG-005 |
| **ZG-017** | Implement phase-coherent partial-domain spectral Auto-Tune | M2 | ZG-007, ZG-013, ZG-016 |
| **ZG-018** | Add constrained multi-comb Chordness and reweighting modes | M2 | ZG-014, ZG-017 |
| **ZG-019** | Measure timbre-dependent dissonance maps and candidate intervals | M2 | ZG-014 |
| **ZG-020** | Add bounded adaptive tuning with anchors, drift limits and voice-leading | M2 | ZG-007, ZG-019 |
| **ZG-021** | Compare pre/post/inter-stage spectral transforms through nonlinear DSP | M2 | ZG-005, ZG-016, ZG-017 |
| **ZG-022** | Add musical source families and timbral-morph controls for melodic zaag | M2 | ZG-008, ZG-018, ZG-021 |
| **ZG-023** | Build a spectral-harmony inspector and expert control surface | M2 | ZG-014, ZG-018, ZG-019, ZG-022 |
| **ZG-024** | Add inverse-fitting research tools for zaag source families | M2 | ZG-012, ZG-014, ZG-022 |
| **ZG-025** | Represent phrase roles and predictable variation windows | M3 | ZG-009 |
| **ZG-026** | Add nested metrical anchors, syncopation and phase-relative event grammar | M3 | ZG-009, ZG-025 |
| **ZG-027** | Implement timbral gesture trajectories and directional fills | M3 | ZG-009, ZG-025 |
| **ZG-028** | Implement linked fake-out, reinterpretation and return objects | M3 | ZG-025, ZG-026, ZG-027 |
| **ZG-029** | Coordinate SYNTHLINE, exciter, BODY, AUX and SUB from musical state | M3 | ZG-010, ZG-016, ZG-020, ZG-026, ZG-027 |
| **ZG-030** | Add layer-aware subtractive space and movement-aware SCULPT automation | M3 | ZG-016, ZG-029 |
| **ZG-031** | Define compact text/vocal gesture notation and import | M3 | ZG-007, ZG-025, ZG-027 |
| **ZG-032** | Capture local vocal gestures with confidence and manual correction | M3 | ZG-006, ZG-012, ZG-013, ZG-031 |
| **ZG-033** | Run aligned reference-pair and synthetic zaag-style ablations | M4 | ZG-006, ZG-014, ZG-015, ZG-018, ZG-019, ZG-021, ZG-022, ZG-040 |
| **ZG-034** | Test Chordness and timbre-dependent tuning against listening | M4 | ZG-015, ZG-018, ZG-020, ZG-022, ZG-040 |
| **ZG-035** | Test linked violation–recovery and retrospective reinterpretation | M4 | ZG-015, ZG-026, ZG-028, ZG-040 |
| **ZG-036** | Test variation location, metrical anchors and gesture direction | M4 | ZG-015, ZG-025, ZG-026, ZG-027, ZG-040 |
| **ZG-037** | Test vocal participation, familiarity, fluency and framing | M4 | ZG-015, ZG-031, ZG-032, ZG-040 |
| **ZG-038** | Test learning and return recognition in unfamiliar tuning grammars | M4 | ZG-011, ZG-015, ZG-020, ZG-029, ZG-040 |
| **ZG-039** | Add uncertainty-aware personalised recipe suggestions | M4 | ZG-003, ZG-015, ZG-024, ZG-040 |
| **ZG-040** | Build preregistration, study manifests and reproducible statistics | M4 | ZG-005, ZG-015 |
| **ZG-041** | Integrate Compose and Research UX without sacrificing the instrument | M4 | ZG-009, ZG-015, ZG-023, ZG-028, ZG-030, ZG-032 |
| **ZG-042** | Profile and optimise bounded long-form audio workloads | M5 | ZG-003, ZG-004, ZG-008, ZG-013, ZG-021, ZG-029 |
| **ZG-043** | Deliver long-form arrangement, stem and tuning-aware export | M5 | ZG-009, ZG-011, ZG-027, ZG-029, ZG-030, ZG-041 |
| **ZG-044** | Validate end-to-end musical workflows and curate release candidates | M5 | ZG-022, ZG-023, ZG-024, ZG-028, ZG-030, ZG-041, ZG-042, ZG-043 |
| **ZG-045** | Package zaaggenz with evidence, compatibility and orchestrator handoff | M5 | ZG-005, ZG-006, ZG-041, ZG-042, ZG-043, ZG-044 |

## Dependency-ready antichains

- **Level 0:** ZG-001
- **Level 1:** ZG-002
- **Level 2:** ZG-003, ZG-005, ZG-006
- **Level 3:** ZG-004, ZG-007, ZG-012, ZG-016
- **Level 4:** ZG-008, ZG-013, ZG-015
- **Level 5:** ZG-009, ZG-010, ZG-014, ZG-017, ZG-040
- **Level 6:** ZG-011, ZG-018, ZG-019, ZG-025
- **Level 7:** ZG-020, ZG-021, ZG-026, ZG-027
- **Level 8:** ZG-022, ZG-023, ZG-024, ZG-028, ZG-029, ZG-031, ZG-036
- **Level 9:** ZG-030, ZG-032, ZG-033, ZG-034, ZG-035, ZG-038, ZG-039, ZG-042
- **Level 10:** ZG-037, ZG-041
- **Level 11:** ZG-043
- **Level 12:** ZG-044
- **Level 13:** ZG-045

These levels show hard-dependency parallelism only. Same-file/contract collisions still serialize integration. `render-integration`, `frontend-integration`, `session-format`, `api-integration`, `band-dsp-integration`, `preset-registry`, and `release-integration` are exclusive shared surfaces.

## Orchestrator rules

1. Stable IDs `ZG-000`…`ZG-045` are authoritative; GitHub issue numbers are deployment mappings.
2. A prerequisite is satisfied only by merged/accepted evidence or an approved equivalent, not merely a closed issue.
3. Create a dedicated worktree/branch per stable ID. Acquire listed shared locks before editing common contracts/entrypoints.
4. Preserve identity/bypass paths and add positive, negative, boundary and adversarial fixtures.
5. Audible default changes require reproducible level-matched comparison and owner approval.
6. Formal research freezes design/stimuli before confirmatory outcomes are inspected; null/inconclusive outcomes are valid completions.
7. Never commit third-party reference recordings, credentials, or participant identity data.

## Shared documentation / RAG

- `docs/zaaggenz/CONTEXT_AND_DECISIONS.md` — artistic target, authority, protected behaviours.
- `docs/zaaggenz/briefs/AGENT_OPERATING_RULES.md` — universal implementation contract.
- `docs/zaaggenz/briefs/SPECTRAL_HARMONY.md` — partial-domain retune/reweight/Chordness and timbre-dependent tuning.
- `docs/zaaggenz/briefs/RHYTHM_EXPECTATION.md` — phrase roles, nested pulse, variation windows, linked returns, gesture direction.
- `docs/zaaggenz/briefs/EXPERIMENTS.md` — bounded study families and inference rules.
- `docs/zaaggenz/briefs/VALIDATION_GATES.md` — G0–G6 evidence gates.
- `programme/tasks.json` / `programme/dependency_graph.json` — machine-readable orchestration.

## Important current gates

- `techrote/zaaggenz` is now the confirmed destination.
- The actual v1.2.1 source/archive still has to be recovered and provenance-checked under **ZG-001** before feature work assumes code paths or baseline hashes.
- The two supplied reference tracks are private observational probes; they are not a causal dataset and are not redistributed in this repository.
