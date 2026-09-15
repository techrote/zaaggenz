# zaaggenz — master programme overview and task atlas

**Repository:** `techrote/zaaggenz` · **Deployment:** ZG-000 plus ZG-001…ZG-045 published as GitHub issues.  
**Live implementation/readiness status:** [`programme/task_state.json`](../../programme/task_state.json). Narrative status reconciliation is tracked separately in #88.

## Mission

Build an offline/asynchronously rendered instrument for **bouncy melodic zaag-oriented uptempo** while adding reproducible audio-science capabilities. Compose mode must remain useful without participant studies, machine learning, GPUs or research logging.

Protected behaviours include `locked_bloom`, source-preserving notes/arrangement, complete SYNTHLINE in combined renders, explicit exciter/BODY/AUX/SUB ownership, final master semantics, responsive preview/cancel, mature UI access and identity-safe bypasses.

```text
musical intent
  -> tuning / notes / sonorities / phrase roles / gestures
  -> source-preserving construction
  -> optional partial-domain retune / reweight / Chordness
  -> explicit nonlinear and band-local DSP placement
  -> SYNTHLINE + exciter + BODY + AUX + SUB coordination
  -> subtractive spectral space
  -> one declared final output policy
```

Research is a separate layer: immutable recipes -> calibrated measurements with uncertainty -> frozen matched stimuli -> controlled observations -> preregistered or explicitly exploratory analysis -> bounded conclusions. Acoustic metrics do not stand in for artistic quality or listener biochemistry.

## Milestones

| Group | Focus | Evidence target |
|---|---|---|
| **M0 — Recover and stabilise** | baseline, contracts, project provenance, jobs, QC, private reference ingest | G0/G1 |
| **M1 — Make and inspect music** | tuning, source-preserving notes, timeline, harmony/modal grammar, shared analysis/listening | G2 + G3 preparation |
| **M2 — Spectral harmony instrument** | component retuning, Chordness, timbre-dependent tuning, nonlinear/band placement, source families | G3/G4 |
| **M3 — Phrase and layer intelligence** | variation windows, nested metre, gesture direction, linked returns, layer coordination, vocal/text gestures | G4 + G5 preparation |
| **M4 — Research with honest inference** | controlled studies, statistics, optional preference suggestions, Compose/Research integration | G5 |
| **M5 — Long-form useful release** | performance, long-form construction/export, owner validation, packaging | G6 |

Milestones are reporting groups, **not global serial barriers**. Readiness is determined from hard prerequisite artefacts, external gates and exclusive integration locks.

## Earliest useful vertical slices

1. **Recover → contracts/project/QC → tuning → preserved melodic notes → timeline**: a useful composition instrument before advanced research is complete.
2. **Shared multiresolution analysis → component tracking → spectral retune → Chordness → source families/inspector**: a playable spectral-harmony instrument.
3. **Timeline → phrase roles → nested anchors/direction → linked return → layer coordination**: rhythm/phrase intelligence without requiring participant studies.
4. **Listening tools → study manifests → one bounded experiment**: empirical feedback that cannot block transparent creative features.

## Authoritative task atlas

Stable IDs are authoritative; actual issue numbers are in [`programme/issue_map.json`](../../programme/issue_map.json). Machine-readable dependencies/locks are in [`programme/tasks.json`](../../programme/tasks.json) and [`programme/dependency_graph.json`](../../programme/dependency_graph.json).

The planned DAG and the current state are deliberately separate. [`programme/task_state.json`](../../programme/task_state.json) records orthogonal implementation, evidence, research, owner-gate and blocker state plus the explicit `dependency_satisfied` decision for each stable task. GitHub issue open/closed is mirrored there for navigation only; it is not used to compute readiness. Validate and derive readiness with `python tools/validate_programme_state.py --validate` / `--report`. Accepted corrective debt does not automatically revoke prerequisite evidence; a task is withheld only when the state record explicitly says its acceptance/gate is not dependency-satisfying.

