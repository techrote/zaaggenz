"""Shared fixtures; use the authenticated materialized baseline on every OS."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
from copy import deepcopy
from zaaggenz_contracts import Contract
from zaaggenz_contracts.legacy import freeze_legacy
from zaaggenz_contracts.rack import RackRecipe, empty_rack, state_blob
from zaaggenz_dsp import CompressionSpec, BitcrushSpec
from zaaggenz_spectral.band_selective import BandSlotSpec, BandSelectiveRequest
from zaaggenz_spectral.rack_adapter import request_to_rack
from zaaggenz_spectral.model import SpectralRetuneRequest, LatticeVoice, LatticeSegment
from zaaggenz_spectral.chordness_request import ChordnessRequest
from zaaggenz_spectral.chordness_model import CombTemplate, ChordnessCoefficients


def source(rate=12000):
    return freeze_legacy({'sr': rate})


def retune(base=None):
    base = source() if base is None else base
    return SpectralRetuneRequest(base.to_dict()['tuning'],
        (LatticeVoice(0, (1., 2., 3.), 'Root'), LatticeVoice(7, (1., 2.), 'Fifth')),
        segments=(LatticeSegment(1200, (LatticeVoice(-12, (1., 3.), 'Bass'),), 'Change'),),
        amount=.75, min_confidence=.4, min_hz=20., max_hz=4000.,
        max_displacement_cents=300., max_correction_slew_cents_per_second=1600.,
        assignment_hysteresis_cents=40., preserve_ambiguous=False)


def chordness():
    return ChordnessRequest((CombTemplate('root', (100., 200., 300.), 2, 'Root', {'method': 'manual'}),
                            CombTemplate('fifth', (150., 300., 450.), 1, 'Fifth', {})),
        mode='hybrid', selection_mode='manual', selected_template_ids=('root', 'fifth'),
        max_selected_templates=2, retune_amount=.7, reweight_amount=.3, min_confidence=.4,
        tolerance_cents=31., max_assignment_cents=900., max_displacement_cents=250.,
        max_correction_slew_cents_per_second=1200., max_gain_db=5., max_gain_slew_db_per_second=20.,
        preserve_ambiguous=False, coefficients=ChordnessCoefficients(.9, .3, .04, .12, .08))


def slot(spectral=None, order=('spectral', 'gain', 'compression', 'bitcrush')):
    return BandSlotSpec(gain_db=3., spectral=spectral, stage_order=order,
        compression=CompressionSpec(threshold_db=-20., ratio=3., attack_ms=3., release_ms=70.,
                                    knee_db=4., makeup_db=1., wet=.8),
        bitcrush=BitcrushSpec(bit_depth=7, hold_samples=3, full_scale=2., wet=.65))


def rack(base=None, spectral=None):
    base = source() if base is None else base
    return request_to_rack(BandSelectiveRequest(slots=(None, slot(spectral), None, None),
                          confine_delta=(True, False, True, True)), base)


def external(identifier='external.test', payload=b'opaque\x00component\xffstate'):
    return {'id': identifier, 'type_id': 'external.vst3', 'version': '1.0.0',
            'bypass': True, 'wet': 1., 'automation': [],
            'params': {'format': 'VST3', 'platform': 'windows-x64',
                       'class_id': '0123456789ABCDEF' * 2, 'binary_sha256': '1' * 64,
                       'component_state': state_blob(payload), 'controller_state': state_blob(b'controller'),
                       'execution_contract': 'preservation-only.v1'}}


def insert(data, stage='compression'):
    return next(i for i in data['bands'][1]['inserts'] if i['type_id'] == 'zg.' + stage)
