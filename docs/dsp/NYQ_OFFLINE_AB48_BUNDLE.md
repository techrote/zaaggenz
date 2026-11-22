# NYQ source-matched A/B audition bundle (opt-in, Draft)

This source-disjoint standalone command creates **one atomically published ZIP**
containing two genuine **48-kHz float32 WAVs** of the **same ordinary Compose
full-mix source**:

- `compose-dry.wav`: the accepted Compose post-rack output **without the added
  Nyquismic sampler**. This is **not** a bypass of the existing rack.
- `compose-nyquismic.wav`: the same authenticated Compose PCM through the
  #267 controlled clock, #266 SamplerPlan and #277 final delivery FIR.
- `manifest.json`: source/project/revision/recipe/packet, both WAV and decoded
  PCM hashes, exact common frame count, dry conversion method/kernel and wet
  numerical identity. No private audio is uploaded.

With this candidate branch installed, save an ordinary Compose
`.zgtimeline.json` and run:

```sh
python -m zaaggenz_runtime.nyquismic_offline_ab48 \
  --project /path/song.zgtimeline.json \
  --output /path/song-nyq-ab.zip \
  --virtual-hz 11730/1 \
  --evaluation-hz 192000
```

Unzip and audition the two waveforms at equal playback gain, aligned at sample
zero. They have the same exact duration/channel count and 48-kHz playback
clock; **neither is peak-normalized, clipped or artificially loudness matched**.
Their audible difference is not a numerical proof of musical quality. Both
WAVs are full-mix, post-Compose assets; Nyquismic is **not yet registered into
ordinary Compose graph/rack export or its UI**.

## Reproducibility and publication

A single fresh RuntimeSession and single owned ordinary Compose full-context
render feed both outputs. The dry comparator uses source PCM directly at 48 kHz
(bit-exact float32 reference), or a specified bounded `24*max(up,down)+1`
Kaiser-beta-10 polyphase FIR conversion at other supported rates. It refuses
unrepresentable 48-kHz duration, exceeding the declared source/output/filter
budgets, non-finite audio or float32 overflow; no unconstrained resampling
approximation. The wet output uses only the already established #275/#267/#266/
#277 pipeline, without invented upstream feature routing. The manifest
names the exact dry interpolation method.

The archive uses deterministic ZIP metadata and uncompressed embedded WAVs;
cold reopening the same saved project should reproduce byte-identical ZIP
content **within the tested environment**. Source, decoded PCM, WAV and ZIP
SHA-256 receipts are emitted only after publication. Cross-host numerical
identity is inspected from original test logs, not assumed universally.

The ZIP is staged and flushed within the destination directory, verified,
then linked without overwrite under the #275 job/document lock ordering.
Later edits, job revocation and caller cancellation before that commit refuse
publication and clean temporary files. Existing output files, including
symlinks, are protected. On a filesystem lacking hard-link support this fails
closed. Neither directory-fsync crash durability nor acceptance of a physical
Windows packaged workflow is claimed.

## Qualification and ownership

New-file-only lease:
`zaaggenz_runtime/nyquismic_offline_ab48.py`,
`tests/runtime/test_nyquismic_offline_ab48.py`,
`docs/dsp/NYQ_OFFLINE_AB48_BUNDLE.md`.
This Draft stacks on #279 without editing its owned files, #275's
session/graph code or #266/#267 author source. The main-based assembled #280
is being independently qualified and remains untouched.

```sh
python -m unittest discover -s tests/runtime -p 'test_nyquismic_offline_ab48.py' -v
python -m unittest discover -s tests/runtime -p 'test_nyquismic_offline_export.py' -v
python -m unittest discover -s tests/runtime -p 'test_nyquismic_compose_delivery.py' -v
python -m unittest discover -s tests/runtime -p 'test_nyquismic_compose_file_export.py' -v
```

Require new exact-head full Ubuntu/Windows ZG-041 and relevant direct/reverse
workflows, original numerical receipts, and independent Integration review.
This source change is **not self-approved**. NYQ #252/#253 remain unaccepted;
#254 is blocked. MBR-004 #242's physical-Windows and spectral-portability
owner gates remain separately blocked; no VST #243, no default/preset changes.
