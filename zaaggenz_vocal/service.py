"""Session-local capture service; compilation depends only on immutable edit data, not retained audio."""
from __future__ import annotations
from zaaggenz_textgesture import DictionaryRegistry,starter_registry
from .analysis import analyse_vocal
from .edit import make_edit,compile_edit,mark_source_discarded
from .model import VocalEdit,VocalCaptureError
from .store import SessionAudioStore,decode_wav_bytes,encode_wav_bytes

class VocalService:
    def __init__(self,registry=None):
        self.registry=starter_registry() if registry is None else registry
        if not isinstance(self.registry,DictionaryRegistry):raise VocalCaptureError('DictionaryRegistry required')
        self.store=SessionAudioStore()
    def ingest_wav(self,payload,origin='local-import'):
        sr,x=decode_wav_bytes(payload);identifier=self.store.put(x,sr,origin)
        audio,_,_=self.store.get(identifier)
        return {'source_id':identifier,'sample_rate_hz':sr,'channels':audio.shape[1],'frame_count':len(audio),'origin':origin,'duration_seconds':len(audio)/sr}
    def analyse(self,source_id,dictionary_id='local-soft',grid_beats='1/4'):
        x,sr,origin=self.store.get(source_id);analysis=analyse_vocal(x,sr,origin=origin)
        if analysis.to_dict()['source']['id']!=source_id:raise AssertionError('session-store content identity changed during analysis')
        edit=make_edit(analysis,self.registry,dictionary_id,grid_beats=grid_beats)
        compilation=compile_edit(edit,self.registry)
        return {'analysis':analysis.to_dict(),'analysis_sha256':analysis.sha256,'edit':edit.to_dict(),'edit_sha256':edit.sha256,
                'preview':compilation.preview,'timeline':compilation.timeline.to_dict(),'timeline_revision_id':compilation.timeline.revision_id,
                'automation':compilation.automation,'compilation_sha256':compilation.sha256}
    def compile(self,edit_document):
        edit=VocalEdit(edit_document);compilation=compile_edit(edit,self.registry)
        return {'edit_sha256':edit.sha256,'preview':compilation.preview,'timeline':compilation.timeline.to_dict(),
                'timeline_revision_id':compilation.timeline.revision_id,'phrase_sha256':compilation.phrase.sha256,
                'automation':compilation.automation,'compilation_sha256':compilation.sha256}
    def discard(self,source_id,edit_document):
        edit=VocalEdit(edit_document)
        if edit.to_dict()['analysis']['source']['id']!=source_id:raise VocalCaptureError('discard source does not match edit analysis identity')
        self.store.discard(source_id);updated=mark_source_discarded(edit)
        compiled=compile_edit(updated,self.registry)
        return {'discarded':True,'source_id':source_id,'edit':updated.to_dict(),'edit_sha256':updated.sha256,
                'timeline_revision_id':compiled.timeline.revision_id,'compilation_sha256':compiled.sha256}
    def wave(self,source_id):
        x,sr,_=self.store.get(source_id);return encode_wav_bytes(x[:,0] if x.shape[1]==1 else x,sr),sr
