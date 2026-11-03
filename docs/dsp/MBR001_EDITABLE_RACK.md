# MBR-001: saved editable rack and legacy adapters

Scope: issue #239, master #238. This is the **saved contract and persistence**
foundation, not acceptance of the Compose rack UI or native plug-in hosting.
MBR-002 owns actual RuntimeSession/JobScheduler execution; MBR-003 owns editing;
MBR-004 closes built-in workflow acceptance. Phase B remains separate.

Runtime follow-up: [MBR-002 Compose execution](MBR002_COMPOSE_EXECUTION.md)
implements the backend route below without changing these accepted formats.
Historical MBR-001-only rejection statements describe the foundation commit;
current Compose consumes built-in racks, while unsupported consumers still
fail explicitly. UI, Phase-A acceptance and native hosting remain separate.

## Version boundaries and compatibility

| Envelope | Without a rack | Explicit rack opt-in |
| --- | --- | --- |
| RenderRecipe | `1.0.0`, unchanged | `1.1.0`, required `rack` |
| Project | `format_version: 1.0.0`, unchanged | `1.1.0`, required `rack_presets` |
| TimelineDocument | `1.0.0` | Still `1.0.0`; its authoritative nested Project understands both versions |
| MultibandRack / built-in insert | Absent | `1.0.0` |
| Nested time/tuning/phrase/DSP contracts | `1.0.0` | Unchanged `1.0.0` |

`schema()` and `schema('RenderRecipe')` still export the frozen v1 definitions.
Select `schema('RenderRecipe', version='1.1.0')` for the extension. Structural
JSON Schema **and** semantic `Contract`/`RackRecipe` validation are required.
Unknown versions/types/fields fail; the importer does not guess migrations.

Opening/resaving a no-rack project neither synthesizes a rack nor changes its
format, source recipe, revision hash, output policy or sonic identity. Opt-in is
an explicit `Project.set_rack` commit. The full original revision remains in the
same Project; no browser-local parallel store is involved. Old readers reject
v1.1 rather than silently playing it dry. Resetting processing removes `rack`
and returns that working recipe to v1.0, but the Project stays v1.1 while it
retains rack history or presets. It never silently discards saved data.

## Actual route and ownership

The saved placement is fixed and validated:

```text
complete source-derived notes -> sum on SYNTHLINE -> multiband effect-delta rack
  -> existing synth-owned SCULPT OR explicit DSP graph -> existing final master
EXCITER (source-derived roll slices) remains separate and unprocessed by this rack
BODY / AUX / SUB remain owned by the retained legacy Project
```

This describes the rack insertion boundary MBR-002 must execute, not an assertion
that this commit has installed a runtime processor. `compile_recipe` already
forwards the exact saved rack and protected source through the existing
`transform_melodic_recipe` for rack-bearing projects. A synth-owned SCULPT or
explicit graph is preserved. The existing transform retains full-mix
arrangement/reversebass/SCULPT in the Project instead of rebinding them to the
melodic SYNTHLINE branch; ambiguous non-synth graphs fail explicitly. The old
no-rack compilation path is unchanged. EXCITER's downstream treatment by the
existing topology/final-master stage is unchanged.

The four spectral pockets are `sub`, `lowmid`, `highmid`, `air`. The first is a
frequency pocket of SYNTHLINE, **not** the synthesizer's independent SUB stem.
The method identity is `zg.butter4_sosfiltfilt_effect_delta.v1`, adapting the
existing offline four-band router. Default crossovers remain 105/520/3600 Hz;
all crossovers must satisfy `20 <= low < mid < high < 0.49 * sample_rate` even
when all processing is bypassed. No hidden normalization, clipping, distortion
or second master is introduced. Rack policy is linked shape-preserving
channels, reset-per-render state, zero-aligned offline output, input-length
tail, no normalization and **0 dB additional master**. Sample rate and channels
must match the saved source context. The generic router contract supports
8–192 kHz and mono/stereo; that does not enlarge the legacy synth's 96 kHz cap
or Compose's existing mono source-derived consumer.

Until MBR-002 is implemented, Compose's melodic consumer explicitly rejects a
rack-bearing recipe **before source rendering**, including a bypassed one. It
must not silently discard the saved contract. The adapter below already proves
exact identity **at the rack processing boundary**; that component proof is
not end-to-end browser/runtime acceptance.

## Saved state and bypass semantics

`RackRecipe` owns a defensive serialized snapshot. Its exact fields are
`kind`, `version`, `id`, `source_binding`, `placement`, `sample_rate_hz`,
`channels`, `crossovers`, `bypass`, `wet`, `bands`, `policy`, `display`.

