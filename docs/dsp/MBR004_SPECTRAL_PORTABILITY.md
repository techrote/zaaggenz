# MBR-004 Gate B — original-source spectral portability diagnostic

**Scope:** #242 only. This is a bounded diagnosis, **not** Phase-A acceptance, an approved PCM tolerance, a new sonic default, or physical packaged Windows evidence.

## Frozen original evidence

Merged #270; source under investigation: `f28b4db07b863653370baf55b076f34f73c6a628`. Original [ZG-009 #42597270382](https://github.com/techrote/zaaggenz/actions/runs/42597270382), 9 November 2026, includes hosted Ubuntu and Windows 3.13, NumPy 2.3.5, SciPy 1.17.0, OPENBLAS_NUM_THREADS=1; both jobs passed. Original WAV artifact IDs: Ubuntu `13664143795`, Windows `13664820614`. ZIP digests (SHA-256, from the actual current downloads): Ubuntu `ccdc37f723f3837618d259298f5745d94deeceaf57029598b3e12eb45669cfcc`; Windows `9cbf9dbbb01dd236facc00b528c66e023c472bf7f601f99658026567dae42abc`.

Both contain the same 30 original named 48-kHz mono WAVs and byte-identical saved order-A/order-B timeline documents. After independent float32 PCM decoding, **25 near-match**, while **five** differ materially (two of the five are same-host saved/reopen copies). Descriptive differences:

| Original exported fixture | Cross-host RMS error (FS) | Error / smaller output RMS |
| --- | ---: | ---: |
| Compression → spectral | 0.0009601021452 | 5.621% |
| Scheduled spectral target A / reopen | 0.0013442139477 | 7.356% |
| Scheduled target B | 0.0017199108624 | 9.415% |

The original browser evidence shows spectral→compression 86 changed frames on each host, compression→spectral **67 Ubuntu vs 60 Windows**, and scheduled A tracker/transform **325/100 Ubuntu vs 326/128 Windows**. This is evidence of discrete numerical decision divergence, not by itself proof of a DSP defect. Same-host exact reopen, dry and bypass identity already passed. The earlier 0.1% waveform-relative-RMS **screen is an unapproved proposal**, not a contractual threshold.

## Executable oracle

The dedicated tool is `tools/zg242_spectral_portability_trace.py`; its adversarial tests are in `tests/acceptance/test_zg242_spectral_trace.py`. Use the **original run artifacts**, not recreated examples or different source music. Install the already accepted dependencies and materialize the authenticated legacy source renderer before running:

```bash
python -m unittest discover -s tests/acceptance -p 'test_zg242_spectral_trace.py' -v

python tools/zg242_spectral_portability_trace.py inventory \
  --ubuntu original-zg009-ubuntu.zip --windows original-zg009-windows.zip \
  --out original-30-pairs.json

# Execute on original Ubuntu host, using its ORIGINAL immutable saved project:
OPENBLAS_NUM_THREADS=1 python tools/zg242_spectral_portability_trace.py capture \
  --artifact original-zg009-ubuntu.zip \
  --document rack-order-compression-then-spectral.zgtimeline.json \
  --out ubuntu-source-trace.json

# Execute on original Windows host (PowerShell: $env:OPENBLAS_NUM_THREADS = '1')
python tools/zg242_spectral_portability_trace.py capture \
  --artifact original-zg009-windows.zip \
  --document rack-order-compression-then-spectral.zgtimeline.json \
  --out windows-source-trace.json

python tools/zg242_spectral_portability_trace.py compare \
  --ubuntu ubuntu-source-trace.json --windows windows-source-trace.json \
  --out stage-local-decision-matrix.json
```

The read-only capture executes the genuine saved Timeline → compiled source recipe → whole-context renderer → saved rack, with scoped and automatically restored instrumentation. It records **source and method identities**, numerical environment, 48-kHz source PCM float32/float64 hashes, band and stage input/output/delta hashes, source-tracker IDs, anchors/supports, phase/confidence/actions, all transform/abstention decisions (native floating-point hex values), chosen targets, stage-local changed-support bounds and an independently recomputed crossover effect-delta reconstruction. It compares rendered samples with the original exported WAV **without rescaling**. If the new ordinary replay does not reproduce the original export, it must be treated as a new execution, **not claimed as the original-run internal trace**.

