"""Opt-in 48-kHz IEEE-float WAV bytes from a current Compose-controlled NYQ render.

This is a stacked production adapter, not a graph/rack registration or the
ordinary Compose export route. No files are written and no defaults change.
Source authority and final handoff belong to #275's ComposeControlledSource.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import io

import numpy as np
from scipy.io import wavfile

from zaaggenz_contracts import digest
from zaaggenz_contracts.nyquismic import EvaluationPolicy, ResourceBudget, SonicSpec
from zaaggenz_dsp.nyquismic_delivery import (
    DeliveryConversionPolicy, admit_delivery_stages, convert_numerical_to_delivery,
)
from zaaggenz_jobs import JobError
from zaaggenz_runtime.nyquismic_compose import ComposeControlledSource


OUTPUT_RATE_HZ = 48000
METHOD = 'nyq.compose-controlled-48k-float-wav.v1'


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise JobError('controlled Compose 48-kHz WAV: ' + reason)


@dataclass(frozen=True)
class ComposeControlledWav48k:
    """In-memory WAV receipt, authenticated only at the handoff that produced it."""
    wav_bytes: bytes
    wav_sha256: str
    pcm_f32le_sha256: str
    numerical_f64le_sha256: str
    converted_f64le_sha256: str
    source_asset_sha256: str
    source_revision_sha256: str
    recipe_sha256: str
    packet_sha256: str
    sampler_render_sha256: str
    conversion_policy_sha256: str
    conversion_kernel_sha256: str
    sample_rate_hz: int
    numerical_rate_hz: int
    frames: int
    channels: int
    identity_sha256: str


def render_compose_controlled_48k_wav(
    binding: ComposeControlledSource,
    sonic: SonicSpec,
    packet,
    evaluation: EvaluationPolicy,
    *,
    policy: DeliveryConversionPolicy = DeliveryConversionPolicy(),
    budget: ResourceBudget = ResourceBudget(),
    cancelled=None,
) -> ComposeControlledWav48k:
    """Run the complete authored-route, full-phrase pipeline and emit WAV bytes.

    Reuse #275's authenticated current Compose source, #267 packet and #266
    controlled sampler; convert *after* the artistic renderer using #252's
    bounded FIR. Require an exactly representable 48-kHz physical end. Emit
    32-bit float WAV (never integer-PCM clipping or peak normalization).
    No disk side effects: the final serialized artifact is published under
    the same Compose/job/session lock boundary used by #275.
    """
    _require(type(binding) is ComposeControlledSource,
             'expected an actual Compose-controlled source binding')
    _require(type(sonic) is SonicSpec and type(evaluation) is EvaluationPolicy,
             'sonic and evaluation policies must be versioned NYQ records')
    _require(type(policy) is DeliveryConversionPolicy and type(budget) is ResourceBudget,
             'delivery policy and budget must be versioned NYQ records')
    _require(cancelled is None or callable(cancelled), 'invalid cancellation hook')
    binding._guard()

    # The packet owns the musical/physical end; neither a caller-supplied
    # frame count nor a rounded WAV tail may replace it.
    extent = Fraction(packet.full_end_s) - Fraction(sonic.clock.origin_s)
    _require(extent > 0 and
             (extent * OUTPUT_RATE_HZ).denominator == 1 and
             (extent * evaluation.evaluation_rate_hz).denominator == 1,
             'packet duration must fit both numerical and 48-kHz grids exactly')
    # This candidate publishes a complete owned Compose phrase, not a
    # caller-selected shortened packet that silently drops the source tail.
    asset = binding.source.asset.to_dict()
    source_extent = Fraction(asset['frame_count'], binding.source.sample_rate_hz)
    _require(extent == source_extent,
             'packet must cover the complete owned Compose PCM physical extent')
    numerical_frames = int(extent * evaluation.evaluation_rate_hz)
    final_frames = int(extent * OUTPUT_RATE_HZ)
    channels = asset['channels']
    _require(numerical_frames * channels <= budget.max_frames and
             final_frames * channels <= budget.max_frames,
             'physical extent exceeds delivery budget')

    # Preflight the declared filter budget before expensive sampler evaluation.
    admit_delivery_stages(evaluation.evaluation_rate_hz, OUTPUT_RATE_HZ,
                          policy=policy, budget=budget, frames=numerical_frames)
    handle = binding.prepare(sonic, packet, evaluation, cancelled=cancelled)
    numeric = handle.render(cancelled=cancelled)
    _require(len(numeric.audio) == numerical_frames,
             'controlled source did not render its full physical extent')
    converted = convert_numerical_to_delivery(
        numeric.audio, evaluation.evaluation_rate_hz, OUTPUT_RATE_HZ,
        policy=policy, budget=budget, cancelled=cancelled)
    _require(converted.audio.shape[0] == final_frames,
             'FIR output changed exact packet duration')
    _require(converted.diagnostics['source_pcm_sha256'] ==
             numeric.diagnostics['pcm_sha256'],
             'FIR input does not match the published numerical sampler PCM')

    # Explicitly admit IEEE float32 output; reject overflow rather than clamp.
    with np.errstate(over='ignore', invalid='ignore'):
        pcm = np.array(converted.audio, dtype='<f4', order='C', copy=True)
    _require(np.isfinite(pcm).all(), 'float32 export would overflow')
    pcm_bytes = pcm.tobytes(order='C')
    buffer = io.BytesIO()
    wavfile.write(buffer, OUTPUT_RATE_HZ, pcm)
    raw_wav = buffer.getvalue()
    header_rate, decoded = wavfile.read(io.BytesIO(raw_wav))
    _require(header_rate == OUTPUT_RATE_HZ and decoded.dtype == np.float32 and
             decoded.shape == pcm.shape and
             decoded.tobytes(order='C') == pcm_bytes,
             'serialized WAV header or decoded PCM disagrees with delivery')

    wav_hash = hashlib.sha256(raw_wav).hexdigest()
    pcm_hash = hashlib.sha256(pcm_bytes).hexdigest()
    identity = digest({
        'domain': METHOD,
        'source': binding.source.asset.sha256,
        'revision': binding.timeline_revision_id,
        'recipe': binding.recipe_sha256,
        'packet': packet.sha256,
        'sampler_render': numeric.render_sha256,
        'numerical_f64': numeric.diagnostics['pcm_sha256'],
        'conversion_policy': policy.sha256,
        'conversion_kernel': converted.diagnostics['kernel_sha256'],
        'converted_f64': converted.diagnostics['output_pcm_sha256'],
        'delivery_rate_hz': OUTPUT_RATE_HZ,
        'frames': final_frames,
        'channels': channels,
        'pcm_f32le': pcm_hash,
        'wav': wav_hash,
    })
    result = ComposeControlledWav48k(
        raw_wav, wav_hash, pcm_hash, numeric.diagnostics['pcm_sha256'],
        converted.diagnostics['output_pcm_sha256'],
        binding.source.asset.sha256, binding.timeline_revision_id,
        binding.recipe_sha256, packet.sha256, numeric.render_sha256,
        policy.sha256, converted.diagnostics['kernel_sha256'],
        OUTPUT_RATE_HZ, evaluation.evaluation_rate_hz, final_frames, channels,
        identity,
    )
    return binding._publish(result, cancelled=cancelled)
