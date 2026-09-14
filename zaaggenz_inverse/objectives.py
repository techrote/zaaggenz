"""Raw-level objectives + inherited descriptors, never one irreversible score."""
from __future__ import annotations

from dataclasses import dataclass
import math
import threading

import numpy as np

from zaaggenz_contracts import digest, loads
from zaaggenz_analysis import STFTSpec, stft, AnalysisCache
from zaaggenz_components import analyse_components, ComponentTrackerSpec
from zaaggenz_descriptors import DescriptorAnalysisSpec, analyse_descriptors
from zaaggenz_qc.metrics import diagnose
from zaaggenz_spectral.chordness_model import CombTemplate
from zaaggenz_spectral.chordness_descriptors import evaluate_union
from zaaggenz_tuning.dissonance_source import spectrum_from_partial_bundle
from zaaggenz_tuning.dissonance_model import DissonanceModelSpec, DissonanceError
from zaaggenz_tuning.dissonance_curve import interaction_roughness
from .contracts import Snapshot, document, fields, require, finite, MAX_FRAMES
from .render import AudioBuffer

# name: (unit of raw loss, normalising scale, default scalar-search weight).
# These engineering tolerances are NOT calibrated perceptual thresholds.
LOSS_SPECS = {
    'waveform': ('target-rms-ratio', 1., 1.),
    'envelope': ('target-rms-ratio', 1., .5),
    'spectrum': ('dB', 20., .5),
    'level': ('dB', 6., .5),
    'periodicity': ('unitless', 1., .1),
    'occupancy': ('unitless', 1., .1),
    'roughness': ('unitless', 1., .1),
    'comb_fit': ('unitless', 1., .1),
    'comb_precision': ('unitless', 1., .1),
    'dissonance_profile': ('unitless', 1., .1),
}
AXES = tuple(LOSS_SPECS)
FEATURE_METHOD = 'zg.inverse.measured-window.v1.1'
RMS_FLOOR = 1e-8
SPECTRUM_FLOOR = 1e-6


@dataclass(frozen=True, init=False)
class ObjectivePlan(Snapshot):
    def __init__(self, *, weights=None, scales=None, templates=(), stft_spec=STFTSpec(256, 64, 256),
                 descriptor_spec=DescriptorAnalysisSpec(max_samples=MAX_FRAMES), dissonance_intervals=(0., 702.),
                 component_spec=ComponentTrackerSpec(assignment_cost_policy='integer-microcent-v1')):
        require(isinstance(stft_spec, STFTSpec) and stft_spec.role == 'observation', 'observation STFTSpec required')
        require(stft_spec.window_samples <= 4096 and stft_spec.fft_samples <= 4096, 'bounded inverse STFT required')
        require(isinstance(descriptor_spec, DescriptorAnalysisSpec), 'DescriptorAnalysisSpec required')
        require(descriptor_spec.max_samples <= MAX_FRAMES, 'descriptor bound exceeds inverse PCM bound')
        require(isinstance(component_spec, ComponentTrackerSpec), 'ComponentTrackerSpec required')
        require(component_spec.max_tracks <= 16, 'inverse component cap exceeds 16')
        weights = {} if weights is None else weights
        scales = {} if scales is None else scales
        require(type(weights) is dict and set(weights) <= set(AXES), 'unknown objective weight')
        require(type(scales) is dict and set(scales) <= set(AXES), 'unknown objective scale')
        metrics = {k: {'unit': unit, 'scale': finite(scales.get(k, scale), 'scale', 1e-9, 1e6),
                       'weight': finite(weights.get(k, weight), 'weight', 0, 100)}
                   for k, (unit, scale, weight) in LOSS_SPECS.items()}
        require(any(v['weight'] > 0 for v in metrics.values()), 'at least one objective weight must be positive')
        require(isinstance(templates, (tuple, list)) and len(templates) <= 8
                and all(isinstance(t, CombTemplate) for t in templates), 'bounded existing CombTemplate values required')
        require(len({t.id for t in templates}) == len(templates), 'duplicate comb template')
        require(len({f for t in templates for f in t.teeth_hz}) <= 128, 'comb union exceeds 128 teeth')
        intervals = tuple(finite(x, 'dissonance interval', -2400, 2400) for x in dissonance_intervals)
        require(1 <= len(intervals) <= 8 and len(set(intervals)) == len(intervals), '1..8 distinct dissonance probes required')
        super().__init__(document('InverseObjectivePlan', metrics=metrics, axes=list(AXES),
            stft=stft_spec.metadata(), descriptors=descriptor_spec.to_dict(), components=component_spec.metadata(), templates=[t.to_dict() for t in templates],
            dissonance_intervals_cents=list(intervals), level_policy='unmatched-unclamped',
            rms_floor=RMS_FLOOR, spectrum_amplitude_floor=SPECTRUM_FLOOR,
            unavailable_policy='target-only-applicability; candidate-abstention-is-not-zero'))

    @classmethod
    def from_dict(cls, data):
        keys = ('metrics', 'axes', 'stft', 'descriptors', 'components', 'templates', 'dissonance_intervals_cents',
                'level_policy', 'rms_floor', 'spectrum_amplitude_floor', 'unavailable_policy')
        fields(data, keys, 'InverseObjectivePlan')
        require(type(data['metrics']) is dict and set(data['metrics']) == set(AXES), 'objective inventory mismatch')
        out = cls(weights={k: v['weight'] for k, v in data['metrics'].items()},
                  scales={k: v['scale'] for k, v in data['metrics'].items()},
                  stft_spec=STFTSpec(**data['stft']), descriptor_spec=DescriptorAnalysisSpec(**data['descriptors']),
                  component_spec=ComponentTrackerSpec(**data['components']),
                  templates=tuple(CombTemplate(**t) for t in data['templates']),
                  dissonance_intervals=tuple(data['dissonance_intervals_cents']))
        require(out.to_dict() == data, 'unsupported or noncanonical objective configuration')
        return out


