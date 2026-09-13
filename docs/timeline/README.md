# ZG-009 — practical note and clip timeline

An opt-in browser composition view alongside the recovered instrument. It adds
editable source-preserving notes, rests, rolls, exact snap grids, undo/redo, named
phrase regions, save/reopen, asynchronous rendering and revision-safe comparisons.
No recovered source payload or frozen contract schema is changed.

## Launch and compose

```console
python baseline/recovered_source/materialize_v2.py --out .
python -m pip install numpy==2.3.5 scipy==1.17.0 -r requirements-contracts.txt -r requirements-jobs.txt
python -m zaaggenz_timeline --open
```

The launcher binds only `127.0.0.1`, default port 8765. Choose another port with
`--port`. The `/timeline` view has an **Open full instrument** link; the unchanged
legacy page has a link back. No browser automation package is needed at runtime.

Use **Add event**, then select a note and change onset, duration, degree, detune,
gain, mute or roll density. **Apply edit** moves/resizes/updates it. Horizontal
mouse dragging moves; Shift-drag resizes. Double-clicking empty timeline space
adds at the snapped position using the event editor's other fields. Duplicate
puts a copy immediately after the selected object. Muting retains authored pitch
and settings rather than destroying them. Rests are explicit no-pitch objects.

Snap values are quarter-note beats. Fractions such as `1/3` are exact; decimal
input is reduced to a rational before snapping. Nearest-grid ties round upward.
Keyboard undo/redo and deletion are scoped away from text inputs. History is
bounded to 64 snapshots; event identity counters are part of each snapshot,
making duplication after undo deterministic. New edits discard the redo branch.

Four-/sixteen-bar example buttons create editable phrases with rests and
source-derived roll slices; they are original generated examples, not reference
recordings. Save downloads `.zgtimeline.json`; Reopen uses a file picker. Manual
editing of project JSON is not needed. Source frequency, active tuning and the
selected event's computed target frequency are displayed separately.

## Clips, render regions and named outputs

A clip is a named `[start,end)` phrase region, not an independent DSP container.
Overlaps are allowed. Clip duplication copies only completely contained events
and appends the region; extend the phrase first when needed. Notes crossing a
clip boundary are not partially duplicated. The precise operation is deliberate,
not a DAW-style hidden split or note crop.

Full and region renders use the existing bounded asynchronous scheduler. A region
is extracted **after full-phrase rendering**, preserving events/tails crossing its
start. Its compute/memory admission is therefore based on the full phrase. Region
bounds and sample offset are included with waveform/event metadata. Event onsets
can be negative in a cropped scope when they started before the selection.

Every result contains the authoring revision, compiled RenderRecipe hash, PCM hash,
region and scopes. Audio/scopes publish together through the existing RenderTransport
stale-result gate. Edits, stop and replacement render requests invalidate pending
publication. An output can be played only under its matching editing revision.
Selecting an older named output explicitly restores that saved revision; Undo can
return to the more recent edits. Up to eight output blobs remain in the browser tab.
The server retains at most sixteen scheduler history records and has bounded queues.

Saved projects contain editing state, not transient audio blobs or undo stacks.
Re-rendering reopens the same recipe and is tested for sample identity in the same
environment. Generated reports record platform-specific PCM/WAV hashes; no new
cross-platform bit-identical DSP claim is made. Playback is user-initiated, with
native controls, scrubbing, stop, a waveform and WAV download. No claim of perceptual
quality or owner listening approval follows from numerical/browser tests.

## Ownership and compatibility boundary

The timeline wrapper retains the **entire existing Project document**, including
SYNTHLINE/exciter/BODY/AUX/SUB arrangement, reversebass and SCULPT parameters. A fixed
ownership map makes the boundary explicit. Default source is a copy of the recovered
`locked_bloom`; one-shot/tempo/sample-rate settings are explicit. The stored legacy
project is never silently rewritten when notes are edited.

The new timeline render is an explicitly declared **SYNTHLINE + source-sliced exciter
melody branch**. It does not claim to coordinate/render persistent BODY/AUX/SUB or
SCULPT across its note timeline. Those settings remain available in the retained
project and the full instrument's existing workflow; timeline-driven coordination
belongs to ZG-029. This limitation is displayed in the UI, not hidden in release
notes. Frozen RenderRecipe/Project v1 stay untouched: `.zgtimeline.json` is a separate
versioned authoring wrapper, and compilation produces an ordinary melody recipe.

## Bounds and local trust

Maximum 256 note/rest objects, 128 roll gestures, 128 named clips, 60 seconds per
render and the existing scheduler's 256 MiB per-job admission limit. An estimate
is conservative admission metadata, not an operating-system RSS guarantee.
Maximum roll density is 16 events/beat and 64 retriggers per object; longer rolls
must be split rather than silently truncated. Renderable target pitches are 15–240 Hz
and source ratios 0.25–4, inherited from ZG-008. Pitch limits are not scale limits.
Master gain is explicit dB and applied once by the existing output policy.

The wrapper uses existing bounded strict JSON and project-hash validation. HTTP
requests are bounded to 2 MB. New timeline mutations require the local session token;
Host/Origin checks reject foreign origins and DNS-rebinding hostnames. Static timeline
routes are allowlisted; no API takes a filesystem path from the browser. This is a
single-user loopback development launcher, not a hardened public web deployment.
The legacy application remains a local tool and its endpoint semantics are not
silently redesigned by this issue.

## Verification

```console
python -m unittest discover -s tests/timeline -v
node tests/timeline/editor.mjs
node tests/jobs/browser_transport.mjs
python -m pip install playwright==1.57.0
python -m playwright install chromium
python tests/timeline/browser.py --out timeline-browser-48k --sample-rate 48000
```

Browser verification uses actual Chromium interactions, the real loopback server
and numerical renderer, including editing/dragging, duplication, undo/redo,
save/reopen downloads/uploads, four-/sixteen-bar 48 kHz rendering, native playback,
region PCM equivalence and an edit while a real job is pending. It writes original
WAVs, saved projects, hashes, scopes and a screenshot. CI runs on Windows and Linux;
the independent legacy/contract workflow must also pass before merge.

Automation references: Playwright's official Python documentation for
[downloads](https://playwright.dev/python/docs/downloads),
[input actions](https://playwright.dev/python/docs/input) and
[browser launch](https://playwright.dev/python/docs/api/class-browsertype).
Playwright is development-only and is not added to runtime dependencies.
