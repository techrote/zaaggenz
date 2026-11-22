# NYQ consolidated owner-evaluation candidate — 22 November 2026

**State: DRAFT/HOLD. DO NOT MERGE or promote NYQ-003/#252, NYQ-004/#253, MBR-004/#242 or NYQ-007/008/009.**

## Frozen basis and source custody

- Accepted main: `d7e580c190d00e1d00a573a6b845c75ddddc1d4c`.
- Safe production/listener base: PR #320 exact `e4d7a6ed1a6accd1b7379d03528fb575e708a455`; its branch was originally stacked on #319's earlier head, not #319's later conflicting version.
- #320's Linux `renameat2(RENAME_NOREPLACE)` / Windows destination-rejecting rename is retained. **Never transplant** #319's later `mkdir` + `Path.rename` or speculative cleanup of another owner's empty directory.
- Original #319 staged export and independent verifier failure/cleanup tests were present in #320; a bounded final-publication error/retry test was added without weakening the no-replace primitive.
- PR #312's failure-only screenshot/JSON diagnostic was ported onto #309's *text_content()* Chromium revision fix; never weaken the assertion or retry on failure.
- Recovered exact untouched Git donor blobs are pinned by `NYQ_RECONCILIATION_DONORS_20261122.json` and checked by `test_nyq_reconciliation_donors.py`. 57 files: **38** NYQ-004 author paths (#267), **3** unique Chromium testing paths (#290/#293), and **16** opt-in NYQ postprocessing source/test paths (#300–#306 and corrected #308).
- Five #267 touched files were already in the main-based assembly and were deliberately NOT overwritten. The accepted original six ZG-022 presets, rack defaults, private recording exclusions, and programme acceptance authority are unchanged.

## Executable scope, explicitly limited

Ordinary Compose / editable rack are inherited from main. The current user-facing NYQ path is **opt-in post-Compose full-mix** saved-project -> verified 48-kHz WAV/DAW kit -> offline Web Audio listener. This is NOT a native NYQ graph insert, in-rack module, approved dynamic physical sampling clock, or normal final master export.

NYQ-004 modules recovered from #267 are preserved with their own proof and contract tests but not wired into the default UI or declared a finished #253 programme gate. Optional A/B bounce, parallel wet, phrase comp, wet automation, selective stereo wet, rate morph, dual-rate stereo and one-shot stereo export likewise remain experimental.

## Required CI on the exact new head

1. Ubuntu and Windows: full ZG-041 runtime/Compose tests; source-exact 57-path donor identity; focused recovered NYQ-004 contracts and numerical DSP tests.
2. Native original-host Chromium on BOTH hosts: full source-verified kit, actual UI-saved-project kit and one-command 256/512-Hz listener, plus **restored #290 sweep ZIP/index test and #293 single-page multirate comparison test**.
3. ZG-002 legacy, ZG-023 inspector, ZG-024a inverse, ZG-000 direct/reverse and ZG-045 packaging/environment on final head as relevant. An absent workflow is NOT a pass.
4. For all original failures, retain and investigate logs; no test assertion relaxation or cherry-pick of already-failed evidence.
5. Independently compare chosen exact assembled head's protected original donor blobs and full source/audition workflow before merge deliberation.

## Physical owner Windows evaluation (never count hosted CI as physical acceptance)

```powershell
git fetch origin integration/nyq-reconciled-source-exact-20261122
git switch -c nyq-reconciled-owner origin/integration/nyq-reconciled-source-exact-20261122
git rev-parse HEAD
.\0setup.bat
.\1run.bat
```

In Compose: inspect six themes and the dense square UI; edit a normal musical phrase, render/play/A-B, modify and reorder rack stages, save project to `.zgtimeline.json`, restart/reopen and verify output/PCM. For the opt-in NYQ kit:

```powershell
.\.venv\Scripts\python.exe tools\nyq_listen_saved_compose.py "C:\path\to\song.zgtimeline.json"
```

Confirm original/256/512-Hz WAVs, playback, A/B, seek/pause/download and the independently source-bound receipt. No private reference audio is needed.

## Outside this candidate

- MBR-004 #242 physical installed-wheel Gate A and cross-host spectral Gate B are separate dependencies (#272/#274 are tools only).
- Krach #236/#237, ZG-000 dispatcher #271 and VST3 #243+ remain separate workstreams.
- #276 is a parallel WAV delivery candidate, not substituted for selected #277.
- #266/#267 old-base PRs and all older NYQ assemblies remain frozen source/evidence records until formal reconciliation; no PR is to be closed merely for being green.
- Only an independent reviewer of the **exact final combined head** can deliver merge-readiness; this implementation's own source checks and CI are not independent approval.