| ID | Task | Milestone | Hard prerequisites |
|---|---|---|---|
| **ZG-001** | Recover the verified baseline and freeze musical compatibility | M0 | — |
| **ZG-002** | Freeze versioned musical, analysis and DSP contracts | M0 | 001 |
| **ZG-003** | Immutable project-state snapshots and render provenance | M0 | 001,002 |
| **ZG-004** | Bounded async jobs with responsive preview and cancellation | M0 | 002,003 |
| **ZG-005** | Independent audio QC fixtures and numerical CI | M0 | 001,002 |
| **ZG-006** | Private reference ingest, rights manifests and paired annotation | M0 | 001,002 |
| **ZG-007** | Tuning, scale-degree and keyboard mapping primitives | M1 | 002,003 |
| **ZG-008** | Source-preserving melodic notes, glides and roll gestures | M1 | 005,007 |
| **ZG-009** | Practical clip/note timeline for offline composition | M1 | 003,004,008 |
| **ZG-010** | Sonority progression and constrained voice-leading | M1 | 007,008 |
| **ZG-011** | Directional and motif-based modal grammars | M1 | 007,010 |
| **ZG-012** | Shared multiresolution analysis and feature timeline | M1 | 003,005,006 |
| **ZG-013** | Harmonic-component analysis with transient/residual reconstruction | M1 | 012 |
| **ZG-014** | Calibrated acoustic, harmonic and chord-fit descriptors | M1 | 012,013 |
| **ZG-015** | Reproducible level-matched listening and annotation tools | M1 | 003,004,005 |
| **ZG-016** | Validated DSP graphs and identity-safe multiband routing | M2 | 002,005 |
| **ZG-017** | Phase-coherent partial-domain spectral Auto-Tune | M2 | 007,013,016 |
| **ZG-018** | Constrained multi-comb Chordness and reweighting modes | M2 | 014,017 |
| **ZG-019** | Compare pre/post/inter-nonlinearity spectral control | M2 | 005,016,017 |
| **ZG-020** | Timbre-dependent dissonance maps and bounded adaptive tuning | M2 | 007,014,018 |
| **ZG-021** | Band-selective tuning, compression and bitcrusher experiments | M2 | 016,017,019 |
| **ZG-022** | Curate bouncy melodic zaag gesture/source families | M2 | 008,018,019,021 |
| **ZG-023** | Harmonic-comb and transformation inspector | M2 | 009,014,017,018,020,021 |
| **ZG-024** | Bounded multi-stage inverse search with Pareto results | M2 | 003,004,005,014,018,019,020 |
| **ZG-025** | Phrase-role grammar and predictable variation windows | M3 | 002,008,009 |
| **ZG-026** | Nested metrical anchors, phase clocks and true cross-rhythms | M3 | 012,025 |
| **ZG-027** | Directionality-preserving timbral/rhythmic gestures | M3 | 008,025 |
| **ZG-028** | Linked fake-out, reinterpretation and return events | M3 | 010,025,026,027 |
| **ZG-029** | Coordinate harmonic state, tuning and persistent layer roles | M3 | 010,011,017,020,025,027 |
| **ZG-030** | Layer-aware spectral pockets and sidechain separation | M3 | 016,021,029 |
| **ZG-031** | User-editable syllable/text-to-gesture language | M3 | 007,025,027 |
| **ZG-032** | Local vocal-gesture capture with confidence/manual correction | M3 | 006,012,013,031 |
| **ZG-033** | Aligned reference-pair and synthetic zaag-style ablations | M4 | 006,014,015,018,019,021,022,040 |
| **ZG-034** | Listening evaluation of Chordness/timbre-dependent tuning | M4 | 015,018,020,022,040 |
| **ZG-035** | Linked violation–recovery / reinterpretation experiment | M4 | 015,026,028,040 |
| **ZG-036** | Variation location, metrical anchors and gesture-direction study | M4 | 015,025,026,027,040 |
| **ZG-037** | Vocal participation, familiarity, fluency and framing study | M4 | 015,031,032,040 |
| **ZG-038** | Learning/return recognition in unfamiliar tuning grammars | M4 | 011,015,020,029,040 |
| **ZG-039** | Uncertainty-aware personalised recipe suggestions | M4 | 003,015,024,040 |
| **ZG-040** | Study manifests, preregistration and reproducible statistics | M4 | 005,015 |
| **ZG-041** | Compose/Research UX integration | M4 | 009,015,023,028,030,032 |
| **ZG-042** | Profile/optimise bounded long-form audio workloads | M5 | 003,004,008,013,021,029 |
| **ZG-043** | Long-form arrangement, stem and tuning-aware export | M5 | 009,011,027,029,030,041 |
| **ZG-044** | End-to-end musical validation and release candidates | M5 | 022,023,024,028,030,041,042,043 |
| **ZG-045** | Package zaaggenz with evidence and orchestrator handoff | M5 | 005,006,041,042,043,044 |

## Hard-dependency parallelism