Full partial-window Hann support is finite; final rack PCM support is **not** confined to the changed-window union because `zaaggenz_dsp/multiband.py` uses forward/backward zero-phase Butterworth `scipy.signal.sosfiltfilt`. The oracle checks the actual routed delta and reports tails rather than incorrectly requiring strict zero outside the Hann support.

### Separately labelled sensitivity probe

An optional, explicitly **counterfactual** test substitutes the original artifact's *exported dry float32 WAV* as the rack's pre-rack input; it cannot authenticate original internal float64 source samples:

```bash
OPENBLAS_NUM_THREADS=1 python tools/zg242_spectral_portability_trace.py capture \
  --artifact original-zg009-ubuntu.zip \
  --document rack-order-compression-then-spectral.zgtimeline.json \
  --frozen-pre-rack-wav rack-one-bar-dry-reference.wav \
  --out ubuntu-counterfactual.json
```

Trace policy is `EXPLICIT-COUNTERFACTUAL-FROZEN-PCM-NOT-AUTHENTICATED-PRE-RACK` and cannot be confused with normal replay.

### Local source-exact experiment — not an original hosted host pair

On this investigator's Debian Python 3.13.5, NumPy 2.3.5 and SciPy 1.17.0 using the original f28b4d source ZIP plus materialized legacy source, normal saved-order-B rerender yielded **322 tracked and 53 changed frames**, original Ubuntu export RMS error **0.0008857207243 FS**. The freshly generated source PCM differed from the original Ubuntu exported dry float32 samples by only **2.12e-11 FS RMS** (36 float32 samples changed on downconversion).

With just the *explicit frozen dry-input substitution*, the **same local code** yielded **67 changed frames** and reproduced the original Ubuntu exported 57,600 float32 samples **bit-for-bit**, RMS error zero; independently reconstructed routed delta also equalled production exactly. Repeating the same Linux counterfactual with the Windows artifact dry PCM did **not** reproduce Windows's original output (RMS error `0.0008092534981 FS`). The small input perturbation causing a large output change is a **demonstrated precision-sensitive branching witness**, not proof of which FFT, least-squares, BLAS, SciPy or source-synthesis operation caused the original host split. Host-native original-source stage traces are still required for that attribution.

## Acceptance decision still required

Integration and the DSP owner should preregister a **source-specific, executable criterion** that (1) requires authenticated identical source/rack, explicit numerical environment and exact no-rack/bypass/reopen identity, (2) locates the *first* divergent input, filter, tracker frame, threshold/abstention, target choice, transformed partial, routed delta or final PCM, (3) separately evaluates allowable near-threshold decisions and audible consequences, and (4) quantifies tolerance tied to the actual algorithm, *not* the observed PCM to make a failing test pass. Earlier MBR-002 inverse projection numeric budgets are **not** whole-rack PCM policy. No silent normalization or changed defaults.

**Gate B HOLD:** original-host source-exact normal replays and a separate matched-input tracker comparison have executed. The first discrete Hungarian split is isolated, but DSP-owner source review, a preregistered near-tie/portability criterion and audible-consequence qualification remain pending. **Gate A EXTERNAL PENDING:** ordinary installed-wheel Windows 11 Compose startup, edit, restart/reopen and export receipts are absent; existing issue #242 operator procedure is the entry point. #243 native VST remains blocked. Integration alone admits #242, merges, or changes programme gates. This PR changes only new diagnostic tools/tests/docs; no shared implementation source or CI.


## Actual numerical tracker subledger (same commands, no counterfactual)

