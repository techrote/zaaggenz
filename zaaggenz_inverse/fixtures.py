"""Synthetic benchmark catalogue. Ground truth is owned here, never by the search API."""
from __future__ import annotations

from dataclasses import dataclass, replace
from copy import deepcopy
import numpy as np
from zaaggenz_contracts import Contract, digest
from zaaggenz_contracts.legacy import freeze_legacy, envelope
from zaaggenz_project import Project
from .contracts import (ParameterAxis, ParameterDomain, SearchBudget, Window, WindowPlan,
                        ObjectiveTerm, ObjectivePolicy)
from .recipes import (render_trace, frozen_audio, parameter_spec, state_from_recipe, engine_identity)
from .laboratory import request_from_project, prepare_experiment

NAMES = ('identifiable', 'weak-residual', 'drive-trim-equivalence', 'polarity-feature-conflict',
         'holdout-step', 'sonority-nonlinear')


def _source(**changes):
    # All settings are local fixtures; no product presets/defaults are modified.
    p = dict(sr=12000, bpm=120., beats=1, beat_fill=1., f0_hz=72., seed=24,
             harmonic_count=7, harmonic_decay=1.2, odd_even_ratio=1.4, harmonic_tilt_db_per_oct=0.,
             sweep_semitones=0., pitch_jitter_cents=0., harmonic_lock_cents=0.,
             roughness=0., noise_level=0., drive_db=0., input_trim_db=-10.,
             shaper_mix=0., hard_clip_mix=0., asymmetry=0., wavefold=0., preemphasis=0.,
             attack_ms=1., decay_ms=200., sustain=.04, transient_click=.04,
             post_hp_hz=20., post_lp_hz=4500., peak=.35)
    p.update(changes)
    return freeze_legacy(p)


def _with_graph(recipe, node):
    d = recipe.to_dict()
    d['nodes'], d['output_node'] = [node], node['id']
    return Contract(d)


def _gain_step(recipe, late_db):
    node = envelope('DSPNodeSpec', id='gain-step', type_id='core.gain.v1', inputs=['source'],
        channels=1, params={'gain_db': 0.}, state_policy='stateless', phase_policy='source-derived',
        latency_samples=0, lookahead_samples=0, bypass='identity',
        automation=[{'parameter': 'gain_db', 'unit': 'dB', 'interpolation': 'step',
                     'points': [{'sample': 0, 'value': 0.}, {'sample': 3600, 'value': late_db}]}])
    return _with_graph(recipe, node)


def _axis(recipe, path, lower, upper):
    spec = parameter_spec(recipe, path)
    return ParameterAxis(path, lower, upper, spec['unit'], spec['type'])


@dataclass(frozen=True)
class SyntheticFixture:
    name: str
    description: str
    generation: str
    ground_truth_recipe: Contract
    base_recipe: Contract
    domain: ParameterDomain
    target: np.ndarray
    plan: WindowPlan
    objective: ObjectivePolicy
    budget: SearchBudget
    seed: str = '24'

    def __post_init__(self):
        object.__setattr__(self, 'target', frozen_audio(self.target))

    @property
    def request(self):
        return request_from_project(Project(self.base_recipe), self.target, self.plan, self.domain,
            objective=self.objective, budget=self.budget, seed=self.seed)

    def experiment(self, **kwargs):
        # This is the sole bridge to search: no ground-truth state, name, generation
        # description or fixture object is retained by either search capability.
        return prepare_experiment(self.request, self.target, self.plan, **kwargs)

    @property
    def ground_truth_state(self):
        return state_from_recipe(self.ground_truth_recipe, self.domain)

    def catalogue_record(self):
        definition = {'name': self.name, 'description': self.description, 'generation': self.generation,
            'ground_truth_recipe': self.ground_truth_recipe.to_dict(),
            'ground_truth_parameters': self.ground_truth_state.to_dict(),
            'base_recipe': self.base_recipe.to_dict(), 'domain': self.domain.to_dict(),
            'windows': self.plan.to_dict(), 'objective': self.objective.to_dict(),
            'seed': self.seed, 'budget': self.budget.to_dict()}
        identity = {'definition_sha256': digest(definition), 'target_asset': self.request.target_asset.to_dict(),
                    'implementation_sha256': engine_identity()}
        return {'kind': 'InverseSyntheticFixture', 'version': '1.0.0', 'definition': definition,
                **identity, 'fixture_id': digest({'domain': 'zaaggenz.inverse-fixture-v1', **identity}),
                'truth_separation': 'catalogue/evidence only; never supplied to run_grid or FitEvaluator'}


