"""Fresh preregistered ZG-024d staged-search fixtures.

Development and confirmation fixture names, seeds, domains, budgets, stage partitions
and decision roles are frozen in source before confirmation outcomes are inspected.
Ground truth remains catalogue/evidence-owner data and is never passed to the search
capability.  The confirmation set is not used to tune stage definitions or thresholds.
"""
from __future__ import annotations

from dataclasses import replace

from zaaggenz_contracts.legacy import envelope, freeze_legacy
from zaaggenz_contracts import Contract
from zaaggenz_inverse import ParameterDomain, SearchBudget
from zaaggenz_inverse.fixtures import SyntheticFixture, _axis, _source, synthetic_fixture
from zaaggenz_inverse.recipes import render_trace

from .staged import StageDefinition, StagedPlan

DEV_NAMES = (
    "dev-root-envelope",
    "dev-spectral",
    "dev-nonlinear",
    "dev-mixed",
    "dev-nonidentifiable",
    "dev-holdout",
)
CONFIRM_NAMES = (
    "confirm-mixed-a",
    "confirm-mixed-b",
    "confirm-nonidentifiable",
    "confirm-holdout",
    "confirm-transient-safe",
)
DEV_SEEDS = ("31", "211", "2027")
CONFIRM_SEEDS = ("43", "509", "4099")
SAFETY_NAMES = ("safety-silence", "safety-transient-damage", "safety-clipping")


def _with_graph(recipe, node):
    data = recipe.to_dict()
    data["nodes"], data["output_node"] = [node], node["id"]
    return Contract(data)


def _gain_step(recipe, late_db, sample=3600):
    node = envelope(
        "DSPNodeSpec", id="zg024d-gain-step", type_id="core.gain.v1", inputs=["source"],
        channels=1, params={"gain_db": 0.}, state_policy="stateless",
        phase_policy="source-derived", latency_samples=0, lookahead_samples=0,
        bypass="identity", automation=[{
            "parameter": "gain_db", "unit": "dB", "interpolation": "step",
            "points": [{"sample": 0, "value": 0.}, {"sample": sample, "value": late_db}],
        }],
    )
    return _with_graph(recipe, node)


def _stage(id, axes, evaluations, retain=3):
    proposal = {
        "stage-a-root-envelope": "shifted-halton-v1",
        "stage-b-spectral": "parented-shifted-halton-v1",
        "stage-c-texture": "parented-coordinate-v1",
    }[id]
    return StageDefinition(id, tuple(axes), evaluations, retain, proposal)


def _plan(a=(), b=(), c=(), budgets=(0, 0, 0), retains=(3, 3, 3)):
    return StagedPlan((
        _stage("stage-a-root-envelope", a, budgets[0], retains[0]),
        _stage("stage-b-spectral", b, budgets[1], retains[1]),
        _stage("stage-c-texture", c, budgets[2], retains[2]),
    ))


def _make(name, *, truth, base, axes, plan, seed, description):
    template = synthetic_fixture("identifiable")
    target = render_trace(truth).output
    budget = SearchBudget(sum(s.evaluations for s in plan.stages), 5, 2)
    fixture = SyntheticFixture(
        name=name,
        description=description,
        generation=("fresh ZG-024d fixture; accepted RenderRecipe/render_trace; canonical f32; "
                    "truth held by catalogue/evidence owner only"),
        ground_truth_recipe=truth,
        base_recipe=base,
        domain=ParameterDomain(tuple(axes)),
        target=target,
        plan=template.plan,
        objective=template.objective,
        budget=budget,
        seed=seed,
    )
    plan.validate_request(fixture.request)
    return fixture, plan


