"""Lossless adapters to the recovered dataclasses, not HTTP coercion or new DSP."""
from copy import deepcopy
from .model import Contract, ContractError, check_json, rational
from .schema import VERSION
from .registry import legacy_catalogue, legacy_schema
from .validation import shape, validate, require


def adapt_parameters(family, values):
    check_json(values)
    require(type(values) is dict, 'legacy parameters must be an object')
    catalogue = legacy_catalogue()
    require(family in catalogue, 'unsupported legacy family')
    defaults = deepcopy(catalogue[family]['defaults'])
    supplied = deepcopy(values)
    if family == 'arrangement':
        derived = {k: supplied.pop(k) for k in ('bars', 'beats', 'duration_s') if k in supplied}
        defaults.update(supplied)
        require(type(defaults['sections']) is list, 'sections must be an array')
        sections = []
        # Explicit defaults for old partial sections, preserving existing field meanings.
        section_props = catalogue[family]['schema']['properties']['sections']['items']['properties']
        from_defaults = dict(name='section', bars=4, intensity_start=.35, intensity_end=.55,
                             roll_amount=.35, max_subdivision=4, pattern='progressive', timbre_drift=.35, density_bias=0.)
        for section in defaults['sections']:
            require(type(section) is dict, 'section must be an object')
            require(set(section) <= set(section_props), 'unknown legacy section field')
            sections.append({**from_defaults, **section})
        defaults['sections'] = sections
        shape(defaults, legacy_schema(family))
        bars = sum(s['bars'] for s in sections)
        expected = dict(bars=bars, beats=bars * defaults['beats_per_bar'],
                        duration_s=bars * defaults['beats_per_bar'] * 60. / defaults['bpm'])
        require(all(v == expected[k] for k, v in derived.items()), 'inconsistent derived arrangement fields')
    else:
        defaults.update(supplied)
    shape(defaults, legacy_schema(family))
    # JSON Schema integer permits integral numeric spelling (e.g. 4.0).
    def ints(value, spec):
        if spec.get('type') == 'integer':
            return int(value)
        if spec.get('type') == 'object':
            return {k: ints(v, spec['properties'][k]) for k, v in value.items()}
        if spec.get('type') == 'array':
            return [ints(v, spec['items']) for v in value]
        return value
    return ints(defaults, legacy_schema(family))


def legacy_object(family, values):
    p = adapt_parameters(family, values)
    # Fixed imports, never from a method id/filename supplied in a recipe.
    from uptempo_harmony.synth import KickParams
    from uptempo_harmony.reversebass import ReverseBassParams
    from uptempo_harmony.multiband import SpectralSculptParams
    from uptempo_harmony.arrangement import ArrangementSpec, ArrangementSection
    if family == 'arrangement':
        p['sections'] = [ArrangementSection(**v) for v in p['sections']]
    return {'synth': KickParams, 'reversebass': ReverseBassParams,
            'sculpt': SpectralSculptParams, 'arrangement': ArrangementSpec}[family](**p)


def envelope(kind, **fields):
    return dict(kind=kind, version=VERSION, **fields)


def freeze_legacy(synth, *, mode='synth', arrangement=None, reversebass=None, sculpt=None, master_gain_db=0.0):
    p = adapt_parameters('synth', synth)
    ar = adapt_parameters('arrangement', arrangement) if arrangement is not None else None
    rb = adapt_parameters('reversebass', reversebass) if reversebass is not None else None
    sc = adapt_parameters('sculpt', sculpt) if sculpt is not None else None
    bpm = ar['bpm'] if ar else p['bpm']
    meter = ar['beats_per_bar'] if ar else 4
    return Contract(envelope('RenderRecipe', render_mode=mode,
        source=dict(id='source', method='legacy.synth.1.2.1', params=p),
        arrangement=ar, reversebass=rb, sculpt=sc,
        time_map=envelope('TimeMap', sample_rate_hz=p['sr'], origin_sample=0,
            beat_unit='quarter_note', rounding='nearest_ties_even',
            tempo_segments=[dict(beat='0/1', bpm=rational(bpm))],
            meter_segments=[dict(beat='0/1', numerator=meter, denominator=4)]),
        tuning=envelope('TuningSpec', id='legacy-12edo', reference_hz=p['f0_hz'], reference_degree=0,
            period_ratio=2., degree_ratios=[2**(k/12) for k in range(12)], keyboard=None),
        phrase=None, nodes=[], output_node='source', channels=1,
        phase_policy='legacy-v1.2.1', state_policy='reset-render',
        tail=dict(mode='legacy', maximum_samples=0), quality='legacy',
        random=dict(algorithm='sha256-named-u64-v1', root=str(p['seed']), streams=[]),
        output=dict(master_gain_db=master_gain_db, clipping='clip_at_full_scale', normalisation='none',
                    diagnostic_stems='pre_master', mix='post_master')))


def thaw_legacy(recipe):
    """Reject unsupported musical/DSP intent instead of dropping it on the old engine."""
    d = recipe.to_dict() if isinstance(recipe, Contract) else deepcopy(recipe)
    validate(d, 'RenderRecipe')
    expected = freeze_legacy(d['source']['params'], mode=d['render_mode'], arrangement=d['arrangement'],
        reversebass=d['reversebass'], sculpt=d['sculpt'], master_gain_db=d['output']['master_gain_db'])
    require(Contract(d).sha256 == expected.sha256,
            'recipe is not a legacy-exact projection; requires a new consumer (no fields silently ignored)')
    result = {'synth': legacy_object('synth', d['source']['params']), 'mode': d['render_mode'],
              'master_gain_db': d['output']['master_gain_db']}
    for family in ('arrangement', 'reversebass', 'sculpt'):
        result[family] = None if d[family] is None else legacy_object(family, d[family])
    return result
