"""Bounded recipes, graphs and study artefact metadata; no plugin loader."""
from .schema import *


def recipes():
    from .registry import legacy_schema
    source = obj(id=ID, method=const('legacy.synth.1.2.1'), params=legacy_schema('synth'))
    output = obj(master_gain_db=num(-36, 12), clipping=enum('clip_at_full_scale', 'error', 'unbounded_float'),
                 normalisation=const('none'), diagnostic_stems=const('pre_master'), mix=const('post_master'))
    tail = obj(mode=enum('legacy', 'preserve', 'truncate'), maximum_samples=integer())
    stimulus = obj(id=ID, recipe_sha256=HASH, asset=ref('AudioAssetRef'),
                   start_sample=integer(), end_sample=integer(), matching_gain_db=num(-120, 24))
    artifact = obj(kind=enum('audio', 'features', 'partials', 'report'), sha256=HASH)
    return {
        'DSPNodeSpec': contract('DSPNodeSpec', id=ID, type_id=ID, inputs=array(ID, 1, 16, unique=True),
            channels=CHANNELS, params={'type': 'object', 'maxProperties': 128},
            state_policy=STATE, phase_policy=PHASE, latency_samples=integer(0, 1920000),
            lookahead_samples=integer(0, 1920000), bypass=enum('identity', 'unsupported'),
            automation=array(obj(parameter=ID, unit=string(32), interpolation=enum('step', 'linear'),
                                 points=array(obj(sample=integer(), value=num()), 1, 4096)), 0, 32)),
        'RenderRecipe': contract('RenderRecipe', render_mode=enum('synth', 'arrange', 'arrange_bass', 'bass'),
            source=source, arrangement=nullable(legacy_schema('arrangement')),
            reversebass=nullable(legacy_schema('reversebass')), sculpt=nullable(legacy_schema('sculpt')),
            time_map=ref('TimeMap'),
            tuning=ref('TuningSpec'), phrase=nullable(ref('PhrasePlan')),
            nodes=array(ref('DSPNodeSpec'), 0, 128), output_node=ID, channels=CHANNELS,
            phase_policy=PHASE, state_policy=enum('reset-render'), tail=tail,
            quality=enum('legacy', 'standard', 'high'), random=RANDOM, output=output),
        'TrialSpec': contract('TrialSpec', id=ID, protocol_sha256=HASH,
            mode=enum('exploratory', 'confirmatory'), preregistration_sha256=nullable(HASH),
            stimuli=array(stimulus, 2, 16), presentation_order=array(ID, 2, 64),
            random=RANDOM, matching_method=METHOD,
            endpoints=array(enum('liking', 'arousal', 'amusement', 'urge_to_move', 'effort', 'absorption', 'accuracy'), 1, 7, unique=True)),
        'RunManifest': contract('RunManifest', id=ID, recipe_sha256=HASH, engine_sha256=HASH,
            source_commit=nullable(string(40, pattern=r'^[0-9a-f]{40}$')),
            input_assets=array(ref('AudioAssetRef'), 0, 64), artifacts=array(artifact, 0, 128),
            methods=array(METHOD, 1, 64), random=RANDOM,
            status=enum('queued', 'running', 'succeeded', 'cancelled', 'failed'),
            error=nullable(obj(code=ID, message=string(1024))),
            environment=obj(python=string(64), numpy=string(64), scipy=string(64), platform=string(256))),
    }
