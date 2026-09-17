# Shared multiresolution analysis v1

ZG-012 separates **what owns resynthesis** from additional observations.

## Canonical representation

`zg-multiresolution-features-v1` uses a periodic Hann window, hop N/4, explicit half-window zero padding and raw real-FFT units. The medium-resolution STFT is the only `canonical-resynthesis` representation. Its window-squared overlap normalization reconstructs mono/stereo input to numerical precision, including edges and very short files.

Short and long STFTs are marked `observation` and `istft()` rejects them. They cannot accidentally be combined with the canonical representation and double spectral energy.

At 48 kHz the target supports are roughly 11 ms / 43 ms / 341 ms (power-of-two windows). Actual window/hop/bin resolution is always stored in metadata. The long view can separate close low components that the short view cannot, but its hundreds-of-milliseconds support is visible to callers rather than presented as instantaneous onset information.

## Resource envelope

Custom STFT execution is governed by `zg-stft-resource-bounds-v1`. `window_samples` and `fft_samples` are each limited to **32,768 samples** and are rejected at `STFTSpec` admission when they exceed that bound. The limit makes the historical 32,768-sample ceiling already used by `resolution_specs()` authoritative for custom execution as well. It covers all existing default short/medium/long resolutions across the supported 8–192 kHz sample-rate range; the 192 kHz long observation is the boundary case. Accepted values are never silently reduced, coarsened or truncated.

`estimate_stft_resources(source_frames, channels, spec)` provides deterministic pre-allocation accounting for downstream job admission. It reports exact padded/frame cardinality plus conservative Python-visible array storage for the float64 source view/copy, padded signal, Hann window, materialised weighted frames, complex128 RFFT output and result-support arrays. `fft_point_count = frame_count * channels * fft_samples` is exposed as a simple deterministic work proxy. `estimated_live_bytes` deliberately does **not** claim to include caller-owned input buffers, Python object overhead, allocator fragmentation, NumPy/SciPy/FFT-backend scratch space or process-wide memory. Schedulers therefore apply their normal safety headroom above the reported module-owned estimate rather than treating it as peak RSS.

Resource validation is performed before padding, sliding-window materialisation or FFT allocation. A malformed/tampered `STFTSpec` is revalidated at the execution boundary, so it cannot bypass constructor admission. Source length still contributes linearly to the reported frame/work estimate; callers that execute analysis asynchronously should use that estimate in their own finite memory/work admission policy rather than relying on a caller-supplied guess.

This resource policy is a fail-closed correction to the existing v1 execution envelope, not a spectral-method or cache-identity revision. `STFTSpec.metadata()` is unchanged, so every previously valid default/in-bound spec retains its existing analysis/cache identity and numerical meaning. Legacy custom documents above the new bound are rejected explicitly; they are not migrated by hidden downsampling or FFT-size repair.

## Feature timelines

Each frame stores:
- anchor sample and half-open support interval;
- fraction of support backed by real source samples rather than padding;
- validity mask;
- spectral centroid/flatness/dominant frequency;
- spectral flux where a predecessor is valid;
- bounded prominent-frequency candidates.

Silence yields invalid/`None` spectral features, never a fabricated 0 Hz observation. Stereo frequencies use mean spectral power for observation while channel-resolved complex spectra remain in the canonical representation.

## Cache and provenance

`analysis_key()` includes audio content identity/domain, sample rate, channel count, method, complete STFT settings/role and channel policy. Source/window/channel changes therefore invalidate the cache. The initial `AnalysisCache` is a bounded local LRU for immutable in-process results; durable project artefacts remain ZG-003/RunManifest territory.

## Intervals and reference overlays

`select_interval()` supports explicit support-overlap or anchor selection. `overlay_landmarks()` projects reference annotations into an analysis sample rate and returns frame indices/labels; it does not upgrade automatic suggestions to accepted correspondence.

CQT/ERB adapters are deliberately absent from v1: no accepted use case currently requires duplicating another transform. They can be added later as observation-only adapters with explicit cost/support if a downstream task demonstrates the need.
