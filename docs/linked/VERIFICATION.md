# ZG-028 verification record

Branch: `zg-028/linked-fakeout-return`. Base: accepted ZG-027 merge `56346648fe8947b01dd2d2b1098f83e60fa43c62`.

Local pre-publication checks on Python 3.13 / NumPy 2.3.5 / SciPy 1.17.0:

- linked event suite: **19 passed**;
- accepted ZG-010 harmony suite: **17 passed**;
- accepted ZG-025 phrase suite: **17 passed**;
- accepted ZG-026 meter suite: **19 passed**;
- accepted ZG-027 gesture suite: **14 passed**;
- accepted ZG-009 timeline suite: **24 passed**;
- five-condition fixture report at **48,000 Hz**: passed.

All five local full-rate source-derived controls contain 230,400 samples (4.8 s at the active 200 BPM TimeMap), report zero clipped fraction and retain the same protected source, event time/duration/gain signature, slow sway tick sequence and final return. Local raw PCM hashes:

- baseline `2d567b1de4a10eb7f52db1277743f98e527ccf306f9cd7704044b27791f66df3`;
- violation only `488e6b6e8822b0b22fdfdae854119148122fc092772e58a513d96d54fb4bb4a5`;
- recovery only `a5b568c7bb80cc204cc6c216188481139fc7da769a969d266f11a116e73c467b`;
- both linked `64c84aa54b8fa2a94b77cf3ba351575a94cbd8f9ea6beb6f892bbc81dc4cde6b`;
- both unrelated `2e3020ed01fb38d060df560c0e67db0c961adb9d9dc4fb0ee9cf64c23b3bd87b`.

The linked bridge distances decrease strictly (both-linked approximately 750 → 600 → 450 → 300 → 150 cents before the shared return); the unrelated control is non-monotonic (1100 → 500 → 1200 → 300 → 1000 cents). Playback-only matching reaches approximately -24 dBFS whole-file RMS with matched sample peaks below 0.30 in the local run.

Final acceptance is produced by `.github/workflows/zg028-linked.yml` on Windows and Ubuntu plus the independent ZG-002 contracts/legacy workflow. The PR/issue completion record supplies final head, workflow IDs and remote evidence artifact IDs; local hashes are evidence, not new cross-platform golden requirements.

Evidence boundaries: bridge convergence is an engine/compositional property, not a listener response; the stable meter anchor is authored state; four transformation families remain explicit deferred controls; matching is playback-only RMS; no owner preference, pleasure, excitement or biochemical claim is inferred.
