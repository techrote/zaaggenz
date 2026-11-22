# NYQ / local A/B browser audition (opt-in)

This is an **offline listening convenience** for the real #281 saved Compose dry/NYQ ZIP. It does not implement a registered graph node, ordinary Compose UI export, upstream-feature routing, modulation, or admission of NYQ #252/#253.

Generate the source-identified ZIP using the existing production command, then generate a portable, local HTML page:

~~~sh
python -m zaaggenz_runtime.nyquismic_offline_ab48 \
  --project song.zgtimeline.json --output song-ab.zip \
  --virtual-hz 11730/1 --evaluation-hz 192000

python -m zaaggenz_runtime.nyquismic_ab48_listen \
  --bundle song-ab.zip --output song-ab.html
~~~

Open the generated song-ab.html locally in Firefox or Chromium. Press **PLAY**; select **A / ORIGINAL** or **B / NYQUISMIC** to switch between two audio sources running on the same Web Audio timeline. Seek and pause are supported, and both original WAVs can be saved. An 8-ms output-gain ramp avoids switching clicks without rewriting either file. No gain matching, clipping, gain compensation or normalization is applied. Browser audio devices may resample the *playback*, independently of the verified 48-kHz files.

The page contains both verified WAV payloads and the original source, project, revision, packet, and PCM hashes. No network requests, CDN scripts, hosted server, private audio uploads or mandatory external services are involved. The page can be carried to another computer and played without the Python package. The source manifest is a **receipt**, not a digital signature; it does not protect against someone intentionally forging both media and the manifest.

Before publishing, the generator enforces ZIP entry order and stored-entry format, a 64-MiB input budget, original per-WAV SHA-256, decoded 48-kHz float32 format, finite PCM samples, mono/stereo frame alignment, and decoded PCM hashes. Output uses a same-directory staged write, file fsync, checksum and atomic no-clobber hard link. Existing user HTML is preserved. Unsupported hard links fail closed. This does not claim crash-durable directory sync, filesystem-independent atomicity, or live Compose job/session publication: the *input is an already finalized exported ZIP*, not a live editing session.

## Qualification and source ownership

Exclusive new-file lease for this incremental Draft: zaaggenz_runtime/nyquismic_ab48_listen.py, tests/runtime/test_nyquismic_ab48_listen.py, this document. It is stacked on the opt-in #281 original-output branch. No edits to the Integration-owned #275 graph/session binding, #266 sampler, #267 clock, #280 assembled main, production #281 source, shared registries, programme state, defaults, presets, CI, MBR or VST.

Run:

~~~sh
python -m unittest discover -s tests/runtime -p 'test_nyquismic_ab48_listen.py' -v
python -m unittest discover -s tests/runtime -p 'test_nyquismic_offline_ab48.py' -v
python -m unittest discover -s tests/runtime -v
~~~

The new tests use a real synthetic saved-Compose source and exported A/B archive. They verify unmodified embedded source WAVs, exact file/PCM provenance, tampered PCM and manifests, incorrect sample types, unknown ZIP entries, HTML script injection, staging-time cancellation, concurrent destination creation, existing file preservation and CLI output identity. Original-host CI and a real browser listening smoke are distinct evidence boundaries; Python static tests do not establish browser usability or perceptual parity. Independent Integration qualification is required before any guarded assembly or merge.
