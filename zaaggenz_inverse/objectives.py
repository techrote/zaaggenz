"""Decomposed measurements and independent engineering gates, never a preference score."""
from __future__ import annotations

from copy import deepcopy
import math
import numpy as np

from zaaggenz_analysis import AnalysisCache, STFTSpec, stft, analysis_key
from zaaggenz_contracts import digest
from zaaggenz_descriptors import (pcm_asset, periodicity_observations, occupancy_observation,
    DescriptorError, DescriptorAnalysisSpec, analyse_descriptors)
from zaaggenz_qc.metrics import diagnose, source_preservation
from zaaggenz_spectral.chordness_descriptors import evaluate_union
from zaaggenz_spectral.chordness_templates import harmonic_comb
from zaaggenz_tuning import (DissonanceError, DissonanceModelSpec, harmonic_spectrum,
    spectrum_from_partial_bundle, interaction_roughness)
from .contracts import LOSS_UNITS, ObjectivePolicy, ValidationPolicy, require
from .recipes import frozen_audio, feature_engine_identity
from .transient import transient_preservation

RMS_FLOOR = 1e-8
STFT = STFTSpec(256, 64, 512)


def feature_configuration(sr, root_hz, sonority):
    """Compose the accepted component, Chordness and dissonance specifications."""
    return {'method_id': 'zg.inverse.features.v1', 'stft': STFT.metadata(),
            'channels': 'all physical channels; no mono cancellation',
            'descriptor_spec': DescriptorAnalysisSpec(max_f0_hz=min(1200., sr * .49)).to_dict(),
            'sonority_enabled': bool(sonority),
            'comb': harmonic_comb('declared-anchor', root_hz, harmonics=8, max_hz=sr/2).to_dict(),
            'dissonance_model': DissonanceModelSpec(audible_max_hz=min(20000., sr*.49)).to_dict(),
            'interaction_anchor': harmonic_spectrum('declared-anchor', root_hz, partials=8).to_dict(),
            'interaction_interval_cents': 0., 'source': 'base-recipe tuning anchor; not fixture ground truth'}


def _null(reason):
    return {'value': None, 'validity': 'abstained', 'reason': reason}


