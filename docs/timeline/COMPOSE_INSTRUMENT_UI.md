# Compose instrument UI

Owner-requested UI correction, 10 November 2026. Compose (`/timeline`) follows the authenticated main synth (`/`) appearance before another physical Windows acceptance attempt.

## Appearance and workflow

- Use the main instrument's Consolas/Cascadia Mono typography, square borders, compact controls and dense panel spacing.
- Preserve the exact Earth / Neutral, Phosphor, Amber CRT, Ice / Steel, Plum / Ash and Mono palette definitions and custom accent/background expansion. Both interfaces use `uptempo-ui-theme-v12`; Compose observes changes from another tab. The authenticated recovered instrument files remain the reference.
- Keep render, Render & play, Play/Pause, Stop, WAV export and status visible while the editing pane scrolls. A separate monitor pane holds the waveform, square scrub bar/timecodes, output history, raw/processed A/B, band audition and measurements.
- A successful spectral add opens its target controls. Rack edits show an immediate local pending state, preserve queued command ordering and display failures beside the rack as well as in the permanent status bar. The editing proposal can redraw before final adoption; saving/rendering still waits for the final authoritative validated revision.
- Render & play uses the same numerical job and processed output as Render full phrase. Browser autoplay restrictions fall back to an explicit Play instruction. Hear dry/processed/band starts the selected monitor. Stop rewinds playback and retains the processed download; editing still invalidates stale output.
- The one-bar example replaces the phrase explicitly and is undoable. It uses the existing example melody and source rather than a new sound preset.

## Spectral limit

The existing default 48-kHz, sixteen-beat phrase exceeds the 256-MiB full-context spectral rack bound. A failed Add spectral must show the rejection and a useful next step. The one-bar example is an available short starting point. Rendering a selected region still requires the whole phrase context. This UI change does not increase the memory bound or silently shorten a saved phrase.

## Validation

`tests/timeline/browser_ui.py --out compose-ui-48k` exercises the actual unified runtime at 48 kHz. It compares all six palettes to the main synth, reloads the saved theme, checks visible transport and overflow at desktop/narrow widths, reproduces the spectral rejection, adds spectral through the one-bar example, auditions and downloads the real processed WAV, and verifies save/reopen PCM identity. It produces screenshots and a JSON receipt. The ZG-009 Linux/Windows workflow runs it alongside the existing complete timeline browser regression.

Existing timeline, rack, runtime, editor and stale-transport checks remain required. Numerical checks are not listening acceptance. Physical Windows Gate A and spectral portability Gate B under #242 remain separate owner/integration decisions.

## Editing responsiveness

Two redundant backend computations were removed: source-preset identification reuses an already validated recipe, and rack compilation no longer constructs a discarded no-rack melodic recipe. No cache, session authority, admission threshold or validation ticket changed. Three warmed local samples per identical 48-kHz fixture measured proposal-plus-validation medians of 1.2651 to 1.1265 seconds (5 revisions), 1.9337 to 1.6916 seconds (8), and 2.7947 to 2.3884 seconds (12). Complete proposal and validation response hashes matched before/after. These local measurements do not establish a Windows latency guarantee; longer histories can still be perceptibly slow.
