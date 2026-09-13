# ZG-011 — directional modal grammar v1

This opt-in authoring layer expands a versioned, data-only grammar into the existing
`PhrasePlan` / source-derived `RenderRecipe`. It does not change `locked_bloom`, the
legacy UI, the source's nonlinear topology, or the frozen contract schemas. It is
not a culture-specific modal model, a chord recogniser or a listener-preference model.

## Create, save, reopen and render

From a materialized checkout with the repository's numerical/contract/job dependencies:

```console
python baseline/recovered_source/materialize_v2.py --out .
python -m zaaggenz_grammar create phrase.zggrammar.json --grammar step-return --events 32 --seed 42
python -m zaaggenz_grammar render phrase.zggrammar.json phrase.wav
```

The CLI starts with an unchanged copy of `locked_bloom`, apart from explicit sample
rate, tempo and one-shot settings. The default 32 half-beat events span four bars
at 4/4. Use `--events 128` for sixteen bars. `--grammar-file` accepts an edited
copy of either JSON file in `examples/grammars/`. Render jobs use the existing
bounded scheduler, immutable revision identity and cancellation checkpoints; Ctrl+C
requests cancellation. Output WAV is mono float32, with the recipe's declared
master policy, not an automatically level-matched audition.

Python consumers use `GrammarSpec`, `ExpansionRequest`, `expand_grammar`,
`make_grammar_recipe` and `submit_grammar_render`. Every field survives the authoring
wrapper. Expansion produces editable ordinary note/rest events; setting
`enabled=False` and supplying a manual `PhrasePlan` passes those events through
exactly, even when they lie outside the grammar's allowed degrees.

## Coordinates and rules

`period_degrees` must match the active tuning's degree count, not an assumed octave.
`degrees` gives sorted allowed relative-tonic degrees and positive integer hierarchy
weights. Register minimum/maximum are relative-tonic **degree indices**, inclusive.
The request's `tonic_degree` transposes the entire register and cadence. Thus the
same representation supports negative degrees and non-octave tunings. Register and
renderable source-shift range are different constraints: a grammatically valid
note can still exceed the source renderer's supported frequency/ratio range and
then fails explicitly rather than being clamped.

Ascending/descending steps count positions in the **allowed-pitch register**, not
semitones. Their integer weights multiply the destination hierarchy weight.
Each walk choice has a SHA-256-derived named random draw, so seeds do not depend on
Python's global PRNG or other tasks. The trace records requested and realised
direction, reflection, selected weight and total candidate weight. These are
engine selection quantities, not listener expectations.

A motif is a list of scale-index offsets from its entry note, beginning at zero.
An ornament must return to that entry. Pattern weights choose among eligible
whole patterns. Direction applies at pattern entry; the motif's internal contour
then takes precedence over the per-event direction cycle. Pattern IDs and positions
appear on every emitted pattern event. A cadence is an authored absolute
relative-tonic `return_path`, reserved before expansion, ending on a resting degree.
It deliberately overrides walking/direction/ornament rules: it is not a hidden
fallback transition. The initial event is always the tonic; the direction cycle
is indexed by the subsequent absolute event position, including rests.

Precedence is entry, scheduled rest, ornament, motif, directional walk, with the
reserved return path last. Rest/walk scheduling is evaluated at pattern boundaries;
an accepted pattern is atomic and not interrupted by a later scheduled rest.
If a whole requested motif fits in the remaining window but cannot fit the current
register/direction, expansion fails with its event index. A shorter remaining
window uses walk events rather than truncating the motif. Boundary `reflect` uses
the opposite directional rule only when the requested one has no legal transition;
`error` rejects that situation. Neither mode invents an unconstrained leap.

## Serialization and compatibility decision

`zaaggenz-modal-grammar` and `zaaggenz-grammar-recipe` have independent version
`1.0.0`. The `.zggrammar.json` authoring file contains the full grammar, request,
ordinary `zaaggenz-project` document and expansion hash. Loading validates project
revision hashes and **re-expands** the grammar; a different recipe, trace or request
cannot claim the old expansion identity. Unknown fields/versions and duplicate
JSON keys fail. Save uses an atomic replace.

No fields were added to frozen `RenderRecipe` or `Project` v1. Exporting only
`bundle.render_recipe` or `bundle.project` intentionally exports the **expanded**
notes, not the generator. Retain the `.zggrammar.json` wrapper to continue grammar
authoring. This explicit adapter avoids a silent shared-format migration. Future
timeline integration may expose these authoring controls without changing this
boundary; this issue does not claim a new graphical timeline or coordinated
persistent BODY/AUX/SUB rendering (ZG-009/ZG-029).

Expansion is bounded to 2,048 events, 64 motifs, 32 offsets per motif and a 513-degree
register. Serialization also respects the inherited JSON bounds: 2 MB total,
100,000 nodes, depth 32 and 65,536 characters per string, including each embedded
project recipe snapshot. The wrapper rejects oversize projects **at construction**,
not after saving an unreadable file. The supported four-/sixteen-bar examples fit;
2,048-event expansion does not promise that every such phrase fits the authoring
wrapper. Long dense history needs a future explicit project-format evolution.

The render admission estimate includes output arrays, source/pitch-shift workspace
and margin, and uses the scheduler's existing memory limits. It is a conservative
estimate, not an operating-system memory guarantee. Source and timing limits remain
those of ZG-007/ZG-008. No mandatory GPU, network, trained model or microphone is used.

## Starter grammars and evidence

`step-return` and `skip-return` share the five allowed degrees and hierarchy but
have different ascending/descending preferences and return paths. They carry
original synthetic provenance and CC0 fixture-data metadata. `source-reviewed`
metadata on a custom grammar is the author's provenance declaration, not an
automatic authenticity certification by this software.

```console
python -m unittest discover -s tests/grammar -v
python tools/grammar_fixture_report.py --out grammar-fixtures-48k.json --audio-dir grammar-listening-48k --sample-rate 48000
python tools/check_contracts.py --baseline --report contracts-check.json
```

The fixture report produces two four-bar contrasts and one sixteen-bar example
with rests/ornaments. It saves exact authoring recipes, per-event traces, raw PCM
hashes and matched WAV hashes. Matching uses one playback-only whole-file RMS gain
per example and a common peak ceiling; it is **not** a perceptual-loudness or
true-peak guarantee. Gains never rewrite the source recipe. CI uploads these
original generated-source WAVs on Windows and Linux. Tests distinguish reduced-rate
render checks from this 48 kHz evidence. Numerical repeatability and distinct
contours are demonstrated; owner listening approval and cultural/perceptual claims
are not inferred. No default sound is replaced.
