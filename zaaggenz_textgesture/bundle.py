"""Immutable text-gesture authoring bundles with recompile-on-open verification."""
from __future__ import annotations
import json
from dataclasses import dataclass
from zaaggenz_contracts import digest
from zaaggenz_contracts.model import check_json,loads
from zaaggenz_timeline import TimelineDocument,default_document
from zaaggenz_gesture import DirectionalGesture
from .model import DictionaryRegistry,TextGestureError,VERSION,exact
from .compile import compile_text

BUNDLE_FORMAT='zaaggenz-text-gesture-bundle'

@dataclass(frozen=True,init=False)
class TextGestureBundle:
    _json:str
    def __init__(self,document):
        try:check_json(document)
        except (ValueError,TypeError) as exc:raise TextGestureError('bundle exceeds strict JSON bounds: '+str(exc)) from exc
        exact(document,{'format','version','text','dictionary_id','registry','base_timeline','ast','gesture','phrase_sha256','timeline','preview','compilation_sha256'},'text gesture bundle')
        if document['format']!=BUNDLE_FORMAT or document['version']!=VERSION:raise TextGestureError('unsupported text gesture bundle format/version')
        if type(document['text'])is not str:raise TextGestureError('bundle text must be a string')
        registry=DictionaryRegistry.from_document(document['registry']);base=TimelineDocument(document['base_timeline'])
        stored_timeline=TimelineDocument(document['timeline']);stored_gesture=DirectionalGesture(document['gesture'])
        compilation=compile_text(document['text'],registry,document['dictionary_id'],base=base)
        if compilation.ast!=document['ast']:raise TextGestureError('bundle AST does not match text/dictionary compilation')
        if compilation.gesture.to_dict()!=stored_gesture.to_dict():raise TextGestureError('bundle gesture does not match text/dictionary compilation')
        if compilation.phrase.sha256!=document['phrase_sha256']:raise TextGestureError('bundle phrase identity mismatch')
        if compilation.timeline.to_dict()!=stored_timeline.to_dict():raise TextGestureError('bundle timeline does not match text/dictionary compilation')
        if compilation.preview!=document['preview']:raise TextGestureError('bundle preview does not match text/dictionary compilation')
        if compilation.sha256!=document['compilation_sha256']:raise TextGestureError('bundle compilation identity mismatch')
        object.__setattr__(self,'_json',json.dumps(document,sort_keys=True,separators=(',',':'),allow_nan=False))
    def to_dict(self):return loads(self._json)
    @property
    def sha256(self):return digest(self.to_dict())
    @property
    def registry(self):return DictionaryRegistry.from_document(self.to_dict()['registry'])
    @property
    def timeline(self):return TimelineDocument(self.to_dict()['timeline'])
    @property
    def gesture(self):return DirectionalGesture(self.to_dict()['gesture'])
    @property
    def compilation(self):
        d=self.to_dict();return compile_text(d['text'],DictionaryRegistry.from_document(d['registry']),d['dictionary_id'],base=TimelineDocument(d['base_timeline']))
    @classmethod
    def from_json(cls,text):return cls(loads(text))

def make_bundle(text,registry,dictionary_id,base=None,*,sample_rate=48000):
    if not isinstance(registry,DictionaryRegistry):raise TextGestureError('DictionaryRegistry required')
    base_document=default_document(sample_rate) if base is None else base
    if not isinstance(base_document,TimelineDocument):raise TextGestureError('base must be a TimelineDocument')
    compilation=compile_text(text,registry,dictionary_id,base=base_document,sample_rate=sample_rate)
    return TextGestureBundle({'format':BUNDLE_FORMAT,'version':VERSION,'text':text,'dictionary_id':dictionary_id,
        'registry':registry.to_dict(),'base_timeline':base_document.to_dict(),'ast':compilation.ast,'gesture':compilation.gesture.to_dict(),
        'phrase_sha256':compilation.phrase.sha256,'timeline':compilation.timeline.to_dict(),'preview':compilation.preview,
        'compilation_sha256':compilation.sha256})
