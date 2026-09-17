"""Fresh development and anti-degeneracy fixtures for frozen ZG-024d protocol v2.

Ground truth is catalogue/orchestration evidence only. ``FitEvaluator`` receives only
its request and independent fit excerpts. Confirmation targets deliberately live in a
separate module committed after the v2 design-freeze commit.
"""
from __future__ import annotations

import numpy as np

from zaaggenz_inverse import ParameterDomain, SearchBudget, Window, WindowPlan
from zaaggenz_inverse.fixtures import SyntheticFixture, _axis, _source
from zaaggenz_inverse.recipes import RenderTrace, render_trace

DEVELOPMENT_NAMES = ('dev-structure', 'dev-spectral', 'dev-texture', 'dev-mixed', 'dev-equivalence')
SENTINEL_NAMES = ('sentinel-transient', 'sentinel-silence', 'sentinel-clipping')
SEARCH_SEEDS = ('41', '211', '2027')
BUDGET = SearchBudget(24, 5, 2)
PLAN = WindowPlan((Window('attack-fit', 0, 1400), Window('body-fit', 1900, 3200)),
                  (Window('tail-holdout', 3900, 5600),), 6000)


def _domain(base, *, equivalence=False):
    axes = [
        _axis(base, '/source/params/f0_hz', 60., 84.),
        _axis(base, '/source/params/attack_ms', 1., 18.),
        _axis(base, '/source/params/decay_ms', 120., 300.),
        _axis(base, '/source/params/harmonic_decay', .7, 2.0),
        _axis(base, '/source/params/odd_even_ratio', .5, 3.0),
        _axis(base, '/source/params/drive_db', 0., 18.),
        _axis(base, '/source/params/shaper_mix', 0., 1.),
    ]
    if equivalence:
        axes.append(_axis(base, '/source/params/input_trim_db', -14., -6.))
    return ParameterDomain(tuple(axes))


def _fixture(name, truth, base, description, seed, *, equivalence=False):
    domain = _domain(base, equivalence=equivalence)
    return SyntheticFixture(
        name=name,
        description=description,
        generation=('fresh ZG-024d v2 target: accepted RenderRecipe/render_trace, canonical f32; '
                    'truth is never supplied to FitEvaluator'),
        ground_truth_recipe=truth,
        base_recipe=base,
        domain=domain,
        target=render_trace(truth).output,
        plan=PLAN,
        objective=__import__('zaaggenz_inverse.fixtures', fromlist=['synthetic_fixture']).synthetic_fixture('identifiable').objective,
        budget=BUDGET,
        seed=seed,
    )


