"""MBR-002: execute the saved SYNTHLINE rack using the ZG-021 primitives.

The dry path is never split/recombined. Inserts run in saved order, then the
band wet is applied before the existing effect-delta confinement; rack wet is
applied to the combined delta. This module does not run a master or normalize.
"""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import hashlib
import math
import numpy as np
import scipy

from zaaggenz_contracts import digest
from zaaggenz_contracts.rack import RackRecipe, RackCompatibilityError
from zaaggenz_dsp.band_router import route_band_processors, filter_metadata, BAND_NAMES
from zaaggenz_dsp.multiband import split_bands
from .band_selective import BandSlotSpec, process_builtin_stage
from .rack_adapter import insert_spec

EXECUTOR_VERSION = 'zg.saved-rack-executor.1.0.0'
RESOURCE_POLICY = 'zg.saved-rack-full-context-budget.1.0.0'
MAX_WORKING_BYTES = 256 * 1024**2
MAX_TRACK_FRAME_EVALUATIONS = 250_000
MAX_FFT_POINTS = 256_000_000


@dataclass(frozen=True)
class CompiledRack:
    recipe: RackRecipe
    specs: tuple[tuple[object, ...], ...]
    active: tuple[bool, ...]

    @property
    def identity(self):
        return not any(self.active)


def compile_rack(rack, source_recipe=None):
    """Validate every stored field, including inactive/unavailable insert state."""
    saved = RackRecipe(rack.to_dict() if isinstance(rack, RackRecipe) else rack)
    if source_recipe is not None:
        saved.require_source(source_recipe)
    data = saved.to_dict()
    specs = tuple(tuple(insert_spec(i, data['sample_rate_hz']) for i in b['inserts'])
                  for b in data['bands'])
    active = []
    for band, typed in zip(data['bands'], specs):
        values = {}
        for insert, spec in zip(band['inserts'], typed):
            if not insert['bypass'] and insert['wet'] != 0:
                stage = insert['type_id'].removeprefix('zg.')
                values['gain_db' if stage == 'gain' else stage] = spec
        # The legacy whole-slot identity rule is intentional. A spectral
        # amount-zero insert inside another active chain still observes the
        # legacy float32 analysis boundary; do not independently optimize it out.
        identity = BandSlotSpec(**values).identity
        active.append(not (data['bypass'] or data['wet'] == 0 or band['bypass'] or
                           band['wet'] == 0 or identity))
    return CompiledRack(saved, specs, tuple(active))


@lru_cache(maxsize=1)
def implementation_identity():
    """Installed algorithm bytes + numerical library versions, not a mutable tag.

    LF normalization makes the identity portable across checkout platforms.
    Evaluated once per immutable installed process, not once per audio frame.
    """
    root = Path(__file__).resolve().parents[1]
    packages = ('zaaggenz_spectral', 'zaaggenz_components', 'zaaggenz_analysis',
                'zaaggenz_dsp', 'zaaggenz_tuning', 'zaaggenz_melody',
                'zaaggenz_contracts', 'zaaggenz_zaag', 'zaaggenz_timeline')
    files = {}
    for package in packages:
        for path in sorted((root / package).rglob('*.py')):
            raw = path.read_bytes().replace(b'\r\n', b'\n')
            files[path.relative_to(root).as_posix()] = hashlib.sha256(raw).hexdigest()
    # Include the actual installed, accepted source renderer/SCULPT bytes.
    import importlib.util
    legacy = importlib.util.find_spec('uptempo_harmony.synth')
    if legacy is None or legacy.origin is None:
        raise RackCompatibilityError('accepted source implementation is unavailable')
    for path in sorted(Path(legacy.origin).parent.rglob('*.py')):
        relative = path.relative_to(Path(legacy.origin).parent).as_posix()
        files['uptempo_harmony/' + relative] = hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    return digest({'domain': EXECUTOR_VERSION, 'python_modules': files,
                   'numpy': np.__version__, 'scipy': scipy.__version__})