def _rms(a):
    return float(np.sqrt(np.mean(np.asarray(a, dtype=np.float64) ** 2)))


def _frames_rms(audio, rate):
    a = np.asarray(audio, dtype=np.float64)
    if a.ndim == 1:
        a = a[:, None]
    # Partial final frame remains visible: no omitted tail or time warping.
    block = max(8, round(rate * .002))
    return np.asarray([_rms(a[s:s + block]) for s in range(0, len(a), block)])


def _measure(buffer, plan):
    a, rate = buffer.audio, buffer.rate
    cfg = plan.to_dict()
    spec = DescriptorAnalysisSpec(**cfg['descriptors'])
    components = analyse_components(a, rate, ComponentTrackerSpec(**cfg['components']))
    desc = analyse_descriptors(a, rate, partials=components.bundle, spec=spec).descriptors
    observations = {o.metric: o.to_dict() for o in desc.observations}
    templates = tuple(CombTemplate(**v) for v in cfg['templates'])
    comb = evaluate_union(components.bundle, templates, tolerance_cents=spec.tolerance_cents) if templates else None
    model = DissonanceModelSpec(audible_max_hz=min(20000., rate / 2.))
    dissonance = None
    try:
        timbre = spectrum_from_partial_bundle(components.bundle, (len(a) - 1) // 2,
                                               max_components=min(32, spec.component_cap),
                                               max_anchor_distance_samples=max(1, len(a) // 2))
        points = [interaction_roughness(timbre, timbre, cents, model).to_dict()
                  for cents in cfg['dissonance_intervals_cents']]
        if all(p['value'] is not None for p in points):
            dissonance = points
    except DissonanceError:
        pass  # Explicit abstention, never an invented zero.
    s = stft(a, rate, STFTSpec(**cfg['stft']))
    # Mean channel power avoids anti-phase cancellation; amplitude is in FS units.
    power = np.mean(np.abs(s.spectra) ** 2, axis=(0, 1)) / (s.spec.window_samples / 2.) ** 2
    amplitude = np.sqrt(power)
    spectrum_db = 20. * np.log10(np.maximum(amplitude, SPECTRUM_FLOOR))
    freq = s.frequencies_hz()
    edges = np.linspace(0., rate / 2., 9)
    bands = [float(np.sum(power[(freq >= lo) & ((freq < hi) if i < 7 else (freq <= hi))]))
             for i, (lo, hi) in enumerate(zip(edges, edges[1:]))]
    total = float(np.sum(power))
    centroid = float(np.dot(freq, power) / total) if total > 1e-24 else 0.
    return Snapshot(document('InverseWindowFeatures', asset=buffer.asset.to_dict(), method=FEATURE_METHOD,
        descriptor_bundle=desc.to_dict(), partials_sha256=components.bundle.sha256, observations=observations,
        chordness=comb, dissonance=dissonance, dissonance_model=model.to_dict(),
        spectrum_db=spectrum_db.tolist(), envelope_rms=_frames_rms(a, rate).tolist(),
        band_energy=bands, band_edges_hz=edges.tolist(), spectral_centroid_hz=centroid,
        qc=diagnose(a, rate), padding='STFT zero padding within this excerpt only'))


class FeatureStore:
    """Reuse ZG-012's bounded AnalysisCache and optional ZG-003 ArtifactCache.

    A single lock protects both caches when shared by local scheduler jobs. Cache
    locators/hit counts never enter acoustic or candidate identity.
    """
    def __init__(self, execution, *, max_entries=64, artifact_cache=None):
        self.execution = Snapshot(execution)
        self.memory = AnalysisCache(max_entries)
        self.disk = artifact_cache
        self.hits = self.misses = 0
        self._lock = threading.RLock()

    def measure(self, buffer, plan):
        require(isinstance(buffer, AudioBuffer) and isinstance(plan, ObjectivePlan), 'canonical buffer and objective plan required')
        key = digest({'domain': FEATURE_METHOD, 'asset': buffer.asset.to_dict(), 'plan': {k: v for k, v in plan.to_dict().items() if k != 'metrics'},
                      'execution': self.execution.to_dict()})
        with self._lock:
            found = self.memory.get(key)
            if found is None and self.disk is not None:
                payload = self.disk.get(key)
                if payload is not None:
                    saved = loads(payload)
                    require(saved['key'] == key and saved['features']['asset'] == buffer.asset.to_dict(), 'cached feature identity mismatch')
                    found = Snapshot(saved['features'])
            if found is not None:
                self.hits += 1
                self.memory.put(key, found)
                return found
            self.misses += 1
            found = _measure(buffer, plan)
            self.memory.put(key, found)
            if self.disk is not None:
                payload = Snapshot({'key': key, 'features': found.to_dict()})._json
                self.disk.put(key, payload, buffer.asset.to_dict())
            return found


def _descriptor(data, name):
    row = data['observations'].get(name)
    return row['value'] if row and row['validity'] == 'valid' else None


def measurement_values(features):
    d = features.to_dict()
    target = d['chordness']['target'] if d['chordness'] else {}
    def comb(name):
        row = target.get(name)
        return row['value'] if row and row['validity'] == 'valid' else None
    return {'periodicity': _descriptor(d, 'periodicity_peak'),
            'occupancy': _descriptor(d, 'spectral_occupancy'),
            'roughness': _descriptor(d, 'roughness_pairwise'),
            'comb_fit': comb('target_comb_fit'), 'comb_precision': comb('target_comb_precision'),
            'dissonance_profile': None if d['dissonance'] is None else [p['value'] for p in d['dissonance']]}


def compare_window(target, candidate, target_features, candidate_features, plan):
    require(target.audio.shape == candidate.audio.shape and target.rate == candidate.rate, 'objective audio alignment mismatch')
    t, c = target_features.to_dict(), candidate_features.to_dict()
    tr = t['qc']['rms']
    raw = {
        'waveform': _rms(candidate.audio.astype(np.float64) - target.audio) / max(tr, RMS_FLOOR),
        'envelope': _rms(np.asarray(c['envelope_rms']) - np.asarray(t['envelope_rms'])) / max(tr, RMS_FLOOR),
        'spectrum': _rms(np.asarray(c['spectrum_db']) - np.asarray(t['spectrum_db'])),
        'level': abs(20. * math.log10(max(c['qc']['rms'], RMS_FLOOR) / max(tr, RMS_FLOOR))),
    }
    tv, cv = measurement_values(target_features), measurement_values(candidate_features)
    statuses = {k: 'valid' for k in raw}
    for name in tv:
        if tv[name] is None:
            raw[name], statuses[name] = None, 'not_applicable'
        elif cv[name] is None:
            raw[name], statuses[name] = None, 'unavailable'
        else:
            raw[name] = _rms(np.asarray(cv[name]) - np.asarray(tv[name]))
            statuses[name] = 'valid'
    cfg = plan.to_dict()['metrics']
    losses = {name: dict(raw=raw[name], scaled=None if raw[name] is None else raw[name] / cfg[name]['scale'],
                        unit=cfg[name]['unit'], scale=cfg[name]['scale'], status=statuses[name]) for name in AXES}
    summary = {'target': {**tv, 'rms': tr, 'band_energy': t['band_energy'], 'centroid_hz': t['spectral_centroid_hz']},
               'candidate': {**cv, 'rms': c['qc']['rms'], 'band_energy': c['band_energy'], 'centroid_hz': c['spectral_centroid_hz']},
               'signed_level_delta_db': 20. * math.log10(max(c['qc']['rms'], RMS_FLOOR) / max(tr, RMS_FLOOR))}
    return {'losses': losses, 'measurements': summary, 'target_feature_id': target_features.sha256,
            'candidate_feature_id': candidate_features.sha256}


def aggregate(windows, plan):
    require(bool(windows), 'at least one measured window required')
    cfg = plan.to_dict()['metrics']
    losses = {}
    for name in AXES:
        rows = [w['objective']['losses'][name] for w in windows]
        applicable = [r for r in rows if r['status'] != 'not_applicable']
        state = ('not_applicable' if not applicable else
                 'unavailable' if any(r['status'] != 'valid' for r in applicable) else 'valid')
        raw = float(np.mean([r['raw'] for r in applicable])) if state == 'valid' else None
        losses[name] = {'raw': raw, 'scaled': None if raw is None else raw / cfg[name]['scale'],
                        'unit': cfg[name]['unit'], 'scale': cfg[name]['scale'], 'status': state,
                        'applicable_windows': len(applicable)}
    complete = not any(r['status'] == 'unavailable' for r in losses.values())
    weighted = [(losses[k]['scaled'], cfg[k]['weight']) for k in AXES
                if losses[k]['status'] == 'valid' and cfg[k]['weight'] > 0]
    score = sum(v * w for v, w in weighted) / sum(w for _, w in weighted) if weighted and complete else None
    return {'components': losses, 'axes': list(AXES), 'vector': [losses[k]['scaled'] for k in AXES],
            'applicable': [losses[k]['status'] != 'not_applicable' for k in AXES],
            'complete': complete, 'search_score': score,
            'aggregation': 'equal-window-mean; target-only applicability; configured weighted mean'}