def development_fixture(name, *, seed='41'):
    if name not in DEVELOPMENT_NAMES + SENTINEL_NAMES:
        raise ValueError('unknown ZG-024d development fixture')
    if seed not in SEARCH_SEEDS:
        raise ValueError('seed is outside frozen ZG-024d set')

    base = _source(f0_hz=68., attack_ms=2., decay_ms=170., harmonic_decay=1.0,
                   odd_even_ratio=1.0, drive_db=2., shaper_mix=.15, input_trim_db=-10.)
    if name == 'dev-structure':
        truth = _source(f0_hz=77.3, attack_ms=6.2, decay_ms=255., harmonic_decay=1.0,
                        odd_even_ratio=1.0, drive_db=2., shaper_mix=.15, input_trim_db=-10.)
        desc = 'Fresh Family-A root/envelope displacement with spectral/texture nuisance dimensions.'
        return _fixture(name, truth, base, desc, seed)
    if name == 'dev-spectral':
        truth = _source(f0_hz=68., attack_ms=2., decay_ms=170., harmonic_decay=1.73,
                        odd_even_ratio=2.35, drive_db=2., shaper_mix=.15, input_trim_db=-10.)
        desc = 'Fresh Family-B harmonic-structure displacement with structural/texture nuisance dimensions.'
        return _fixture(name, truth, base, desc, seed)
    if name == 'dev-texture':
        truth = _source(f0_hz=68., attack_ms=2., decay_ms=170., harmonic_decay=1.0,
                        odd_even_ratio=1.0, drive_db=12.4, shaper_mix=.71, input_trim_db=-10.)
        desc = 'Fresh Family-C nonlinear/texture displacement with structural/spectral nuisance dimensions.'
        return _fixture(name, truth, base, desc, seed)
    if name == 'dev-mixed':
        truth = _source(f0_hz=74.6, attack_ms=5.5, decay_ms=238., harmonic_decay=1.58,
                        odd_even_ratio=1.92, drive_db=10.7, shaper_mix=.63, input_trim_db=-10.)
        desc = 'Fresh mixed A/B/C target requiring structure, spectral and nonlinear decisions.'
        return _fixture(name, truth, base, desc, seed)
    if name == 'dev-equivalence':
        base_eq = _source(f0_hz=70., attack_ms=3., decay_ms=205., harmonic_decay=1.3,
                          odd_even_ratio=1.55, drive_db=10., input_trim_db=-6., shaper_mix=.8)
        truth = _source(f0_hz=70., attack_ms=3., decay_ms=205., harmonic_decay=1.3,
                        odd_even_ratio=1.55, drive_db=14., input_trim_db=-10., shaper_mix=.8)
        desc = ('Fresh deliberate drive+trim equivalence manifold: distinct editable recipes can share '
                'the accepted nonlinear drive sum; exact alternatives must not be erased.')
        return _fixture(name, truth, base_eq, desc, seed, equivalence=True)

    # Sentinels use an ordinary target/domain; a declared custom renderer injects the
    # adversarial candidate pathology so the existing versioned gate—not the search—
    # owns rejection. They never participate in method selection.
    truth = _source(f0_hz=72., attack_ms=1.5, decay_ms=210., harmonic_decay=1.25,
                    odd_even_ratio=1.45, drive_db=5., shaper_mix=.35, input_trim_db=-10.)
    sentinel_base = _source(f0_hz=66., attack_ms=4., decay_ms=160., harmonic_decay=.9,
                            odd_even_ratio=.9, drive_db=3., shaper_mix=.2, input_trim_db=-10.)
    desc = {
        'sentinel-transient': 'Search candidates are rendered with their attack region removed; transient-v4 must fail closed.',
        'sentinel-silence': 'Search candidates are rendered as silence; silence/energy gates must fail closed.',
        'sentinel-clipping': 'Search candidates are rendered through an adversarial hard plateau; clipping gates must fail closed.',
    }[name]
    return _fixture(name, truth, sentinel_base, desc, seed)


def sentinel_renderer(name):
    """Return a declared adversarial renderer and explicit method ID for one sentinel."""
    if name not in SENTINEL_NAMES:
        raise ValueError('not a sentinel fixture')

    def render(recipe):
        trace = render_trace(recipe)
        if name == 'sentinel-silence':
            pre = np.zeros_like(trace.pre_master); out = np.zeros_like(trace.output)
        elif name == 'sentinel-transient':
            pre = np.array(trace.pre_master, copy=True); out = np.array(trace.output, copy=True)
            pre[:900] = 0.; out[:900] = 0.
        else:
            pre = np.asarray(trace.pre_master, dtype=np.float64) * 12.0
            out = np.clip(pre * trace.gain, -0.08, 0.08).astype('<f4')
        return RenderTrace(recipe, trace.source, pre, out)

    return render, 'zg024d.' + name.replace('sentinel-', 'sentinel-') + '.v1'


def normalized_parameter_error(fixture, candidate):
    truth = dict(fixture.ground_truth_state.values)
    values = dict(candidate.to_dict()['parameters']['values'])
    terms = []
    for axis in fixture.domain.axes:
        span = axis.upper-axis.lower
        terms.append(((values[axis.path]-truth[axis.path])/span)**2 if span else 0.)
    return (sum(terms)/len(terms))**0.5
