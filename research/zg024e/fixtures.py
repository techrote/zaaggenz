"""Fresh development and safety fixtures for frozen ZG-024e protocol v1.

This module contains development material only. Confirmation fixtures are deliberately
absent until the development-only selection record is frozen in repository history.
Truth remains catalogue/orchestration evidence and is never supplied to FitEvaluator.
"""
from __future__ import annotations

import numpy as np

from zaaggenz_inverse import ParameterDomain, SearchBudget, Window, WindowPlan
from zaaggenz_inverse.fixtures import SyntheticFixture, _axis, _source, synthetic_fixture
from zaaggenz_inverse.recipes import RenderTrace, render_trace

DEVELOPMENT_NAMES = (
    "dev2-structure-spectral-starvation",
    "dev2-structure-budget",
    "dev2-spectral-budget",
    "dev2-mixed-texture",
    "dev2-identifiability",
)
SENTINEL_NAMES = ("sentinel2-transient", "sentinel2-silence", "sentinel2-clipping")
SEARCH_SEEDS = ("53", "307", "4099")
PLAN = WindowPlan(
    (Window("attack-fit2", 100, 1500), Window("body-fit2", 2100, 3350)),
    (Window("tail-holdout2", 4200, 5750),),
    6000,
)
OBJECTIVE = synthetic_fixture("identifiable").objective


def _budget(evaluations):
    if type(evaluations) is not int or evaluations not in (24, 36):
        raise ValueError("ZG-024e fixture budget must be 24 or 36")
    return SearchBudget(evaluations, 5, 2)


def _domain(base, *, equivalence=False):
    axes = [
        _axis(base, "/source/params/f0_hz", 59.0, 85.0),
        _axis(base, "/source/params/attack_ms", 1.0, 20.0),
        _axis(base, "/source/params/decay_ms", 115.0, 305.0),
        _axis(base, "/source/params/harmonic_decay", 0.65, 2.05),
        _axis(base, "/source/params/odd_even_ratio", 0.45, 3.05),
        _axis(base, "/source/params/drive_db", 0.0, 18.0),
        _axis(base, "/source/params/shaper_mix", 0.0, 1.0),
    ]
    if equivalence:
        axes.append(_axis(base, "/source/params/input_trim_db", -14.0, -5.0))
    return ParameterDomain(tuple(axes))


def _fixture(name, truth, base, description, seed, evaluations, *, equivalence=False):
    return SyntheticFixture(
        name=name,
        description=description,
        generation=(
            "fresh ZG-024e development target: accepted RenderRecipe/render_trace, canonical f32; "
            "truth is diagnostic only and is never supplied to FitEvaluator"
        ),
        ground_truth_recipe=truth,
        base_recipe=base,
        domain=_domain(base, equivalence=equivalence),
        target=render_trace(truth).output,
        plan=PLAN,
        objective=OBJECTIVE,
        budget=_budget(evaluations),
        seed=seed,
    )


