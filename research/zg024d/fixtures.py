"""Independent preregistered fixtures for ZG-024d staged-search research.

The values in this module are protocol inputs, not optimizer inputs.  Ground truth is
owned only by the experiment/report layer; ``FitEvaluator`` never receives it.
"""
from __future__ import annotations

from zaaggenz_inverse import ParameterDomain, SearchBudget
from zaaggenz_inverse.fixtures import SyntheticFixture, _axis, _source, synthetic_fixture
from zaaggenz_inverse.recipes import render_trace

CALIBRATION_NAME = 'staged-calibration-nonlinear'
AUDIT_NAMES = ('staged-audit-envelope', 'staged-audit-timbre3')
ALL_NAMES = (CALIBRATION_NAME,) + AUDIT_NAMES
SEARCH_SEEDS = ('41', '211', '2027')


def _build(name, seed):
    template = synthetic_fixture('identifiable')
    if name == CALIBRATION_NAME:
        truth = _source(shaper_mix=.57, drive_db=14.35, input_trim_db=-10.)
        base = _source(shaper_mix=.08, drive_db=6.5, input_trim_db=-10.)
        domain = ParameterDomain((
            _axis(base, '/source/params/drive_db', 6., 18.),
            _axis(base, '/source/params/shaper_mix', 0., 1.),
        ))
        budget = SearchBudget(18, 5, 2)
        description = ('Preregistered calibration target for global-to-local allocation. Truth is off-grid and was '
                       'not used in ZG-024b strategy selection.')
    elif name == 'staged-audit-envelope':
        truth = _source(f0_hz=70.85, decay_ms=247.)
        base = _source(f0_hz=60., decay_ms=120.)
        domain = ParameterDomain((
            _axis(base, '/source/params/f0_hz', 60., 84.),
            _axis(base, '/source/params/decay_ms', 120., 280.),
        ))
        budget = SearchBudget(18, 5, 2)
        description = ('Independent envelope/root audit. Truth and seeds are distinct from the ZG-024b fixtures; '
                       'the repaired transient-v4 gate remains authoritative and is not weakened for this audit.')
    elif name == 'staged-audit-timbre3':
        truth = _source(f0_hz=78.15, harmonic_decay=1.62, odd_even_ratio=1.75)
        base = _source(f0_hz=60., harmonic_decay=.7, odd_even_ratio=.5)
        domain = ParameterDomain((
            _axis(base, '/source/params/f0_hz', 60., 84.),
            _axis(base, '/source/params/harmonic_decay', .7, 2.0),
            _axis(base, '/source/params/odd_even_ratio', .5, 4.0),
        ))
        budget = SearchBudget(30, 5, 2)
        description = ('Independent three-axis timbre audit with off-grid truth. It tests whether staged local '
                       'refinement generalises beyond the two-axis calibration family.')
    else:
        raise ValueError('unknown ZG-024d fixture')

    return SyntheticFixture(
        name=name,
        description=description,
        generation='ZG-024a accepted RenderRecipe/render_trace; canonical f32; truth hidden from FitEvaluator',
        ground_truth_recipe=truth,
        base_recipe=base,
        domain=domain,
        target=render_trace(truth).output,
        plan=template.plan,
        objective=template.objective,
        budget=budget,
        seed=seed,
    )


def research_fixture(name, *, seed='41'):
    if name not in ALL_NAMES:
        raise ValueError('unknown ZG-024d fixture')
    if seed not in SEARCH_SEEDS:
        raise ValueError('seed is outside the preregistered ZG-024d set')
    return _build(name, seed)


def normalized_parameter_error(fixture, candidate):
    truth = dict(fixture.ground_truth_state.values)
    values = dict(candidate.to_dict()['parameters']['values'])
    terms = []
    for axis in fixture.domain.axes:
        span = axis.upper - axis.lower
        terms.append(((values[axis.path] - truth[axis.path]) / span) ** 2 if span else 0.)
    return (sum(terms) / len(terms)) ** 0.5