def research_fixture(name, *, seed):
    allowed = DEV_SEEDS if name in DEV_NAMES else CONFIRM_SEEDS if name in CONFIRM_NAMES else ()
    if seed not in allowed:
        raise ValueError("seed outside preregistered fixture role")

    if name == "dev-root-envelope":
        truth = _source(f0_hz=76.4, attack_ms=3.7, decay_ms=237.)
        base = _source(f0_hz=61., attack_ms=1., decay_ms=125.)
        a = (_axis(base, "/source/params/f0_hz", 58., 90.),
             _axis(base, "/source/params/attack_ms", .5, 12.),
             _axis(base, "/source/params/decay_ms", 100., 320.))
        plan = _plan(a=[x.path for x in a], budgets=(18, 0, 0))
        return _make(name, truth=truth, base=base, axes=a, plan=plan, seed=seed,
                     description="Development root/attack/envelope coverage with deliberately off-grid truth.")

    if name == "dev-spectral":
        truth = _source(harmonic_decay=1.47, odd_even_ratio=2.35, harmonic_tilt_db_per_oct=-1.6)
        base = _source(harmonic_decay=.75, odd_even_ratio=.6, harmonic_tilt_db_per_oct=1.0)
        b = (_axis(base, "/source/params/harmonic_decay", .6, 2.1),
             _axis(base, "/source/params/odd_even_ratio", .4, 4.2),
             _axis(base, "/source/params/harmonic_tilt_db_per_oct", -3., 2.))
        plan = _plan(b=[x.path for x in b], budgets=(0, 18, 0))
        return _make(name, truth=truth, base=base, axes=b, plan=plan, seed=seed,
                     description="Development spectral-structure coverage with three interacting off-grid axes.")

    if name == "dev-nonlinear":
        truth = _source(drive_db=13.2, shaper_mix=.68)
        base = _source(drive_db=4., shaper_mix=.08)
        c = (_axis(base, "/source/params/drive_db", 3., 19.),
             _axis(base, "/source/params/shaper_mix", 0., 1.))
        plan = _plan(c=[x.path for x in c], budgets=(0, 0, 18))
        return _make(name, truth=truth, base=base, axes=c, plan=plan, seed=seed,
                     description="Development local nonlinear texture case for drive/wet refinement.")

    if name == "dev-mixed":
        truth = _source(f0_hz=74.7, decay_ms=224., harmonic_decay=1.38,
                        odd_even_ratio=2.6, drive_db=11.9, shaper_mix=.57)
        base = _source(f0_hz=60., decay_ms=120., harmonic_decay=.7,
                       odd_even_ratio=.5, drive_db=4., shaper_mix=.05)
        a = (_axis(base, "/source/params/f0_hz", 58., 88.),
             _axis(base, "/source/params/decay_ms", 100., 300.))
        b = (_axis(base, "/source/params/harmonic_decay", .6, 2.0),
             _axis(base, "/source/params/odd_even_ratio", .4, 4.0))
        c = (_axis(base, "/source/params/drive_db", 3., 18.),
             _axis(base, "/source/params/shaper_mix", 0., .95))
        plan = _plan(a=[x.path for x in a], b=[x.path for x in b], c=[x.path for x in c],
                     budgets=(10, 10, 10), retains=(3, 3, 3))
        return _make(name, truth=truth, base=base, axes=a+b+c, plan=plan, seed=seed,
                     description="Development six-axis mixed case exercising all three stages and parent promotion.")

    if name == "dev-nonidentifiable":
        truth = _source(shaper_mix=.8, drive_db=13.6, input_trim_db=-9.8)
        base = _source(shaper_mix=.8, drive_db=9., input_trim_db=-12.)
        c = (_axis(base, "/source/params/drive_db", 8., 17.),
             _axis(base, "/source/params/input_trim_db", -14., -6.))
        plan = _plan(c=[x.path for x in c], budgets=(0, 0, 16), retains=(3, 3, 4))
        return _make(name, truth=truth, base=base, axes=c, plan=plan, seed=seed,
                     description="Development known drive+trim equivalence manifold; raw recipe recovery is not success.")

    if name == "dev-holdout":
        truth = _gain_step(_source(), 4.5, 3650)
        base = _gain_step(_source(), -5.0, 3650)
        a = (_axis(base, "/nodes/0/automation/0/points/1/value", -5., 5.),)
        plan = _plan(a=[x.path for x in a], budgets=(9, 0, 0), retains=(4, 3, 3))
        return _make(name, truth=truth, base=base, axes=a, plan=plan, seed=seed,
                     description="Development fit-equivalent late automation; holdout must not feed search or promotion.")

    if name == "confirm-mixed-a":
        truth = _source(f0_hz=79.1, decay_ms=188., harmonic_decay=1.62,
                        odd_even_ratio=1.9, drive_db=14.4, shaper_mix=.71)
        base = _source(f0_hz=63., decay_ms=280., harmonic_decay=.82,
                       odd_even_ratio=3.6, drive_db=5., shaper_mix=.1)
        a = (_axis(base, "/source/params/f0_hz", 60., 92.),
             _axis(base, "/source/params/decay_ms", 100., 320.))
        b = (_axis(base, "/source/params/harmonic_decay", .65, 2.2),
             _axis(base, "/source/params/odd_even_ratio", .5, 4.2))
        c = (_axis(base, "/source/params/drive_db", 4., 20.),
             _axis(base, "/source/params/shaper_mix", 0., .95))
        plan = _plan(a=[x.path for x in a], b=[x.path for x in b], c=[x.path for x in c],
                     budgets=(10, 10, 10), retains=(3, 3, 3))
        return _make(name, truth=truth, base=base, axes=a+b+c, plan=plan, seed=seed,
                     description="Sealed confirmation mixed case A; not used to choose stage budgets or rules.")

    if name == "confirm-mixed-b":
        truth = _source(f0_hz=70.6, attack_ms=5.2, harmonic_decay=1.24,
                        harmonic_tilt_db_per_oct=-1.1, drive_db=10.8, shaper_mix=.49)
        base = _source(f0_hz=86., attack_ms=1., harmonic_decay=1.9,
                       harmonic_tilt_db_per_oct=1.5, drive_db=3., shaper_mix=.05)
        a = (_axis(base, "/source/params/f0_hz", 58., 90.),
             _axis(base, "/source/params/attack_ms", .5, 14.))
        b = (_axis(base, "/source/params/harmonic_decay", .6, 2.1),
             _axis(base, "/source/params/harmonic_tilt_db_per_oct", -3., 2.))
        c = (_axis(base, "/source/params/drive_db", 2., 18.),
             _axis(base, "/source/params/shaper_mix", 0., .9))
        plan = _plan(a=[x.path for x in a], b=[x.path for x in b], c=[x.path for x in c],
                     budgets=(10, 10, 10), retains=(3, 3, 3))
        return _make(name, truth=truth, base=base, axes=a+b+c, plan=plan, seed=seed,
                     description="Sealed confirmation mixed case B with attack and spectral tilt.")

    if name == "confirm-nonidentifiable":
        truth = _source(shaper_mix=.78, drive_db=15.1, input_trim_db=-11.4, harmonic_decay=1.33)
        base = _source(shaper_mix=.78, drive_db=9., input_trim_db=-12., harmonic_decay=.75)
        b = (_axis(base, "/source/params/harmonic_decay", .6, 2.0),)
        c = (_axis(base, "/source/params/drive_db", 8., 18.),
             _axis(base, "/source/params/input_trim_db", -15., -6.))
        plan = _plan(b=[x.path for x in b], c=[x.path for x in c], budgets=(0, 10, 14), retains=(3, 3, 4))
        return _make(name, truth=truth, base=base, axes=b+c, plan=plan, seed=seed,
                     description="Sealed confirmation includes a known non-identifiable drive/trim manifold.")

    if name == "confirm-holdout":
        truth = _gain_step(_source(f0_hz=71.5), 5.0, 3700)
        base = _gain_step(_source(f0_hz=71.5), -4.0, 3700)
        a = (_axis(base, "/nodes/0/automation/0/points/1/value", -4., 6.),)
        plan = _plan(a=[x.path for x in a], budgets=(9, 0, 0), retains=(4, 3, 3))
        return _make(name, truth=truth, base=base, axes=a, plan=plan, seed=seed,
                     description="Sealed fit-equivalent late-gain confirmation sentinel; holdout cannot rerank.")

    if name == "confirm-transient-safe":
        truth = _source(f0_hz=77.2, attack_ms=2.4, decay_ms=205., transient_click=.055,
                        harmonic_decay=1.31, drive_db=8.7, shaper_mix=.36)
        base = _source(f0_hz=62., attack_ms=8., decay_ms=290., transient_click=.055,
                       harmonic_decay=.8, drive_db=3., shaper_mix=.05)
        a = (_axis(base, "/source/params/f0_hz", 58., 90.),
             _axis(base, "/source/params/attack_ms", .5, 12.),
             _axis(base, "/source/params/decay_ms", 120., 320.))
        b = (_axis(base, "/source/params/harmonic_decay", .65, 2.0),)
        c = (_axis(base, "/source/params/drive_db", 2., 16.),
             _axis(base, "/source/params/shaper_mix", 0., .8))
        plan = _plan(a=[x.path for x in a], b=[x.path for x in b], c=[x.path for x in c],
                     budgets=(12, 8, 10), retains=(4, 3, 3))
        return _make(name, truth=truth, base=base, axes=a+b+c, plan=plan, seed=seed,
                     description="Sealed transient-bearing mixed case after the independently repaired transient-v4 gate.")

    raise ValueError("unknown ZG-024d fixture")


