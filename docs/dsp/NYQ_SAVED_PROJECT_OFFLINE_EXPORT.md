# NYQ saved-Compose offline 48-kHz export

**Draft/HOLD, isolated stack on #278.** This is a command-line, opt-in production path, not ordinary Compose GUI export, a registered graph/rack node, per-band insertion, upstream-feature route or accepted #252/#253.

Use **Compose → Save** to obtain a real `.zgtimeline.json` file. In an environment with this proposed branch installed, run:

```sh
python -m zaaggenz_runtime.nyquismic_offline_export \
  --project /path/to/my-song.zgtimeline.json \
  --output /path/to/my-song-nyq.wav \
  --virtual-hz 11730/1 \
  --evaluation-hz 192000
```

The command cold-opens the saved timeline in a fresh `RuntimeSession`, submits a real ordinary Compose full-context job, authenticates its actual PCM against its owned job/document/recipe through #275, builds a source-matched static authored #267 clock packet (without falsely claiming an upstream-feature route), runs #266 SamplerPlan and #277 final FIR delivery, then writes a verified **48,000 Hz IEEE-float32 WAV** through #278's atomic no-clobber path. The project is not changed. No private recording, external API, cloud use or VST is required. Output and decoding identity, PCM hashes and source/project/packet receipts are returned as JSON **only after** successful publication.

The artistic virtual rate, the numerical evaluation clock (192/384/768 kHz), and final 48-kHz delivery clock are separate. The complete actual Compose render asset including any tail determines packet physical extent. This command uses a user-selected *static* clock and does not yet supply saved GUI control routing, musical modulation, automated A/B or upstream features. Existing target files cannot be overwritten; invalid .zgtimeline.json, malformed rate, unsupported source extent, render failure, cancellation, stale job/revision and an unsupported filesystem reject. Input is bounded by Compose's 2-MB saved-project authoring limit. Disk stage/commit remains delegated to #278's guard and hard-link publication. No claim of whole-directory crash durability or cross-host bit identity on arbitrary audio.

**Qualification required before Integration admission:** `python -m unittest discover -s tests/runtime -p 'test_nyquismic_offline_export.py' -v`, full runtime suite, and source-exact Ubuntu/Windows ZG-041 plus ZG-002, ZG-016, ZG-024a and ZG-000 direct/reverse. Tests use only a synthetic saved timeline, authentic ordinary Compose jobs, decoded original 48-kHz WAV/PCM hashes, cold reopen replay, no-clobber, adversarial late edit, disk-stage cancellation and actual CLI entrypoint. Request independent source/PCM review on the final head. Protect #266/#267/#275/#277/#278 and Integration-owned graph/session/provenance files; no self-admission or merges.
