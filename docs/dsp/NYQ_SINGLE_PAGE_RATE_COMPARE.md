# NYQ synchronized offline multi-rate audition (opt-in)

The nyquismic_rate_compare module converts an **already rendered and source-verified** NYQ rate-sweep ZIP into one local HTML page. Instead of opening a separate player for each virtual sampling rate, the user can immediately switch between the dry original and all 2–6 wet rates. All tracks share one Web Audio playback time and position, with an 8-ms gain crossfade. Seeking, pause/resume, original WAV downloads and immutable PCM identities are retained. There is no gain matching, normalization, audio alteration, new render, or external service.

## Usage

Generate a sweep using the existing Finisher tool:

    python -m zaaggenz_runtime.nyquismic_audition_sweep --project song.zgtimeline.json --output rates.zip --virtual-hz 11730/1 --virtual-hz 16000/1 --virtual-hz 22050/1

Generate the synchronized comparison:

    python -m zaaggenz_runtime.nyquismic_rate_compare --sweep rates.zip --output instant-compare.html

Open the new HTML file locally in a browser. No HTTP server or network connection is necessary. This is an **offline HTML postprocessor**, not a registered Compose GUI, rack node, upstream feature, session-bound graph route or admission of #252/#253. It preserves the post-Compose full-mix source exactly as previously exported; later edits to the saved Compose source require a new sweep. Browser audio hardware may resample output and human listening quality has not been certified.

## Authentication and bounds

The output is generated exclusively from one bounded ZIP byte snapshot. The module verifies the outer source asset/revision, project, recipe, variant rate/packet, exact embedded WAV bytes, decoded finite float32 PCM and shared 48-kHz extent against the manifest and each embedded page. Wrong, duplicate or foreign rates; altered pages; non-48-kHz and integer/NaN audio; extra ZIP entries; and source changes fail closed. A valid source sweep can be refused solely because this compact all-rates player exceeds its more restrictive memory budget: maximum ZIP 128 MiB, embedded page 32 MiB, decoded WAV payload total 64 MiB and 4,000,000 frames. The independent-page sweep remains usable for longer audio.

The new HTML carries unmodified WAV downloads and a source/numerical receipt. It has a hard-edged dark UI, keyboard-focusable controls and a CSP prohibiting outbound network access. New files are staged adjacent to the destination, fsynced, hash-verified, atomically hardlinked create-if-absent and cleaned on failure/cancellation; existing user outputs cannot be overwritten.

## Qualification

    python -m unittest discover -s tests/runtime -p 'test_nyquismic_rate_compare.py' -v
    python -m unittest discover -s tests/runtime -p 'test_nyquismic_audition_sweep.py' -v
    python -m unittest discover -s tests/runtime -p 'test_*.py' -v

The test includes actual saved Compose two-rate audio when run in a complete source checkout, direct unmodified WAV identities, same-host cold-reopen byte identity, foreign-source adversarial mutations, cancellation after fsync, output collision and traversal rejection. Original-host Ubuntu/Windows CI, independent review and real Chromium multi-rate playback assertions remain separate gates. Hosted CI is not physical Windows MBR-004 operator acceptance and does not establish musical improvement.
