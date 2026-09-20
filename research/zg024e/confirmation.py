"""ZG-024e sealed confirmation catalogue.

Repository history is intentional: the preregistered protocol freeze
a7156aa6cb148582a943b8c0f211e5f603b1670b and the development-selection freeze
3364e563aa8094bc39655570d7197542fba2e6b5 both predate this module.

Confirmation is therefore disclosure-only: it cannot choose another intervention,
matched null, causal diagnosis, budget, seed set, gate policy, or objective.
"""
from __future__ import annotations

from zaaggenz_inverse.fixtures import SyntheticFixture, _source
from zaaggenz_inverse.recipes import render_trace

from .fixtures import OBJECTIVE, PLAN, SEARCH_SEEDS, _budget, _domain

CONFIRMATION_NAMES = (
    "confirm2-structure-spectral-starvation",
    "confirm2-mixed-texture",
    "confirm2-identifiability-coupled",
)
DESIGN_FREEZE_COMMIT = "a7156aa6cb148582a943b8c0f211e5f603b1670b"
SELECTION_FREEZE_COMMIT = "3364e563aa8094bc39655570d7197542fba2e6b5"
SELECTION_DECISION_SHA256 = "d673e22602aee773005e242910a0a54b60f2e9cedfff26c5d6898b3cf3ba6629"
SELECTED_METHOD = "zg024e.coupled-ab-36.v1"
MATCHED_NULL_METHOD = "zg024e.factorized-36-balanced.v1"


def _confirmation_fixture(name, truth, base, description, seed, *, equivalence=False):
    return SyntheticFixture(
        name=name,
        description=description,
        generation=(
            "sealed ZG-024e confirmation target disclosed only after committed "
            "development selection; accepted RenderRecipe/render_trace, canonical f32; "
            "truth is post-selection diagnostic only"
        ),
        ground_truth_recipe=truth,
        base_recipe=base,
        domain=_domain(base, equivalence=equivalence),
        target=render_trace(truth).output,
        plan=PLAN,
        objective=OBJECTIVE,
        budget=_budget(36),
        seed=seed,
    )


def confirmation_fixture(name, *, seed="53"):
    if name not in CONFIRMATION_NAMES:
        raise ValueError("unknown ZG-024e confirmation fixture")
    if seed not in SEARCH_SEEDS:
        raise ValueError("seed is outside frozen ZG-024e set")

    if name == "confirm2-structure-spectral-starvation":
        base = _source(
            f0_hz=62.7, attack_ms=2.0, decay_ms=142.0, harmonic_decay=0.77,
            odd_even_ratio=0.61, drive_db=3.2, shaper_mix=0.15, input_trim_db=-10.0,
        )
        truth = _source(
            f0_hz=81.7, attack_ms=7.8, decay_ms=276.0, harmonic_decay=1.94,
            odd_even_ratio=2.71, drive_db=3.2, shaper_mix=0.15, input_trim_db=-10.0,
        )
        return _confirmation_fixture(
            name, truth, base,
            "Untouched confirmation: fresh simultaneous structural+spectral displacement "
            "testing the frozen cross-family-coupling diagnosis.",
            seed,
        )

    if name == "confirm2-mixed-texture":
        base = _source(
            f0_hz=63.2, attack_ms=2.5, decay_ms=148.0, harmonic_decay=0.84,
            odd_even_ratio=0.76, drive_db=1.8, shaper_mix=0.10, input_trim_db=-10.0,
        )
        truth = _source(
            f0_hz=75.6, attack_ms=6.7, decay_ms=252.0, harmonic_decay=1.69,
            odd_even_ratio=2.12, drive_db=13.2, shaper_mix=0.69, input_trim_db=-10.0,
        )
        return _confirmation_fixture(
            name, truth, base,
            "Untouched confirmation: fresh A+B displacement plus strong nonlinear texture "
            "change, distinct from prior calibration and confirmation targets.",
            seed,
        )

    base = _source(
        f0_hz=70.2, attack_ms=3.1, decay_ms=198.0, harmonic_decay=1.08,
        odd_even_ratio=1.31, drive_db=8.8, input_trim_db=-5.8, shaper_mix=0.72,
    )
    truth = _source(
        f0_hz=74.0, attack_ms=4.7, decay_ms=226.0, harmonic_decay=1.52,
        odd_even_ratio=1.82, drive_db=13.1, input_trim_db=-10.1, shaper_mix=0.72,
    )
    return _confirmation_fixture(
        name, truth, base,
        "Untouched confirmation: fresh drive/input-trim equivalence embedded in "
        "structural+spectral nuisance displacement.",
        seed, equivalence=True,
    )