Each of the four fixed bands has an instance `id`, fixed spectral `band` name,
`bypass`, `wet`, `confine_delta` and ordered `inserts`. Each insert has `id`,
`type_id`, processor `version`, `bypass`, `wet`, `params`, `automation`.
Instance IDs are globally unique within a rack, bounded to 64 characters and
match `[a-z][a-z0-9_.-]*`. IDs are independent of display labels; reordering
moves the same record, not a freshly initialized processor. Band assignment
and array order are sonic intent. At most one of each built-in stage occurs in
a band; preserved external descriptors may occupy additional ordered positions.

Rack, band and insert bypass are distinct persistent controls. Bypassing any
level retains and **still validates** every latent setting. Zero wet means dry;
nonzero wet is in [0,1]. For the later runtime, insert wet blends that stage's
input/output, band wet scales that band's effect delta, and rack wet scales the
sum of band deltas. `confine_delta=true` applies the existing band confinement
to the delta; false intentionally allows spill. The dry source is never rebuilt
by merely adding crossover outputs. Empty chains/all-bypassed processing are
exact identity at the boundary, with original dtype/shape/sample bytes.

`display` is an ID-to-label map (128-character labels). Retune voice/segment and
Chordness template labels are also explicitly cosmetic. Monitoring-only solo,
A/B selection, meter/cache/UI state is **not** rack sonic data and is rejected
as an unknown field here; later runtime/session owners must keep it separate.
`automation` currently must be an empty array. Unsupported automation is an
error, not a ignored lane or a secretly static control.

## Processor parameters and resource admission

`processor_definition(type_id)` supplies defensive units, bounds and defaults.
Types are `zg.gain`, `zg.compression`, `zg.bitcrush`, `zg.spectral` and the
preservation-only `external.vst3`. Built-in payloads instantiate the original
specs; no competing compressor, retuner or router is implemented.

Gain is -36…24 dB, default 0. Compression retains threshold (-120…24 dBFS),
ratio (1…100), attack (0.01…5000 ms), release (0.01…10000 ms), knee (0…48 dB),
makeup (-36…36 dB), processor wet (0…1) and linked-peak detector. Bitcrush
retains depth (2…24 bits), hold (1…1024 samples), full scale (>0…32), processor
wet (0…1) and no dither. Their defaults are tested against the original typed
specs, including the separate internal wet parameters.

The spectral stage stores either null, the complete `SpectralRetuneRequest`,
or complete `ChordnessRequest`, including tuning/method version, schedules,
voices, templates, selection and coefficients. Null compression/bitcrush/
spectral parameters retain the old absent-stage interpretation. New authoring
bounds are explicit: at most 32 voices, 128 ratios/teeth, 64 retune changes and
32768 candidate teeth; retune degree ±4096, ratios <=1,000,000, segment sample
position <=192000*3600, correction/slew/hysteresis <=1,000,000 in their declared
units. Frequency limits must respect the saved Nyquist frequency. Out-of-bound
legacy requests fail adaptation rather than being clipped or partially saved.
Original Chordness mode/selection/bounds and coefficients are retained. No
bypassed-path exemption exists for NaN, infinity, invalid types or rate errors.

Limits apply together, not independently attainable maxima: 16 inserts per
band; 48000 serialized UTF-8 rack bytes; 8192 decoded bytes **each** for an
external component/controller state; 32 named rack presets; the existing 4096
Project revision/32 render-slot caps. A rack-bearing recipe must also fit the
Project's 65536-character recipe string and the complete Project must remain
within the strict portable JSON node/depth/string/<2 MB byte limits. Admission
occurs before changing the live head/preset inventory or allocating DSP/native
state. Failed edits leave the previous committed document intact.

## Legacy adapter: a permutation is not an arbitrary chain

`zaaggenz_spectral.rack_adapter` exports:

```python
saved = request_to_rack(old_band_selective_request, source_recipe)
old_again = rack_to_request(saved)  # strict, lossless stored-contract conversion
band = slot_to_band(old_slot, band='lowmid')
old_slot_again = band_to_slot(band, source_recipe)
```

An absent slot becomes an empty chain; a present slot becomes **all four**
legacy stage anchors, including null/identity stages, in its exact
`spectral/gain/compression/bitcrush` permutation. All 24 permutations round-trip.
Do not reinterpret a missing stage, extra insert, fractional outer mix or
bypass edit as a representable old `BandSlotSpec`; strict conversion rejects it.

`execution_request(saved)` is a separately named temporary legacy projection.
It maps fully disabled built-in processing to exact identity, or substitutes
an identity spec for an individually bypassed stage while retaining saved
parameters. It does not mutate the snapshot. Fractional active outer mixes and
arbitrary active chains require MBR-002; external slots require Phase B. These
cases fail clearly rather than being silently dropped. `insert_spec` returns
the existing processor spec for later runtime composition, not a new DSP engine.

## Working copies, presets and identity

```python
from zaaggenz_contracts.rack import empty_rack
from zaaggenz_project import Project, save_project, load_project

project = Project(accepted_source_recipe)
project.set_rack(empty_rack(project.head_recipe))
project.save_rack_preset('user.clean', 'Clean working rack')
save_project(project, 'working.zaag.json')
reopened = load_project('working.zaag.json')
reopened.apply_rack_preset('user.clean')
```

