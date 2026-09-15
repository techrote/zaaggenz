# Vocal WAV ingest and canonical PCM identity

ZG-032 treats uploaded WAV bytes as an encoding boundary. The WAV container itself is not the semantic source identity: supported samples are decoded once into canonical float32 PCM, and the existing `pcm-f32le-interleaved-v1` identity is computed from those canonical samples.

## Integer and float decoding

`decode_wav_bytes()` follows the sample representation returned by the supported SciPy WAV reader and applies these explicit rules:

| SciPy sample dtype | Canonical float32 rule | Endpoint notes |
| --- | --- | --- |
| `uint8` | `(code - 128) / 128` | WAV digital silence `128` is exactly `0.0`; `0` maps to `-1.0`; `255` maps to `127/128` (`0.9921875`). The one-code positive/negative asymmetry is inherent in the 8-bit PCM representation and is not compensated by gain or clipping. |
| signed integer PCM | `code / max(abs(dtype.min), dtype.max)` | Existing signed behavior is retained. For `int16` the divisor is 32768; for `int32` it is 2147483648. SciPy exposes 24-bit PCM left-justified in an `int32` container, so this rule also preserves its full-scale interpretation. |
| floating-point WAV | cast to float32 without level, offset, or clipping changes | NaN and positive/negative infinity are rejected after conversion. Finite values outside `[-1, 1]` remain finite unclipped float samples. |

Only `uint8` is accepted as an unsigned integer PCM representation. Any other unsigned integer dtype reaching the decoder fails explicitly rather than being interpreted with a guessed midpoint. Unsupported/compressed WAV encodings rejected by SciPy remain rejected as invalid PCM/float WAV input.

The decoder does not normalize loudness, remove DC, clip, resample, or otherwise repair the signal. Mono and stereo layout are preserved.

## Why uint8 is special

8-bit PCM WAV stores zero around code 128. Treating it like a signed integer and dividing `0..255` by a positive full-scale value maps silence to roughly `+0.5`, creating a large synthetic DC component before analysis and hashing. The canonical rule above removes the representation offset only; it does not alter the recorded waveform beyond decoding its declared PCM convention.

## Identity and compatibility

`SessionAudioStore` and `analyse_vocal()` continue to hash little-endian, C-order, interleaved float32 PCM under `pcm-f32le-interleaved-v1`. Correctly decoded uint8 uploads therefore receive identities derived from `(code - 128) / 128`, exactly like any other source after it has crossed the WAV encoding boundary.

Raw capture PCM is session-local and is not embedded in the exported Timeline document. Existing ZG-032 analysis/edit documents are immutable evidence for the PCM that was observed when they were created; this repair does **not** rewrite their stored source hashes or reinterpret them in place. If an older analysis was created from an incorrectly decoded uint8 WAV, explicitly re-importing that WAV under the corrected decoder produces a new canonical PCM identity and new analysis evidence. That identity change is intentional and must not be hidden by migration or hash rewriting.

This correction is the decoding prerequisite for the separate vocal semantic-identity repair in #104. #104 must bind any future persisted source identity to the corrected canonical PCM semantics rather than preserving the historical uint8 decoding error.
