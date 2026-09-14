"""Engineering safety diagnostics kept separate from acoustic-fit objectives."""
from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np

from zaaggenz_qc.metrics import diagnose, source_preservation
from zaaggenz_dsp.graph import apply_output_policy, GraphError
from .contracts import Snapshot, document, fields, require, finite
from .objectives import _frames_rms, RMS_FLOOR


@dataclass(frozen=True)
class GatePolicy:
    silence_ratio: float = .03
    max_level_delta_db: float = 6.
    min_transient_flux_ratio: float = .35
    max_new_fullscale_fraction: float = .01
    max_new_plateau_fraction: float = .10
    min_band_energy_ratio: float = .10
    active_target_band_fraction: float = .03
    min_centroid_ratio: float = .35
    normalisation_gap_db: float = 3.

    def __post_init__(self):
        for name in ('silence_ratio', 'min_transient_flux_ratio', 'max_new_fullscale_fraction',
                     'max_new_plateau_fraction', 'min_band_energy_ratio', 'active_target_band_fraction',
                     'min_centroid_ratio'):
            object.__setattr__(self, name, finite(getattr(self, name), name, 0., 1.))
        for name in ('max_level_delta_db', 'normalisation_gap_db'):
            object.__setattr__(self, name, finite(getattr(self, name), name, .01, 120.))
        require(self.active_target_band_fraction > 0, 'active target band threshold must be positive')

    def to_dict(self):
        return document('InverseGatePolicy', **{k: getattr(self, k) for k in self.__dataclass_fields__},
                        normalisation='none', output_clipping='reject-any-destructive-clipping',
                        interpretation='engineering guardrails, not musical-quality judgements')

    @classmethod
    def from_dict(cls, data):
        names = tuple(cls.__dataclass_fields__)
        fields(data, (*names, 'normalisation', 'output_clipping', 'interpretation'), 'InverseGatePolicy')
        out = cls(**{k: data[k] for k in names})
        require(out.to_dict() == data, 'unsupported gate semantics')
        return out


def screen_output(audio):
    """Cheap public preflight: never silently replace NaN/Inf with usable audio."""
    a = np.asarray(audio)
    if a.ndim not in (1, 2) or not a.size or (a.ndim == 2 and a.shape[1] not in (1, 2)):
        return {'valid': False, 'code': 'invalid_shape', 'finite_fraction': None}
    if not np.issubdtype(a.dtype, np.number) or np.iscomplexobj(a):
        return {'valid': False, 'code': 'invalid_numeric_type', 'finite_fraction': None}
    fraction = float(np.mean(np.isfinite(a)))
    if fraction < 1.:
        return {'valid': False, 'code': 'nonfinite_output', 'finite_fraction': fraction}
    if np.max(np.abs(a)) > 1e6:
        return {'valid': False, 'code': 'excessive_output', 'finite_fraction': fraction}
    return {'valid': True, 'code': None, 'finite_fraction': fraction}


def _plateau(audio):
    a = np.asarray(audio, dtype=np.float64)
    if a.ndim == 1:
        a = a[:, None]
    peak = np.max(np.abs(a), axis=0)
    if not np.any(peak > RMS_FLOOR):
        return 0.
    stationary = np.abs(np.diff(a, axis=0)) <= np.maximum(peak, RMS_FLOOR) * 1e-5
    near_peak = np.abs(a[1:]) >= .8 * peak
    active = peak > RMS_FLOOR
    return float(np.mean(stationary[:, active] & near_peak[:, active]))


def _transient(reference, candidate, rate):
    ref = _frames_rms(reference, rate)
    cand = _frames_rms(candidate, rate)
    # Exclude an invented onset at the excerpt boundary. No samples outside this
    # fitting/held-out support are read to construct the novelty measurement.
    change = np.diff(ref)
    threshold = max(.15 * float(np.max(ref)), 4. * float(np.median(np.abs(change))), RMS_FLOOR)
    indices = np.flatnonzero(change > threshold)
    tc = np.maximum(0., np.diff(cand))
    ref_flux = float(np.sum(change[indices]))
    cand_flux = sum(float(np.max(tc[max(0, i - 1):min(len(tc), i + 2)])) for i in indices)
    return {'target_onset_blocks': indices.tolist(), 'block_samples': max(8, round(rate * .002)),
            'target_positive_flux': ref_flux, 'candidate_positive_flux': cand_flux,
            'flux_ratio': cand_flux / ref_flux if ref_flux > RMS_FLOOR else None,
            'threshold': threshold, 'tolerance_blocks': 1,
            'interpretation': '2 ms RMS novelty at target onsets; no perceptual attack claim'}


