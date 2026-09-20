# ZG-022 bouncy melodic zaag source and gesture families

ZG-022 is a curated experimental preset layer above the recovered v1.2.1 source, ZG-008 source-preserving pitch construction and the later spectral/DSP work. It deliberately does **not** replace the protected `locked_bloom` sound.

## Protected compatibility anchor

`locked_bloom` is represented only by the recovered canonical preset SHA-256 `6a6e5a55f04f978e57e90b9e582d2b830b3d82192aec7d0f727112ef75b5afe2`, its verified invariants and baseline render hashes. ZG-022 does not copy parameters from screenshots, remembered values or a reconstructed approximation. Existing product code remains authoritative for the actual preset.

No new ZG-022 recipe has `approved_default=true`. A default change requires an explicit owner decision after listening.

## Candidate families

The first owner audition pack (PR #80, preserved again after #110/#139) was explicitly rejected on 2026-09-20 as too close to a set of dull tonal twangs and too far from the brutal zaag source brief. Corrective #229 therefore **replaces the active candidate IDs** rather than silently mutating those historical renders. The rejected audio/manifests remain preserved as research evidence in their original artifacts and git history.

The replacement set deliberately uses six different character mechanisms after the recovered source/motion stages:

| ID | Character mechanism | Useful source range | Phase / tail | Cost | Main limitation |
|---|---|---:|---|---|---|
| `zaag.bloom-bark` | relaxed front edge blooming into asymmetric fold/bark + high-band bite | 25–102 Hz | source-derived / preserve | high | dense rolls can mask the bloom-to-bark transition |
| `zaag.formant-snarl` | strong moving resonances driven into a saturated snarl | 24–108 Hz | source-derived / preserve | high | wide stacks can crowd the resonant motion |
| `zaag.upper-chop` | continuous low body with hard chopped/re-excited upper band | 27–112 Hz | source-derived / preserve | high | extreme BPM can turn the upper chop into a bright buzz |
| `zaag.split-maul` | opposed low/high spectral slams instead of a gentle crossfade | 24–104 Hz | source-derived / preserve | high | coarse alternation deliberately dominates sparse sustains |
| `zaag.crushed-teeth` | destructive nonlinear edge, low-bit hold and upper re-excitation | 29–88 Hz | source-derived / preserve | high | dense transposition loses pitch clarity fastest |
| `zaag.harmonic-rip` | dense partial source with short-comb/ring-like tearing sidebands | 24–106 Hz | source-derived / preserve | high | wide chords make the metallic rip denser |

The exposed macros remain `attack_relax`, `vowel_motion`, `upper_bounce`, `complementary_motion`, `grit` and `harmonic_motion`, each bounded 0–1. Expert controls keep formant endpoints/Q, bounce/complementary depth, nonlinear drive/oversampling, sample-hold/bit depth, pitch-ratio range, phase policy, tail policy and quality cost explicit.

The six character profiles are fixed deterministic renderer mechanisms (`bark`, `snarl`, `chop`, `split`, `crush`, `rip`). They are engineering identities, not scores. CI asserts that all six are present and that their matched source waveforms do not collapse into a near-identical degenerate set; owner listening still decides creative usefulness.

## Deliberate contrasts

`contrast.piep`, `contrast.noise-wall` and `contrast.overflattened` are intentional controls. They remain in the registry so owner auditions can reject or contextualise them without deleting the evidence. Their names do not imply objective badness; they describe the intended experimental direction.

In particular, low flatness, lower clipping, higher harmonic concentration or lower roughness cannot certify a better zaag sound.

## Source rendering

Each family starts from a new versioned set of recovered `legacy.synth.1.2.1` parameter overrides. It is **not** derived by editing a reconstructed `locked_bloom` parameter set.

The post-source motion path is fixed and inspectable:

1. vowel/formant-like resonant crossfade where enabled;
2. upper-group bounce where enabled;
3. complementary low/upper envelope exchange where enabled;
4. one explicit replacement-family character profile (`bark`, `snarl`, `chop`, `split`, `crush` or `rip`) for genuine candidates;
5. bounded antialiased tanh and optional deterministic sample-hold/bitcrush grit.

No final normalization is performed. The vowel stage is an engineered resonant gesture, not a physiological vocal-formant model. Sample hold is allowed to produce deliberate alias/images and is documented as such.

### Formant sample-rate contract

Active vowel motion uses the versioned `fail-closed-exact-v1` formant policy. A formant endpoint is admissible only when its requested centre frequency is in the inclusive range `20 Hz .. 0.45 * sample_rate_hz`. `formant_start_hz` and `formant_end_hz` are checked independently against the actual render sample rate before the recovered source is synthesised and before any formant filter executes. A reverse sweep is valid when both endpoints are in range; a sweep with either endpoint outside the range is rejected with `ZaagFamilyError`.

There is no formant-frequency clamping, remapping or hidden adaptive transform. For every successful active render, the requested and realised formant endpoints are therefore identical and are recorded in `ZaagSourceRender.diagnostics.formant` together with the policy and supported band. The exact boundary is accepted; values immediately outside it fail closed. This keeps a recipe's stored formant values semantically exact instead of allowing the same recipe identity to mean different silently-clamped frequencies at different sample rates.

The runtime check applies only when the vowel filter actually executes (`vowel_motion > 0` and non-zero formant boost). Inert formant controls do not impose an unrelated sample-rate restriction. The static recipe schema continues to bound expert formant values independently of render sample rate; the runtime contract adds the stricter rate-dependent admissibility needed by the filter.

This repair does not alter `locked_bloom`, any registered family values, source topology, protected defaults or preference status. Existing registered active vowel families already lie inside the supported band at their accepted evidence rates, so they retain their exact requested frequencies rather than receiving a new adaptation.

## Example manifests

`examples/zg022_zaag_family_examples.json` freezes three reproducibility targets:

- `zg022-one-shot`: one-bar/single-note source-character check;
- `zg022-four-bar-bounce`: 32 half-beat source-derived melodic events using Upper Bounce;
- `zg022-sixteen-bar-turn`: 64 events across four explicit family/progression sections.

The arranger renders each family source **once per arrangement**, caches each required pitch ratio and reuses that source for every event. It does not re-synthesise the source topology per note. Harmonic intervals in the long example are explicit manifest degrees; no chord vocabulary is inferred.

### Arrangement execution envelope

`ArrangementManifest` is an executable artifact, so its `1.0.0` domain is finite and is validated before source generation or arrangement allocation. The envelope is intentionally larger than the current examples while remaining proportional to the declared 1–64-bar timeline:

- at most **16 events per declared bar** (1,024 events at 64 bars), equivalent to a sustained 16th-note event grid in 4/4;
- at most **8 explicit integer degrees per event**, allowing substantially wider stacks than the current single notes/triads; the resulting worst-case admitted work is 8,192 note voices at 64 bars;
- event `beat`, `duration_beats`, and `gain_db` are finite native numbers rather than bool/string/coercible values; `0 <= beat < bars * 4`, positive duration must end within `bars * 4`, and event gain is bounded to **-120..+24 dB** so the executable linear-gain conversion is finite;
- degrees are checked against the selected family's declared pitch-ratio range by logarithmic integer-degree bounds **before** `2 ** (degree / 12)` is evaluated. There is no overflow-prone trial exponentiation and no pitch clamping;
- a one-beat family source remains duration-preserving through static transposition. Preflight reserves a conservative maximum source-tail envelope of **3 seconds**, derived from the frozen legacy synth import minimum of 20 BPM. At the largest supported arrangement (64 bars, 60 BPM, 48 kHz) the absolute output envelope is therefore **12,432,000 samples**. The normal output remains the nominal arrangement length unless a real preserved source tail crosses it.

`arrangement_work_estimate()` exposes the model-owned event, note-voice, nominal-output and conservative maximum-output cardinalities for future shared-scheduler admission. The renderer repeats admission against the manifest immediately before allocating output or synthesising a source, so mutation of nested event data cannot turn a previously accepted object into unbounded work.

These are fail-closed execution bounds, not musical transforms. No accepted event is dropped, coalesced, normalized, truncated, moved, or silently clamped. Preserve-tail ownership is unchanged: an event must start and have its authored duration inside the declared arrangement timeline, while its source-derived audio tail may extend beyond the nominal final beat only within the validated source-tail envelope. The one-shot, four-bar, and sixteen-bar example manifests remain inside this domain without any event, source, pitch, gain, topology, or DSP change.

## Owner audition gate

`build_owner_audition_pack()` produces a deterministic level-matched pack containing all six replacement candidates and all three contrasts. The evidence tool also emits a one-bar identical-pattern melodic demo for every genuine candidate so the owner is not forced to judge source identity from isolated 48 Hz hits alone. Matching is whole-item RMS with peak-safe gain reduction only: no compression, clipping or hidden normalization is used to make conditions look similar.

The audition deliberately has four separate 1–7 endpoints:

- bounce;
- melodic identity;
- source character;
- practical usefulness.

There is also free-text keep/reject rationale. Rejected variants remain evidence rather than disappearing from the registry.

The replacement pack is revision `zg022-brutal-family-redesign-229-v1` and is initially `pending-owner`. It does **not** include a reconstructed `locked_bloom` waveform; the verified existing product remains the listening anchor. The owner can compare the pack against the real protected preset. Until an explicit decision is recorded, `new_default` remains `null`.

## Evidence and claims

`tools/zaag_family_report.py` renders every family, records deterministic hashes and engineering descriptors, renders the one-shot/4-bar/16-bar examples, and can emit WAV files plus the owner-audition manifest as a CI artifact. The report also records a multi-rate formant-admissibility matrix at 8, 12, 24, 48 and 96 kHz so the fail-closed boundary remains visible in engineering evidence.

Spectral flatness, centroid and harmonic-band concentration are logged only to establish that the source families are measurably distinct. They are never aggregated into a preference, bounce or usefulness score.
