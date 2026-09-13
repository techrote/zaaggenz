"""Project-local mnemonic dictionaries for the safe ZG-031 text language."""
from __future__ import annotations
from dataclasses import dataclass
import json,math,re
from zaaggenz_contracts import digest
from zaaggenz_contracts.model import check_json,fraction,loads

VERSION='1.0.0'
_ID=re.compile(r'[a-z][a-z0-9_.-]{0,63}\Z')
_TOKEN=re.compile(r'[a-z][a-z0-9-]{0,31}\Z')

class TextGestureError(ValueError): pass

def exact(v,keys,name):
    if type(v)is not dict or set(v)!=set(keys): raise TextGestureError(f'{name}: missing or unknown fields')
def ident(v,name):
    if type(v)is not str or not _ID.fullmatch(v): raise TextGestureError(f'{name}: lowercase identifier required')
def number(v,lo,hi,name):
    if type(v) not in (int,float) or type(v)is bool or not math.isfinite(float(v)) or not lo<=float(v)<=hi: raise TextGestureError(f'{name}: finite {lo}..{hi} required')
    return float(v)
def integer(v,lo,hi,name):
    if type(v)is not int or not lo<=v<=hi: raise TextGestureError(f'{name}: integer {lo}..{hi} required')
    return v

def _mapping(v,name):
    exact(v,{'duration_beats','accent_db','degree_offset','detune_cents','brightness_fraction','roughness_fraction','spectral_occupancy_fraction','spectral_width_fraction','density_per_beat'},name)
    try:d=fraction(v['duration_beats'])
    except (ValueError,TypeError) as exc: raise TextGestureError(str(exc)) from exc
    if not 0<d<=4: raise TextGestureError(f'{name}.duration_beats must be in (0,4]')
    number(v['accent_db'],-24,24,name+'.accent_db');integer(v['degree_offset'],-32,32,name+'.degree_offset');number(v['detune_cents'],-1200,1200,name+'.detune_cents')
    for key in ('brightness_fraction','roughness_fraction','spectral_occupancy_fraction','spectral_width_fraction'): number(v[key],0,1,name+'.'+key)
    integer(v['density_per_beat'],1,16,name+'.density_per_beat')

def validate_dictionary(data):
    try:check_json(data)
    except (ValueError,TypeError) as exc:raise TextGestureError(str(exc)) from exc
    exact(data,{'format','version','id','description','base_degree','base_gain_db','brightness_range_hz','return_mapping','entries'},'dictionary')
    if data['format']!='zaaggenz-text-dictionary' or data['version']!=VERSION:raise TextGestureError('unsupported mnemonic dictionary format/version')
    ident(data['id'],'dictionary.id')
    if type(data['description'])is not str or not data['description'].strip() or len(data['description'])>1024:raise TextGestureError('dictionary description required')
    integer(data['base_degree'],-4096,4096,'base_degree');number(data['base_gain_db'],-120,24,'base_gain_db')
    br=data['brightness_range_hz'];exact(br,{'closed_hz','open_hz'},'brightness_range_hz');lo=number(br['closed_hz'],0,96000,'closed_hz');hi=number(br['open_hz'],0,96000,'open_hz')
    if not lo<hi:raise TextGestureError('brightness range requires closed_hz < open_hz')
    _mapping(data['return_mapping'],'return_mapping')
    entries=data['entries']
    if type(entries)is not list or not 1<=len(entries)<=128:raise TextGestureError('dictionary requires 1..128 entries')
    seen=set()
    for i,entry in enumerate(entries):
        exact(entry,{'token','mapping'},f'entry[{i}]')
        token=entry['token']
        if type(token)is not str or not _TOKEN.fullmatch(token):raise TextGestureError('dictionary token must match [a-z][a-z0-9-]{0,31}')
        if token in seen:raise TextGestureError('duplicate dictionary token')
        seen.add(token);_mapping(entry['mapping'],f'entry[{i}].mapping')

@dataclass(frozen=True,init=False)
class MnemonicDictionary:
    _json:str
    def __init__(self,data):validate_dictionary(data);object.__setattr__(self,'_json',json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False))
    def to_dict(self):return loads(self._json)
    @property
    def sha256(self):return digest(self.to_dict())
    def mapping(self,token):
        for entry in self.to_dict()['entries']:
            if entry['token']==token:return entry['mapping']
        raise KeyError(token)
    @classmethod
    def from_json(cls,text):return cls(loads(text))

@dataclass(frozen=True,init=False)
class DictionaryRegistry:
    _json:str
    def __init__(self,dictionaries):
        raw=[d.to_dict() if isinstance(d,MnemonicDictionary) else d for d in dictionaries]
        if not 1<=len(raw)<=32:raise TextGestureError('registry requires 1..32 dictionaries')
        parsed=[MnemonicDictionary(d) for d in raw];ids=[d.to_dict()['id'] for d in parsed]
        if len(ids)!=len(set(ids)):raise TextGestureError('duplicate dictionary id')
        doc={'format':'zaaggenz-text-dictionary-registry','version':VERSION,'dictionaries':[d.to_dict() for d in parsed]}
        check_json(doc);object.__setattr__(self,'_json',json.dumps(doc,sort_keys=True,separators=(',',':'),allow_nan=False))
    def to_dict(self):return loads(self._json)
    def get(self,dictionary_id):
        for d in self.to_dict()['dictionaries']:
            if d['id']==dictionary_id:return MnemonicDictionary(d)
        raise TextGestureError(f'unknown dictionary {dictionary_id!r}')
    @property
    def ids(self):return tuple(d['id'] for d in self.to_dict()['dictionaries'])
    @property
    def sha256(self):return digest(self.to_dict())
    @classmethod
    def from_document(cls,data):
        exact(data,{'format','version','dictionaries'},'dictionary registry')
        if data['format']!='zaaggenz-text-dictionary-registry' or data['version']!=VERSION:raise TextGestureError('unsupported registry format/version')
        return cls(data['dictionaries'])
