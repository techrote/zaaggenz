"""ZG-024d v2 confirmation catalogue.

Repository history is intentional: protocol-v2 design freeze commit
35e6f5ed6f905fa853d2eb58a683065b126c84b3 predates this file.  The report imports
this module only after the development-only staged-method choice is frozen.
"""
from __future__ import annotations

from zaaggenz_inverse.fixtures import _source
from .fixtures import SEARCH_SEEDS, _fixture

CONFIRMATION_NAMES = ('confirm-structure-spectral', 'confirm-texture-mixed', 'confirm-equivalence')
DESIGN_FREEZE_COMMIT = '35e6f5ed6f905fa853d2eb58a683065b126c84b3'


def confirmation_fixture(name, *, seed='41'):
    if name not in CONFIRMATION_NAMES:
        raise ValueError('unknown ZG-024d confirmation fixture')
    if seed not in SEARCH_SEEDS:
        raise ValueError('seed is outside frozen ZG-024d set')

    if name == 'confirm-structure-spectral':
        base = _source(f0_hz=63., attack_ms=2.5, decay_ms=145., harmonic_decay=.82,
                       odd_even_ratio=.72, drive_db=3.5, shaper_mix=.18, input_trim_db=-10.)
        truth = _source(f0_hz=79.1, attack_ms=7.4, decay_ms=271., harmonic_decay=1.84,
                        odd_even_ratio=2.62, drive_db=3.5, shaper_mix=.18, input_trim_db=-10.)
        return _fixture(name, truth, base,
            'Untouched confirmation: coupled structural and spectral displacement with texture nuisance axes.', seed)

    if name == 'confirm-texture-mixed':
        base = _source(f0_hz=65., attack_ms=3.2, decay_ms=155., harmonic_decay=.92,
                       odd_even_ratio=.82, drive_db=1.5, shaper_mix=.08, input_trim_db=-10.)
        truth = _source(f0_hz=72.9, attack_ms=4.8, decay_ms=224., harmonic_decay=1.46,
                        odd_even_ratio=1.68, drive_db=15.2, shaper_mix=.79, input_trim_db=-10.)
        return _fixture(name, truth, base,
            'Untouched confirmation: mixed A/B displacement plus strong local nonlinear texture change.', seed)

    base = _source(f0_hz=71., attack_ms=3.8, decay_ms=215., harmonic_decay=1.34,
                   odd_even_ratio=1.62, drive_db=9., input_trim_db=-6., shaper_mix=.76)
    truth = _source(f0_hz=71., attack_ms=3.8, decay_ms=215., harmonic_decay=1.34,
                    odd_even_ratio=1.62, drive_db=13., input_trim_db=-10., shaper_mix=.76)
    return _fixture(name, truth, base,
        'Untouched confirmation: distinct drive/trim recipe on an exact nonlinear equivalence manifold.',
        seed, equivalence=True)