def estimate_rack_resources(rack, frames):
    """Conservative whole-context peak reservation plus finite analysis work.

    Bands/analyses execute sequentially. PCM scratch is reserved once; retained
    component frame/decision/JSON objects and matrix work are explicitly added.
    No region discount, source synthesis allocation, or final-master credit.
    """
    compiled = compile_rack(rack.recipe if isinstance(rack, CompiledRack) else rack)
    data = compiled.recipe.to_dict(); sr = data['sample_rate_hz']; channels = data['channels']
    if type(frames) is not int or not 0 <= frames <= sr * 60:
        raise RackCompatibilityError('rack full context must be between zero and 60 seconds')
    # Includes dry/outputs, four split bands, sosfiltfilt and delta/leakage
    # scratch, compressor vectors, meters and final finite-float validation.
    pcm_bytes = frames * channels * 8 * 64
    live = 2 * 1024**2 + pcm_bytes
    analyses = 0; fft_points = 0; track_frames = 0
    if not compiled.identity and frames < 8:
        raise RackCompatibilityError('nonzero multiband processing requires at least 8 samples')
    from zaaggenz_components.model import ComponentTrackerSpec
    from zaaggenz_analysis.stft import STFTSpec, estimate_stft_resources, resolution_specs
    tracker = ComponentTrackerSpec()
    for band, specs, active in zip(data['bands'], compiled.specs, compiled.active):
        if not active:
            continue
        for insert, spec in zip(band['inserts'], specs):
            if insert['type_id'] != 'zg.spectral' or spec is None or insert['bypass'] or insert['wet'] == 0:
                continue
            analyses += 1
            window = 2 ** round(math.log2(sr * tracker.window_seconds))
            stft_spec = STFTSpec(window, window // tracker.hop_fraction,
                                 window * tracker.fft_factor, role='observation')
            resources = [estimate_stft_resources(frames, channels, stft_spec)]
            resources += [estimate_stft_resources(frames, channels, value)
                          for value in resolution_specs(sr).values()]
            candidates = resources[0].frame_count * tracker.max_tracks
            track_frames += candidates
            fft_points += sum(value.fft_point_count for value in resources)
            # 4096 bytes/track-frame covers multiple Python dictionaries, JSON
            # snapshots, decisions and retained original/transformed bundles.
            objects = candidates * 4096
            # Least-squares sin/cos matrices and reconstruction frame scratch.
            matrices = window * tracker.max_tracks * channels * 8 * 16
            # Tracker STFT remains alive while candidate rows are assembled;
            # observation feature timelines can overlap their temporary spectra.
            spectral_live = sum(value.estimated_live_bytes for value in resources)
            live = max(live, 2 * 1024**2 + pcm_bytes + objects + matrices + spectral_live)
    if track_frames > MAX_TRACK_FRAME_EVALUATIONS or fft_points > MAX_FFT_POINTS:
        raise RackCompatibilityError('rack full-context analysis exceeds finite work budget')
    return {'policy': RESOURCE_POLICY, 'frames': frames, 'channels': channels,
            'estimated_live_bytes': live, 'spectral_analyses': analyses,
            'track_frame_evaluations': track_frames, 'fft_point_count': fft_points,
            'context_policy': 'whole-phrase-then-crop', 'analyses_execute': 'sequential'}


def _meter(audio):
    x = np.asarray(audio, dtype=np.float64)
    # Scaling avoids spurious overflow in RMS for large, finite valid input.
    peak = float(np.max(np.abs(x), initial=0))
    rms = 0. if not peak else peak * float(np.sqrt(np.mean((x / peak)**2)))
    view = x[:, None] if x.ndim == 1 else x
    channel_peak = np.max(np.abs(view), axis=0, initial=0)
    channel_rms = [0. if p == 0 else float(p * np.sqrt(np.mean((view[:, i] / p)**2)))
                   for i, p in enumerate(channel_peak)]
    return {'peak': peak, 'rms': rms, 'channel_peak': channel_peak.tolist(),
            'channel_rms': channel_rms, 'finite': bool(np.isfinite(x).all()),
            'over_unity_fraction': float(np.mean(np.abs(x) > 1)) if x.size else 0.,
            'sample_count': len(x)}


def _mix(before, after, wet):
    if wet == 0:
        return before.copy()
    if wet == 1:
        return after
    return before + wet * (after - before)