`set_rack` creates a new source-bound revision. A preset is portable data in
`rack_presets`, not a factory catalogue mutation; it records its own stable ID,
name, exact rack snapshot, snapshot/sonic hashes and retained source revision.
Replacing an existing preset needs `replace=True`. Renaming changes only the
preset name; editing the working rack cannot mutate its saved preset or source.

`source_binding.source_sha256` hashes the complete existing source envelope.
`origin_recipe_sha256` must resolve to an actual retained **no-rack ancestor**,
not merely a plausible digest. Applying a preset to a different source/rate/
channel context fails. A standalone rack-bearing Project root is rejected;
create the Project from the source first and commit its rack working copy.
The existing factory-source renderer checks are not relaxed. Changing factory
selection while a rack is still source-bound fails rather than rebinding it.

Distinct reset/recall operations:

* `reset_rack()` removes only processing; current source, SCULPT/graph and output
  settings stay intact. Saved presets and immutable history remain.
* `restore_source_and_rack()` restores the current rack's full no-rack origin;
  this is an explicit whole-source reset, not the processing-only action.
* `restore_source_and_rack(preset_id)` explicitly recalls a saved preset **with
  its original source**. `apply_rack_preset(preset_id)` never substitutes source.

`RackRecipe.sha256` is full saved identity; `sonic_sha256` excludes only the
explicit cosmetic labels. `Contract.sha256` remains unchanged as full recipe
identity. `Contract.sonic_sha256` preserves the exact historical value without
a rack and otherwise includes source+topology+master+rack sonic intent. Order,
IDs, bypass, wet, confinement, tuning/method, latent settings and opaque future
state identity are conservatively hashed. This is **intent identity**, not a
claim that two different settings cannot happen to produce identical PCM.
Monitoring-only A/B state is outside both rack identities. MBR-002 must use the
exact saved revision for cache/preview/export binding, even when a cosmetic
revision can share a sonic cache result.

## External extension boundary (not hosting)

An `external.vst3` insert v1 stores only `format=VST3`, `platform=windows-x64`,
32-uppercase-hex `class_id`, binary SHA-256, canonical base64 component/controller
state with verified byte hashes, and `execution_contract=preservation-only.v1`.
It contains **no library path, module import, shell command, trust grant or
native loader**. Round-trip is permitted without any host installed.
`processor_definition` explicitly reports `executable=False`. Both legacy
adapters reject external execution, even behind bypass; no implicit fallback
is sold as a plug-in run.

Phase B must supply trusted discovery, isolation, executable processor-version
adapters, larger state storage where required, saved component/controller
recall, latency/tail compensation and crash/hang bounds. Versioned processor
payloads and stable ordered instance records permit that extension without
changing a legacy four-stage permutation or losing saved identities. This
foundation claims neither VST2, real-time nor universal plug-in compatibility.

## Ownership, regression evidence and CI

Shared ownership for #239 was recorded on the issue before editing:
contracts-registry, session-format, band-DSP integration and narrow Compose
compilation forwarding. PR #237's draft preset/render-source work is neither
merged nor a dependency; the changed timeline/render hunks avoid its source
catalogue/audition integration. No canonical programme completion state or hard
dependency is rewritten by this local MBR follow-up.

The existing `zg021-band-selective.yml` workflow remains owned by `ZG-021` in
`programme/ci_reverse_dependencies.json`. It now runs `tests/rack` once per
existing bounded Ubuntu/Windows job and checks out the exact PR head. Native
triggers include contracts/project/melody/timeline dependencies, rack tests and
this contract. Existing source ownership patterns already cover every added
module (`ZG-002`, `ZG-003`, `ZG-008/009`, `ZG-017/018/019/021`); no duplicate MBR
workflow, private runner or speculative matrix is introduced. The existing
impact dispatcher continues to select only missing downstream runs.

Local evidence is reproduced by:

```sh
python -m unittest discover -s tests/rack -v
python -m unittest discover -s tests/project -v
# With the authenticated legacy app on PYTHONPATH:
python app/tests/source_preserve_smoke.py
python app/tests/spectral_sculpt_smoke.py
python app/tests/audio_headroom_smoke.py
```

The rack tests include all legacy permutations, actual gain/compression/
bitcrush/retune/Chordness numerical parity in mono/stereo, exact bypass,
source-binding/ancestry tamper, limits, hidden invalid state, label vs sonic
identity, portable save/reopen, factory golden identity and preservation of
SCULPT/graph/layer ownership during Compose contract compilation. GitHub CI
also retains the prior DSP/spectral/frozen 48 kHz acceptance and inherited
contracts/project/reverse-dependency suites. These component/contract checks
are not a replacement for MBR-004 browser acceptance or Phase-B native Windows
and packaged-host acceptance.
