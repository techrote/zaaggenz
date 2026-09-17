"""Phase-robust transient-preservation diagnostics for inverse eligibility.

This module owns only the inverse-search safety diagnostic. It intentionally does
not change the accepted ZG-019 placement metrics, acoustic objective, renderer, or
candidate proposal logic.
"""
from __future__ import annotations

import numpy as np

METHOD_ID = 'zg.inverse.transient-onset-contrast.v4'
RMS_FLOOR = 1e-8
ANCHOR_WINDOW_SECONDS = .004
ANCHOR_RELATIVE_PEAK = .25
ANCHOR_MIN_CONTRAST = .05
ANCHOR_SEPARATION_SECONDS = .012
MAX_ANCHORS_PER_CHANNEL = 8
EARLY_SECONDS = .006
LATE_END_SECONDS = .024
HIGH_BAND_MAX_HZ = 1000.
HIGH_BAND_SR_FRACTION = .20
HIGH_BAND_FRACTION_FLOOR = 1e-4


def _matrix(value):
    a = np.asarray(value, dtype=np.float64)
    return a[:, None] if a.ndim == 1 else a


def _rms(value):
    a = np.asarray(value, dtype=np.float64)
    return float(np.sqrt(np.mean(a*a))) if len(a) else 0.


def _onset_contrast(value, sample_rate_hz):
    """Return target/candidate normalized positive RMS rise at every sample."""
    a = np.asarray(value, dtype=np.float64)
    radius = max(1, round(sample_rate_hz*ANCHOR_WINDOW_SECONDS))
    square = a*a
    cumulative = np.concatenate(([0.], np.cumsum(square)))
    index = np.arange(len(a), dtype=np.int64)
    pre_lo = np.maximum(0, index-radius)
    pre_hi = index
    post_lo = index
    post_hi = np.minimum(len(a), index+radius)
    pre_rms = np.sqrt((cumulative[pre_hi]-cumulative[pre_lo]) /
                      np.maximum(pre_hi-pre_lo, 1))
    post_rms = np.sqrt((cumulative[post_hi]-cumulative[post_lo]) /
                       np.maximum(post_hi-post_lo, 1))
    contrast = np.maximum(post_rms-pre_rms, 0.) / np.maximum(post_rms, RMS_FLOOR)
    return contrast, radius


def _target_anchors(value, sample_rate_hz):
    """Select only target-derived anchors; a candidate can never move them."""
    contrast, radius = _onset_contrast(value, sample_rate_hz)
    if len(value) < 2*radius+1:
        return [], contrast
    eligible = np.arange(radius, len(value)-radius, dtype=np.int64)
    if not len(eligible):
        return [], contrast
    peak = float(np.max(contrast[eligible]))
    threshold = max(ANCHOR_MIN_CONTRAST, ANCHOR_RELATIVE_PEAK*peak)
    separation = max(1, round(sample_rate_hz*ANCHOR_SEPARATION_SECONDS))
    anchors = []
    for raw_index in eligible[np.argsort(-contrast[eligible], kind='stable')]:
        index = int(raw_index)
        if contrast[index] < threshold:
            break
        if all(abs(index-other) >= separation for other in anchors):
            anchors.append(index)
        if len(anchors) == MAX_ANCHORS_PER_CHANNEL:
            break
    return anchors, contrast


def _high_band_fraction(value, sample_rate_hz):
    """Attack-local high-band power fraction, not a global timbre score."""
    a = np.asarray(value, dtype=np.float64)
    if len(a) < 2:
        return 0.
    window = np.hanning(len(a))
    power = np.abs(np.fft.rfft(a*window))**2
    total = float(np.sum(power))
    if total <= 1e-30:
        return 0.
    frequency = np.fft.rfftfreq(len(a), 1./sample_rate_hz)
    cutoff = min(HIGH_BAND_MAX_HZ, HIGH_BAND_SR_FRACTION*sample_rate_hz)
    return float(np.sum(power[frequency >= cutoff])/total)


def _anchor_record(target, candidate, target_contrast, candidate_contrast,
                   index, sample_rate_hz):
    early = max(1, round(sample_rate_hz*EARLY_SECONDS))
    late_end = max(early+1, round(sample_rate_hz*LATE_END_SECONDS))
    target_early = target[index:min(len(target), index+early)]
    target_late = target[min(len(target), index+early):min(len(target), index+late_end)]
    candidate_early = candidate[index:min(len(candidate), index+early)]
    candidate_late = candidate[min(len(candidate), index+early):min(len(candidate), index+late_end)]

    if not len(target_late) or not len(candidate_late):
        # Target anchor selection normally excludes this case. Keep the record
        # finite and conservative if a future very-low-rate boundary reaches it.
        onset_ratio = amplitude_ratio = spectral_ratio = score = 1.
        applicable = False
        target_hf_early = target_hf_late = candidate_hf_early = candidate_hf_late = 0.
    else:
        onset_ratio = (float(candidate_contrast[index]) /
                       max(float(target_contrast[index]), RMS_FLOOR))
        target_amplitude = _rms(target_early)/max(_rms(target_late), RMS_FLOOR)
        candidate_amplitude = _rms(candidate_early)/max(_rms(candidate_late), RMS_FLOOR)
        amplitude_ratio = (candidate_amplitude/max(target_amplitude, RMS_FLOOR)
                           if target_amplitude > RMS_FLOOR else 1.)

        target_hf_early = _high_band_fraction(target_early, sample_rate_hz)
        target_hf_late = _high_band_fraction(target_late, sample_rate_hz)
        candidate_hf_early = _high_band_fraction(candidate_early, sample_rate_hz)
        candidate_hf_late = _high_band_fraction(candidate_late, sample_rate_hz)
        applicable = (target_hf_early >= HIGH_BAND_FRACTION_FLOOR and
                      target_hf_late >= HIGH_BAND_FRACTION_FLOOR)
        if applicable:
            target_spectral = target_hf_early/max(target_hf_late, RMS_FLOOR)
            candidate_spectral = candidate_hf_early/max(candidate_hf_late, RMS_FLOOR)
            spectral_ratio = (candidate_spectral/max(target_spectral, RMS_FLOOR)
                              if target_spectral > RMS_FLOOR else 1.)
        else:
            spectral_ratio = 1.
        score = min(max(onset_ratio, 0.), max(amplitude_ratio, 0.),
                    max(spectral_ratio, 0.))

    return {
        'anchor_sample': int(index),
        'target_onset_contrast': float(target_contrast[index]),
        'candidate_onset_contrast': float(candidate_contrast[index]),
        'onset_contrast_ratio': float(onset_ratio),
        'amplitude_ratio': float(amplitude_ratio),
        'spectral_ratio': float(spectral_ratio),
        'spectral_applicable': bool(applicable),
        'target_high_band_fraction_early': float(target_hf_early),
        'target_high_band_fraction_late': float(target_hf_late),
        'candidate_high_band_fraction_early': float(candidate_hf_early),
        'candidate_high_band_fraction_late': float(candidate_hf_late),
        'score': float(score),
    }


