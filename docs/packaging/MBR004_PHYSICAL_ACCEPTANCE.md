# MBR-004 — Physical Windows installed-wheel acceptance

**Status: physical operator execution pending; NOT admission.** This is Gate A for issue #242. Gate B is the separate cross-host spectral-portability qualification. #241 / PR #270 is already accepted and merged.

## Environment

Use an actual Windows 11 x64 machine, Python 3.13 x64, Git, a browser and authorized local dependency installation. No VST, private recordings, cloud service, or Research workspace. Read [#242 instructions](https://github.com/techrote/zaaggenz/issues/242#issuecomment-6744182004) and [environment policy](ENVIRONMENT.md).

The operator harness resides on this isolated Draft branch but builds the application from the immutable accepted-main commit **d7e580c190d00e1d00a573a6b845c75ddddc1d4c**. A detached temporary source worktree is materialized and built; a separate virtual environment outside the checkout installs that wheel under the accepted constraints. It verifies the built artifact and installs no VST. The harness records its own branch HEAD separately.

## Run one command

From a checkout of this Draft harness branch, in native Windows PowerShell at the repo root:

~~~powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\zg242_physical_acceptance.ps1
~~~

The script is interactive and creates a fresh temporary evidence directory under %TEMP% for every run, without overwriting earlier evidence. Type **INSTALL-APPROVED** only after approving pinned dependency installation. The application opens as ordinary Compose in a separate PowerShell window, with a browser at http://127.0.0.1:18765/timeline. If port 18765 is occupied, first stop your own existing service; the harness does not kill unrelated processes. Save every output file and screenshot to the printed evidence directory.

**First session:** Select an accepted factory source such as locked_bloom as a *working copy*. Create a bounded musical phrase. Enable four-band rack, set upper-band spectral tuning/retune and compression, reorder these noncommuting stages, exercise insert/band/global bypass and A/B, preview, and test rapid edit/cancel without stale render publication. Save **both** a project and a separately named rack preset. Export the exact 48-kHz processed phrase as **before.wav**, dry no-rack counterpart as **dry.wav**, and all-bypassed counterpart as **bypass.wav**, keeping source and extent identical. Capture a PNG/JPEG screenshot showing source and controls. Type **FIRST-WORKFLOW-DONE** after this actual GUI work; provide the paths when prompted. The verifier snapshots all first-session evidence and checks exact dry/bypass PCM identity.

In the separate Python runtime PowerShell window, press **Ctrl+C** to stop the server normally; then close that console. Type **CTRL-C-STOPPED** in the controlling console. A nonzero exit, missing transcript, or live process blocks evidence. Do not claim closing a window or killing the process via Task Manager was graceful.

**Second session:** The script launches a new process from the same installed wheel. Reopen project and rack preset from disk; verify source identity, controls, stages, bypass, preview. Export **after.wav** with exactly the same recipe and extent as before.wav. Capture second screenshot. Type **SECOND-WORKFLOW-DONE** and perform another Ctrl+C stop.

## Evidence integrity

The standalone Python verifier enforces:

- Nonempty evidence files up to 256 MiB; PNG/JPEG file signatures for screenshots.
- 48-kHz IEEE float32 WAV, finite mono/stereo decoded PCM, positive frame counts and matching shapes; unsupported formats are not silently converted.
- Exact decoded PCM identity of dry versus full bypass and before versus cold-reopen after. On differences it reports RMS/peak and fails, without adjusting tolerances or normalizing samples.
- SHA-256 of project, rack preset, wheel and initial WAVs, captured before first shutdown and rechecked after reopening.
- Two separate loopback HTTP startup checks, process exit status zero, console transcript hashes and explicit operator attestations. Operator testimony is recorded as testimony: screenshot hashes and flags are not proof of automated UI interaction.

The output is **receipt-shareable.json** (no local absolute paths or tokens), containing pinned source/harness SHA, wheel SHA, Windows/Python/package versions, frontend/backend release fingerprints, artifact basenames/hashes, PCM stats and session evidence. The original WAVs, screenshots, saved project/preset files and private transcripts stay in the local evidence directory; nothing uploads automatically. Review private files for sensitive data before sharing.

On failure, the harness preserves the first error in **first-failure.txt** and local evidence, and removes only its temporary source worktree. Running it again creates a new evidence directory.

## Qualification boundary and handoff

Synthetic verifier regression, runnable with Python 3.13 / declared dependencies:

~~~text
python -m unittest discover -s tests/packaging -p test_zg242_receipt.py -v
~~~

These tests cover good/invalid receipts, WAV format/rate, screenshots, bypass, reopened PCM, saved-file hashes and false process attestations. They do **not** qualify the PowerShell launch itself or substitute for a real physical Windows execution. Physical Windows proof is **not yet available**.

**Operator action:** On Windows 11, run the one command above and submit receipt-shareable.json, the four original WAVs, two screenshots and the source/preset identity evidence to [issue #242](https://github.com/techrote/zaaggenz/issues/242). For failures submit first-failure.txt and relevant redacted logs. Integration independently reviews Gate A and Gate B; #242 and VST #243 remain blocked until both pass.
