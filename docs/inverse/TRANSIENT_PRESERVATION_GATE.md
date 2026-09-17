# Inverse transient-preservation gate

**Production method:** `zg.inverse.transient-onset-contrast.v3`  
**Issue:** #87, corrective follow-up under ZG-024  
**Policy threshold:** `ValidationPolicy.min_transient_ratio`, unchanged default `0.4`

## What the gate measures

The gate is a bounded engineering check for whether target-derived attack/onset structure survives in an inverse-search candidate. It is deliberately separate from acoustic fit and from preference.

For each physical channel, the method selects at most eight anchors from the **target only** using positive 4 ms pre/post RMS contrast. Anchors must exceed both an absolute contrast floor (`0.05`) and 25% of the target's peak onset contrast, and are separated by at least 12 ms. The candidate cannot move an anchor to a later surviving transient.

At every target anchor three relative quantities are retained:

1. **Onset contrast preservation:** candidate positive pre/post RMS contrast divided by the target contrast at the same sample.
2. **Attack/tail amplitude preservation:** candidate early/late RMS ratio divided by the target early/late RMS ratio, using 0–6 ms versus 6–24 ms after the anchor.
3. **Attack-local high-band preservation:** where the target has enough high-band evidence, the candidate's early/late high-band power-fraction ratio divided by the target's. The high-band boundary is `min(1000 Hz, 0.20 * sample_rate_hz)` and the target applicability floor is `1e-4` power fraction.

The anchor score is the minimum non-negative value of those three components. The final transient ratio is the minimum score over all target anchors and physical channels. If an active target has no qualifying attack anchor, this diagnostic is neutral (`1.0`) rather than inventing evidence; the existing silence, level, bandwidth, energy, clipping and provenance gates remain independent.

The validation record retains method ID, parameters, target anchor samples, per-channel ratios, per-anchor raw components and the aggregate ratio even when eligibility is rejected.

## Why the previous gate changed

The previous implementation selected peaks of the target **sample derivative** and compared candidate/target derivative RMS around those locations. That is not attack-specific: global gain scales the metric directly, and periodic root/phase/timbre differences can change carrier derivatives without destroying an attack. Accepted ZG-024b evidence also showed severe eligibility interaction: the off-grid envelope grid produced 0 eligible candidates in all three 16-evaluation runs, predominantly through `transient_loss`, while rejected candidates still had finite decomposed fit measurements.

Issue #87 therefore treated the gate itself as the research subject instead of weakening its threshold to improve optimizer results. The frozen research lineage and independent confirmation evidence are in `research/zg024c/`.

## Versioning and compatibility

`ValidationPolicy.min_transient_ratio` and its default `0.4` are unchanged. `InverseValidation` remains format `1.0.0`, but the diagnostic record now declares `zg.inverse.transient-onset-contrast.v3`; the inverse implementation/feature identity necessarily changes because `zaaggenz_inverse` source changed. Persisted Candidate 2.0 evidence remains bound to the implementation identity under which it was produced, so historical derivative-anchor records are **not** silently reinterpreted.

No renderer, recipe, source PCM, protected audio, tuning, objective term, proposal strategy, fit/holdout capability boundary, normalization policy, clipping policy or product default is changed by this repair. Rejected candidates continue to retain raw objective and validation measurements; hard eligibility is not converted into optimizer score.

## What the gate does not measure

This is not a perceptual-quality metric, preference score, transient "pleasantness" score, source-separation algorithm, or proof that one optimizer is better than another. It does not assert that every timbre-preserving transform should retain exactly the same onset spectrum. The high-band component is deliberately applicable only when the target has sufficient high-band evidence, and the method is calibrated as a safety diagnostic on bounded deterministic fixtures rather than as a universal auditory model.

Remaining uncertainty includes unusual source families whose musically meaningful attack is longer than the fixed 24 ms local comparison window, very low sample rates where high-band evidence becomes uninformative, and material whose intended onset is primarily spatial rather than per-channel energetic. Those cases must remain visible in raw diagnostics and may motivate a future versioned method; they are not grounds for silently retuning v3.

## Verification

CI must run the inverse objective/gate suite on Ubuntu and Windows. The adversarial suite covers preserved gain/phase/root/timbre changes, attack removal, rounding, attenuation, onset-only low-pass damage, flattening, multiple target onsets, a candidate-side decoy onset, one-channel stereo damage, exact threshold semantics, 32-sample minimum length, silence, near-silence and low sample rate. Frozen confirmation-v2 portable values use absolute `1e-7` / relative `1e-5` comparison tolerance, with exact pass/reject classification.
