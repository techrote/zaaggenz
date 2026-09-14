"""Predeclared off-grid ZG-024b search fixtures.

Ground truth is retained only by the experiment/evidence owner. ``experiment()`` still
returns the frozen ZG-024a fit capability and separate audit capability.
"""
from __future__ import annotations

from dataclasses import replace

from zaaggenz_inverse import ParameterDomain, SearchBudget
from zaaggenz_inverse.fixtures import SyntheticFixture, _axis, _source, synthetic_fixture
from zaaggenz_inverse.recipes import render_trace

CORE_NAMES = (
    'offgrid-envelope',
    'offgrid-nonlinear',
    'offgrid-timbre3',
    'offgrid-nonidentifiable',
)
SENTINEL_NAME = 'holdout-sentinel'
SEARCH_SEEDS = ('24', '97', '1337')


def _fixture(name, *, seed='24'):
    if name == 'offgrid-envelope':
        truth = _source(f0_hz=73.3, decay_ms=213.)
        base = _source(f0_hz=60., decay_ms=120.)
        domain = ParameterDomain((
            _axis(base, '/source/params/f0_hz', 60., 84.),
            _axis(base, '/source/params/decay_ms', 120., 280.),
        ))
        description = ('Off-grid identifiable frequency/envelope case. Truth is deliberately absent from the '
                       'five-level grid; parameter error is meaningful but does not imply original-chain recovery.')
        budget = SearchBudget(16, 5, 2)
    elif name == 'offgrid-nonlinear':
        truth = _source(shaper_mix=.63, drive_db=13.7, input_trim_db=-10.)
        base = _source(shaper_mix=.1, drive_db=6., input_trim_db=-10.)
        domain = ParameterDomain((
            _axis(base, '/source/params/drive_db', 6., 18.),
            _axis(base, '/source/params/shaper_mix', 0., 1.),
        ))
        description = ('Off-grid nonlinear interaction: drive and shaper wetness vary together under the accepted '
                       'legacy source path. No target-derived initialization is supplied.')
        budget = SearchBudget(16, 5, 2)
    elif name == 'offgrid-timbre3':
        truth = _source(f0_hz=75.3, harmonic_decay=1.37, odd_even_ratio=2.2)
        base = _source(f0_hz=60., harmonic_decay=.7, odd_even_ratio=.5)
        domain = ParameterDomain((
            _axis(base, '/source/params/f0_hz', 60., 84.),
            _axis(base, '/source/params/harmonic_decay', .7, 2.0),
            _axis(base, '/source/params/odd_even_ratio', .5, 4.0),
        ))
        description = ('Three-axis off-grid spectral/timbre recovery. The 24-evaluation budget covers only a prefix '
                       'of the 125-point five-level lattice, stressing coverage without enlarging CI excessively.')
        budget = SearchBudget(24, 5, 2)
    elif name == 'offgrid-nonidentifiable':
        truth = _source(shaper_mix=.8, drive_db=13.4, input_trim_db=-9.9)
        base = _source(shaper_mix=.8, drive_db=10., input_trim_db=-13.)
        domain = ParameterDomain((
            _axis(base, '/source/params/drive_db', 10., 16.),
            _axis(base, '/source/params/input_trim_db', -13., -7.),
        ))
        description = ('Off-grid non-identifiable drive/trim case. The accepted legacy shaper depends on their sum; '
                       'raw parameter distance is intentionally not treated as an identification success metric.')
        budget = SearchBudget(16, 5, 2)
    else:
        raise ValueError('unknown ZG-024b fixture')

    template = synthetic_fixture('identifiable')
    target = render_trace(truth).output
    return SyntheticFixture(
        name=name,
        description=description,
        generation='ZG-024a accepted RenderRecipe/render_trace; canonical f32; truth hidden from FitEvaluator',
        ground_truth_recipe=truth,
        base_recipe=base,
        domain=domain,
        target=target,
        plan=template.plan,
        objective=template.objective,
        budget=budget,
        seed=seed,
    )


def research_fixture(name, *, seed='24'):
    if seed not in SEARCH_SEEDS:
        raise ValueError('seed is outside the preregistered ZG-024b set')
    if name in CORE_NAMES:
        return _fixture(name, seed=seed)
    if name == SENTINEL_NAME:
        base = synthetic_fixture('holdout-step')
        return replace(base, name=SENTINEL_NAME, seed=seed, budget=SearchBudget(9, 9, 2),
            description=(base.description + ' ZG-024b leakage sentinel expands only search resolution/budget; '
                         'all fitting windows still precede the step.'))
    raise ValueError('unknown ZG-024b fixture')


def normalized_parameter_error(fixture, candidate):
    """Post-search truth diagnostic for identifiable research fixtures only."""
    if fixture.name == 'offgrid-nonidentifiable' or fixture.name == SENTINEL_NAME:
        return None
    truth = dict(fixture.ground_truth_state.values)
    values = dict(candidate.to_dict()['parameters']['values'])
    terms = []
    for axis in fixture.domain.axes:
        span = axis.upper-axis.lower
        terms.append(((values[axis.path]-truth[axis.path])/span)**2 if span else 0.)
    return (sum(terms)/len(terms))**0.5


def nonidentifiable_manifold_error(fixture, candidate):
    """Distance from the known observable drive+trim equivalence class, not recipe identity."""
    if fixture.name != 'offgrid-nonidentifiable':
        return None
    truth = dict(fixture.ground_truth_state.values)
    values = dict(candidate.to_dict()['parameters']['values'])
    target_sum = truth['/source/params/drive_db'] + truth['/source/params/input_trim_db']
    candidate_sum = values['/source/params/drive_db'] + values['/source/params/input_trim_db']
    # Combined range is 12 dB, used only to produce a bounded scale for reporting.
    return abs(candidate_sum-target_sum)/12.0