The normal \`capture\` command now records the real component-tracker STFT
Hann-weighted input, original \`np.fft.rfft\` result, actual
\`scipy.signal.find_peaks\` thresholds and local bins, parabolic peak
neighbours, admitted confidence/frequency, returned weighted-fit candidates,
Hungarian cost/accepted pairs and transient mask. Full per-frame float64
digests are retained, with raw first-four-frame float64 snapshots bounded.
All taps restore native methods and preserve actual DSP outputs.

The existing \`compare\` command emits \`tracker_subledger\`: first changed
pre-FFT/FFT/peak-fit operation, first differing frame and retained float64
values in hexadecimal, then first changed candidate/admission/assignment by
frame/anchor/frequency **not generated track ID**. If a later changed frame
is outside the four snapshots, report frame digest only; never invent a bin
value. Only identical analysis-input float64 SHA permits host tracker
attribution. The Integration-owned matrix already triggers on changes to
the diagnostic file, so no new workflow or dispatch is required.

Later **original-host source-exact** normal replays in [#42729088425](https://github.com/techrote/zaaggenz/actions/runs/42729088425) reproduce **both** respective original exported WAVs exactly, 57,600/57,600 float32 samples per host; earlier unauthenticated Ubuntu replays above are historical. These are new re-executions that authenticate the output-matched stage path, not recordings of the original run's internal tracker state.
This ledger is a source-local diagnostic, not an adopted portability
tolerance, DSP defect verdict, or substitute for physical Gate A. Whole-rack
\`sosfiltfilt\` tails are noncompact. DSP owner and Integration must
preregister an audible/algorithmic numerical criterion before Gate B.

## Authenticated normal replay is distinct from common-input tracker attribution

The original-source [host replay #42718441488](https://github.com/techrote/zaaggenz/actions/runs/42718441488) exercised the first real subledger on both hosts. Unlike preceding [#42713857672](https://github.com/techrote/zaaggenz/actions/runs/42713857672), **both normal replays now match their own original exported PCM exactly**, 57,600 float32 samples each. But the upstream freshly generated sources and resulting spectral analysis inputs no longer match across hosts: Ubuntu spectral analysis float32 SHA-256 `70bc5e82a9efc06e474d1213883119ca11b87e8500bfbc982f7506b1614b0815`; Windows `053c34f34243e3574e00db26bf1f90e12fe150dd5246bc656e6427dd8d1b95f9`. Hence the comparison's `different-f64-analysis-input` is the **correct fail-closed boundary**. The prior common-input run had no subledger; combining its input hash with the new host subledgers would fabricate evidence. Earlier new Ubuntu source and present new Ubuntu source also differ despite nominally identical Python/NumPy/SciPy versions; determine that upstream cause separately, not by presuming an FFT defect.

The later source-exact [#42722081869](https://github.com/techrote/zaaggenz/actions/runs/42722081869), diagnostics/tests head `b315e7dc839f3bcaf9f1c1cfb53bab26488d953d`, executed **seven targeted tests per host**, each green, original ZIP digest checks, ordinary saved-order-B captures, and the original-export/routed-delta exactness controls. Its host traces now additionally carry the actual **230,400-byte float32 spectral analysis input**, encoded and SHA-bound within `subledger.stage_input_f32le_b64`. The normal production render is not fed any substituted input.

**Next Integration-owned, single bounded CI amendment:** reuse the existing `.github/workflows/zg242-original-spectral-trace.yml`. Obtain the original-success Windows trace from run #42722081869 artifact **13720288381**, ZIP SHA-256 **59bad277a78a55c329f6c479415daa09dc5f9e2ce4d27efbb9da98e9ff2fbe5b**, using the same authenticated GitHub artifact API mechanism already present in the workflow. Verify that ZIP digest and extract `trace-windows.json` on **both** host runners. Then add the flag `--match-stage-from trace-windows.json` to the existing ordinary `capture` command (keep the original host-specific `--artifact` and original saved timeline, do not add the dry-WAV counterfactual). The original normal render remains intact, and the optional separate probe runs the actual v1 tracker against one byte-identical, source/rack/request-checked stage PCM buffer. The compare job already emits `matched_stage` with first weighted Hann / FFT hex difference, candidate and assignment threshold changes and anchor/frequency/action decisions when both traces carry the additional probe.

The specific existing command, once the verified Windows trace has been placed alongside each original host artifact:

```bash
python tools/zg242_spectral_portability_trace.py capture \
  --artifact original-zg009.zip \
  --document rack-order-compression-then-spectral.zgtimeline.json \
  --match-stage-from trace-windows.json \
  --out "trace-${TRACE_HOST}.json"
