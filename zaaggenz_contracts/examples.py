"""Portable test/example metadata. Hash placeholders are NOT existing media."""
from copy import deepcopy
from .legacy import envelope, freeze_legacy


def examples():
    asset = envelope('AudioAssetRef', content_sha256='0'*64, identity_domain='pcm-f32le-interleaved-v1',
        sample_rate_hz=48000, channels=2, channel_layout='stereo-lr', frame_count=48000,
        level_domain='source', sample_policy='unclamped_float')
    time = envelope('TimeMap', sample_rate_hz=48000, origin_sample=48000, beat_unit='quarter_note',
        rounding='nearest_ties_even', tempo_segments=[dict(beat='0/1', bpm='200/1'), dict(beat='8/1', bpm='240/1')],
        meter_segments=[dict(beat='0/1', numerator=4, denominator=4)])
    tuning = envelope('TuningSpec', id='tritave', reference_hz=48., reference_degree=0,
        period_ratio=3., degree_ratios=[1., 1.5, 2.], keyboard=dict(first_key=0, last_key=127,
        middle_key=60, reference_key=60, formal_period_degrees=3, entries=[0, None, 1, 2]))
    support = dict(start_sample=0, end_sample=2048, anchor_sample=1024, padding='none')
    method = dict(id='example.synthetic', version='1', configuration={'window_samples': 2048})
    random = dict(algorithm='sha256-named-u64-v1', root='18446744073709551615', streams=['notes', 'texture'])
    feature = envelope('FeatureBundle', asset=asset, method=method, observations=[dict(feature='f0',unit='Hz',
        value=None, role='estimate', validity='abstained', confidence=None, support=support)])
    partial = envelope('PartialTrackBundle', asset=asset, method=method,
        phase_convention='cosine-at-anchor-radians-v1', channel_policy='shared-frequency-independent-channel-coefficients',
        data_origin='estimated', tracks=[dict(id='p1', segment_id='segment1', continuity='continuous',
            frames=[dict(support=support, frequency_hz=48., amplitudes=[.5, .5], phases_radians=[0., 3.141592653589793],
                         confidence=.8, action='preserve')])],
        residual_asset=None, transient_asset=None, remainder_policy='additive-owned-remainders-v1')
    gesture = envelope('GestureSpec', id='rise', duration_beats='1/1', curves=[dict(axis='pitch_cents', unit='cents',
        interpolation='linear', points=[dict(beat='0/1', value=0.), dict(beat='1/1', value=700.)])])
    phrase = envelope('PhrasePlan', start_beat='-1/4', end_beat='16/1', tuning_id='tritave', source_ids=['source'],
        gestures=[gesture], events=[dict(id='pickup', beat='-1/4', duration_beats='1/4', source_id='source',
            pitch=dict(tuning_id='tritave', degree=-1, detune_cents=0.), gain_db=-6., gesture_id='rise', layer_role='synthline')],
        roles=[dict(beat='12/1',duration_beats='4/1',role='variation')], bass_role='pedal', random=random)
    node = envelope('DSPNodeSpec', id='trim', type_id='core.gain.v1', inputs=['source'], channels=1,
        params=dict(gain_db=-6.), state_policy='stateless', phase_policy='source-derived', latency_samples=0,
        lookahead_samples=0, bypass='identity', automation=[dict(parameter='gain_db',unit='dB',interpolation='linear',
            points=[dict(sample=0,value=-6.),dict(sample=48000,value=0.)])])
    recipe = freeze_legacy({}).to_dict()
    trial = envelope('TrialSpec', id='example-ab', protocol_sha256='1'*64, mode='exploratory', preregistration_sha256=None,
        stimuli=[dict(id=key, recipe_sha256=char*64, asset=asset, start_sample=0,end_sample=48000,matching_gain_db=-12.)
                 for key,char in [('a','a'),('b','b')]], presentation_order=['b','a'], random=random,
        matching_method=dict(id='example.manual', version='1',configuration={}), endpoints=['liking','effort'])
    run = envelope('RunManifest', id='example-run', recipe_sha256='2'*64, engine_sha256='3'*64, source_commit=None,
        input_assets=[asset], artifacts=[], methods=[method], random=random, status='queued', error=None,
        environment=dict(python='not-recorded', numpy='not-recorded',scipy='not-recorded',platform='example-only'))
    return deepcopy({v['kind']:v for v in [asset,time,tuning,feature,partial,gesture,phrase,node,recipe,trial,run]})
