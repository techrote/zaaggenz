"""Synthetic controllers and private ground-truth witnesses, not search helpers.

Only FixtureCase.problem()'s FitProblem is passed to the baseline. The renderer
contains a public forward model/source, never the truth state or a target lookup.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np

from zaaggenz_contracts import digest, derive_seed
from zaaggenz_contracts.legacy import envelope
from zaaggenz_qc.fixtures import fixture as qc_fixture
from zaaggenz_spectral.placement import NonlinearStageSpec
from zaaggenz_spectral.chordness_model import CombTemplate
from .contracts import (Snapshot, ParameterBound, ParameterDomain, ParameterState, Grid,
                        Window, WindowPlan, Budget, Stage, SearchRequest, document, require)
from .render import AudioBuffer, GraphRenderer, finish_render, execution_identity
from .objectives import ObjectivePlan
from .validation import GatePolicy
from .engine import prepare_problem

CATALOGUE = ('identifiable-bands', 'weakly-identifiable-gains', 'nonidentifiable-gains',
             'polarity-feature-conflict', 'fit-only-tail', 'rich-nonlinear-48k')
GAIN_TWO = 20. * math.log10(2.)


def _node(id, type_id, params, inputs=('source',), automation=()):
    return envelope('DSPNodeSpec', id=id, type_id=type_id, inputs=list(inputs), channels=1, params=params,
                    state_policy='stateless', phase_policy='source-derived', latency_samples=0,
                    lookahead_samples=0, bypass='identity', automation=list(automation))


def _source(rate, n, seed, rich):
    t = np.arange(n, dtype=np.float64) / rate
    x = .16 * np.sin(2 * np.pi * 187.5 * t) + .11 * np.cos(2 * np.pi * 750. * t) + .08 * np.sin(2 * np.pi * 2250. * t)
    if rich:
        noise = qc_fixture('bandlimited_noise', rate, n / rate, int(derive_seed(seed, 'fixture-noise'))).data
        x += .10 * noise
        # Four separated attacks, each strictly inside one evaluation window.
        for start in range(n // 32, n, n // 4):
            count = min(round(.004 * rate), n - start)
            x[start:start + count] += .35 * np.exp(-np.arange(count) / (.001 * rate))
    return AudioBuffer(x, rate)


@dataclass(frozen=True)
class PolarityRenderer:
    """One transparent synthetic phase ambiguity, not a new production DSP node."""
    source: AudioBuffer

    @property
    def method(self):
        return {'id': 'zg.inverse.fixture-polarity.v1', 'version': '1.0.0',
                'configuration': {'source_sha256': self.source.asset.sha256, 'equation': 'output = polarity * source',
                                  'normalisation': 'none', 'scope': 'synthetic laboratory only'}}

    def validate_domain(self, domain):
        require(len(domain.bounds) == 1 and domain.bounds[0].name == 'polarity', 'polarity-only domain required')
        b = domain.bounds[0]
        require(b.integral and b.unit == 'sign' and -1 <= b.lower <= b.upper <= 1, 'invalid polarity bound')

    def render(self, state, seed, checkpoint=lambda: None):
        checkpoint()
        require(set(state.to_dict()) == {'polarity'}, 'polarity parameter required')
        return finish_render(self.source.audio.astype(np.float64) * state.to_dict()['polarity'], self.source.rate,
                             {'method': self.method, 'parameters': state.to_dict(), 'seed': seed})


@dataclass(frozen=True)
class FixtureCase:
    name: str
    fixture_id: str
    renderer: object
    target: AudioBuffer
    request: SearchRequest
    witness: Snapshot

    def problem(self, *, store=None):
        return prepare_problem(self.request, self.renderer, self.target, store=store)


def make_fixture(name, *, seed='20260914', search_seed='24001', budget=None):
    require(name in CATALOGUE, 'unknown inverse fixture')
    rich = name == 'rich-nonlinear-48k'
    rate, n = (48000, 32768) if rich else (12000, 8192)
    source = _source(rate, n, seed, rich)
    levels = (-GAIN_TWO, 0., GAIN_TWO)
    templates = (CombTemplate('observed-sonority', (187.5, 750., 2250.), label='public synthetic comb'),)
    objective = ObjectivePlan(templates=templates)
    if name == 'identifiable-bands':
        params = dict(low_xover_hz=120., mid_xover_hz=1000., high_xover_hz=3000., sub_gain_db=0.,
                      lowmid_gain_db=0., highmid_gain_db=0., air_gain_db=0., confine_delta=True)
        nodes = [_node('bands', 'core.multiband_gain.v1', params)]
        bindings = {'low_gain_db': '/nodes/0/params/lowmid_gain_db', 'high_gain_db': '/nodes/0/params/highmid_gain_db'}
        renderer = GraphRenderer(source, nodes, bindings, output_node='bands')
        axes = ((k, (-6., 0., 6.)) for k in bindings)
        truth = {'low_gain_db': 6., 'high_gain_db': -6.}
        note = 'Two independently occupied bands; exact on-grid recovery should be unique.'
    elif name in ('weakly-identifiable-gains', 'nonidentifiable-gains'):
        if name == 'weakly-identifiable-gains':
            source = AudioBuffer(source.audio * .025, rate)
        nodes = [_node('gain-a', 'core.gain.v1', {'gain_db': 0.})]
        if name == 'weakly-identifiable-gains':
            stage = NonlinearStageSpec('tanh', 'legacy', 1, 0., .7, 1.)
            nodes.append(_node('shape', stage.type_id, stage.params(), ('gain-a',)))
            preceding = 'shape'
            note = 'Near-linear tanh weakly separates reciprocal gain recipes; near-equality is not exact identification.'
        else:
            preceding = 'gain-a'
            note = 'Two serial gains identify only their sum; reciprocal factor-two recipes have identical PCM.'
        nodes.append(_node('gain-b', 'core.gain.v1', {'gain_db': 0.}, (preceding,)))
        bindings = {'gain_a_db': '/nodes/0/params/gain_db', 'gain_b_db': f'/nodes/{len(nodes)-1}/params/gain_db'}
        renderer = GraphRenderer(source, nodes, bindings, output_node='gain-b')
        axes = ((k, levels) for k in bindings)
        truth = {'gain_a_db': 0., 'gain_b_db': 0.}
    elif name == 'polarity-feature-conflict':
        renderer = PolarityRenderer(source)
        axes = (('polarity', (-1., 1.)),)
        truth = {'polarity': 1.}
        objective = ObjectivePlan(templates=templates, weights={'waveform': 0.})
        note = 'Opposite polarity has identical phase-insensitive features/sonority and waveform NRMSE 2.'
    elif name == 'fit-only-tail':
        automation = [{'parameter': 'gain_db', 'unit': 'dB', 'interpolation': 'step',
                       'points': [{'sample': n // 2, 'value': 0.}]}]
        nodes = [_node('tail', 'core.gain.v1', {'gain_db': 0.}, automation=automation)]
        renderer = GraphRenderer(source, nodes, {'tail_gain_db': '/nodes/0/automation/0/points/0/value'}, output_node='tail')
        axes = (('tail_gain_db', (-12., 0., 12.)),)
        truth = {'tail_gain_db': 0.}
        note = 'All tail gains are invisible in both fitting windows; holdouts expose the ordinal-first overfit candidate.'
    else:
        stage = NonlinearStageSpec('tanh', 'antialiased', 2, 6., .7, 1.)
        nodes = [_node('shape', stage.type_id, stage.params()),
                 _node('post', 'core.gain.v1', {'gain_db': -6.}, ('shape',))]
        renderer = GraphRenderer(source, nodes, {'drive_db': '/nodes/0/params/drive_db',
                                                'post_gain_db': '/nodes/1/params/gain_db'}, output_node='post')
        axes = (('drive_db', (0., 3., 6., 9., 12.)), ('post_gain_db', (-12., -9., -6., -3., 0.)))
        truth = {'drive_db': 6., 'post_gain_db': -6.}
        note = '48 kHz seeded texture and attacks through accepted 2x antialiased tanh; drive/output-gain covariance.'
    grid = Grid(tuple((k, tuple(v)) for k, v in axes))
    domain = ParameterDomain(tuple(ParameterBound(k, 'sign' if k == 'polarity' else 'dB', min(v), max(v), k == 'polarity')
                                   for k, v in grid.axes))
    domain.validate(ParameterState.from_mapping(truth))
    render_seed = derive_seed(search_seed, 'inverse-render')
    ground_render = renderer.render(ParameterState.from_mapping(truth), render_seed, lambda: None)
    target = ground_render.output
    quarter = n // 4
    windows = WindowPlan((Window('fit-a', 0, quarter), Window('fit-b', quarter, 2 * quarter)),
                         (Window('holdout-a', 2 * quarter, 3 * quarter), Window('holdout-b', 3 * quarter, n)))
    count = grid.size if budget is None else budget
    request = SearchRequest(source=source.asset, target=target.asset, renderer=renderer.method, domain=domain,
        grid=grid, windows=windows, budget=Budget(count, min(count, 9)), seed=search_seed,
        objectives=objective.to_dict(), validation=GatePolicy().to_dict(), execution=execution_identity(), stage=Stage('calibration'))
    witness = Snapshot(document('InverseFixtureWitness', catalogue='zg.inverse.fixtures.v1', name=name, source_seed=seed,
        search_seed=search_seed, render_seed=render_seed, parameters=truth, render=ground_render.identity(),
        generation='three fixed carriers; optional ZG-005 seeded bandlimited noise + four exponential attacks; explicit graph transform',
        note=note, source=source.asset.to_dict(), target=target.asset.to_dict()))
    fixture_id = digest(document('InverseFixtureIdentity', name=name, witness_sha256=witness.sha256,
                                 request_sha256=request.sha256))
    return FixtureCase(name, fixture_id, renderer, target, request, witness)
