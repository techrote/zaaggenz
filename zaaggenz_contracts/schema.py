"""Frozen v1 JSON Schema factories. Exported schemas have only local $refs."""
from copy import deepcopy
from .model import RATIONAL, SEED, SAFE_INT

VERSION = '1.0.0'
DRAFT = 'https://json-schema.org/draft/2020-12/schema'


def obj(**properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


def string(max_length=256, **kw):
    return dict(type='string', maxLength=max_length, **kw)


def num(lo=-1e12, hi=1e12):
    return dict(type='number', minimum=lo, maximum=hi)


def integer(lo=0, hi=SAFE_INT):
    return dict(type='integer', minimum=lo, maximum=hi)


def array(item, minimum=0, maximum=4096, unique=False):
    return dict(type='array', items=item, minItems=minimum, maxItems=maximum, uniqueItems=unique)


def enum(*values):
    return {'enum': list(values)}


def const(value):
    return {'const': value}


def nullable(schema):
    return {'anyOf': [schema, {'type': 'null'}]}


def ref(name):
    return {'$ref': '#/$defs/' + name}


def contract(name, **fields):
    return obj(kind=const(name), version=const(VERSION), **fields)


ID = {**string(64, pattern=r'^[a-z][a-z0-9_.-]{0,63}$'), 'not': {'pattern': r'[\r\n]'}}
HASH = string(64, pattern=r'^[0-9a-f]{64}$')
RAT = string(28, pattern=RATIONAL)
UINT64 = string(20, pattern=SEED)
RATE = integer(8000, 192000)
CHANNELS = enum(1, 2)
PARAMS = dict(type='object', maxProperties=64, propertyNames=ID,
              additionalProperties={'type': ['number', 'boolean', 'string', 'null']})
METHOD = obj(id=ID, version=string(32, minLength=1), configuration=PARAMS)
SUPPORT = obj(start_sample=integer(-SAFE_INT), end_sample=integer(-SAFE_INT),
              anchor_sample=integer(), padding=enum('none', 'zero', 'reflect'))
RANDOM = obj(algorithm=const('sha256-named-u64-v1'), root=UINT64,
             streams=array(ID, 0, 64, unique=True))
PHASE = enum('legacy-v1.2.1', 'continuous-integrated', 'reset-event', 'source-derived')
STATE = enum('stateless', 'reset-render', 'carry-within-render')


def definitions():
    from .music_schema import musical
    from .audio_schema import audio
    from .recipe_schema import recipes
    return {**musical(), **audio(), **recipes()}


KINDS = ('AudioAssetRef', 'TimeMap', 'TuningSpec', 'FeatureBundle', 'PartialTrackBundle',
         'GestureSpec', 'PhrasePlan', 'DSPNodeSpec', 'RenderRecipe', 'TrialSpec', 'RunManifest')


def schema(kind=None):
    if kind is not None and kind not in KINDS:
        raise ValueError('unsupported contract kind')
    root = ref(kind) if kind else {'oneOf': [ref(k) for k in KINDS]}
    return deepcopy({'$schema': DRAFT, '$id': 'urn:zaaggenz:contracts:1.0.0' + (':' + kind if kind else ''),
                     '$defs': definitions(), **root})