| Level | Potentially ready together after parents pass |
|---:|---|
| 0 | ZG-001 |
| 1 | ZG-002 |
| 2 | ZG-003, ZG-005, ZG-006 |
| 3 | ZG-004, ZG-007, ZG-012, ZG-016 |
| 4 | ZG-008, ZG-013, ZG-015 |
| 5 | ZG-009, ZG-010, ZG-014, ZG-017, ZG-040 |
| 6 | ZG-011, ZG-018, ZG-019, ZG-025 |
| 7 | ZG-020, ZG-021, ZG-026, ZG-027 |
| 8 | ZG-022, ZG-023, ZG-024, ZG-028, ZG-029, ZG-031, ZG-036 |
| 9 | ZG-030, ZG-032, ZG-033, ZG-034, ZG-035, ZG-038, ZG-039, ZG-042 |
| 10 | ZG-037, ZG-041 |
| 11 | ZG-043 |
| 12 | ZG-044 |
| 13 | ZG-045 |

These levels ignore write conflicts. `render-integration`, `frontend-integration`, project/session format, API integration, band-DSP integration, preset registry and release integration are exclusive shared surfaces. Frozen-contract module work can proceed concurrently; integration onto the same shared entrypoint must serialize.

## Orchestrator rules

1. Stable `ZG-*` IDs are authoritative. Do not encode dependencies by issue number.
2. A parent is satisfied only when `programme/task_state.json` records `dependency_satisfied: true` from accepted evidence/gates or an explicit approved equivalent is recorded through review. Closing/abandoning an issue is not enough.
3. One branch/worktree per stable ID. Acquire declared shared locks before touching common entrypoints/contracts.
4. Preserve bypass/identity paths and add positive, negative, boundary and adversarial fixtures.
5. Audible default changes require reproducible level-matched comparison and explicit owner approval.
6. Formal research freezes design/stimuli before confirmatory outcomes are inspected; null/inconclusive outcomes are valid completions.
7. Third-party reference recordings remain private unless redistribution rights are separately established.
8. Batch research/analysis work may share immutable caches but must not starve live preview or mutate current Compose state.

## Important blockers and non-blockers

**Historical bootstrap gate:** ZG-001 originally gated all production-path assumptions on recovery/provenance of the v1.2.1 source. That evidence is now accepted; live blockers and gates are represented in `programme/task_state.json`. The separate #88 reconciliation pass will remove remaining stale bootstrap-era prose throughout the programme documentation.

**Spectral bottleneck:** trusted component/remainder reconstruction precedes retuning; calibrated descriptors precede Chordness; validated graph insertion precedes band-local hybrid presets.

**Musical bottleneck:** tuning/time/note contracts precede harmonic and phrase coordination; full SYNTHLINE remains explicit through every combined render.

**Research bottleneck:** immutable level-matched stimuli and the ZG-040 study scaffold precede confirmatory collection.

**Not blockers for Compose:** success of expectation/participation hypotheses, participant studies, DDSP/ML, GPUs, named traditional grammar packs, or a runtime vector database.

## Shared research/RAG support

- [`CONTEXT_AND_DECISIONS.md`](CONTEXT_AND_DECISIONS.md) — artistic target, authority and protected behaviours.
- [`briefs/AGENT_OPERATING_RULES.md`](briefs/AGENT_OPERATING_RULES.md) — universal implementation contract.
- [`briefs/SPECTRAL_HARMONY.md`](briefs/SPECTRAL_HARMONY.md) — partial-domain harmony and tuning.
- [`briefs/RHYTHM_EXPECTATION.md`](briefs/RHYTHM_EXPECTATION.md) — phrase roles, metre, linked returns and gesture direction.
- [`briefs/EXPERIMENTS.md`](briefs/EXPERIMENTS.md) — bounded empirical programme.
- [`briefs/VALIDATION_GATES.md`](briefs/VALIDATION_GATES.md) — G0–G6 evidence gates.
- [`RAG_INDEX.md`](RAG_INDEX.md) — section/read-set navigation.
- [`programme/tasks.json`](../../programme/tasks.json), [`dependency_graph.json`](../../programme/dependency_graph.json), [`issue_map.json`](../../programme/issue_map.json) — planned machine-readable orchestration.
- [`programme/task_state.json`](../../programme/task_state.json) — live evidence-aware task/readiness state.

The repository destination and source-baseline gate are resolved. Current readiness is the validated state record, not GitHub issue closure.
