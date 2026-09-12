"""Shape AND semantic validation; both are required for G1 acceptance."""
from functools import lru_cache
from jsonschema import Draft202012Validator
from referencing import Registry
from .model import ContractError, check_json, fraction, seed_value
from .schema import schema, KINDS, VERSION
from .registry import node_definition
from .audio_schema import FEATURE_UNITS


def require(condition, message):
    if not condition:
        raise ContractError(message)


@lru_cache(maxsize=12)
def _validator(kind):
    s = schema(kind)
    Draft202012Validator.check_schema(s)
    # No remote retrieval callback; only bundled fragment references are used.
    return Draft202012Validator(s, registry=Registry())


def shape(value, s):
    error = next(Draft202012Validator(s, registry=Registry()).iter_errors(value), None)
    if error:
        raise ContractError(f'{list(error.absolute_path)}: {error.message[:400]}')


def unique(rows, key='id'):
    keys = [r[key] for r in rows]
    require(len(keys) == len(set(keys)), 'duplicate ' + key)


def increasing(values, name):
    require(all(a < b for a, b in zip(values, values[1:])), name + ' must be strictly increasing')


def support(s, asset):
    lo, hi, at = (s[k] for k in ('start_sample', 'end_sample', 'anchor_sample'))
    require(lo <= at < hi, 'anchor must lie within half-open support')
    require(0 <= at < asset['frame_count'], 'anchor outside source')
    if s['padding'] == 'none':
        require(lo >= 0 and hi <= asset['frame_count'], 'unpadded support outside source')


def _time(d):
    for field in ('tempo_segments', 'meter_segments'):
        positions = [fraction(v['beat']) for v in d[field]]
        require(positions[0] == 0, 'time map must start at beat zero')
        increasing(positions, field)
    for seg in d['tempo_segments']:
        require(20 <= fraction(seg['bpm']) <= 360, 'tempo outside 20..360 quarter notes/minute')


def _tuning(d):
    ratios = d['degree_ratios']
    require(ratios[0] == 1, 'degree zero must be unison')
    increasing(ratios, 'degree ratios')
    require(ratios[-1] < d['period_ratio'], 'period is excluded from explicit degrees')
    k = d['keyboard']
    if k:
        require(k['first_key'] <= k['last_key'], 'reversed keyboard range')
        require(k['first_key'] <= k['reference_key'] <= k['last_key'], 'reference key outside range')
        q, r = divmod(int(k['reference_key']) - int(k['middle_key']), len(k['entries']))
        degree = k['entries'][r]
        require(degree is not None, 'reference key is unmapped')
        require(q * k['formal_period_degrees'] + degree == d['reference_degree'], 'reference degree disagrees with keyboard')


def _asset(d):
    require(d['channel_layout'] == ('mono' if d['channels'] == 1 else 'stereo-lr'), 'channel layout/count mismatch')


def _features(d):
    for v in d['observations']:
        support(v['support'], d['asset'])
        require(v['unit'] == FEATURE_UNITS[v['feature']], 'feature unit mismatch')
        if v['validity'] != 'valid':
            require(v['value'] is None and v['confidence'] is None, 'missing/abstained observation must use null value/confidence')
        else:
            require(v['value'] is not None, 'valid observation requires a value')
            if v['feature'] in ('f0', 'spectral_centroid'):
                require(0 < v['value'] < d['asset']['sample_rate_hz'] / 2, 'frequency observation outside physical band')
            if v['feature'] == 'rms':
                require(v['value'] >= 0, 'negative RMS')
            if v['role'] == 'estimate':
                require(v['confidence'] is not None, 'estimate needs explicit confidence')
        if v['role'] == 'target':
            require(v['confidence'] is None, 'a target is not a confidence-rated observation')