def transient_preservation(target, candidate, sample_rate_hz):
    """Measure target-anchored attack preservation per physical channel.

    Attack components are deliberately relative: global gain, root and timbre may
    change without becoming attack loss, while a candidate can never choose or
    move target anchors. A gain-normalized per-channel activity component also
    prevents complete loss of one physical channel from becoming invisible when
    aggregate stereo level remains plausible.
    """
    target_matrix, candidate_matrix = _matrix(target), _matrix(candidate)
    if target_matrix.shape != candidate_matrix.shape:
        raise ValueError('transient preservation requires matching arrays')

    target_global_rms = _rms(target_matrix.reshape(-1))
    candidate_global_rms = _rms(candidate_matrix.reshape(-1))
    if target_global_rms > RMS_FLOOR and candidate_global_rms > RMS_FLOOR:
        global_gain_ratio = candidate_global_rms/target_global_rms
    elif target_global_rms > RMS_FLOOR:
        global_gain_ratio = 0.
    else:
        global_gain_ratio = 1.

    channel_ratios, channel_anchors, channels = [], [], []
    for channel in range(target_matrix.shape[1]):
        reference = target_matrix[:, channel]
        proposal = candidate_matrix[:, channel]
        anchors, target_contrast = _target_anchors(reference, sample_rate_hz)
        candidate_contrast, _ = _onset_contrast(proposal, sample_rate_hz)
        records = [_anchor_record(reference, proposal, target_contrast,
                                  candidate_contrast, index, sample_rate_hz)
                   for index in anchors]
        anchor_ratio = min((record['score'] for record in records), default=1.)

        target_channel_rms = _rms(reference)
        candidate_channel_rms = _rms(proposal)
        if target_channel_rms <= RMS_FLOOR:
            channel_activity_ratio = 1.
        elif global_gain_ratio <= RMS_FLOOR:
            channel_activity_ratio = 0.
        else:
            local_gain_ratio = candidate_channel_rms/max(target_channel_rms, RMS_FLOOR)
            channel_activity_ratio = local_gain_ratio/global_gain_ratio
        ratio = min(anchor_ratio, max(channel_activity_ratio, 0.))

        channel_ratios.append(float(ratio))
        channel_anchors.append(anchors)
        channels.append({
            'channel': channel,
            'ratio': float(ratio),
            'anchor_ratio': float(anchor_ratio),
            'channel_activity_ratio': float(channel_activity_ratio),
            'target_channel_rms': float(target_channel_rms),
            'candidate_channel_rms': float(candidate_channel_rms),
            'anchors': records,
        })
    aggregate = min(channel_ratios, default=1.)
    return {
        'method': METHOD_ID,
        'ratio': float(aggregate),
        'channel_ratios': channel_ratios,
        'anchor_samples': channel_anchors,
        'channels': channels,
        'global': {
            'target_rms': float(target_global_rms),
            'candidate_rms': float(candidate_global_rms),
            'gain_ratio': float(global_gain_ratio),
        },
        'parameters': {
            'anchor_window_ms': ANCHOR_WINDOW_SECONDS*1000.,
            'anchor_relative_peak': ANCHOR_RELATIVE_PEAK,
            'anchor_min_contrast': ANCHOR_MIN_CONTRAST,
            'anchor_separation_ms': ANCHOR_SEPARATION_SECONDS*1000.,
            'max_anchors_per_channel': MAX_ANCHORS_PER_CHANNEL,
            'early_ms': EARLY_SECONDS*1000.,
            'late_end_ms': LATE_END_SECONDS*1000.,
            'high_band_cutoff_hz': min(HIGH_BAND_MAX_HZ, HIGH_BAND_SR_FRACTION*sample_rate_hz),
            'high_band_fraction_floor': HIGH_BAND_FRACTION_FLOOR,
            'channel_activity': ('candidate/target channel RMS gain divided by candidate/target '
                                 'global RMS gain; target-inactive channel is neutral'),
            'aggregation': ('minimum of target-anchor preservation and gain-normalized channel '
                            'activity over all physical channels'),
        },
    }
