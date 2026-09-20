# ZG-043 long-form arrangement and tuning-aware export

ZG-043 adds a versioned authoring/export wrapper above the accepted Compose, Project, harmony, layer and long-workload contracts. It does **not** migrate or widen `zaaggenz-project/1.0.0`, `zaaggenz-timeline/1.0.0`, `RenderRecipe/1.0.0` or `PhrasePlan/1.0.0`.

## Format and authority

The authoring file is:

- format: `zaaggenz-longform-arrangement`
- version: `1.0.0`
- ordinary extension used by evidence/examples: `.zglongform.json`

A long-form document retains:

- one immutable current Project v1 base whose head is a phrase-free mono synth recipe;
- explicit TuningSpec documents, including non-octave tunings;
- optional complete ZG-011 grammar source documents as provenance for motif origins;
- bounded motifs made of ordinary source-preserving note/rest intent;
- ordered sections with motif reuse, transpose/gain variation, exact tempo and meter maps, tuning selection and named section identity;
- explicit harmony roots plus a fully serialized ZG-010 `VoicingConstraints` record;
- an explicit ZG-029 `LayerRuntimeSpec`;
- optional ZG-030 pocket plans;
- pre-master contribution automation for `source_bus`, BODY, AUX and SUB;
- explicit reset roles;
- explicit deferred intent labels for continuous spectral retuning, adaptive tuning and timbral gestures;
- an export policy controlling optional diagnostic `source_bus` and `pre_master` WAVs.

The wrapper is canonical JSON and content-addressed. Save uses an atomic replace. Reload revalidates the embedded Project, tunings, grammars, runtime, harmony, pockets, timing maps, automation and bounded request domain.

## Why this is a wrapper, not Project/Timeline v2

Project v1 remains the portable immutable RenderRecipe/revision authority. Timeline v1 remains the practical short-form Compose authoring document. ZG-043 composes those accepted products instead of silently changing their meanings.

Each long-form section compiles to a normal synth-mode RenderRecipe with its own exact TimeMap/TuningSpec/PhrasePlan. Harmony is deterministically re-solved from the persisted tuning, roots and complete voicing constraints. Runtime-only `ProgressionResult` objects are never serialized as authoring authority.

The long-form request is bounded to:

- 64 motifs;
- 256 events per motif;
- 128 sections;
- 64 repeats per section;
- 4,096 expanded source events;
- 5,000,000 total output frames;
- 32 tunings;
- 32 grammar sources;
- 128 automation points per curve.

Oversize constructions fail before proportional output allocation. Larger works are represented as explicit export parts instead of relying on an unbounded hidden spool.

## Section timing, motif reuse and long-cycle variation

Every section declares a local exact TimeMap:

- tempo segments are rational BPM values in 20..360;
- meter segments are explicit and may change inside a section;
- all beat→sample conversion uses the existing nearest-ties-even TimeMap policy.

Motifs are immutable reusable event templates. Section identity, motif identity and the first earlier section using the same motif are emitted in render/export metadata. Transposition, tuning, gain, pocket plan, automation and tempo/meter differences therefore remain explicit rather than turning a copied motif into an unrelated anonymous phrase.

The repository fixtures include:

- `structured_90s_example()` — twelve four-bar sections around 90 seconds, with recurring motifs, rests, internal tempo changes, a meter change, pocketing and source/persistent gain automation;
- `stress_64bar_example()` — sixteen four-bar sections (64 bars), with tempo changes, rests, 12-EDO ↔ 13-ED3 tuning changes, microtonal/bend intent and deferred spectral/adaptive/timbral warnings.

They are original deterministic engineering fixtures, not reference recordings and not preference evidence.

## Render ownership

Long-form rendering deliberately reuses accepted owners rather than creating a parallel engine.

### Source roles

Each section's motif expands to an ordinary PhrasePlan and renders through ZG-008 source-preserving melody on the declared section TimeMap/TuningSpec.

- `synthline` and `exciter` remain raw source-owned audition/provenance stems.
- The section's existing source topology/SCULPT executes before the source contribution becomes `source_bus`.
- ZG-043 never automates or rewrites the raw audition stems.

