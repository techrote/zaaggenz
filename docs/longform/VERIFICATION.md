# ZG-043 verification and acceptance map

| ZG-043 acceptance requirement | Executable evidence |
| --- | --- |
| section/phrase sequencing, motif reuse, deliberate long-cycle variation | strict long-form model + `structured_90s_example` / `stress_64bar_example`; section ranges record repeated motif returns |
| tempo and meter maps | per-section validated TimeMap; fixtures include internal changes; tests preserve them across save/reload |
| automation curves | bounded `source_bus`/BODY/AUX/SUB dB curves; rendered after source topology/pockets and before final master |
| returns | repeated motif identity and `return_of_section_id` in rendered/exported section metadata |
| structured ~90-second example | evidence tool fails unless duration remains 85..100 seconds and 12 sections render/export |
| 64-bar stress construction | fixture has exactly 16 × four-bar sections; evidence tool renders/exports all 16 |
| full SYNTHLINE/exciter/BODY/AUX/SUB | aligned mandatory WAVs + nonzero focused fixture coverage; `source_bus` and `pre_master` separately available |
| post-SCULPT/master semantics | base synth topology/SCULPT preserved on source bus; pockets/automation are pre-master contribution stages; one RenderRecipe.output executes after assembly |
| sample-accurate alignment | every stem and mix shares exactly one frame count; manifest/WAV tests assert it |
| documented tail/latency policy | source crossing tails fail closed; persistent ZG-042 release state crosses representable boundaries; zero-phase pockets do not shift dry path |
| save/reload section/tuning/automation | canonical content-addressed JSON + atomic save/load + deterministic rerender hash tests |
| rests and tempo changes | deterministic fixtures include both; exact TimeMap conversion |
| non-octave tuning | 13-ED3 stress sections compile/render/export; exact TuningSpec retained |
| section-boundary tails | adversarial test creates a following-section harmony gap and verifies BODY release continues across the exact boundary |
| no silent 12-TET reduction | MIDI integer field only on exact representable 12-EDO notes; explicit warnings otherwise |
| no dropped layer ownership | note export + manifest name raw source stems, processed source bus, BODY/AUX/SUB, pre-master and final master owner |
| grammar/tuning export | canonical `grammars.json` and `tunings.json`; motif origins retain grammar source identity |

## Protected contracts

ZG-043 must not mutate Project v1, Timeline v1, RenderRecipe/PhrasePlan v1, ZG-029 layer ownership/runtime state, ZG-030 pocket semantics, ZG-042 persistent-section representability/memory policy, protected recovered source bytes, source topology/SCULPT ownership, or final master/normalization defaults.

A future need that cannot be represented by `zaaggenz-longform-arrangement/1.0.0` requires a reviewed long-form format successor. It must not be smuggled into Project/Timeline v1 fields.

## Evidence interpretation

The generated examples are deterministic engineering fixtures. They establish construction, render, save/reload and export behavior. They do not establish listener preference, musical superiority, cultural authenticity or full-band mastering quality.

The 12 kHz CI evidence is explicitly structural/resource-bounded evidence. Audible/default changes still require the normal full-rate listening/default approval gates.
