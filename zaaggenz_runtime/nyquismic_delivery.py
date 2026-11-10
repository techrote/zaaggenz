"""Opt-in 48-kHz float-WAV handoff for a source-bound Compose NYQ render.

Candidate stacked on the #275 post-Compose full-mix adapter. This module does
not register an effect, alter the project/export route or attest to an upstream
feature graph. Numerical evaluation, virtual clock and delivery are distinct.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from hashlib import sha256
import io

import numpy as np
from scipy.io import wavfile
from scipy.signal import firwin, resample_poly

from zaaggenz_dsp.nyquismic_controlled_consumer import ControlledSamplerPlan
from zaaggenz_runtime.nyquismic_compose import ComposeControlledRender, _require


DELIVERY_RATE_HZ = 48_000
SUPPORTED_EVALUATION_HZ = (192_000, 384_000, 768_000)
MAX_WAV_BYTES = 128 * 1024 * 1024
METHOD = 'nyq.compose-fullmix-float32-wav48-kaiser86-v1'


@dataclass(frozen=True)
class ControlledWav48:
    """A complete, independently hashable in-memory RIFF/IEEE-float artifact."""

    wave_bytes: bytes
    source_revision_id: str
    source_recipe_sha256: str
    source_asset_sha256: str
    controlled_render_sha256: str
    evaluation_rate_hz: int
    delivery_rate_hz: int
    frame_count: int
    channels: int
    filter_coefficients_sha256: str
    numerical_pcm_sha256: str
    delivery_pcm_sha256: str
    wav_sha256: str
    method: str = METHOD

    def receipt(self) -> dict:
        """JSON-compatible receipt; raw audio remains in wave_bytes only."""
        return {field.name: getattr(self, field.name) for field in fields(self)
                if field.name != 'wave_bytes'}


def _convert_48k(audio: np.ndarray, evaluation_rate_hz: int, channels: int):
    """Finite full-grid FIR conversion, no clipping, normalization or dither.

    Zero extension at phrase boundaries and a 20*decimation+1 symmetric Kaiser
    FIR define ringing and edge support. The fixed output grid contains every
    48-kHz sample time strictly before the admitted numerical end time (ceil).
    No evaluation-rate convergence is inferred from this single fixed pass.
    """
    _require(type(evaluation_rate_hz) is int and
             evaluation_rate_hz in SUPPORTED_EVALUATION_HZ,
             'delivery requires an admitted 192/384/768-kHz evaluation grid')
    _require(type(channels) is int and channels in (1, 2),
             'delivery supports only mono or stereo')
    x = np.asarray(audio)
    _require(x.ndim == (1 if channels == 1 else 2) and
             (channels == 1 or x.shape[1] == 2) and len(x) > 0,
             'invalid numerical PCM/channel shape')
    _require(x.dtype in (np.dtype('float32'), np.dtype('float64')) and
             np.isfinite(x).all(), 'finite floating-point numerical PCM required')
    down = evaluation_rate_hz // DELIVERY_RATE_HZ
    expected = (len(x) + down - 1) // down
    _require(expected * channels * 4 + 64 <= MAX_WAV_BYTES,
             'delivery exceeds bounded in-memory WAV budget')
    taps = firwin(20 * down + 1, cutoff=1 / down,
                  window=('kaiser', 8.6), pass_zero='lowpass')
    # Explicit taps and zero padding; preserve out-of-range finite float
    # amplitudes rather than silently clipping to [-1, 1].
    y = resample_poly(x.astype(np.float64, copy=False), 1, down,
                      axis=0, window=taps, padtype='constant', cval=0.0)
    _require(len(y) == expected and np.isfinite(y).all(),
             'delivery FIR failed fixed-duration/finite admission')
    pcm = np.asarray(y, dtype='<f4', order='C')
    _require(np.isfinite(pcm).all(), 'float32 export overflow/nonfinite PCM')
    tap_sha = sha256(np.asarray(taps, dtype='<f8').tobytes()).hexdigest()
    return pcm, tap_sha


def export_compose_controlled_wav48(handle: ComposeControlledRender, *, cancelled=None) -> ControlledWav48:
    """Serialize a current full-phrase NYQ result; refuse stale publication.

    Only a #275-authenticated handle is admitted. All DSP/RIFF serialization is
    performed outside the Compose edit locks; the last handoff is revalidated
    through the adapter's same synchronized publication point. This returns
    bytes and a receipt, not a writable file path or a registered UI export.
    """
    _require(type(handle) is ComposeControlledRender and
             type(handle._plan) is ControlledSamplerPlan,
             'an authenticated Compose-to-NYQ SamplerPlan is required')
    _require(cancelled is None or callable(cancelled), 'invalid cancellation hook')
    binding = handle.source_binding
    binding._guard()
    _require(cancelled is None or not cancelled(), 'caller cancelled export')
    plan = handle._plan
    channels = binding.source.asset.to_dict()['channels']
    result = handle.render(cancelled=cancelled)
    _require(result.render_sha256 == plan.render_sha256 and
             len(result.audio) == plan.frame_count,
             'numerical PCM does not cover the authenticated full render')
    delivery_pcm, taps_sha = _convert_48k(result.audio, plan.sample_rate_hz, channels)
    _require(cancelled is None or not cancelled(), 'caller cancelled conversion')
    buffer = io.BytesIO()
    wavfile.write(buffer, DELIVERY_RATE_HZ, delivery_pcm)
    payload = buffer.getvalue()
    _require(len(payload) <= MAX_WAV_BYTES, 'encoded WAV exceeds export budget')
    receipt = ControlledWav48(
        wave_bytes=payload,
        source_revision_id=binding.timeline_revision_id,
        source_recipe_sha256=binding.recipe_sha256,
        source_asset_sha256=binding.source.asset.sha256,
        controlled_render_sha256=result.render_sha256,
        evaluation_rate_hz=plan.sample_rate_hz,
        delivery_rate_hz=DELIVERY_RATE_HZ,
        frame_count=len(delivery_pcm),
        channels=channels,
        filter_coefficients_sha256=taps_sha,
        numerical_pcm_sha256=sha256(np.asarray(result.audio, dtype='<f8', order='C').tobytes()).hexdigest(),
        delivery_pcm_sha256=sha256(delivery_pcm.tobytes(order='C')).hexdigest(),
        wav_sha256=sha256(payload).hexdigest(),
    )
    return binding._publish(receipt, cancelled=cancelled)