The source phrase uses explicit `tail_mode=truncate`. A SYNTHLINE/exciter result that extends beyond the declared section boundary fails the long-form render instead of being silently cropped; the author must shorten the gesture or leave explicit rest space.

### Persistent roles and section-boundary tails

The complete BODY/AUX/SUB sequence is passed through the accepted ZG-042 `render_persistent_sections()` path.

That means:

- one immutable bounded section snapshot;
- ZG-029 `LayerRuntimeState` continuation across sections;
- explicit `LayerSectionTransition`;
- phase/last-target/release-tail continuity;
- an unsupported boundary through an unfinished serialized glide fails before PCM work;
- section reset roles are explicit;
- BODY/AUX/SUB state may continue through a rest at the start of a following section.

This is the authoritative section-boundary tail policy. Long-form concatenation is not treated as an implicit oscillator reset.

### ZG-030 pockets and automation

Section pocket plans consume the accepted ZG-030 layer-pocket implementation. Only BODY/AUX/SUB may yield; raw SYNTHLINE/exciter remain immutable detector/provenance stems and `source_bus` is never decomposed.

ZG-043 gain automation is applied after protected source topology for `source_bus` and after ZG-030 pocket processing for persistent stems, but before the single final master. Accepted targets are `source_bus`, `body`, `aux` and `sub`. No hidden makeup or normalization is introduced.

### Final mix/master

The global aligned pre-master is exactly:

```text
source_bus + body + aux + sub
```

after authored section automation/pockets.

The base RenderRecipe `output` policy executes once for the returned long-form mix. Current fixture policy therefore retains one final `render-recipe.output` owner and normalization `none`.

## Sample alignment and export bundle

`export_longform()` writes float32 WAV files sharing one sample rate and exactly one frame count:

- `mix.wav`;
- `stem-synthline.wav`;
- `stem-exciter.wav`;
- `stem-body.wav`;
- `stem-aux.wav`;
- `stem-sub.wav`;
- optional `stem-source_bus.wav`;
- optional `stem-pre_master.wav`.

It also writes:

- `project.zglongform.json` — canonical long-form authoring document;
- `tunings.json` — exact TuningSpec collection;
- `grammars.json` — exact grammar source collection plus motif-origin mapping;
- `note-events.json` — interoperable note-event evidence with exact sample/time, tuning coordinate and frequency;
- `manifest.json` — section ranges, tail/latency policy, layer ownership, file hashes, PCM hashes, final runtime state, master ownership and note-export warnings.

## Simple note-event representation and fidelity warnings

Simple note export is deliberately **not** the authority for the arrangement.

Every pitched event always keeps tuning ID through its section, tuning degree, detune cents, exact realised base frequency, absolute start sample/time and duration, and original pitch-curve points where present.

`midi_note_12tet` is included only when the persisted tuning is exact 12-EDO, static detune is zero and no continuous pitch curve is needed. Otherwise it is `null`.

Warnings are mandatory for intent that a simple integer-note representation cannot faithfully round-trip, including non-12-TET tuning, static microtonal offsets, continuous pitch bends, persistent layer retuning, continuous spectral retuning, adaptive tuning, timbral gestures, pre-master contribution automation and ZG-030 pockets.

The exact TuningSpec, long-form document, layer ownership and deferred intent remain authoritative. ZG-043 never rounds those meanings to 12-TET or deletes them merely to populate a note field.

## Validation

Focused validation:

```text
python -m unittest discover -s tests/longform -v
```

Generated evidence:

```text
python tools/zg043_fixture_report.py --out zg043-evidence.json --sample-rate 12000
```

The evidence run actually renders and exports both required constructions, verifies aligned frame counts/one final master/warning coverage, hashes the complete temporary bundles, and retains only compact JSON evidence. The WAV bundles are not uploaded by CI.

12 kHz evidence proves deterministic timing/state/ownership/export structure and does **not** certify full-band sound quality or owner preference. Existing full-rate source/layer/performance gates remain separate authorities.
