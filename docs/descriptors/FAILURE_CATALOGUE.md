# ZG-014 descriptor failure catalogue

This catalogue is part of the measurement contract. A valid numeric value means “the named method produced this value on the named support”, not “the music is objectively good” or “the listener will respond in a particular way”.

| Failure / confound | Affected measurement | Behaviour / mitigation |
|---|---|---|
| Silence or constant signal | f0 / periodicity | Abstain. DC removal followed by negligible energy cannot yield a meaningful periodic candidate. |
| Very short support | periodicity / modulation / occupancy | Abstain or fail the requested f0 range rather than pad invisibly and report normal confidence. |
| Stereo antiphase | periodicity / modulation | Analyse highest-energy physical channel, not L+R sum. Spectral occupancy averages channel power. |
| Strong missing fundamental | autocorrelation f0 | Several lags can be plausible. Alternate candidates and octave-ambiguity flag are retained. |
| Octave/subharmonic ambiguity | autocorrelation f0 | Near-equal autocorrelation peaks prefer the shortest lag, but alternatives remain in details; no chord/key inference follows. |
| Broadband/noise-like wall | f0 / partial harmonicity | Periodicity may become unknown and ZG-013 may abstain. A forced harmonic explanation is not substituted. |
| Mastering distortion creates many sidebands | harmonicity / roughness / comb fit | Descriptors measure the observed components; they cannot infer which partials were intentional before the nonlinear chain. Compare explicit pre/post graph taps in later issues. |
| Partial crossing / merge | component metrics | ZG-013 continuity/confidence propagates through amplitude×confidence weights. `unknown` tracks are observations, not automatically transformable components. |
| Component tracker leakage / sidelobes | component metrics | ZG-013 clean-tone regression bounds spurious tracks; ZG-014 also applies a component cap and reports available vs used count. |
| Different global gain | RMS | RMS changes by design. |
| Different global gain | occupancy / relative roughness / comb fits | Intended to be approximately invariant because they use normalized power or relative component weights. This does not make them absolute psychoacoustic measures. |
| Different playback SPL | roughness | Current method does not model SPL-dependent auditory filters/specific loudness. Use the term **relative pairwise roughness**, not sensory dissonance at a claimed loudness. |
| Different bandwidth/sample rate | occupancy / roughness / harmonicity | Results can change because available components/bins change. Method details and sample rate must accompany comparisons. Prefer matched bandwidth. |
| Very dense target comb | source coverage | Raw coverage is density-biased upward. Always inspect tooth precision, balanced fit, mismatch and target count. |
| Very sparse target comb | target precision | Precision can look high when only a few well-supported teeth are supplied. Balanced fit plus target count prevents silent conflation. |
| Wrong target f0 / chord | harmonicity / comb fit | The method answers fit to the supplied target, not “true key/chord”. Report the target explicitly. |
| Uncertain f0 | harmonicity | Without an explicit override, harmonicity becomes unknown if periodicity did not produce a valid f0 candidate. |
| Explicit f0 override | harmonicity | Override affects only harmonicity evaluation. The independently measured periodicity/f0 observation remains unchanged and configuration records `explicit-analysis-override`. |
| Timbre-dependent tuning | harmonicity / comb fit | Static equal-tempered or harmonic targets can be inappropriate. ZG-020 owns adaptive/timbre-dependent tuning; ZG-014 does not silently optimise a target. |
| Modulation sidebands mistaken for independent tones | component metrics | This is a representation limitation. Later harmonic/sideband grouping may add a new method ID; current outputs retain method provenance. |
| Fast chirp / pitch sweep | component harmonicity | Anchor-time component snapshot may not summarize the whole excerpt. Use shorter explicit supports or a timeline consumer. |
| Envelope modulation with <~one cycle in support | modulation Hz | Frequency confidence falls or abstains. A long enough caller-selected excerpt is required. |
| Multiple modulation rates | modulation Hz | Only the strongest 0.5–30 Hz envelope-spectrum candidate is reported; it is not a complete modulation decomposition. |
| Long file passed directly | all | `analyse_descriptors()` rejects excerpts over the configured sample bound. Caller must select an explicit support rather than accept hidden cropping. |
| Private reference filename matches but bytes differ | reference calibration | ZG-006 exact SHA-256/byte identity is the hard gate; no filename substitution. |
| Automatic paired reference suggestion | reference calibration | Zero-confidence automatic suggestions remain labelled as such. Descriptor differences do not upgrade them to a validated correspondence. |
| Dependency/runtime differences | all floating descriptors | CI fixes NumPy/SciPy versions for evidence. Cross-environment use should compare documented tolerances/method semantics, not assume raw byte identity unless stated. |
| Metric correlates with user preference in one sample | all | Not evidence of a general preference model, mechanism or biochemical response. Controlled study issues own those claims. |

## Interpretation rule

Keep the nouns literal. `harmonicity_comb_fit` is a fit to an integer-harmonic comb. `roughness_pairwise` is a normalized pairwise interaction descriptor. `target_comb_fit` is a balanced geometric matching calculation. None is a hidden alias for consonance, emotion, genre authenticity, dopamine, “zaagness” or quality.

When a later experiment wants one of those constructs, it must define the construct, freeze the stimulus/measurement method, and analyse it under the ZG-040 study framework rather than renaming a convenient acoustic proxy.