def normalized_parameter_error(fixture, candidate):
    if "nonidentifiable" in fixture.name or "holdout" in fixture.name:
        return None
    truth = dict(fixture.ground_truth_state.values)
    values = dict(candidate.to_dict()["parameters"]["values"])
    terms = []
    for axis in fixture.domain.axes:
        span = axis.upper - axis.lower
        terms.append(((values[axis.path] - truth[axis.path]) / span) ** 2 if span else 0.)
    return (sum(terms) / len(terms)) ** 0.5


def manifold_error(fixture, candidate):
    if "nonidentifiable" not in fixture.name:
        return None
    truth = dict(fixture.ground_truth_state.values)
    values = dict(candidate.to_dict()["parameters"]["values"])
    target = truth["/source/params/drive_db"] + truth["/source/params/input_trim_db"]
    actual = values["/source/params/drive_db"] + values["/source/params/input_trim_db"]
    return abs(actual - target) / 20.0


def safety_fixture(name):
    """Return a fresh target plus an intentionally unsafe probe state.

    These probes are post-protocol anti-degeneracy checks.  Their eligibility is an
    outcome, not an assertion baked into fixture construction.  Any unsafe probe that
    remains eligible blocks production promotion in the frozen decision rule.
    """
    template = synthetic_fixture("identifiable")
    if name == "safety-silence":
        truth = _source(peak=0.)
        base = _source(peak=.25)
        axes = (_axis(base, "/source/params/peak", 0., .4),)
        unsafe = {"/source/params/peak": .4}
        purpose = "non-silent output must not become an acceptable surrogate for a silent target"
    elif name == "safety-transient-damage":
        truth = _source(f0_hz=74., attack_ms=.6, decay_ms=190., transient_click=.08)
        base = _source(f0_hz=74., attack_ms=.6, decay_ms=190., transient_click=.08)
        axes = (_axis(base, "/source/params/attack_ms", .5, 90.),)
        unsafe = {"/source/params/attack_ms": 90.}
        purpose = "deliberately smeared attack must remain an explicit eligibility failure"
    elif name == "safety-clipping":
        truth = _source(drive_db=2., shaper_mix=.15, hard_clip_mix=0.)
        base = _source(drive_db=2., shaper_mix=.15, hard_clip_mix=0.)
        axes = (_axis(base, "/source/params/drive_db", 2., 30.),
                _axis(base, "/source/params/hard_clip_mix", 0., 1.))
        unsafe = {"/source/params/drive_db": 30., "/source/params/hard_clip_mix": 1.}
        purpose = "extreme drive plus hard clipping must not win by objective exploitation"
    else:
        raise ValueError("unknown ZG-024d safety fixture")
    fixture = SyntheticFixture(
        name=name, description=purpose,
        generation="fresh ZG-024d anti-degeneracy probe; accepted RenderRecipe/render_trace; canonical f32",
        ground_truth_recipe=truth, base_recipe=base, domain=ParameterDomain(tuple(axes)),
        target=render_trace(truth).output, plan=template.plan, objective=template.objective,
        budget=SearchBudget(1, 3, 2), seed="7309",
    )
    state = fixture.request.domain.validate_state(
        __import__("zaaggenz_inverse").ParameterState(tuple(unsafe.items())))
    return fixture, state, purpose