def validate_window(target, rendered, window, target_features, candidate_features, policy):
    require(isinstance(policy, GatePolicy), 'GatePolicy required')
    ref = target.audio
    before = rendered.before_gain.audio[window.start:window.end]
    out = rendered.output.audio[window.start:window.end]
    codes = []
    preflight = screen_output(out)
    if not preflight['valid']:
        return {'valid': False, 'codes': [preflight['code']], 'screen': preflight}
    t, c = target_features.to_dict(), candidate_features.to_dict()
    tq, cq = t['qc'], c['qc']
    ratio = cq['rms'] / max(tq['rms'], RMS_FLOOR)
    level_db = 20. * math.log10(max(cq['rms'], RMS_FLOOR) / max(tq['rms'], RMS_FLOOR))
    if tq['rms'] > RMS_FLOOR and ratio < policy.silence_ratio:
        codes.append('silence_collapse')
    if abs(level_db) > policy.max_level_delta_db:
        codes.append('level_mismatch')
    transient = _transient(ref, out, target.rate)
    if transient['flux_ratio'] is not None and transient['flux_ratio'] < policy.min_transient_flux_ratio:
        codes.append('transient_loss')
    if cq['abs_ge_1_fraction'] > tq['abs_ge_1_fraction'] + policy.max_new_fullscale_fraction:
        codes.append('fullscale_excess')
    plateau_delta = _plateau(out) - _plateau(ref)
    if plateau_delta > policy.max_new_plateau_fraction:
        codes.append('saturation_excess')
    energy = np.asarray(t['band_energy'])
    after_energy = np.asarray(c['band_energy'])
    active = energy > max(float(np.sum(energy)) * policy.active_target_band_fraction, 1e-20)
    band_ratios = [float(b / max(a, 1e-20)) if on else None for a, b, on in zip(energy, after_energy, active)]
    lost = [i for i, value in enumerate(band_ratios) if value is not None and value < policy.min_band_energy_ratio]
    if lost:
        codes.append('band_energy_collapse')
    centroid_ratio = c['spectral_centroid_hz'] / max(t['spectral_centroid_hz'], 1e-12)
    if t['spectral_centroid_hz'] > 30 and centroid_ratio < policy.min_centroid_ratio:
        codes.append('bandwidth_collapse')
    output_policy = rendered.policy.to_dict()
    declared_gain = output_policy['master_gain_db']
    unbounded = before.astype(np.float64) * 10. ** (declared_gain / 20.)
    clip_fraction = float(np.mean(np.abs(unbounded) > 1.))
    if output_policy['clipping'] == 'clip_at_full_scale' and clip_fraction > 0.:
        codes.append('destructive_output_clipping')
    try:
        expected, _ = apply_output_policy(before, output_policy)
        consistent = bool(np.array_equal(expected, out))
    except GraphError:
        consistent = False
    if not consistent:
        codes.append('gain_provenance_mismatch')
    preservation = source_preservation(ref, out)
    gain_fit = abs(preservation['gain_fit'])
    gain_fit_db = 20. * math.log10(max(gain_fit, 1e-12))
    # This gain-aligned error is diagnostic ONLY. The actual waveform loss never
    # applies this fitted gain, even when it would flatter a quiet candidate.
    if (preservation['gain_aligned_relative_rms'] < .05 and abs(gain_fit_db) > policy.normalisation_gap_db) or not consistent:
        codes.append('normalisation_exploit')
    return {'valid': not codes, 'codes': codes, 'screen': preflight, 'target_qc': tq, 'candidate_qc': cq,
            'level_ratio': ratio, 'level_delta_db': level_db, 'transient': transient,
            'plateau_fraction': {'target': _plateau(ref), 'candidate': _plateau(out), 'delta': plateau_delta},
            'band_energy_ratios': band_ratios, 'lost_active_bands': lost, 'centroid_ratio': centroid_ratio,
            'gain_aligned_diagnostic_only': preservation,
            'gain_provenance': {'declared_master_gain_db': declared_gain, 'normalisation': output_policy['normalisation'],
                'before_gain_qc': diagnose(before, target.rate), 'after_gain_unclipped_qc': diagnose(unbounded, target.rate),
                'actual_output_qc': cq, 'output_clip_fraction': clip_fraction, 'policy_consistent': consistent}}
