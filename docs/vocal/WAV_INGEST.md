# Vocal WAV ingest and canonical PCM identity

ZG-032 treats uploaded WAV bytes as an encoding boundary. The WAV container itself is not the semantic source identity: supported samples are decoded once into canonical float32 PCM, and the PCM content hash is computed from those canonical samples.

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

## Content identity versus authoritative source identity

`pcm-f32le-interleaved-v1` names the canonical PCM **content-hash domain**. `SessionAudioStore` and `analyse_vocal()` compute a full SHA-256 over little-endian, C-order, interleaved float32 bytes after decoding. Correctly decoded uint8 uploads therefore receive the same PCM content hash they would receive if those exact canonical samples arrived through another supported representation.

ZG-032 analysis/edit version `1.1.0` adds a distinct authoritative source identity domain, `zaaggenz-vocal-source-v1`. Its full `capture-v1-<64 hex>` digest binds the PCM content SHA-256 plus sample rate, channel count and frame count. Consequently identical flattened PCM bytes interpreted at a different sample rate or channel layout cannot reuse/rebind the same source identity. Origin remains separately recorded provenance and is covered by the enclosing immutable analysis/edit digest; it is not an interpretation field in the source digest. A session-store attempt to attach a different origin to an already-known semantic source is rejected instead of rewriting provenance.

No filesystem path, original filename or private locator participates in either digest.

## Compatibility

Raw capture PCM is session-local and is not embedded in the exported Timeline document. Source provenance embedded in a `1.1.0` VocalAnalysis/VocalEdit survives raw-source discard.

Existing ZG-032 `1.0.0` analysis/edit documents used a truncated `capture-<16 hex>` identifier whose meaning did not bind sample rate or channel interpretation. They are immutable historical evidence and are **not** silently reinterpreted as metadata-complete identities. Loading those documents through the `1.1.0` model fails closed with an explicit instruction to re-import/re-analyse from retained source audio. No guessed migration exists after raw source has been discarded.

The earlier uint8 correction follows the same rule: if an older analysis was created from incorrectly decoded uint8 WAV, explicitly re-importing that WAV under the corrected decoder produces corrected canonical PCM, a new PCM content hash and a new metadata-complete vocal source identity. Neither the old source hash nor old analysis evidence is rewritten in place.
