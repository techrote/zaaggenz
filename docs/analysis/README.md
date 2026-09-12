# Shared multiresolution analysis v1

ZG-012 separates **what owns resynthesis** from additional observations.

## Canonical representation

`zg-multiresolution-features-v1` uses a periodic Hann window, hop N/4, explicit half-window zero padding and raw real-FFT units. The medium-resolution STFT is the only `canonical-resynthesis` representation. Its window-squared overlap normalization reconstructs mono/stereo input to numerical precision, including edges and very short files.

Short and long STFTs are marked `observation` and `istft()` rejects them. They cannot accidentally be combined with the canonical representation and double spectral energy.

At 48 kHz the target supports are roughly 11 ms / 43 ms / 341 ms (power-of-two windows). Actual window/hop/bin resolution is always stored in metadata. The long view can separate close low components that the short view cannot, but its hundreds-of-milliseconds support is visible to callers rather than presented as instantaneous onset information.

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
