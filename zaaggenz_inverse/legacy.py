"""Read-only characterization/execution of the recovered inverse benchmark."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import numpy as np
from zaaggenz_contracts import digest
from zaaggenz_descriptors import pcm_asset
from .recipes import ROOT, ensure_legacy_engine


def provenance():
    ensure_legacy_engine()
    from uptempo_harmony.inverse import BASE_BOUNDS, INVERSE_PROFILES, DEFAULT_WEIGHTS, MULTISTAGE_STAGES
    files = ('app/uptempo_harmony/inverse.py', 'app/uptempo_harmony/synth.py', 'app/tests/inverse_smoke.py')
    return {'kind': 'RecoveredInverseBaseline', 'version': '1.0.0',
            'original_archive': 'zaaggenz-v1.2.1.zip',
            'original_archive_sha256': '90be319a4660a637077df935a8ebcbd1bb4c3a629e28e2f6d4bfe62d88dfe8a8',
            'runtime_payload_sha256': 'eaf5d3ab822dfa121cd3b795d62619af9e62c041fb02de19f8dbeafb0014c919',
            'runtime_files': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files},
            'profiles': INVERSE_PROFILES, 'absolute_bounds': {k: list(v) for k, v in BASE_BOUNDS.items()},
            'dynamic_f0_bounds': 'absolute bounds intersect measured terminal pitch +/-2.5 semitones',
            'component_weights': DEFAULT_WEIGHTS, 'multistage': MULTISTAGE_STAGES,
            'method': {'optimizer': 'scipy.optimize.differential_evolution', 'polish': False,
                       'workers': 1, 'updating': 'immediate', 'tol': .008, 'atol': 1e-4,
                       'minimum_maxiter': 1, 'minimum_popsize': 3,
                       'stage_seed_rule': 'seed + stage_index*7919', 'final_candidate_evaluation': True},
            'loss': 'weighted RMS of dimensionless pitch/spectrum/envelope/flatness/HF/harmonic losses',
            'gain_handling': 'reference DC removal and peak normalization; relative frame spectra/envelopes; legacy source normalizers remain',
            'pitch_asymmetry': 'reference acoustic estimator versus candidate synth debug f0 trajectory',
            'cancel': 'cooperative objective/generation callback; in-memory best retained; early cancellation may have no finite best score',
            'checkpoint': 'no durable resume state or population lineage in recovered module',
            'cache': 'precomputed reference FeatureField; no content-addressed candidate render/feature cache in recovered module',
            'limitations': ['single excerpt; no independent holdout', 'no waveform objective or Pareto archive',
                           'no independent gain/degeneracy gate', 'normalization erases absolute level evidence',
                           'determinism is pinned-environment seeded, not universal cross-platform byte equality']}


def run_recovered_benchmark():
    """Replicate inverse_smoke.py exactly; don't tune the old benchmark to favor this pass."""
    ensure_legacy_engine()
    from uptempo_harmony.inverse import (extract_reference_features, extract_candidate_features,
        feature_distance, inverse_optimize, bounds_for)
    from uptempo_harmony.synth import PRESETS, synthesize_one
    truth = replace(PRESETS['swept_mixed'], sr=16000, beats=1)
    target_audio, _ = synthesize_one(truth)
    beat_n = int(round(truth.sr*60./truth.bpm))
    target_audio = np.pad(target_audio, (0, max(0, beat_n-len(target_audio))))[:beat_n]
    target = extract_reference_features(target_audio, truth.sr, truth.bpm, f0_hint=truth.f0_hz)
    base = replace(PRESETS['neutral'], sr=16000, bpm=truth.bpm, beats=1)
    audio, debug = synthesize_one(base)
    initial_score, initial_components = feature_distance(extract_candidate_features(audio, debug, base, target), target)
    result = inverse_optimize(target, base, profile='quick', maxiter=3, popsize=3, seed=7)
    keys, bounds = bounds_for('quick', target.terminal_f0_hz)
    return {'kind': 'RecoveredInverseBenchmarkRun', 'version': '1.0.0',
            'provenance_sha256': digest(provenance()), 'target_asset': pcm_asset(target_audio, truth.sr),
            'ground_truth': truth.to_dict(), 'initial_parameters': base.to_dict(),
            'profile': 'quick', 'maxiter': 3, 'popsize': 3, 'seed': 7,
            'bounds': {key: list(b) for key, b in zip(keys, bounds)},
            'f0_hint': truth.f0_hz, 'hint_note': 'truth hint is inherited from the original smoke, NOT supplied to new fixture search',
            'initial_score': initial_score, 'initial_components': initial_components,
            'best_score': result.score, 'best_components': result.components,
            'best_parameters': result.params.to_dict(), 'evaluations': result.evaluations,
            'iterations': result.iterations, 'cancelled': result.cancelled,
            'comparison_warning': 'different targets/objectives/budgets; not an optimizer league table'}
