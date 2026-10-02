"""Lossless legacy adapters; never reinterpret a four-stage permutation.

The stored adapter is strict. The explicitly named execution projection may
replace bypassed settings with identity in a temporary request, but never
mutates saved data. New fractional rack/band/insert mixes and arbitrary external
positions need MBR-002/MBR-007 consumers, not a lossy old-request conversion.
"""
from __future__ import annotations
from copy import deepcopy

from zaaggenz_contracts.rack import (RackRecipe, RackError, RackCompatibilityError,
                                    RACK_VERSION, STAGES, EXTERNAL_TYPE,
                                    COMPRESSION, BITCRUSH, empty_rack, validate_insert)


def _spectral_from_dict(data):
    if data is None:
        return None
    # RackRecipe has already validated the complete type/version/field set.
    if data['kind'] == 'SpectralRetuneRequest':
        from .model import SpectralRetuneRequest, LatticeVoice, LatticeSegment
        values = deepcopy(data)
        del values['kind']; del values['version']
        values['voices'] = tuple(LatticeVoice(**v) for v in values['voices'])
        values['segments'] = tuple(LatticeSegment(s['start_sample'],
                                    tuple(LatticeVoice(**v) for v in s['voices']), s['label'])
                                    for s in values['segments'])
        return SpectralRetuneRequest(**values)
    if data['kind'] == 'ChordnessRequest':
        from .chordness_request import ChordnessRequest
        from .chordness_model import CombTemplate, ChordnessCoefficients
        values = deepcopy(data)
        del values['kind']; del values['version']
        values['templates'] = tuple(CombTemplate(**t) for t in values['templates'])
        values['coefficients'] = ChordnessCoefficients(**values['coefficients'])
        return ChordnessRequest(**values)
    raise RackError('unsupported spectral request')


def insert_spec(insert, sample_rate_hz):
    """Return an existing typed processor spec, not an executable new engine."""
    validate_insert(insert, sample_rate_hz)
    params = insert['params']
    if insert['type_id'] == EXTERNAL_TYPE:
        raise RackCompatibilityError('VST3 descriptor is preserved data, not an executable host')
    if insert['type_id'] == 'zg.gain':
        return params['gain_db']
    if params is None:
        return None
    if insert['type_id'] == 'zg.spectral':
        return _spectral_from_dict(params)
    if insert['type_id'] == 'zg.compression':
        from zaaggenz_dsp.dynamics import CompressionSpec
        return CompressionSpec(**params)
    from zaaggenz_dsp.bitcrush import BitcrushSpec
    return BitcrushSpec(**params)


def _slot_inserts(slot, band_id):
    values = {
        'spectral': None if slot.spectral is None else slot.spectral.to_dict(),
        'gain': {'gain_db': slot.gain_db},
        'compression': None if slot.compression is None else
                       {key: getattr(slot.compression, key) for key in COMPRESSION},
        'bitcrush': None if slot.bitcrush is None else
                    {key: getattr(slot.bitcrush, key) for key in BITCRUSH},
    }
    return [{'id': band_id + '.' + stage, 'type_id': 'zg.' + stage,
             'version': RACK_VERSION, 'bypass': False, 'wet': 1.,
             'params': deepcopy(values[stage]), 'automation': []}
            for stage in slot.stage_order]


def slot_to_band(slot, *, band='sub', band_id=None, confine_delta=True):
    """Preserve absent slot versus present-but-identity, including all four anchors."""
    from .band_selective import BandSlotSpec
    if slot is not None and not isinstance(slot, BandSlotSpec):
        raise RackError('BandSlotSpec or None required')
    identifier = 'band.' + band if band_id is None else band_id
    return {'id': identifier, 'band': band, 'bypass': False, 'wet': 1.,
            'confine_delta': confine_delta,
            'inserts': [] if slot is None else _slot_inserts(slot, identifier)}


def request_to_rack(request, source_recipe, *, rack_id='rack'):
    from .band_selective import BandSelectiveRequest
    if not isinstance(request, BandSelectiveRequest):
        raise RackError('BandSelectiveRequest required')
    data = empty_rack(source_recipe, rack_id=rack_id).to_dict()
    data['crossovers']['frequencies_hz'] = list(request.crossovers_hz)
    data['bands'] = [slot_to_band(slot, band=band['band'], band_id=band['id'], confine_delta=confine)
                     for band, slot, confine in zip(data['bands'], request.slots, request.confine_delta)]
    return RackRecipe(data)


