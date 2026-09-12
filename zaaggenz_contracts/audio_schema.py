"""Observation and component formats with explicit support/units/ownership."""
import math
from .schema import *

FEATURE_UNITS = {
    'f0': 'Hz', 'rms': 'linear_amplitude', 'spectral_centroid': 'Hz',
    'roughness_score': 'unitless', 'chord_fit_score': 'unitless',
    'loudness_integrated': 'LUFS', 'true_peak': 'dBTP',
}


def audio():
    observation = obj(feature=enum(*FEATURE_UNITS), unit=enum(*sorted(set(FEATURE_UNITS.values()))),
                      value=nullable(num()), role=enum('target', 'estimate', 'measurement'),
                      validity=enum('valid', 'unknown', 'abstained'), confidence=nullable(num(0, 1)),
                      support=SUPPORT)
    frame = obj(support=SUPPORT, frequency_hz=num(0.000001, 96000),
                amplitudes=array(num(0, 1e6), 1, 2), phases_radians=array(num(-math.pi, math.pi), 1, 2),
                confidence=num(0, 1), action=enum('transform', 'preserve'))
    track = obj(id=ID, segment_id=ID, continuity=enum('continuous', 'reanchored', 'unknown'),
                frames=array(frame, 1, 8192))
    return {
        'AudioAssetRef': contract('AudioAssetRef', content_sha256=HASH,
            identity_domain=enum('encoded-file-bytes-v1', 'pcm-f32le-interleaved-v1'),
            sample_rate_hz=RATE, channels=CHANNELS, channel_layout=enum('mono', 'stereo-lr'),
            frame_count=integer(), level_domain=enum('source', 'pre_master', 'post_master'),
            sample_policy=const('unclamped_float')),
        'FeatureBundle': contract('FeatureBundle', asset=ref('AudioAssetRef'), method=METHOD,
                                   observations=array(observation, 0, 8192)),
        'PartialTrackBundle': contract('PartialTrackBundle', asset=ref('AudioAssetRef'), method=METHOD,
            phase_convention=const('cosine-at-anchor-radians-v1'),
            channel_policy=const('shared-frequency-independent-channel-coefficients'),
            data_origin=enum('estimated', 'source_known'), tracks=array(track, 0, 256),
            residual_asset=nullable(ref('AudioAssetRef')), transient_asset=nullable(ref('AudioAssetRef')),
            remainder_policy=const('additive-owned-remainders-v1')),
    }