def development_fixture(name, *, seed="53", budget_evaluations=36):
    if name not in DEVELOPMENT_NAMES + SENTINEL_NAMES:
        raise ValueError("unknown ZG-024e development fixture")
    if seed not in SEARCH_SEEDS:
        raise ValueError("seed is outside frozen ZG-024e set")

    if name == "dev2-structure-spectral-starvation":
        base = _source(
            f0_hz=61.5, attack_ms=2.2, decay_ms=150.0, harmonic_decay=0.80,
            odd_even_ratio=0.70, drive_db=2.5, shaper_mix=0.12, input_trim_db=-10.0,
        )
        truth = _source(
            f0_hz=80.4, attack_ms=7.1, decay_ms=268.0, harmonic_decay=1.88,
            odd_even_ratio=2.55, drive_db=2.5, shaper_mix=0.12, input_trim_db=-10.0,
        )
        return _fixture(
            name, truth, base,
            "Fresh coupled structural+spectral displacement intended to expose A-only eligible-parent starvation.",
            seed, budget_evaluations,
        )

    if name == "dev2-structure-budget":
        base = _source(
            f0_hz=66.0, attack_ms=3.0, decay_ms=165.0, harmonic_decay=1.05,
            odd_even_ratio=1.10, drive_db=2.0, shaper_mix=0.16, input_trim_db=-10.0,
        )
        truth = _source(
            f0_hz=76.2, attack_ms=8.8, decay_ms=282.0, harmonic_decay=1.05,
            odd_even_ratio=1.10, drive_db=2.0, shaper_mix=0.16, input_trim_db=-10.0,
        )
        return _fixture(
            name, truth, base,
            "Fresh dominant structural displacement with spectral/texture nuisance axes for stage-allocation diagnosis.",
            seed, budget_evaluations,
        )

    if name == "dev2-spectral-budget":
        base = _source(
            f0_hz=69.0, attack_ms=2.4, decay_ms=185.0, harmonic_decay=0.75,
            odd_even_ratio=0.65, drive_db=3.0, shaper_mix=0.20, input_trim_db=-10.0,
        )
        truth = _source(
            f0_hz=69.0, attack_ms=2.4, decay_ms=185.0, harmonic_decay=1.91,
            odd_even_ratio=2.72, drive_db=3.0, shaper_mix=0.20, input_trim_db=-10.0,
        )
        return _fixture(
            name, truth, base,
            "Fresh dominant spectral displacement with structural/texture nuisance axes for stage-allocation diagnosis.",
            seed, budget_evaluations,
        )

    if name == "dev2-mixed-texture":
        base = _source(
            f0_hz=64.0, attack_ms=2.8, decay_ms=150.0, harmonic_decay=0.88,
            odd_even_ratio=0.82, drive_db=1.0, shaper_mix=0.07, input_trim_db=-10.0,
        )
        truth = _source(
            f0_hz=74.1, attack_ms=6.0, decay_ms=246.0, harmonic_decay=1.61,
            odd_even_ratio=1.97, drive_db=14.0, shaper_mix=0.74, input_trim_db=-10.0,
        )
        return _fixture(
            name, truth, base,
            "Fresh mixed A/B/C displacement testing whether improved eligibility generalises through strong texture change.",
            seed, budget_evaluations,
        )

    if name == "dev2-identifiability":
        base = _source(
            f0_hz=71.0, attack_ms=3.4, decay_ms=205.0, harmonic_decay=1.15,
            odd_even_ratio=1.40, drive_db=9.5, input_trim_db=-5.5, shaper_mix=0.78,
        )
        truth = _source(
            f0_hz=73.2, attack_ms=4.2, decay_ms=218.0, harmonic_decay=1.45,
            odd_even_ratio=1.70, drive_db=13.5, input_trim_db=-9.5, shaper_mix=0.78,
        )
        return _fixture(
            name, truth, base,
            "Fresh drive+trim exact-sum equivalence embedded in modest A/B nuisance displacement; alternatives must remain visible.",
            seed, budget_evaluations, equivalence=True,
        )

    truth = _source(
        f0_hz=72.0, attack_ms=1.6, decay_ms=214.0, harmonic_decay=1.28,
        odd_even_ratio=1.48, drive_db=5.5, shaper_mix=0.37, input_trim_db=-10.0,
    )
    base = _source(
        f0_hz=65.5, attack_ms=4.2, decay_ms=158.0, harmonic_decay=0.90,
        odd_even_ratio=0.88, drive_db=2.8, shaper_mix=0.18, input_trim_db=-10.0,
    )
    descriptions = {
        "sentinel2-transient": "Candidate attack region is removed; accepted transient-v4/silence safety must reject.",
        "sentinel2-silence": "Candidates are rendered as silence; accepted silence/energy/transient safety must reject.",
        "sentinel2-clipping": "Candidates are forced into a destructive plateau; accepted clipping safety must reject.",
    }
    return _fixture(name, truth, base, descriptions[name], seed, budget_evaluations)


def sentinel_renderer(name):
    if name not in SENTINEL_NAMES:
        raise ValueError("not a ZG-024e sentinel fixture")

    def render(recipe):
        trace = render_trace(recipe)
        if name == "sentinel2-silence":
            pre = np.zeros_like(trace.pre_master)
            out = np.zeros_like(trace.output)
        elif name == "sentinel2-transient":
            pre = np.array(trace.pre_master, copy=True)
            out = np.array(trace.output, copy=True)
            pre[:900] = 0.0
            out[:900] = 0.0
        else:
            pre = np.asarray(trace.pre_master, dtype=np.float64) * 12.0
            out = np.clip(pre * trace.gain, -0.08, 0.08).astype("<f4")
        return RenderTrace(recipe, trace.source, pre, out)

    return render, "zg024e." + name.replace("sentinel2-", "sentinel-") + ".v1"


def normalized_parameter_error(fixture, candidate):
    truth = dict(fixture.ground_truth_state.values)
    values = dict(candidate.to_dict()["parameters"]["values"])
    terms = []
    for axis in fixture.domain.axes:
        span = axis.upper - axis.lower
        terms.append(((values[axis.path] - truth[axis.path]) / span) ** 2 if span else 0.0)
    return (sum(terms) / len(terms)) ** 0.5
