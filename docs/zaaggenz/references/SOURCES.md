# Source register

This register exists to keep prior art, empirical evidence and design hypotheses distinguishable. It is not a claim that every source has been reproduced locally. Follow the original paper/author page where possible; record access date/version in implementation/research manifests.

## Spectral/tuning/DSP

| ID | Source | Why it matters / boundary |
|---|---|---|
| **S01** | W. A. Sethares, *Local Consonance and the Relationship Between Timbre and Scale* (JASA, 1993). Author material: https://sethares.engr.wisc.edu/papers/consance.html | Direct prior art for timbre-dependent sensory-dissonance curves and local minima. Minima are candidate acoustic compatibilities, not universal preference or keys. |
| **S02** | W. A. Sethares, adaptive tuning work. https://sethares.engr.wisc.edu/papers/adaptun.html | Prior art for tuning active tones in relation to spectra/other tones. Zaaggenz must add drift/anchor/voice-leading bounds rather than blindly minimising dissonance. |
| **S03** | W. A. Sethares, *Consonance-Based Spectral Mappings*. https://sethares.engr.wisc.edu/papers/specmap.html | Very direct prior art for mapping spectra toward desired spectral relations; the project must not claim spectral retuning itself as novel. |
| **S04** | R. J. McAulay & T. F. Quatieri, sinusoidal speech analysis/synthesis (IEEE TASSP, 1986), DOI: 10.1109/TASSP.1986.1164910 | Classical sinusoidal-model reference for component tracking/resynthesis. Speech-specific assumptions need revalidation on distorted music. |
| **S05** | X. Serra & J. Smith, *Spectral Modeling Synthesis* (Computer Music Journal, 1990) | Deterministic/sinusoidal plus residual/noise modelling precedent; residual is not automatically discardable noise. |
| **S06** | Julius O. Smith / Stanford CCRMA sinusoidal/phase-vocoder literature and later phase-coherent spectral-processing work | General prior art for phase-aware frequency transformation. Select a concrete method/implementation only after licence/API evaluation. |
| **S07** | D. Griffin & J. Lim, *Signal Estimation from Modified Short-Time Fourier Transform* (IEEE TASSP, 1984), DOI: 10.1109/TASSP.1984.1164317 | Foundational STFT reconstruction reference; does not by itself solve partial identity/tracking. |
| **S08** | Established oversampled waveshaping/antialiasing literature (e.g. Välimäki/Pekonen/DAFx work) | Relevant to nonlinear placement/alias tests. Lower alias energy is not automatically a better zaag sound. Record the exact implementation chosen later. |
| **S09** | Jesse Engel et al., *DDSP: Differentiable Digital Signal Processing* (ICLR 2020), https://arxiv.org/abs/2001.04643 | Optional later modelling/fitting reference. DDSP is not a prerequisite for deterministic Chordness/retuning. |
| **S10** | W. A. Sethares, *Tuning, Timbre, Spectrum, Scale* | Broader timbre/tuning framework and examples. Treat culturally situated tuning practice separately from acoustic dissonance models. |

## Expectation, groove, reward and learning

| ID | Source | Why it matters / boundary |
|---|---|---|
| **S15** | Cheung et al., *Uncertainty and Surprise Jointly Predict Musical Pleasure and Amygdala, Hippocampus, and Auditory Cortex Activity* (Current Biology, 2019), PubMed: https://pubmed.ncbi.nlm.nih.gov/31708393/ | Supports studying uncertainty × surprise interaction. It does **not** establish a “two dopamine hits” mechanism. |
| **S16** | Gold et al., work on predictability/uncertainty and musical pleasure, open version: https://pmc.ncbi.nlm.nih.gov/articles/PMC6867811/ | Supports intermediate/context-dependent predictive complexity rather than “more surprise is better.” |
| **S17** | Witek et al., *Syncopation, Body-Movement and Pleasure in Groove Music* (PLOS ONE, 2014), DOI: 10.1371/journal.pone.0094446 | Evidence for nonlinear relationship between syncopation and groove/pleasure; exact optimum is listener/context dependent. |
| **S18** | Nozaradan et al., *Selective neuronal entrainment to the beat and meter embedded in a musical rhythm* (J Neurosci, 2012), PubMed: https://pubmed.ncbi.nlm.nih.gov/23223281/ | Motivates explicit metrical levels; neural measures are not required for the product feature. |
| **S19** | Burger / Thompson / Luck / Toiviainen and related motion-capture work on embodied metre and movement frequency-locking | Supports investigating movement at multiple metrical levels. Do not equate one preferred movement rate with “correct BPM.” |
| **S20** | Mehrabi, Dixon & Sandler, vocal imitation of synthesised sounds (JASA, 2017), PubMed: https://pubmed.ncbi.nlm.nih.gov/28253682/ | Supports extracting timing/pitch/loudness/spectral-shape trajectories from vocal imitation. It does not imply faithful waveform reconstruction. |
| **S21** | Studies of embodied simulation / singing or miming during musical-emotion tasks, e.g. https://journals.sagepub.com/doi/10.1177/20592043221093836 | Important counterevidence to a simple claim that active imitation always intensifies emotion; framing may matter. |
| **S22** | Movement/tapping studies with mixed or conditional affect/groove effects | Motivates measuring effort/fluency and retaining null effects rather than assuming movement is beneficial. |
| **S23** | EDM build-up/drop tension studies including Solberg/Dibben and later controlled work | Supports separating build-up tension, drop physiology, pleasure and post-event affect; “more tension = more pleasure” is not established. |
| **S24** | Kathios et al., learning/preferences in an unfamiliar musical system (Psychological Science), DOI: 10.1177/09567976231214185 | Supports testing whether exposure can teach a compact synthetic grammar. It does not license treating unfamiliarity as a cultural proxy. |
| **S25** | Salimpoor et al., *Anatomically distinct dopamine release during anticipation and experience of peak emotion to music* (Nature Neuroscience, 2011), DOI: 10.1038/nn.2726 | Establishes dopamine relevance to intense musical experience, but ordinary ratings/audio descriptors do not measure dopamine concentration. |
| **S26** | McDermott et al., cross-cultural consonance work with Tsimane' listeners (Nature, 2016), DOI: 10.1038/nature18635 | Strong caution against assuming Western harmonic preference is universal; distinguish acoustic roughness from learned syntax. |
| **S27** | Balinese gamelan/ombak acoustic literature, including coupled beating modes | Useful example where beating/roughness is desired animation rather than error; do not flatten this into a generic “non-Western tuning” trope. |
| **S28** | EDM/drop collective-movement and familiarity/groove literature | Motivates variation-window and phrase-return studies; particular genre findings require replication in zaaggenz material. |

## Anthropological / musical-system references

Use non-Western and anthropological material to broaden compositional models—directional melody, return gestures, asymmetrical phrase grammar, non-octave tuning, beating and environmental temporal inspiration—rather than as exotic labels.

Examples worth deeper source-specific review before any named pack ships: rāga-oriented directional/motif grammar; Persian dastgāh/gūša/forūd modal-journey concepts; Sama/Sama Dilaut maritime song documentation; gamelan beating/tuning practice. A synthetic algorithm inspired by “swaying cadence of the sea” should be labelled as synthetic unless it actually derives from a reviewed musical source.

## Reference audio

The privately supplied `Activation` / `Zaagtivation` pair is an observational probe. It is not redistributed in this repository and must not be treated as a causal dataset. ZG-006 owns content identification, rights/provenance notes and aligned annotations; ZG-033 owns controlled comparisons.