def _band_disabled(band):
    return (band['bypass'] or band['wet'] == 0 or not band['inserts'] or
            all(i['bypass'] or i['wet'] == 0 for i in band['inserts']))


def _rack_disabled(data):
    return data['bypass'] or data['wet'] == 0 or all(_band_disabled(b) for b in data['bands'])


def _compatibility(data, execution):
    # Known-but-unavailable external types do not become implicit identity, even
    # behind bypass. Their explicit recovery is a later hosting/UI contract.
    if any(i['type_id'] == EXTERNAL_TYPE for b in data['bands'] for i in b['inserts']):
        raise RackCompatibilityError('VST3 descriptor has no executable legacy adapter')
    if not execution and (data['bypass'] or data['wet'] != 1):
        raise RackCompatibilityError('legacy request cannot store rack bypass/wet; use execution_request explicitly')
    if execution and _rack_disabled(data):
        return
    if data['wet'] != 1:
        raise RackCompatibilityError('fractional rack wet requires the rack execution consumer')
    for band in data['bands']:
        if execution and _band_disabled(band):
            continue
        if band['bypass'] or band['wet'] != 1:
            raise RackCompatibilityError('legacy request cannot represent band bypass/fractional wet')
        for insert in band['inserts']:
            if execution and (insert['bypass'] or insert['wet'] == 0):
                continue
            if insert['bypass'] or insert['wet'] != 1:
                raise RackCompatibilityError('legacy request cannot represent insert bypass/fractional wet')


def _band_to_slot(band, sample_rate_hz, *, execution=False):
    from .band_selective import BandSlotSpec
    inserts = band['inserts']
    if not inserts or (execution and _band_disabled(band)):
        return None
    stages = tuple(i['type_id'].removeprefix('zg.') for i in inserts)
    if len(stages) != 4 or set(stages) != set(STAGES):
        raise RackCompatibilityError('BandSlotSpec requires each of the four legacy stages exactly once; '
                                     'an arbitrary insert chain is not a legacy permutation')
    values = {}
    for insert in inserts:
        stage = insert['type_id'].removeprefix('zg.')
        value = insert_spec(insert, sample_rate_hz)
        if execution and (insert['bypass'] or insert['wet'] == 0):
            value = 0. if stage == 'gain' else None
        values['gain_db' if stage == 'gain' else stage] = value
    return BandSlotSpec(stage_order=stages, **values)


def rack_to_request(rack, *, execution=False):
    """Lossless old-contract conversion by default; reject unrepresentable edits."""
    from .band_selective import BandSelectiveRequest
    if type(execution) is not bool:
        raise RackError('execution must be boolean')
    saved = rack if isinstance(rack, RackRecipe) else RackRecipe(rack)
    # Revalidate serialized snapshots rather than trusting caller-owned nested objects.
    data = RackRecipe(saved.to_dict()).to_dict()
    _compatibility(data, execution)
    bypass = execution and _rack_disabled(data)
    slots = (None,) * 4 if bypass else tuple(
        _band_to_slot(band, data['sample_rate_hz'], execution=execution) for band in data['bands'])
    return BandSelectiveRequest(tuple(data['crossovers']['frequencies_hz']), slots,
                                tuple(band['confine_delta'] for band in data['bands']))


def execution_request(rack):
    """A temporary legacy execution projection; saved bypassed settings are retained."""
    return rack_to_request(rack, execution=True)


def band_to_slot(band, source_recipe, *, execution=False):
    """Standalone BandSlotSpec adapter with full contextual validation."""
    if type(band) is not dict:
        raise RackError('band must be an object')
    data = empty_rack(source_recipe).to_dict()
    index = next((i for i, row in enumerate(data['bands']) if row['band'] == band.get('band')), None)
    if index is None:
        raise RackError('unknown spectral band')
    data['bands'][index] = deepcopy(band)
    return rack_to_request(RackRecipe(data), execution=execution).slots[index]
