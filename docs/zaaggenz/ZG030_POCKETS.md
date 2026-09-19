# ZG-030 layer-aware spectral pockets

ZG-030 adds an explicit subtractive layer-separation stage on top of the accepted ZG-029 persistent-layer runtime. It does not change the frozen ZG-002 `RenderRecipe` or `PhrasePlan` wire contracts and it does not rewrite recovered source material.

## Execution boundary

`LayerPocketPlan` is a versioned Python control object (`zaaggenz.layer-pockets/1.0.0`). It requires three explicit ZG-016 crossover frequencies and contains typed static automation and/or dynamic sidechain specifications. No pocket is an implicit product default.

V1 permits BODY, AUX, or SUB to be the **yielding** layer. SYNTHLINE and exciter may be detector inputs but are the raw source-owned audition stems defined by ZG-029 policy 1.1.0; neither they nor the processed `source_bus` are rewritten by the pocket stage. This preserves source evidence and the shared nonlinear source path while still allowing persistent accompaniment to make deliberate space for source arrivals. SUB may be pocketed only when explicitly authored; the curated ZG-030 fixture deliberately leaves SUB untouched so bass support is not selected away by a proxy score.

Each `(yielding_role, band)` has at most one pocket owner in v1. Ambiguous chains fail closed rather than inventing order. Sidechain detector roles must differ from the yielding role.

## Static/automated pockets

`StaticPocketSpec` supplies strictly increasing `PocketAutomationPoint(sample, attenuation_db)` values. Attenuation is linear in dB between points and endpoint values are held outside the authored point span. Values are bounded to 0..36 dB. Authors who want a finite pocket therefore place explicit zero-dB points on both sides of that region.

The resulting gain is strictly `(0, 1]`: this stage cannot add gain. A zero-dB curve is an exact bypass.

## Dynamic sidechain pockets

`SidechainPocketSpec` declares:

- yielding role and detector role;
- one affected ZG-016 band (`sub`, `lowmid`, `highmid`, or `air`);
- threshold in dBFS;
- attack, release, and offline lookahead in samples;
- maximum attenuation in dB.

The detector is the selected band of the **pre-pocket canonical detector stem**. For BODY/AUX/SUB that is the persistent pre-master role stem; for SYNTHLINE/exciter it is the raw audition stem, not a fictitious nonlinear post-topology decomposition. Detector inputs are snapshotted before any pockets run, so one pocket cannot silently alter a later detector. A role muted by the coordinated renderer is explicitly zero at the detector, which makes that sidechain an exact bypass.

Attack/release use a deterministic one-pole envelope over detector magnitude. Gain reduction is the detector excess above threshold, capped by `max_attenuation_db`. There is no ratio/makeup stage and no hidden post-pocket normalization. Lookahead reads future detector samples offline; it does not introduce a delayed dry path.

## Band confinement and spill evidence

Every non-identity pocket uses the accepted ZG-016 effect-delta path:

`dry yielding stem + selected-band projection(processed selected band - selected band)`

The dry path is never split/recombined. The existing fourth-order zero-phase Butterworth policy remains authoritative and its crossover/filter metadata is emitted in pocket diagnostics. Each operation records the ZG-016 `BandDeltaReport`, including routed-delta RMS and measured leakage into every analysis band. This makes transition-band spill visible rather than claiming brick-wall isolation.

## Gain provenance and final master

Every pocket operation records before/after float32 PCM hashes, before/after RMS, requested controls, measured maximum attenuation, active-sample bounds, detector hash/mute state where applicable, and an explicit `makeup_gain_db: 0.0`.

`render_coordinated_pockets()` uses ZG-029 for source and persistent-layer generation. Empty plans, zero-attenuation plans, muted-detector sidechains, and any other plan whose computed persistent-role deltas are exactly zero return the accepted ZG-029 mix/stems bit-for-bit. When a pocket actually changes a persistent stem, the wrapper discards ZG-029's provisional mastered mix, applies only BODY/AUX/SUB deltas around the already-processed `source_bus`, then executes `RenderRecipe.output` once for the returned modified signal path. The pocket stage never attempts to split a shared nonlinear source bus and never normalizes or compensates for subtraction.

The oscillator/phase/tail `LayerRuntimeState` is unchanged by pockets. ZG-029 remains the owner of persistent voice continuity and section transitions.

## Protected semantics

ZG-030 does not change recovered source bytes/provenance, frozen ZG-002 schema versions, ZG-008 source-note derivation, ZG-010 harmony targets, ZG-016 crossover/filter identity, tuning equations, source SYNTHLINE/exciter stems, ZG-029 phase/tail state, final clipping/master ownership, inverse/listening/reference evidence, or artistic defaults.

The curated listening evidence is a matched baseline/pocket pair with the same source, harmony, generator intent, master policy, and SUB. CI treats those matched controls as executable invariants: fixture generation fails if SYNTHLINE, exciter, SUB, runtime state, master ownership, normalization, or zero-makeup constraints drift, or if BODY does not actually yield. The pair is an audition aid, not a preference result and not an optimization target.
