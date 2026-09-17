# ZG-024 transient-gate ablation — issue #87

This directory is the frozen research record for the inverse-search `transient_loss` repair. It is an engineering attack-preservation study, not a perceptual-quality or preference experiment.

## Preregistration chronology

The design was deliberately frozen in public commits before each outcome set was inspected. The initial envelope-only proposal was inadequate after RMS normalization. A second relative derivative-contrast proposal was also inadequate for onset-only low-pass damage. Protocol v3 introduced attack-local high-band contrast, then independent confirmation v1 exposed a structural false negative: removing a secondary target onset still scored `0.8310780175536643`. Protocol v4 therefore added a direct target-anchored onset-contrast component without changing the existing `0.4` threshold, anchor windows, amplitude window, or high-band rule. A fresh confirmation-v2 matrix was frozen before that final candidate was evaluated.

Canonical UTF-8 JSON SHA-256 values used during the research pass:

- `transient_gate_protocol_v1.json`: `08597a63a728bd1ced5808a31ab22f4cc542405127a3443d101da8b7d75a1380`
- `transient_gate_protocol_v2.json`: `ebc00c57b6ba5651b1328041d79f60a911bfa8cb2f7f543d6df5996952f41992`
- `transient_gate_protocol_v3.json`: `ca6e4361ecd34aea9f7f92fd6bd1052dd70c0c33f113da0862e96bfd62bf815f`
- confirmation v1: `455bdaa8ee48e4427e4c50cbb65119fe617bb53bc18edaa4fd7b56ca6fd0ccf7`
- `transient_gate_protocol_v4.json`: `23cb2e5167038dd4dc43ec268c3257f171809561f9c4bb94c774a5c86156540e`
- confirmation v2: `5bb936e49b67db13da4e8aabdfd6cf13c0c12d789d196b3e7f69165785aa2f6c`

The superseded protocols are retained rather than rewritten so unsuccessful diagnostic ideas remain auditable.

## Existing derivative-anchor gate characterization

The accepted ZG-024b evidence already demonstrates a large eligibility interaction: for `offgrid-envelope`, grid prefix produced **0 eligible candidates in all three 16-evaluation runs (0/48)**, predominantly through the old `transient_loss` gate, despite finite decomposed fit values being retained for rejected candidates. Entire runs in the three-axis timbre fixture also lost eligibility. That evidence is why optimizer eligibility could not be interpreted as optimizer quality.

The old gate is additionally scale-sensitive by construction. For an otherwise identical waveform multiplied by positive gain `g`, target-anchored derivative RMS is multiplied by `g`, so the reported transient ratio is `g`; an unchanged attack envelope at gain `<0.4` therefore triggers `transient_loss` in addition to the independent level gate. Conversely, the frozen design-v1 onset-only low-pass case retained an old derivative ratio about `0.531`, above the `0.4` threshold, despite deliberate attack damage. These are false positive/false negative examples for the old diagnostic's stated purpose, not claims about preference.

## Fresh confirmation-v2 result

No parameters or labels were changed after `transient_gate_confirmation_v2.json` was frozen. The final `zg.inverse.transient-onset-contrast.v3` ratios from the deterministic 48 kHz matrix were:

| Case | Label | Ratio |
|---|---|---:|
| identity | preserved | 1.0000000000 |
| gain 0.58 | preserved | 1.0000000000 |
| phase change | preserved | 0.9783233794 |
| root 247→369.99 Hz | preserved | 0.7750903189 |
| timbre change | preserved | 0.8482468177 |
| attack removed | damaged | 0.0000000000 |
| attack smoothed | damaged | 0.1754567974 |
| attack attenuated | damaged | 0.3219963607 |
| onset-only low-pass | damaged | 0.2565276461 |
| flattened attack | damaged | 0.2661670812 |
| secondary onset removed | damaged | 0.0000000000 |
| later onset attenuated | damaged | 0.0539035196 |
| one stereo channel damaged | damaged | 0.2232594585 |

All preserved controls are above the frozen `0.4` threshold; all deliberately damaged/adversarial controls are below it. CI tests regenerate these signal families and additionally cover the 32-sample boundary, silence, near-silence, low sample rate, exact threshold semantics, multiple target onsets, candidate-side decoy onsets, and physical-channel aggregation.

## Interpretation boundary

This evidence supports `zg.inverse.transient-onset-contrast.v3` as a bounded safety diagnostic for preservation of target attack/onset structure. It does **not** establish a universal perceptual transient metric, does not rank optimizers, does not measure musical preference, and does not justify changing product defaults. Search remains fit-only; this validation result is a separate eligibility record. Raw diagnostic records are retained even when a candidate is rejected.