def execute_rack(source, sample_rate_hz, rack, *, checkpoint=None,
                 max_working_bytes=MAX_WORKING_BYTES):
    """Return (PCM, measured diagnostics), preserving sample shape and extent."""
    if checkpoint: checkpoint()
    compiled = compile_rack(rack.recipe if isinstance(rack, CompiledRack) else rack)
    data = compiled.recipe.to_dict()
    if type(sample_rate_hz) is not int or sample_rate_hz != data['sample_rate_hz']:
        raise RackCompatibilityError('rack execution sample-rate mismatch')
    src = np.asarray(source)
    if src.ndim not in (1, 2) or (src.ndim == 2 and src.shape[1] not in (1, 2)):
        raise RackCompatibilityError('rack execution requires mono/stereo PCM')
    if (1 if src.ndim == 1 else src.shape[1]) != data['channels']:
        raise RackCompatibilityError('rack execution channel-count mismatch')
    if src.dtype.kind not in 'fiu' or not np.isfinite(src).all():
        raise RackCompatibilityError('rack execution requires finite real PCM')
    if np.max(np.abs(src), initial=0) > np.finfo(np.float32).max:
        raise RackCompatibilityError('rack input cannot be represented as finite float32 PCM')
    estimate = estimate_rack_resources(compiled, len(src))
    if type(max_working_bytes) is not int or not 0 < max_working_bytes <= MAX_WORKING_BYTES:
        raise RackCompatibilityError('invalid rack working-memory bound')
    if estimate['estimated_live_bytes'] > max_working_bytes:
        raise RackCompatibilityError('rack full-context memory estimate exceeds working-memory bound')
    crossovers = tuple(data['crossovers']['frequencies_hz'])
    rows = [{'id': b['id'], 'band': b['band'], 'bypass': b['bypass'], 'wet': b['wet'],
             'active': active, 'confine_delta': b['confine_delta'],
             'order': [i['id'] for i in b['inserts']], 'stages': [],
             'input': None, 'output': None, 'routed_output': None}
            for b, active in zip(data['bands'], compiled.active)]
    def observe(index, before, after):
        rows[index]['input'] = _meter(before)
        rows[index]['output'] = _meter(after)
    processors = []
    for index, (band, specs, active) in enumerate(zip(data['bands'], compiled.specs, compiled.active)):
        if not active:
            rows[index]['stages'] = [{'id': i['id'], 'type_id': i['type_id'],
                                     'bypass': i['bypass'], 'wet': i['wet'],
                                     'executed': False, 'reason': 'rack-or-band-identity'}
                                    for i in band['inserts']]
            processors.append(None)
            continue
        def processor(audio, band=band, specs=specs, index=index):
            current = np.asarray(audio, dtype=np.float64)
            for insert, spec in zip(band['inserts'], specs):
                if checkpoint: checkpoint()
                row = {'id': insert['id'], 'type_id': insert['type_id'],
                       'bypass': insert['bypass'], 'wet': insert['wet'], 'input': _meter(current)}
                if insert['bypass'] or insert['wet'] == 0:
                    row.update(executed=False, reason='explicit-insert-bypass-or-zero-wet')
                else:
                    changed, measured = process_builtin_stage(current, sample_rate_hz,
                        insert['type_id'].removeprefix('zg.'), spec, checkpoint=checkpoint, collect_decisions=True)
                    current = _mix(current, changed, insert['wet'])
                    row.update(executed=measured is not None, processor=measured)
                    if measured is None:row['reason'] = 'empty-or-unity-anchor'
                    if insert['type_id'] == 'zg.compression':
                        row['gain_reduction_domain'] = 'processor-internal-before-insert-wet'
                row['output'] = _meter(current)
                rows[index]['stages'].append(row)
            return _mix(np.asarray(audio, dtype=np.float64), current, band['wet'])
        processors.append(processor)
    confine = tuple(b['confine_delta'] for b in data['bands'])
    if compiled.identity:
        output = src.copy()
        reports = []
        if len(src) >= 8:
            for i, audio in enumerate(split_bands(src, sample_rate_hz, crossovers)):
                observe(i, audio, audio)
                rows[i]['routed_output'] = rows[i]['output']
        else:
            for row in rows:
                row['meter_unavailable_reason'] = 'fewer-than-eight-samples; exact identity retained'
    else:
        processed, reports = route_band_processors(src, sample_rate_hz, crossovers,
            tuple(processors), confine, checkpoint=checkpoint, observer=observe)
        output = _mix(np.asarray(src, dtype=np.float64), processed, data['wet'])
        for i, audio in enumerate(split_bands(output, sample_rate_hz, crossovers)):
            rows[i]['routed_output'] = _meter(audio)
    if checkpoint: checkpoint()
    if not np.isfinite(output).all() or np.max(np.abs(output), initial=0) > np.finfo(np.float32).max:
        raise RackCompatibilityError('rack output cannot be represented as finite float32 PCM')
    diagnostics = {'executor': EXECUTOR_VERSION, 'implementation_sha256': implementation_identity(),
        'rack_sha256': compiled.recipe.sha256, 'rack_sonic_sha256': compiled.recipe.sonic_sha256,
        'placement': data['placement'], 'identity_path': compiled.identity,
        'input': _meter(src), 'output': _meter(output), 'bands': rows,
        'effect_deltas': [report.to_dict() for report in reports],
        'delta_report_domain': 'after-band-wet-before-global-wet', 'wet': data['wet'],
        'filter': filter_metadata(crossovers, sample_rate_hz), 'resource_estimate': estimate,
        'meter_context': 'complete-input-context', 'normalization': 'none',
        'master_gain_db': 0., 'declared_latency_samples': 0}
    return output, diagnostics
