# ZG-025 verification record

Implementation branch: `zg-025/phrase-role-windows`. Base: merged ZG-009 main `74267daef47d4676c3bdd5ac8df39a3a8bb2e7f7`.

Acceptance evidence is produced by `.github/workflows/zg025-phrase.yml` on the final PR head. It runs phrase-role validation/expansion/integration tests, inherited ZG-008 melody tests, inherited ZG-009 timeline tests, and the four-condition 48 kHz generated-source fixture report on both Ubuntu and Windows. The independent ZG-002 contracts/legacy workflow is also required before merge.

The PR/issue completion comment records the actual final head, workflow IDs and artifact IDs. This file intentionally does not claim a CI result before that run exists.

Evidence boundaries:

- generator probabilities are engineering probabilities, not listener probabilities;
- matched fixture gains are playback-only RMS matching, not perceptual loudness or true-peak certification;
- source-family labels are authoring identities routed through the currently shared protected source renderer, not four newly synthesized timbre engines;
- successful tests do not constitute owner audition approval or evidence for biochemical reward hypotheses;
- existing simple arrangement templates and ZG-009 editing remain separate supported workflows.