def _partials(d):
    unique(d['tracks'])
    for track in d['tracks']:
        centres = [v['support']['anchor_sample'] for v in track['frames']]
        increasing(centres, 'track anchors')
        for v in track['frames']:
            support(v['support'], d['asset'])
            require(v['frequency_hz'] < d['asset']['sample_rate_hz'] / 2, 'partial above Nyquist')
            for field in ('amplitudes', 'phases_radians'):
                require(len(v[field]) == d['asset']['channels'], 'partial channel coefficient count mismatch')
            if track['continuity'] == 'unknown' or not any(v['amplitudes']):
                require(v['action'] == 'preserve', 'unobserved continuity/silent phase cannot authorize transformation')
    for key in ('residual_asset', 'transient_asset'):
        other = d[key]
        if other:
            require(all(other[k] == d['asset'][k] for k in ('sample_rate_hz', 'channels', 'frame_count', 'level_domain')),
                    'remainder shape/domain mismatch')


AXES = {'pitch_cents': ('cents', -4800, 4800), 'brightness_hz': ('Hz', 0, 96000),
        'roughness_fraction': ('ratio', 0, 1), 'density_per_beat': ('events/beat', 0, 64),
        'gain_db': ('dB', -120, 24)}


def _gesture(d):
    duration = fraction(d['duration_beats'])
    require(duration > 0, 'gesture duration must be positive')
    unique(d['curves'], 'axis')
    for c in d['curves']:
        unit, lo, hi = AXES[c['axis']]
        require(c['unit'] == unit, 'gesture axis/unit mismatch')
        times = [fraction(p['beat']) for p in c['points']]
        increasing(times, 'curve positions')
        require(0 <= times[0] and times[-1] <= duration, 'curve outside gesture duration')
        require(all(lo <= p['value'] <= hi for p in c['points']), 'gesture value outside axis bounds')


def _phrase(d):
    start, end = fraction(d['start_beat']), fraction(d['end_beat'])
    require(start < end, 'empty/reversed phrase span')
    unique(d['events']); unique(d['gestures'])
    gestures = {g['id'] for g in d['gestures']}
    previous = start
    for event in d['events']:
        at, duration = fraction(event['beat']), fraction(event['duration_beats'])
        require(start <= at < end and duration > 0 and at + duration <= end, 'event outside phrase span')
        require(at >= previous, 'events must be time ordered (stable list order for ties)')
        previous = at
        require(event['source_id'] in d['source_ids'], 'unknown event source')
        require(event['gesture_id'] is None or event['gesture_id'] in gestures, 'unknown gesture reference')
        require(event['pitch'] is None or event['pitch']['tuning_id'] == d['tuning_id'], 'unknown event tuning')
    previous = start
    for role in d['roles']:
        at, duration = fraction(role['beat']), fraction(role['duration_beats'])
        require(at >= previous and duration > 0 and at + duration <= end, 'overlapping/out-of-span phrase roles')
        previous = at + duration


def _node(d):
    definition = node_definition(d['type_id'])
    properties = definition['parameters']
    shape(d['params'], dict(type='object', properties=properties, required=list(properties), additionalProperties=False))
    require(d['state_policy'] == definition['state'] and d['bypass'] == definition['bypass'], 'node state/bypass metadata mismatch')
    require(d['latency_samples'] == definition['latency'] and d['lookahead_samples'] == definition['lookahead'], 'node latency metadata mismatch')
    require(definition['inputs'][0] <= len(d['inputs']) <= definition['inputs'][1], 'node input arity mismatch')
    require(d['phase_policy'] == 'source-derived', 'these stateless nodes preserve source phase')
    unique(d['automation'], 'parameter')
    for lane in d['automation']:
        spec = properties.get(lane['parameter'])
        require(spec is not None and spec.get('type') == 'number', 'unregistered/non-automatable parameter')
        require(lane['unit'] == spec['unit'], 'automation unit mismatch')
        increasing([p['sample'] for p in lane['points']], 'automation samples')
        for point in lane['points']:
            shape(point['value'], spec)


