# ZG-022 bouncy melodic zaag source and gesture families

ZG-022 is a curated experimental preset layer above the recovered v1.2.1 source, ZG-008 source-preserving pitch construction and the later spectral/DSP work. It deliberately does **not** replace the protected `locked_bloom` sound.

## Protected compatibility anchor

`locked_bloom` is represented only by the recovered canonical preset SHA-256 `6a6e5a55f04f978e57e90b9e582d2b830b3d82192aec7d0f727112ef75b5afe2`, its verified invariants and baseline render hashes. ZG-022 does not copy parameters from screenshots, remembered values or a reconstructed approximation. Existing product code remains authoritative for the actual preset.

No new ZG-022 recipe has `approved_default=true`. A default change requires an explicit owner decision after listening.

## Candidate families

| ID | Primary idea | Useful source range | Phase / tail | Cost | Main limitation |
|---|---|---:|---|---|---|
| `zaag.relaxed-punch` | relaxed attack/decay while retaining nonlinear edge | 27–96 Hz | source-derived / preserve | medium | can lose bite in very dense rolls |
| `zaag.vowel-sway` | moving resonant upper-mid emphasis | 24–110 Hz | source-derived / preserve | high | moving resonance can crowd wide stacks |
| `zaag.upper-bounce` | slower upper-group amplitude bounce over continuous lower body | 28–118 Hz | source-derived / preserve | medium | very fast/pitched-up use can become bright |
| `zaag.complementary-pulse` | opposed lower/upper envelopes | 24–105 Hz | source-derived / preserve | medium | crossing point can sound hollow on sparse notes |
| `zaag.grit-skip` | bounded nonlinear grit plus light sample-hold texture | 31–84 Hz | source-derived / preserve | high | intentional alias/images accumulate in dense stacks |
| `zaag.harmonic-turn` | richer partial source for explicit interval/progression manifests | 24–108 Hz | source-derived / preserve | high | wide chords can become dense |

The exposed macros are `attack_relax`, `vowel_motion`, `upper_bounce`, `complementary_motion`, `grit` and `harmonic_motion`, each bounded 0–1. Expert controls keep the underlying formant endpoints/Q, bounce depth/rate, complementary depth, nonlinear drive/mix/oversampling, sample-hold/bit depth, pitch-ratio range, phase policy, tail policy and quality cost reachable.

The macros are musical handles, not learned latent variables. They compile to explicit deterministic processing and are stored with every recipe.

## Deliberate contrasts

`contrast.piep`, `contrast.noise-wall` and `contrast.overflattened` are intentional controls. They remain in the registry so owner auditions can reject or contextualise them without deleting the evidence. Their names do not imply objective badness; they describe the intended experimental direction.

In particular, low flatness, lower clipping, higher harmonic concentration or lower roughness cannot certify a better zaag sound.

## Source rendering

Each family starts from a new versioned set of recovered `legacy.synth.1.2.1` parameter overrides. It is **not** derived by editing a reconstructed `locked_bloom` parameter set.

The post-source motion path is fixed and inspectable:

1. vowel/formant-like resonant crossfade where enabled;
2. upper-group bounce where enabled;
3. complementary low/upper envelope exchange where enabled;
4. bounded antialiased tanh and optional deterministic sample-hold/bitcrush grit.

No final normalization is performed. The vowel stage is an engineered resonant gesture, not a physiological vocal-formant model. Sample hold is allowed to produce deliberate alias/images and is documented as such.

## Example manifests

`examples/zg022_zaag_family_examples.json` freezes three reproducibility targets:

- `zg022-one-shot`: one-bar/single-note source-character check;
- `zg022-four-bar-bounce`: 32 half-beat source-derived melodic events using Upper Bounce;
- `zg022-sixteen-bar-turn`: 64 events across four explicit family/progression sections.

The arranger renders each family source **once per arrangement**, caches each required pitch ratio and reuses that source for every event. It does not re-synthesise the source topology per note. Harmonic intervals in the long example are explicit manifest degrees; no chord vocabulary is inferred.

## Owner audition gate

`build_owner_audition_pack()` produces a deterministic level-matched pack containing all six candidates and all three contrasts. Matching is whole-item RMS with peak-safe gain reduction only: no compression, clipping or hidden normalization is used to make conditions look similar.

The audition deliberately has four separate 1–7 endpoints:

- bounce;
- melodic identity;
- source character;
- practical usefulness.

There is also free-text keep/reject rationale. Rejected variants remain evidence rather than disappearing from the registry.

The generated ZG-022 pack is initially `pending-owner`. It does **not** include a reconstructed `locked_bloom` waveform; the verified existing product remains the listening anchor. The owner can compare the pack against the real protected preset. Until an explicit decision is recorded, `new_default` remains `null`.

## Evidence and claims

`tools/zaag_family_report.py` renders every family, records deterministic hashes and engineering descriptors, renders the one-shot/4-bar/16-bar examples, and can emit WAV files plus the owner-audition manifest as a CI artifact.

Spectral flatness, centroid and harmonic-band concentration are logged only to establish that the source families are measurably distinct. They are never aggregated into a preference, bounce or usefulness score.