class FeatureMeasurements:
    """Bounded shared AnalysisCache, keyed by canonical PCM + all analysis methods."""
    def __setattr__(self, name, value):
        if name in ('sr', 'root_hz', 'sonority', 'method_sha256', '_configuration') and name in self.__dict__:
            raise AttributeError('feature identity configuration is immutable; create a new evaluator')
        object.__setattr__(self, name, value)

    @property
    def configuration(self):
        return deepcopy(self._configuration)

    def __init__(self, sr, root_hz, sonority=False, cache=None):
        self.sr, self.root_hz, self.sonority = sr, root_hz, sonority
        self.cache = cache if cache is not None else AnalysisCache(8)
        self._configuration = feature_configuration(sr, root_hz, sonority)
        self.method_sha256 = digest({'engine': feature_engine_identity(), 'configuration': self.configuration})
        self.calls = self.hits = 0

    def measure(self, samples):
        a = frozen_audio(samples)
        require(len(a) >= 32 and np.isfinite(a).all(), 'finite >=32-sample excerpt required')
        asset = pcm_asset(a, self.sr)
        key = analysis_key(asset, STFT, method=self.method_sha256)
        cached = self.cache.get(key)
        if cached is not None:
            self.hits += 1
            return cached[0], deepcopy(cached[1])
        self.calls += 1
        magnitude = np.abs(stft(a, self.sr, STFT).spectra)
        # Do not leave writable arrays in a shared cache.
        magnitude = np.frombuffer(np.asarray(magnitude, dtype='<f8').tobytes(), dtype='<f8').reshape(magnitude.shape)
        try:
            periodic = {o.metric: o.to_dict() for o in periodicity_observations(a, self.sr, max_f0_hz=min(1200., self.sr*.49))}
        except DescriptorError as exc:
            periodic = {'periodicity_peak': _null(str(exc)), 'f0_candidate_hz': _null(str(exc))}
        observations = {**periodic, 'spectral_occupancy': occupancy_observation(a, self.sr).to_dict()}
        sonority = None
        if self.sonority:
            # Explicit cap rather than quietly selecting a shorter, easier excerpt.
            require(len(a) <= 16384, 'sonority v1 requires caller-selected <=16384-sample windows')
            spec = DescriptorAnalysisSpec(max_f0_hz=min(1200., self.sr*.49))
            template = harmonic_comb('declared-anchor', self.root_hz, harmonics=8, max_hz=self.sr/2)
            analysis = analyse_descriptors(a, self.sr, target_hz=template.teeth_hz, spec=spec)
            union = evaluate_union(analysis.partials, (template,), tolerance_cents=spec.tolerance_cents)
            try:
                spectrum = spectrum_from_partial_bundle(analysis.partials, (len(a)-1)//2,
                    max_components=32, max_anchor_distance_samples=len(a)//4)
                interaction = interaction_roughness(spectrum,
                    harmonic_spectrum('declared-anchor', self.root_hz, partials=8), 0.,
                    DissonanceModelSpec(audible_max_hz=min(20000., self.sr*.49))).to_dict()
                spectrum_data = spectrum.to_dict()
            except DissonanceError as exc:
                interaction, spectrum_data = _null(str(exc)), None
            sonority = {'descriptors': analysis.descriptors.to_dict(), 'descriptor_sha256': analysis.descriptors.sha256,
                        'partial_bundle_sha256': analysis.partials.sha256, 'chordness': union,
                        'interaction': interaction, 'spectrum': spectrum_data}
        metadata = {'kind': 'InverseFeatures', 'version': '1.0.0', 'asset': asset,
                    'method_sha256': self.method_sha256, 'cache_key': key,
                    'stft_magnitude_f64_sha256': __import__('hashlib').sha256(magnitude.tobytes()).hexdigest(),
                    'observations': observations, 'sonority': sonority}
        self.cache.put(key, (magnitude, deepcopy(metadata)))
        return magnitude, metadata


def _matrix(a):
    a = np.asarray(a, dtype=np.float64)
    return a[:, None] if a.ndim == 1 else a


def _rms(a):
    return float(np.sqrt(np.mean(np.asarray(a, dtype=np.float64)**2)))


def _db_ratio(a, b):
    return 20. * math.log10(max(float(a), RMS_FLOOR) / max(float(b), RMS_FLOOR))


def component(name, value, *, target=None, candidate=None, reason=None):
    return {'name': name, 'unit': LOSS_UNITS[name], 'direction': 'minimize',
            'value': None if value is None else float(value), 'validity': 'valid' if value is not None else 'abstained',
            'target_measurement': target, 'candidate_measurement': candidate, 'reason': reason}


def measure_losses(target, candidate, features):
    """No gain/phase/time alignment. Retain raw and feature losses independently."""
    r, c = frozen_audio(target), frozen_audio(candidate)
    require(r.shape == c.shape and np.isfinite(c).all(), 'objective requires matching finite arrays')
    rm, rf = features.measure(r)
    cm, cf = features.measure(c)
    rr, cr = _rms(r), _rms(c)
    error = _rms(r.astype(np.float64)-c.astype(np.float64))
    signed_level = _db_ratio(cr, rr)
    losses = [component('waveform', error/max(rr, RMS_FLOOR)),
              component('spectrum', float(np.linalg.norm(cm-rm))/max(float(np.linalg.norm(rm)), RMS_FLOOR)),
              component('level', abs(signed_level), target=rr, candidate=cr)]
    for name, metric in (('periodicity', 'periodicity_peak'), ('occupancy', 'spectral_occupancy')):
        a, b = rf['observations'][metric], cf['observations'][metric]
        valid = a['validity'] == b['validity'] == 'valid'
        losses.append(component(name, abs(a['value']-b['value']) if valid else None,
                                target=a['value'], candidate=b['value'], reason=None if valid else 'descriptor abstention is not zero loss'))
    for name in ('comb_fit', 'roughness', 'interaction'):
        if not features.sonority:
            losses.append(component(name, None, reason='sonority analysis not requested'))
            continue
        def observation(f):
            s = f['sonority']
            if name == 'comb_fit': return s['chordness']['target']['target_comb_fit']
            if name == 'roughness': return s['chordness']['roughness']
            return s['interaction']
        a, b = observation(rf), observation(cf)
        valid = a['validity'] == b['validity'] == 'valid'
        losses.append(component(name, abs(a['value']-b['value']) if valid else None,
            target=a['value'], candidate=b['value'], reason=None if valid else 'descriptor abstention is not zero loss'))
    return {'kind': 'InverseWindowMeasurements', 'version': '1.0.0', 'components': losses,
            'intermediate': {'raw_rmse': error, 'reference_rms': rr, 'candidate_rms': cr,
                             'signed_level_delta_db': signed_level, 'rms_floor': RMS_FLOOR,
                             'gain_fit_diagnostic_only': source_preservation(r, c)},
            'target_features': rf, 'candidate_features': cf,
            'feature_pair_sha256': digest([rf, cf])}


def aggregate(windows, policy):
    require(isinstance(policy, ObjectivePolicy), 'ObjectivePolicy required')
    by_name = {name: [] for name in LOSS_UNITS}
    for window in windows:
        for loss in window['measurements']['components']:
            by_name[loss['name']].append(loss['value'])
    values = {k: None if len(v) != len(windows) or any(x is None for x in v) else
              math.sqrt(sum(x*x for x in v)/len(v)) for k, v in by_name.items()}
    terms = [{'name': t.name, 'value': values[t.name], 'scale': t.scale, 'weight': t.weight,
              'scaled_value': None if values[t.name] is None else values[t.name]/t.scale,
              'unit': LOSS_UNITS[t.name], 'direction': 'minimize'} for t in policy.terms]
    active = [t for t in terms if t['weight'] > 0]
    comparable = all(t['value'] is not None for t in active)
    score = math.sqrt(sum(t['weight']*t['scaled_value']**2 for t in active)/sum(t['weight'] for t in active)) if comparable else None
    return {'kind': 'InverseObjectiveVector', 'version': '1.0.0', 'components': values,
            'pareto_axes': terms, 'score': score, 'comparable': comparable,
            'window_aggregation': 'equal-window RMS; unknown on any window remains unknown',
            'score_semantics': 'explicit weighted RMS of scaled losses; engineering calibration, not preference'}


def _band_powers(x, sr):
    a = _matrix(x)
    magnitude = np.abs(np.fft.rfft(a, axis=0))**2
    f = np.fft.rfftfreq(len(a), 1/sr)
    power = np.sum(magnitude, axis=1)
    edges = [0., 200., 1000., min(4000., sr*.4), sr/2+1.]
    bands = [float(np.sum(power[(f >= lo) & (f < hi)])) for lo, hi in zip(edges, edges[1:])]
    total = float(np.sum(power))
    bandwidth = float(np.sqrt(np.sum(power*f*f)/max(total, 1e-30)))
    return bands, bandwidth


def _plateau_fraction(x):
    a = _matrix(x)
    peak = np.max(np.abs(a), axis=0)
    # Adjacent nearly-flat samples near either rail also detect saturation BELOW full-scale.
    near = np.abs(a) >= .95*np.maximum(peak, RMS_FLOOR)
    flat = np.abs(np.diff(a, axis=0)) <= 1e-4*np.maximum(peak, RMS_FLOOR)
    return float(np.mean(flat & near[1:] & near[:-1]))


def validation_measurements(target, candidate, sr, policy=ValidationPolicy(), *, pre_master=None, master_gain=1., clipping='clip_at_full_scale'):
    """Target-dependent gates see only the declared evaluation window.

    Source-internal normalization is disclosed by RenderTrace. This verifies the
    observable final-gain boundary, without guessing hidden internal gain factors.
    """
    require(isinstance(policy, ValidationPolicy), 'ValidationPolicy required')
    r, c = np.asarray(target), np.asarray(candidate)
    findings = []
    def finding(name, triggered, value, threshold, unit):
        findings.append({'gate': name, 'triggered': bool(triggered), 'allowed': name in policy.allowed,
                         'value': value, 'threshold': threshold, 'unit': unit})
    shape_ok = r.shape == c.shape and r.ndim in (1, 2) and len(r) >= 32
    finding('invalid_shape', not shape_ok, list(c.shape), list(r.shape), 'shape')
    finite = bool(np.isfinite(c).all())
    finding('non_finite', not finite, float(np.mean(np.isfinite(c))) if c.size else 0., 1., 'finite_fraction')
    magnitude_safe = finite and (not c.size or float(np.max(np.abs(c))) <= 1e100)
    finding('numerical_overflow_risk', not magnitude_safe, magnitude_safe, True, 'safe_magnitude')
    if not shape_ok or not finite or not magnitude_safe:
        return _validation_result(findings, {})
    rd, cd = diagnose(r, sr), diagnose(c, sr)
    ratio = cd['rms']/max(rd['rms'], RMS_FLOOR)
    level_delta = _db_ratio(cd['rms'], rd['rms'])
    active = rd['rms'] > RMS_FLOOR
    finding('silence_collapse', active and ratio < policy.min_rms_ratio, ratio, policy.min_rms_ratio, 'rms_ratio')
    finding('level_mismatch', abs(level_delta) > policy.max_level_delta_db, level_delta, policy.max_level_delta_db, 'dB_absolute_limit')
    rp, cp = _plateau_fraction(r), _plateau_fraction(c)
    finding('pathological_clipping', cp-rp > policy.max_plateau_excess, cp-rp, policy.max_plateau_excess, 'plateau_fraction_excess')
    rb, rw = _band_powers(r, sr)
    cb, cw = _band_powers(c, sr)
    bandwidth_ratio = cw/max(rw, RMS_FLOOR)
    finding('bandwidth_collapse', active and bandwidth_ratio < policy.min_bandwidth_ratio,
            bandwidth_ratio, policy.min_bandwidth_ratio, 'rms_frequency_ratio')
    band_ratios = [b/max(a, 1e-30) if a > sum(rb)*.01 else None for a, b in zip(rb, cb)]
    band_min = min((v for v in band_ratios if v is not None), default=1.)
    finding('energy_collapse', active and band_min < policy.min_band_energy_ratio,
            band_min, policy.min_band_energy_ratio, 'minimum_active_band_energy_ratio')

    # ZG-024 issue #87: protect target onsets without treating raw carrier derivative
    # differences as attack loss.  The candidate never selects or moves anchors.
    transient = transient_preservation(r, c, sr)
    transient_ratio = transient['ratio']
    finding('transient_loss', active and transient_ratio < policy.min_transient_ratio,
            transient_ratio, policy.min_transient_ratio, 'target_anchored_onset_preservation_ratio')

    alignment = source_preservation(r, c)  # diagnostic only, never used in acoustic score
    suspicious = alignment['gain_aligned_relative_rms'] < .03 and abs(level_delta) > policy.max_level_delta_db
    finding('normalisation_suspect', suspicious, {'gain_fit': alignment['gain_fit'], 'signed_level_delta_db': level_delta},
            {'gain_aligned_error_below': .03, 'level_delta_above': policy.max_level_delta_db}, 'diagnostic')
    provenance = None
    if pre_master is not None:
        p = np.asarray(pre_master, dtype=np.float64)
        valid_trace = (p.shape == c.shape and np.isfinite(p).all() and math.isfinite(master_gain) and master_gain > 0
                       and float(np.max(np.abs(p))) <= 1e100/max(master_gain, 1.))
        finding('invalid_gain_provenance', not valid_trace, valid_trace, True, 'boolean')
        if valid_trace:
            driven = p*master_gain
            clip_fraction = float(np.mean(np.abs(driven) > 1.)) if clipping == 'clip_at_full_scale' else 0.
            expected = np.clip(driven, -1., 1.) if clipping == 'clip_at_full_scale' else driven
            error = float(np.max(np.abs(expected.astype(np.float32).astype(np.float64)-c)))
            finding('hidden_level_handling', error > 1e-7, error, 1e-7, 'peak_linear_amplitude_error')
            finding('destructive_output_clipping', clip_fraction > 0., clip_fraction, 0., 'clipped_sample_fraction')
            provenance = {'pre_master': diagnose(p, sr), 'post_gain_pre_clip': diagnose(driven, sr),
                          'output': cd, 'gain_linear': master_gain, 'clipping': clipping, 'normalisation': 'none'}
    return _validation_result(findings, {'target': rd, 'candidate': cd, 'band_energy_ratios': band_ratios,
        'target_rms_frequency_hz': rw, 'candidate_rms_frequency_hz': cw,
        'transient_anchor_samples': transient['anchor_samples'],
        'transient_channel_ratios': transient['channel_ratios'],
        'transient_measurements': transient['channels'], 'transient_method': transient['method'],
        'transient_method_parameters': transient['parameters'],
        'gain_fit_diagnostic_only': alignment, 'final_gain_provenance': provenance})


def _validation_result(findings, measurements):
    rejected = [x['gate'] for x in findings if x['triggered'] and not x['allowed']]
    allowed = [x['gate'] for x in findings if x['triggered'] and x['allowed']]
    return {'kind': 'InverseValidation', 'version': '1.0.0',
            'state': 'rejected' if rejected else ('accepted-with-exceptions' if allowed else 'accepted'),
            'rejected_reasons': rejected, 'allowed_exceptions': allowed,
            'findings': findings, 'measurements': measurements}