def synthetic_fixture(name):
    if name not in NAMES:
        raise ValueError('unknown inverse fixture')
    plan = WindowPlan((Window('attack-fit', 0, 1600), Window('body-fit', 2200, 3400)),
                      (Window('tail-holdout', 4000, 5600),), 6000)
    objective = ObjectivePolicy()
    truth, base = _source(), _source()
    generation = 'accepted RenderRecipe -> zaaggenz_dsp.legacy.render_recipe; canonical f32, no target normalization'
    if name == 'identifiable':
        base = _source(f0_hz=60., decay_ms=120.)
        domain = ParameterDomain((_axis(base, '/source/params/f0_hz', 60., 84.),
                                  _axis(base, '/source/params/decay_ms', 120., 280.)))
        description = 'Exact in-grid frequency/envelope recovery under fixed seed and source family; not original-chain identification.'
    elif name == 'weak-residual':
        truth = _source(noise_level=.003, noise_decay_ms=180.)
        base = _source(noise_level=0., noise_decay_ms=80.)
        domain = ParameterDomain((_axis(base, '/source/params/noise_level', 0., .006),
                                  _axis(base, '/source/params/noise_decay_ms', 80., 280.)))
        description = 'Weakly identifiable low-level residual: different noise-decay settings make only small waveform changes; zero-noise subspace is exactly ambiguous.'
    elif name == 'drive-trim-equivalence':
        truth = _source(shaper_mix=.8, drive_db=12., input_trim_db=-10.)
        base = _source(shaper_mix=.8, drive_db=10., input_trim_db=-12.)
        domain = ParameterDomain((_axis(base, '/source/params/drive_db', 10., 14.),
                                  _axis(base, '/source/params/input_trim_db', -12., -8.)))
        description = 'Deliberately non-identifiable: the accepted shaper uses drive_db+input_trim_db. Three materially different in-grid recipes have exactly the same drive sum and PCM.'
    elif name == 'polarity-feature-conflict':
        truth = _source(harmonic_count=9)
        base = _source(harmonic_count=7)
        domain = ParameterDomain((_axis(base, '/source/params/harmonic_count', 7, 11),))
        objective = ObjectivePolicy((ObjectiveTerm('spectrum'), ObjectiveTerm('level', 6.), ObjectiveTerm('waveform', 1., 0.)))
        description = 'Target polarity is reversed explicitly. Magnitude/level objectives can be perfect while raw waveform relative RMSE is two. Current recipe family has no polarity node.'
        generation += '; then explicit target-only multiplication by -1 (declared model mismatch)'
    elif name == 'holdout-step':
        truth = _gain_step(_source(), 6.)
        base = _gain_step(_source(), -6.)
        domain = ParameterDomain((_axis(base, '/nodes/0/automation/0/points/1/value', -6., 6.),))
        description = 'All fitting windows precede the gain step. Late gain is completely unobserved by fitting; independent tail windows expose a deliberately wrong -6 dB candidate against +6 dB truth.'
    else:
        truth = _source(harmonic_count=13, roughness=.12, noise_level=.015)
        node = envelope('DSPNodeSpec', id='post-source-aa', type_id='core.tanh_aa.v1', inputs=['source'],
            channels=1, params={'drive_db': 3., 'mix': .35, 'oversample': 2}, state_policy='stateless',
            phase_policy='source-derived', latency_samples=0, lookahead_samples=0, bypass='identity', automation=[])
        truth = _with_graph(truth, node)
        d = truth.to_dict(); d['nodes'][0]['params']['mix'] = 0.; base = Contract(d)
        domain = ParameterDomain((_axis(base, '/nodes/0/params/mix', 0., .7),))
        objective = ObjectivePolicy((ObjectiveTerm('waveform'), ObjectiveTerm('spectrum'), ObjectiveTerm('level', 6.),
            ObjectiveTerm('comb_fit'), ObjectiveTerm('roughness'), ObjectiveTerm('interaction')), sonority=True)
        description = 'Richer opt-in evidence: accepted antialiased post-source nonlinear node, partial analysis, Chordness union and ZG-020 timbre interaction descriptors.'
    target = render_trace(truth).output
    if name == 'polarity-feature-conflict':
        target = -target
    budget = SearchBudget(9 if len(domain.axes) == 2 else 3, 3, 2)
    return SyntheticFixture(name, description, generation, truth, base, domain, target, plan, objective, budget)
