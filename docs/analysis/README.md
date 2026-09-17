# Shared multiresolution analysis v1

ZG-012 separates **what owns resynthesis** from additional observations.

## Canonical representation

`zg-multiresolution-features-v1` uses a periodic Hann window, hop N/4, explicit half-window zero padding and raw real-FFT units. The medium-resolution STFT is the only `canonical-resynthesis` representation. Its window-squared overlap normalization reconstructs mono/stereo input to numerical precision, including edges and very short files.

Short and long STFTs are marked `observation` and `istft()` rejects them. They cannot accidentally be combined with the canonical representation and double spectral energy.

At 48 kHz the target supports are roughly 11 ms / 43 ms / 341 ms (power-of-two windows). Actual window/hop/bin resolution is always stored in metadata. The long view can separate close low components that the short view cannot, but its hundreds-of-milliseconds support is visible to callers rather than presented as instantaneous onset information.

## Resource envelope

Custom STFT execution is governed by `zg-stft-resource-bounds-v1`. `window_samples` and `fft_samples` are each limited to **32,768 samples** and are rejected at `STFTSpec` admission when they exceed that bound. The limit makes the historical 32,768-sample ceiling already used by `resolution_specs()` authoritative for custom execution as well. It covers all existing default short/medium/long resolutions across the supported 8–192 kHz sample-rate range; the 192 kHz long observation is the boundary case. Accepted values are never silently reduced, coarsened or truncated.

Dimensions alone are not enough because a legal 32,768-sample window with hop 1 can materialise tens of gigabytes of overlapping weighted frames. `stft()` therefore also enforces a **256 MiB conservative live-storage ceiling** before float64 conversion, padding, frame materialisation or FFT allocation. This is an analysis-owned bound chosen to match the repository's default per-job scheduler ceiling; it does not import scheduler policy into the lower-level analysis package. Requests over the ceiling fail explicitly rather than changing hop/window/FFT settings.

`estimate_stft_resources(source_frames, channels, spec)` provides deterministic pre-allocation accounting. It reports exact padded/frame cardinality plus conservative Python-visible array storage for the possible float64 source copy, padded signal, Hann window, materialised weighted frames, complex128 RFFT output and result-support arrays. `fft_point_count = frame_count * channels * fft_samples` is exposed as a deterministic work proxy. `estimated_live_bytes` deliberately does **not** claim to include caller-owned input buffers, Python object overhead, allocator fragmentation, NumPy/SciPy/FFT-backend scratch space or process-wide memory, so callers should retain normal process headroom.

`validate_stft_resources(source_frames, channels, spec, max_live_bytes=...)` is the shared admission entry point for asynchronous consumers. Its default ceiling is the analysis-owned 256 MiB maximum; a scheduler/inspector/inverse adapter may pass a **stricter** positive limit derived from its own remaining lane/job budget. It returns the same `STFTResourceEstimate` on acceptance and includes the requested estimate and active bound in a rejection. Callers cannot raise the limit above the shared analysis ceiling, so asynchronous admission and direct `stft()` execution cannot disagree by admitting a request the analysis layer itself would reject.

Resource validation rechecks the full `STFTSpec` at execution time, so a malformed/tampered frozen object cannot bypass constructor admission. Source length, channel count, hop and FFT dimensions all participate in the preflight; this prevents a small hop from evading the dimension bounds. A one-second 48 kHz stereo request at the maximum window/FFT with hop 1, for example, is estimated above 50 GB and is rejected without padding or FFT allocation. Existing one-second stereo default resolutions at every supported sample-rate boundary remain below the shared ceiling.

This resource policy is a fail-closed correction to the existing v1 execution envelope, not a spectral-method or cache-identity revision. `STFTSpec.metadata()` is unchanged, so every request that remains accepted retains its exact analysis/cache identity and numerical meaning. Existing default resolution selection is unchanged. Legacy custom documents above either the dimension or live-storage bounds are rejected explicitly; they are not migrated by hidden downsampling, hop changes or FFT-size repair.

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
