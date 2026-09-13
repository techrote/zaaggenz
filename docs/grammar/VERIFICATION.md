# ZG-011 verification record — 2026-09-13

Base: `fa0ce21e3392df718ca050094e477880343f8d17`. Implementation PR: #65.
The local checked tree is reproduced through the PR's exact-head source artifact;
Git tree identity is compared before publication. No materialized `app/`, caches,
private reference recordings or generated WAVs are committed as source.

## Executed locally

Python 3.13, NumPy 2.3.5, SciPy 1.17.0; Linux; numerical worker threads limited to one.

- `python -m unittest discover -s tests/grammar -v`: **27 passed**, including
  CLI create/reopen/render, actual audio identity, non-octave tuning, deterministic
  motifs/returns, manual bypass, resource admission and invalid input.
- `python tools/check_contracts.py --baseline --report <report>`: **passed**;
  149 contract/legacy equivalence tests, syntax checks and all **13 inherited smoke
  scripts**. Authenticated source payload verified by the materializer.
- Existing suites, individually discovered: tuning **27**, melody **13**, harmony
  **17**, project **16**, jobs **23**, reference **12**, QC **14** — all passed.
- `node tests/jobs/browser_transport.mjs`: stale rejection, atomic snapshot and
  stop invalidation checks passed.
- Shared analysis **15**, components **13** and descriptors **24** also passed as
  additional unchanged-module regression checks.

The unrelated full DSP graph suite was not completed in the local command time
budget; it is not claimed as a fresh pass. No DSP implementation files changed.
The first broad local discovery attempt lacked the legacy `app` import path for
contracts; it was replaced by the repository's `check_contracts.py` runner, which
sets the path and passed. No test was weakened to accommodate that invocation error.

## Full-rate fixtures

Command: `python tools/grammar_fixture_report.py --out grammar-fixtures-48k.json
--audio-dir grammar-listening-48k --sample-rate 48000`.

All three renders completed at **48,000 Hz**, from the recovered `locked_bloom`
source with explicit one-shot settings. Two four-bar variants each contain 230,400
samples (4.8 s); the sixteen-bar example contains 921,600 samples (19.2 s).
Matched whole-file RMS is approximately 0.0630957344 (-24 dBFS RMS); measured sample
peak headroom exceeds 12.29 dB in these fixtures. No true-peak/loudness or artistic
approval is claimed. Recipe and PCM hashes are environment-specific evidence,
not new cross-platform golden-hash requirements.

| Example | Authoring recipe SHA-256 | Raw float32 PCM SHA-256 |
|---|---|---|
| step-return, four bars | `45c5c50000f52eacc7cd3f70388ac57fcc2cec66f65f97bbfbba81f849c9f067` | `624fe70eba45325a435c0556ed0d1498b80f1e0bc3fa17abb858846f356fb51f` |
| skip-return, four bars | `b248ca3e2936a66c259f6a9a10b081e3ac31c6926b27ca38d7868ceb8cc174a7` | `1e4d185ff81c04533a1592293b583abd605d3c9b067f58575db35244de02640c` |
| step-return, sixteen bars | `c97b3f576a009ab56341a53d646defd4605df3504a54ee85e6819a70a781812a` | `b2ae8c41409f3cdf6bd93ec01c273f55501aa8d6fdf370e9272c908f01c31cd1` |

## Remote gate

The final-head `ZG-011 directional modal grammar` matrix runs on Ubuntu and Windows,
including grammar, tuning, melody, harmony and full-rate generated-source fixtures.
The independent existing `ZG-002 contracts and legacy equivalence` matrix runs on
every PR and covers all recovered smoke scripts. Merge requires both workflows
successful on the final head; PR/issue comments record the actual run IDs after
completion. Bootstrap workflow success alone is not acceptance.