```

This **separate matched-input tracker pass is new-execution evidence**, not a substitute for normal source synthesis, authenticated original Ubuntu internal history, original dry/bypass/save-reopen identities or a DSP-owner portability rule. No arbitrary PCM tolerance, forced agreement, source-DSP fix or VST permission follows from this fixture.


## Matched-stage decision separation — 10 November 2026

Authoritative matched-input execution: original-host [#42729088425](https://github.com/techrote/zaaggenz/actions/runs/42729088425), exact Integration workflow head `f0b076de65d9bb8ab4f03dae794b07a1ef0a081c`. Its authenticated original Windows reference trace is artifact `13720288381`, and the two *new-execution* matched-stage trackers consumed identical float64 analysis-input SHA-256 `c1ab91804c52256cd8aa274ce31936a46508c15501e93f9b29818fbac16f17ea`. The original normal Ubuntu/Windows *source* and resulting native spectral inputs were not byte-identical; the matched-stage probe must not be presented as the original 9 November tracker trace. Both independent normal replays on these hosts nevertheless match each host's own original 57,600-sample exported order-B WAV exactly.

The original [host traces](https://github.com/techrote/zaaggenz/actions/runs/42729088425) (Ubuntu `13723697600`, Windows `13723896553`) and [comparison artifact `13723687773`](https://github.com/techrote/zaaggenz/actions/runs/42729088425/artifacts/13723687773) identify **different kinds of first event**:

| Boundary | Evidence from the same verified stage input |
| --- | --- |
| First observed float64 difference | STFT weighted Hann *before FFT*, frame 0 / channel 0 / sample 2392: Ubuntu `-0x1.5a0961ff1719cp-11`; Windows `-0x1.5a0961ff1719bp-11` (1 ULP). |
| Earlier assignment **numeric** drift | Cost at tracker frame 2 differs in hex, while selected row/column and admitted pairs remain identical. This is *not* a discrete split. |
| First actual assignment **discrete** split | Tracker frame **13**, with 15 prediction rows and 13 candidates. Ubuntu chooses `(0,1)` / `(1,0)` and admits `(1,0)`; Windows chooses `(0,0)` / `(1,1)` and admits neither of these pairings under the existing **240-cent** jump rule. |
| Downstream continuity | The same-input probes subsequently yield 26 vs 25 tracks, 65 vs 60 transform-eligible frames. These are new-probe outcomes, not original tracker identities. |

At frame 13, the native captured cost hex for rows 0/1, columns 0/1 is:

| Host | c00 | c01 | c10 | c11 |
| --- | --- | --- | --- | --- |
| Ubuntu | `0x1.5bff843ee6890p+10` | `0x1.cefc052de8edap+10` | `0x1.e1aafc58213bbp+4` | `0x1.ea0cb3818ba5fp+8` |
| Windows | `0x1.5bff843ee688ep+10` | `0x1.cefc052de8ed8p+10` | `0x1.e1aafc58213bbp+4` | `0x1.ea0cb3818ba5fp+8` |

The two-row alternative totals (diagonal and cross, respectively) computed *after the fact* are Ubuntu `0x1.d682b11f49728p+10` / `0x1.d682b11f49729p+10`; Windows `0x1.d682b11f49726p+10` / `0x1.d682b11f49727p+10`. Whole-assignment totals round to the same float64 value for both alternative pairings on each host. These are **post-hoc diagnostic totals, not captured Hungarian internal arithmetic or proof of a particular tie-breaking implementation**. The frame's prediction/candidate physical frequencies and the admission jump explain why a tiny change can affect subsequent continuity. No cross-host raw track ID is taken as a physical identity.

The corrected `compare_subledger()` reports `first_numeric_boundary` and `first_discrete_boundary` independently, plus `first_assignment_numeric_difference`. Its assignment scanner continues past changed floating costs when pairings/admission are unchanged. The bounded regression includes earlier numerical cost drift with later changed pairing/admission, identical-decision numeric-only control, and foreign-input refusal. Reuse the already authorised host capture/compare workflow; do not introduce a second tracer or modify production DSP.

**Acceptance hold:** An independent DSP owner and Integration must *preregister* expected near-tied global-assignment behavior, accepted numerical sensitivity and audible consequences before treating the five original WAV differences as permissible or defective. No 0.1% PCM tolerance, artificial renormalisation, solver modification or physical Windows Gate-A claim is authorised by this evidence.
