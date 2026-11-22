# NYQ saved-Compose virtual-rate audition sweep (opt-in)

**Scope:** independent, source-matched offline production comparison for the existing #284 saved-project A/B exporter. **Not** a graph/feature node, ordinary Compose UI command, rack export, #252/#253 admission, or a live cross-run session. Source is the original ordinary Compose *post-rack full mix*. Only virtual sampling rate varies. Dry reference audio is neither normalized nor bypassed around the existing rack.

## Usage

From a qualified source tree containing the #284 direct audition command and its controlled-clock dependencies:

```bash
python -m zaaggenz_runtime.nyquismic_audition_sweep \
  --project song.zgtimeline.json --output rate-choices.zip \
  --virtual-hz 11730/1 --virtual-hz 16000/1 --virtual-hz 22050/1 \
  --evaluation-hz 192000
```

Extract the **entire ZIP** into a local folder, open `index.html`, then open a listed variant. Every variant is a self-contained browser page that A/B switches one Nyquismic 48-kHz render against the same authenticated 48-kHz dry reference. Each page retains its original WAV downloads. This does **not** supply live switching among arbitrary variants inside one audio graph; open pages separately and do not infer loudness-matched preference from unadjusted levels. No network or paid service is used.

Accepted invocation: 2–6 *distinct*, positive, rational virtual-rate strings in Hz (`n` or `n/d`, up to 1 MHz), evaluation 192/384/768 kHz, maximum 2-MB saved Compose input, per-variant 120-second default wait (bounded 3600 s), maximum 128 MiB HTML per rate / 512 MiB combined pages. Output sample clock stays exactly 48,000 Hz. Rate and evaluation quality are independent controls.

## Authority, reproducibility and limits

Every variant independently opens and renders the saved project through the current ordinary `TimelineService` job, authenticates its immutable session/revision via the existing adapter, compiles the controlled-clock packet and `SamplerPlan`, then uses the existing #281/#282/#284 48-kHz WAV and verified HTML publishers. The batch **does not reuse or invent** live session authority, has no unregistered upstream feature route, and does not claim an uninterrupted shared job across rate selections. Instead, it checks exact original project-file SHA-256 before and after renders, and requires **matching source-asset, source-revision, Compose-recipe, 48-kHz dry PCM, frame and channel identities** on all independently reopened variants. A changed project, source asset, dry render or mismatched receipt aborts the entire package. Source recordings are never included or uploaded separately.

ZIP entries: `index.html`, `manifest.json`, `variant-01.html` … `variant-NN.html`. The JSON records project/source/recipe/dry SHA-256, rate, Nyquismic packet SHA-256, wet float32 PCM SHA-256 and every actual page SHA-256. Each underlying page independently retains its verified embedded WAV and decoded PCM manifests. Fixed ZIP metadata supports same-host cold-reopen byte equality; cross-host whole-ZIP byte identity is **not claimed** because Compose/renderer provenance may legitimately differ even with identical decoded PCM. These identifiers are evidence, not a listening-quality score.

Archive publication is no-clobber atomic hardlink (`os.link`) after fully closed and fsynced temporary ZIP assembly in the destination directory. A pre-existing output, cancellation, failed single render, conflicting writer, source mutation or tampered staging page leaves no new user-facing archive; private temporary files are cleaned. A previously published archive represents a saved-project snapshot only, not monitoring of later edits to the external project. It may be large: keep this an explicitly chosen batch, not a default engine operation.

## Exact-head verification

```bash
python -m unittest discover -s tests/runtime -p 'test_nyquismic_audition_sweep.py' -v
python -m unittest discover -s tests/runtime -p 'test_nyquismic_offline_audition.py' -v
python -m unittest discover -s tests/runtime -p 'test_nyquismic_ab48_listen.py' -v
python -m unittest discover -s tests/runtime -p 'test_*.py' -v
```

The new test includes actual saved Compose source → **two different virtual rates** → authenticated pages and a 48-kHz float32 PCM manifest, plus bounded positive/negative, cancellation, source-revision, cold reopen, competing-writer and ZIP digest regressions. Full source/runtime and browser workflows, Ubuntu/Windows original-host numerical artifacts and independent qualification are required for actual programme admission. Physical Windows MBR #242 and approved near-tie spectral-portability decisions remain distinct external gates.