def _recipe(d):
    mode = d['render_mode']
    require((d['arrangement'] is None) == (mode == 'synth'), 'arrangement presence disagrees with render mode')
    require((d['reversebass'] is not None) == (mode in ('bass', 'arrange_bass')), 'reversebass presence disagrees with render mode')
    p = d['source']['params']
    require(p['sr'] == d['time_map']['sample_rate_hz'], 'source/time-map sample-rate mismatch')
    require(d['channels'] == 1, 'legacy source has no implicit stereo conversion')
    if d['phrase']:
        require(d['phrase']['tuning_id'] == d['tuning']['id'], 'phrase tuning reference mismatch')
        require(d['phrase']['source_ids'] == [d['source']['id']], 'recipe provides only the declared source')
    require(d['tail']['mode'] != 'legacy' or d['tail']['maximum_samples'] == 0, 'legacy tail duration is owned by the legacy renderer')
    unique(d['nodes'])
    source = d['source']['id']
    nodes = {n['id']: n for n in d['nodes']}
    require(source not in nodes, 'source/node id collision')
    ids = set(nodes) | {source}
    require(d['output_node'] in ids, 'unknown output node')
    for node in nodes.values():
        require(set(node['inputs']) <= ids, 'graph has dangling input')
        require(node['channels'] == d['channels'], 'implicit channel conversion prohibited')
    visiting, visited = set(), set()

    def visit(key):
        if key == source or key in visited:
            return
        require(key not in visiting, 'DSP graph cycle')
        visiting.add(key)
        for parent in nodes[key]['inputs']:
            visit(parent)
        visiting.remove(key); visited.add(key)

    visit(d['output_node'])
    require(visited == set(nodes), 'graph has disconnected nodes')


def _trial(d):
    unique(d['stimuli'])
    ids = {s['id'] for s in d['stimuli']}
    require(set(d['presentation_order']) == ids, 'trial order contains unknown or omitted stimulus')
    for s in d['stimuli']:
        require(s['start_sample'] < s['end_sample'] <= s['asset']['frame_count'], 'trial excerpt outside audio asset')
    if d['mode'] == 'confirmatory':
        require(d['preregistration_sha256'] is not None, 'confirmatory trial requires frozen preregistration identity')


def _run(d):
    if d['status'] == 'succeeded':
        require(bool(d['artifacts']) and d['error'] is None, 'successful run requires artifacts and no error')
    else:
        require(not d['artifacts'], 'incomplete run cannot publish artifacts')
    require((d['error'] is not None) == (d['status'] == 'failed'), 'run error/status mismatch')
    unique(d['methods'])


CHECKS = dict(TimeMap=_time, TuningSpec=_tuning, AudioAssetRef=_asset,
              FeatureBundle=_features, PartialTrackBundle=_partials, GestureSpec=_gesture,
              PhrasePlan=_phrase, DSPNodeSpec=_node, RenderRecipe=_recipe, TrialSpec=_trial, RunManifest=_run)


def validate(data, expected_kind=None):
    check_json(data)
    require(type(data) is dict, 'contract root must be an object')
    kind = data.get('kind')
    require(type(kind) is str and kind in KINDS, 'unknown contract kind')
    require(expected_kind is None or kind == expected_kind, 'unexpected contract kind')
    require(data.get('version') == VERSION, 'unsupported contract version; explicit migration required')
    error = next(_validator(kind).iter_errors(data), None)
    if error:
        raise ContractError(f'{list(error.absolute_path)}: {error.message[:400]}')

    def semantic(d):
        CHECKS[d['kind']](d)
        if 'random' in d:
            seed_value(d['random']['root'])
        children = []
        if d['kind'] in ('FeatureBundle', 'PartialTrackBundle'):
            children.append(d['asset'])
        if d['kind'] == 'PartialTrackBundle':
            children.extend(d[k] for k in ('residual_asset', 'transient_asset') if d[k] is not None)
        if d['kind'] == 'RenderRecipe':
            children.extend([d['time_map'], d['tuning'], *d['nodes']])
            if d['phrase'] is not None:
                children.append(d['phrase'])
        if d['kind'] == 'PhrasePlan':
            children.extend(d['gestures'])
        if d['kind'] == 'TrialSpec':
            children.extend(s['asset'] for s in d['stimuli'])
        if d['kind'] == 'RunManifest':
            children.extend(d['input_assets'])
        for child in children:
            semantic(child)

    semantic(data)
    return None
