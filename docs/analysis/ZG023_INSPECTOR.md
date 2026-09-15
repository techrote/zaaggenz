# ZG-023 harmonic-comb / transformation inspector

ZG-023 adds an optional Research workspace for auditing spectral transformations. It does not replace Compose/timeline workflows and it does not let analysis silently alter the working sound.

## Workspace boundary and production source binding

Run `python -m zaaggenz_inspector` after materialising the authenticated recovered runtime. The loopback-only standalone server exposes both `/timeline` and `/inspector` on one origin so a completed timeline render can be bound without copying mutable browser audio. The standalone wrapper remains a narrow development/research surface; the unified product runtime tracked by #95 will consume the same binding contract rather than invent a second one.

Production Inspector state starts **unbound**. A source becomes inspectable only through `POST /api/inspector/bind` with the job ID of a completed render owned by that server's `TimelineService`. The server takes the completed `RenderArtifact` directly from the scheduler and binds its immutable `audio_bytes` and validated `AudioAssetRef`; it does not reconstruct a recipe, rerender, upload arbitrary arrays, or trust browser-declared hashes. The route uses the same loopback Host/Origin and session-token protections as timeline rendering.

A production binding is accepted only for finite mono `pcm-f32le-interleaved-v1` audio with a valid content identity and at least 64 frames. Inspector A uses the artifact's exact `revision_id`, content SHA-256, sample rate and frame count. Binding records the artifact's recipe SHA-256, cache key, product and PCM identity in `source_binding`; each subsequent Inspector snapshot copies that binding into Expert metadata. The A playback WAV is encoded from the exact immutable bound PCM, so decoded float32 PCM hashes to the `AudioAssetRef.content_sha256`.

The synthetic harmonic fixture is no longer an implicit production source. It is available only by an explicit `InspectorService(..., demo_fixture=True)`, `bind_demo_fixture(...)`, or CLI `--demo-fixture` choice for deterministic tests/evidence.

## Snapshot identity and stale-result policy

Every `InspectorSnapshot` binds two immutable slot identities:

- **A / Before** — source PCM hash, sample rate, frame count and source revision ID;
- **B / After** — transformed PCM hash and a revision derived from the A revision plus the complete transform request.

For a bound production artifact, A's revision is the render artifact revision itself rather than a second Inspector-derived identity. Snapshot Expert metadata carries the immutable source-binding record containing revision, recipe/cache/content identity and sample rate.

Async analysis captures A's revision, sample rate and source-binding record when submitted. Completion publishes only when the current A revision still matches that captured revision. If A is rebound while analysis is queued or running, the old B/snapshot are cleared immediately and the old job is reported as stale; its result cannot repopulate B. This is a hard server-side rule, not merely a UI warning. A source rebind also clears working apply history/frozen state so identities from different sources cannot be silently combined.

A snapshot carries its own canonical SHA-256 identity over method, A/B identities, controls, stage order, combs, component decisions, remainder, compatibility, uncertainty, diagnostics and expert disclosure. For production-bound sources that identity therefore also commits to the render-artifact provenance copied into Expert metadata.

## What is visualised

The accepted ZG-018 hybrid Chordness fixture is adapted without introducing a second spectral engine. The shared timeline exposes:

- selected target comb teeth;
- tracked source components and their confidence;
- **requested**, **estimated/source** and **realised** frequency as distinct fields;
- per-frame retune cents and gain motion;
- moved, unaffected and uncertain classifications;
- reason/assignment metadata and target comb ownership;
- residual/remainder RMS through time;
- a ZG-020 timbre-interaction interval compatibility curve;
- exact transformation stage order and method versions.

Confidence masking is presentation only. Raising the visual threshold never changes the underlying transform or relabels uncertainty as certainty.

## Musical controls versus expert disclosure

The compact surface keeps four musical controls visible:

- amount;
- tuning/root frequency;
- sonority interval family;
- anchor policy.

The full Chordness request, assignment bounds, objective terms, candidate evaluations, occupancy, descriptor snapshots, method versions, source binding and state policy live under Expert disclosure. Acoustic/objective values are descriptive engineering evidence rather than preference or pleasure scores.

## Linked A/B transport and compensation

A and B use one linked transport. A is available as soon as an immutable artifact is bound; B remains unavailable until an explicit Analyze completes for that exact A revision. Switching slots preserves the current transport position where possible. B can be RMS-compensated explicitly; the compensation gain is reported, and it is peak-limited when exact RMS matching would exceed 0.98 full scale. The original B artifact is never rewritten.

Keyboard operation remains available outside form controls:

- `1` / `2`: select A / B when present;
- Space: play/pause;
- Left / Right: scrub one second.

## Freeze / apply / undo

Binding, analysis and application are separate operations.

- **Bind** changes A to one completed immutable render artifact and clears any B/working history tied to a different source.
- **Analyze** computes B through the bounded analysis scheduler and publishes only if A still has the captured revision.
- **Freeze view** stores the current snapshot identity for comparison with later analyses of the same source. It does not alter audio.
- **Apply explicitly** is the only operation that moves the inspector's working-sound pointer to B. Applying is refused when the snapshot's source revision differs from current A.
- **Undo apply** restores the previous working identity from history.

Binding never auto-applies or silently transforms audio. Analysis reruns, confidence changes, zooming and A/B listening also never auto-apply.

## Fixture and acceptance evidence

The deterministic fixture synthesises a two-root harmonic source plus one inharmonic component and a short transient, runs accepted component analysis and ZG-018 hybrid Chordness, and builds the ZG-020 compatibility map. It is explicitly synthetic test material only.

`tools/inspector_fixture_report.py` opts into that fixture and records slot hashes, snapshot identity, stage order, counts, controls, diagnostics and compensation policy. `tests/inspector/test_inspector.py` additionally renders a nontrivial timeline through `TimelineService`, binds the resulting `RenderArtifact`, verifies decoded A-slot PCM against the artifact content hash, verifies revision/recipe/cache provenance in the published snapshot, checks exact minimum-frame and mono/finite boundaries, and forces an artifact rebind while analysis is in flight to prove stale publication cannot occur. HTTP tests verify the bind route is token-gated and rejects unknown/non-artifact jobs.

`tests/inspector/browser.py` drives real Chromium against the same-origin timeline/Inspector server: it renders a nontrivial Compose document, binds that exact completed artifact, visibly verifies revision/recipe/cache/content identity, explicitly runs Analyze, exercises A/B switching, compensation, zoom, confidence masking, freeze/apply/undo, normal reruns, then rebinds during an in-flight analysis and verifies stale-result rejection.

The dedicated workflow runs those checks on Windows and Ubuntu, including timeline regressions, and retains browser screenshots/reports. A 48 kHz evidence job keeps the explicit synthetic fixture as deterministic method evidence only; it is not evidence of production source binding.
