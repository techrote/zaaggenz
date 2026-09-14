# ZG-023 harmonic-comb / transformation inspector

ZG-023 adds an optional Research workspace for auditing spectral transformations. It does not replace Compose/timeline workflows and it does not let analysis silently alter the working sound.

## Workspace boundary

Run `python -m zaaggenz_inspector` after materialising the authenticated recovered runtime. The loopback-only server exposes `/inspector`; `/` remains the recovered instrument UI. The inspector uses the same Earth/Neutral visual vocabulary as the existing timeline while keeping the research dashboard separate from ordinary composition.

## Snapshot identity and stale-result policy

Every `InspectorSnapshot` binds two immutable slot identities:

- **A / Before** — source PCM hash, sample rate, frame count and source revision ID;
- **B / After** — transformed PCM hash and a revision derived from the A revision plus the complete transform request.

Async analysis captures A's revision when submitted. Completion publishes only when the current A revision still matches that captured revision. If A changes while analysis is pending, the job is reported as stale and B/current snapshot are not replaced. This is a hard server-side rule, not merely a UI warning.

A snapshot carries its own canonical SHA-256 identity over method, A/B identities, controls, stage order, combs, component decisions, remainder, compatibility, uncertainty, diagnostics and expert disclosure.

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

The full Chordness request, assignment bounds, objective terms, candidate evaluations, occupancy, descriptor snapshots, method versions and state policy live under Expert disclosure. Acoustic/objective values are descriptive engineering evidence rather than preference or pleasure scores.

## Linked A/B transport and compensation

A and B use one linked transport. Switching slots preserves the current transport position where possible. B can be RMS-compensated explicitly; the compensation gain is reported, and it is peak-limited when exact RMS matching would exceed 0.98 full scale. The original B artifact is never rewritten.

Keyboard operation remains available outside form controls:

- `1` / `2`: select A / B;
- Space: play/pause;
- Left / Right: scrub one second.

## Freeze / apply / undo

Analysis and application are separate operations.

- **Freeze view** stores the current snapshot identity for comparison with later analyses. It does not alter audio.
- **Apply explicitly** is the only operation that moves the inspector's working-sound pointer to B. Applying is refused when the snapshot's source revision differs from current A.
- **Undo apply** restores the previous working identity from history.

The initial analysis, reruns, confidence changes, zooming and A/B listening never auto-apply.

## Fixture and acceptance evidence

The deterministic fixture synthesises a two-root harmonic source plus one inharmonic component and a short transient, runs accepted component analysis and ZG-018 hybrid Chordness, and builds the ZG-020 compatibility map. It is synthetic test material only.

`tools/inspector_fixture_report.py` records slot hashes, snapshot identity, stage order, counts, controls, diagnostics and compensation policy. `tests/inspector/test_inspector.py` covers typed snapshot content, explicit apply/undo, frozen snapshot persistence, compensated audio, loopback/CSRF boundaries and a forced stale-job race. `tests/inspector/browser.py` drives real Chromium through A/B switching, compensation, zoom, confidence masking, freeze/apply/undo, normal reruns and stale-result rejection.

The dedicated workflow runs those checks on Windows and Ubuntu and retains browser screenshots/reports. A 48 kHz evidence job verifies the same snapshot/policy at production sample rate.
