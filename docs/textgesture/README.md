# ZG-031 — safe project-local text / syllable gesture language

ZG-031 turns informal mnemonic strings such as `bu budu budubu` into **explicit editable musical data** without claiming that any syllable has a universal acoustic, phonetic or emotional meaning. A project-local dictionary defines the mapping. The same token can intentionally mean something different in another dictionary.

There is no `eval`, expression interpreter, shell expansion, plugin callback or speech-recognition dependency. The parser accepts only the notation documented here and reports exact line/column positions for invalid or ambiguous input.

## Notation

A text gesture is a sequence of lowercase mnemonic tokens, optional bracket modifiers, optional holds, group separators, and one required terminal `@return` marker.

```text
bu[d=1/2,a=2,p=1,b=0.6] ~1/4 |
budu[n=4,c=25] @return[d=1/2]
```

`|` starts a new phrase group. `~1/4` extends the preceding event by exactly one quarter-note beat. `@return` compiles from the dictionary's explicit `return_mapping`, must be terminal, and becomes the ZG-027 landing event.

Modifiers are deliberately small and typed:

| Key | Unit | Meaning |
|---|---|---|
| `d` | quarter-note beats | event duration override, decimal or rational |
| `a` | dB | additive accent relative to dictionary entry |
| `p` | scale degrees | additive pitch offset relative to dictionary entry |
| `c` | cents | additive detune relative to dictionary entry |
| `b` | 0–1 | spectral opening / brightness fraction |
| `r` | 0–1 | roughness fraction |
| `o` | 0–1 | spectral occupancy fraction |
| `w` | 0–1 | spectral width fraction |
| `n` | events/beat | integer source-derived roll density, 1–16 |

Durations are canonicalised to reduced rationals on a grid no finer than 1/960 beat. Exponent notation, arbitrary identifiers, quoting, semicolons, backticks, `$()` and unknown modifier keys are not part of the language. A syntax failure includes its original source offset, line and column.

`format_text(parse_text(text))` gives a canonical textual form. `semantic_ast()` strips only source spans; groups, timing, units, modifiers, holds and the return marker remain. Thus canonical text can round-trip without making source-position formatting part of musical identity.

## Project-local dictionaries

A `zaaggenz-text-dictionary` stores:

- explicit base degree and base gain;
- a project brightness range in Hz;
- one return mapping;
- 1–128 mnemonic entries;
- for each entry: duration, accent, degree/cents offset, brightness, roughness, occupancy, width and density.

`DictionaryRegistry` stores 1–32 complete dictionaries as ordinary JSON data. `starter_registry()` contains `local-soft` and `local-bright`. Both define `bu`, `budu`, `budubu` and `ta`, but intentionally map them differently. These names are synthetic user mnemonics, not speech or cultural models.

The registry is embedded in `TextGestureBundle` together with the retained base ZG-009 project. This attaches mnemonic semantics to the project authoring record rather than a process-global dictionary. Mutating a copy of one dictionary cannot change another project or registry snapshot.

## Preview before apply

```python
from zaaggenz_textgesture import starter_registry, compile_text

registry = starter_registry()
compiled = compile_text(
    "bu ~1/4 | budu[n=4] @return[d=1/2]",
    registry,
    "local-soft",
)
preview = compiled.preview
```

The preview explicitly contains the active `TuningSpec`, tuning ID, base degree/frequency, protected source ID/frequency, modifier units, groups, every resolved event/target frequency, original source span, the full structured ZG-027 gesture, PhrasePlan identity and the future timeline revision. `apply_state` is `preview-only; export/apply is explicit`.

Unknown tokens and renderer-range violations report against the originating text span. The source-derived renderer's current 15–240 Hz and 0.25–4× source-ratio limits are checked before an audio recipe is constructed.

## Explicit apply / export

`compile_text()` returns three derived but still editable surfaces:

1. `gesture` — a valid ZG-027 `DirectionalGesture` containing all eight directional axes and exact landing/turn landmarks;
2. `phrase` — an ordinary source-preserving ZG-008 PhrasePlan with per-event density gestures where requested;
3. `timeline` — an accepted ZG-009 TimelineDocument with one clip per `|` group, ordinary editable note/roll objects, and the entire retained legacy Project unchanged.

Applying text therefore means explicitly choosing one of these data products. Nothing in parsing or preview mutates the Compose project.

`TextGestureBundle` persists raw text, complete registry, retained base project and all derived identities. Reopening a bundle **reparses and recompiles** the source and rejects mismatched AST, gesture, phrase hash, timeline, preview or compilation hash. Cached derived state is never trusted by itself.

A structured gesture remains useful after text is discarded. For example, `edit_landing()` or `replace_trajectory_points()` from ZG-027 can modify the compiled gesture, and `compile_gesture_recipe()` can render that edited structure normally. Text is an optional authoring front end, not a permanent playback dependency.

## Gesture projection and evidence boundary

Pitch modifiers are resolved through the active tuning, not assumed 12-TET. The preview converts realised pitch to the ZG-027 relative-cents contour; inputs outside that issue's ±1200-cent gesture representation fail explicitly instead of being clipped. Non-octave tunings remain valid when the realised contour fits that bound.

Brightness fraction is mapped through the selected dictionary's explicit closed/open Hz range. Roughness, spectral occupancy and width remain the same typed ZG-027 deferred automation axes: the current source-preserving renderer does not silently apply them or alter protected nonlinear topology.

`make_render_recipe()` renders the compiled PhrasePlan with the retained protected source and final project master semantics. No cloud, microphone, model training or speech analysis is used.

## Verification

```console
python -m unittest discover -s tests/textgesture -v
python -m unittest discover -s tests/gesture -v
python -m unittest discover -s tests/tuning -v
python -m unittest discover -s tests/timeline -v
python tools/textgesture_fixture_report.py --out textgesture-fixtures-48k.json --artifact-dir textgesture-evidence-48k --sample-rate 48000
```

The full-rate fixture set compares the **same exact text** under `local-soft` versus `local-bright`, plus an explicit modifier edit under the soft dictionary. It exports self-verifying bundles, previews, structured gestures, editable timelines and level-matched WAVs. This demonstrates dictionary-local meaning and offline rendering; it does not establish universal syllable acoustics, speech recognition, preference or owner listening approval.
